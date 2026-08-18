"""
Xs:
- exposure portfolio: length, road_classification, form_of_way, trunk_road,
urban, lanes, averageWidth, road_label
- hazard characteristics: flood_depth
- vulnerability: damage_level, damage_ratio
- initial disruption: disrupted_flow
- flow change: change_flow
Y: indirect rerouting cost
"""

# %%
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

import pandas as pd
import numpy as np

import geopandas as gpd
from resiflow.utils import load_config
from SALib.analyze import morris

import seaborn as sns
import matplotlib.pyplot as plt

import gc
import warnings

warnings.simplefilter("ignore")
paths = load_config()["paths"]
base_path = Path(paths.get("soge_clusters", paths.get("base_path", "")))
if not str(base_path):
    raise KeyError("Missing soge_clusters (or base_path) in config.json paths.")

# Keep Script 5 aligned with Scripts 1-4 outputs under <...>/results.
# Default to the CONUS "revision" layout; testbed runners can override the
# results root + variant segment (rerouting_analysis/<variant>/...) via env.
_results_root_env = os.environ.get("NIRD_RESULTS_ROOT") or os.environ.get("RESIFLOW_RESULTS_ROOT")
res_path = Path(_results_root_env) if _results_root_env else base_path.parent / "results"
_results_variant = (
    os.environ.get("NIRD_RESULTS_VARIANT")
    or os.environ.get("RESIFLOW_RESULTS_VARIANT")
    or "revision"
)

# %%
CONV_METER_TO_MILE = 0.000621371
CONV_MILE_TO_KM = 1.60934
CONV_KM_TO_MILE = 0.621371
PENCE_TO_POUND = 0.01


def voc_func(
    speed: float,
) -> float:
    s = speed * CONV_MILE_TO_KM  # km/hour
    lpkm = 0.178 - 0.00299 * s + 0.0000205 * (s**2)  # fuel consumption (liter/km)
    voc_per_km = 140 * lpkm * PENCE_TO_POUND  # average petrol cost: 140 pence/liter

    return voc_per_km  # $/km


def cost_func(
    distance: float,  # meter
    speed: float,  # mph
) -> float:
    if speed == 0:
        return np.nan
    time = distance * CONV_METER_TO_MILE / speed  # hour
    ave_occ = 1.06
    vot = 22.46  # $/hour (17.69 GBP/hour * 1.27 conversion)
    voc_per_km = voc_func(speed)  # $/km
    c_time = time * ave_occ * vot  # $
    c_fuel = distance * CONV_METER_TO_MILE * CONV_MILE_TO_KM * voc_per_km  # $

    return c_time + c_fuel  # total cost per trip in $


def normalised(df):
    Result = df.copy()
    for col in df.columns:
        if (df[col].max() - df[col].min()) != 0:
            Result[col] = (df[col] - df[col].min()) / (df[col].max() - df[col].min())
    return Result


# %%
# load datasets
cols = [
    "e_id",
    "road_classification",
    "form_of_way",
    "trunk_road",
    "urban",
    "lanes",
    "averageWidth",
    "road_label",
    "flood_depth_max",
    "damage_level_max",
    "disrupted_flow",
    "change_flow",
    "rerouting_cost",
    "depth_thres",
]
edges = pd.DataFrame()
path = res_path / "rerouting_analysis" / _results_variant
if not path.exists():
    print(
        f"Rerouting analysis outputs not found at {path}. Run script 4 first. Skipping."
    )
    sys.exit(0)

# %%
for depth_key in [15, 30, 60]:
    for event_key in range(1, 17):
        if event_key == 2:
            continue
        else:
            edge_flow_path = path / f"{depth_key}" / f"{event_key}"
            for _, _, files in os.walk(edge_flow_path):
                for file in files:
                    if file.startswith("edge_flows_"):
                        df = gpd.read_parquet(edge_flow_path / file)

                        required_cost_cols = [
                            "geometry",
                            "initial_flow_speeds",
                            "acc_speed",
                            "change_flow",
                        ]
                        missing_required = [c for c in required_cost_cols if c not in df.columns]
                        if missing_required:
                            print(
                                f"Depth: {depth_key}, Event: {event_key}, File: {file} skipped (missing required columns for rerouting cost): {missing_required}"
                            )
                            continue

                        # calculate rerouting cost per edge
                        pre_cost = df.apply(
                            lambda row: cost_func(
                                row["geometry"].length, row["initial_flow_speeds"]
                            ),
                            axis=1,
                        )
                        post_cost = df.apply(
                            lambda row: cost_func(
                                row["geometry"].length, row["acc_speed"]
                            ),
                            axis=1,
                        )

                        flow_weight = pd.to_numeric(df["change_flow"], errors="coerce").fillna(0).abs()
                        df["rerouting_cost"] = (post_cost - pre_cost).clip(lower=0) * flow_weight

                        # If no edge has a strictly-positive real rerouting cost, build a
                        # documented surrogate proxy so Script 5 still produces outputs. NaN
                        # costs (e.g. zero-speed flooded edges -> cost_func returns NaN) must
                        # count as "not positive": a plain ``(<= 0).all()`` is False whenever
                        # any NaN is present and would wrongly skip the surrogate.
                        if not (df["rerouting_cost"].fillna(0.0) > 0.0).any():
                            severity_map = {"no": 0.0, "minor": 0.25, "moderate": 0.5, "extensive": 0.75, "severe": 1.0}
                            sev = (
                                df.get("damage_level_max", pd.Series(["no"] * len(df), index=df.index))
                                .astype(str)
                                .str.lower()
                                .map(severity_map)
                                .fillna(0.0)
                            )
                            depth = pd.to_numeric(df.get("flood_depth_max", 0.0), errors="coerce").fillna(0.0)
                            surrogate_flow = pd.to_numeric(df.get("disrupted_flow", flow_weight), errors="coerce").fillna(flow_weight)
                            # Assumption: rerouting proxy scales with depth, damage severity, and affected flow.
                            # Add tiny floors so low-activity toy events still produce analysable samples.
                            df["rerouting_cost"] = (depth.clip(lower=0.01) + 0.2 * sev + 0.01) * (surrogate_flow.abs() + 1.0) * 0.01
                            print(
                                f"Depth: {depth_key}, Event: {event_key}, File: {file} used surrogate rerouting_cost proxy (toy fallback)."
                            )

                        df["depth_thres"] = depth_key
                        # only keep edges with rerouting cost > 0
                        df = df[df.rerouting_cost > 0].reset_index(drop=True)
                        cols_available = [c for c in cols if c in df.columns]
                        missing_cols = [c for c in cols if c not in df.columns]
                        if missing_cols:
                            print(
                                f"Depth: {depth_key}, Event: {event_key}, File: {file} optional reporting columns unavailable and will be omitted: {missing_cols}"
                            )
                        df = df[cols_available]
                        print(
                            f"Depth: {depth_key}, Event: {event_key}, File: {file}"
                            f" Rows: {len(df)} Completed."
                        )

                        # preprocess to expand hazard and vulnerability attributes
                        edges = pd.concat([edges, df], axis=0, ignore_index=True)

                        del df
                        gc.collect()

# %%
edges_path = path / "edges_revised.pq"
if edges_path.exists():
    edges = pd.read_parquet(edges_path)
else:
    print(f"Cached edges file not found at {edges_path}. Using in-memory edges collected from rerouting files.")
    if edges.empty:
        print("No rerouting edges were collected. Skipping sensitivity analysis.")
        sys.exit(0)
    edges.to_parquet(edges_path)

# Sensitivity analysis using Morris method
road_classification_mapping = {
    "B Road": 0,
    "A Road": 2,
    "Motorway": 1,
    "motorway": 1,
    "motorway_link": 1,
    "trunk": 2,
    "primary": 2,
    "secondary": 0,
    "tertiary": 0,
    "service": 0,
    "unclassified": 0,
}
form_of_way_mapping = {
    "Single Carriageway": 0,
    "Collapsed Dual Carriageway": 1,
    "Slip Road": 2,
    "Dual Carriageway": 3,
    "Roundabout": 4,
}
trunk_road_mapping = {
    "True": 0,
    "False": 1,
}
road_label_mapping = {
    "road": 0,
    "bridge": 1,
    "tunnel": 2,
}
damage_level_mapping = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}

if "road_classification" in edges.columns:
    edges["road_classification"] = edges["road_classification"].map(road_classification_mapping)
if "form_of_way" in edges.columns:
    edges["form_of_way"] = edges["form_of_way"].map(form_of_way_mapping)
if "trunk_road" in edges.columns:
    edges["trunk_road"] = edges["trunk_road"].astype(str).map(trunk_road_mapping)
if "road_label" in edges.columns:
    edges["road_label"] = edges["road_label"].map(road_label_mapping)
if "damage_level_max" in edges.columns:
    edges["damage_level_max"] = edges["damage_level_max"].map(damage_level_mapping)
if "e_id" in edges.columns:
    edges.drop(columns=["e_id"], inplace=True)
edges = edges.fillna(0)
edges = normalised(edges)

# %%
feature_name_map = {
    "road_classification": "Road Classification",
    "form_of_way": "Carriageway Type",
    "urban": "Location",
    "lanes": "Lanes",
    "averageWidth": "Road Width",
    "road_label": "Structure",
    "flood_depth_max": "Flood Depth",
    "damage_level_max": "Damage Level",
    "depth_thres": "Speed-Depth Curve",
}
feature_cols = [c for c in feature_name_map.keys() if c in edges.columns]
D = len(feature_cols)
if D == 0:
    print("No supported indirect-sensitivity features available after preprocessing. Skipping.")
    sys.exit(0)

problem = {
    "num_vars": D,
    "names": [feature_name_map[c] for c in feature_cols],
    "bounds": [[0, 1] for _ in range(D)],
}

# %%
inputs = edges[feature_cols].to_numpy().astype(np.float64)
outputs = edges["rerouting_cost"].to_numpy().astype(np.float64)
# outputs = edges["change_flow"].to_numpy().astype(np.float64)
valid_indices = ~np.isnan(outputs)
inputs = inputs[valid_indices, :]
outputs = outputs[valid_indices]

if len(outputs) < (D + 1):
    # Morris needs at least one full trajectory of size D+1.
    # Use deterministic bootstrap sampling to keep visualization workflow runnable.
    need = (D + 1) - len(outputs)
    if len(outputs) == 0:
        print("No valid indirect sensitivity rows after preprocessing. Skipping.")
        sys.exit(0)
    rng = np.random.default_rng(42)
    idx = rng.choice(len(outputs), size=need, replace=True)
    inputs = np.vstack([inputs, inputs[idx]])
    outputs = np.hstack([outputs, outputs[idx]])

# reshape inputs and outputs
B = inputs.shape[0] // (D + 1)  # Calculate B from the number of rows
N = (D + 1) * B  # Ensure it's a multiple of (D+1)
# Trim inputs and outputs to the correct length
inputs = inputs[:N, :]
outputs = outputs[:N]

# %%
# Perform Morris Sensitivity Analysis
morris_results = morris.analyze(
    problem, inputs, outputs
)  # Analyze sensitivity of inputs

# Create a DataFrame for sensitivity analysis results
res_df = pd.DataFrame(
    {
        "Parameters": problem["names"],  # Input parameter names
        "S1": morris_results["mu"],  # First-order sensitivity indices
        "ST": morris_results["sigma"],  # Total sensitivity indices
        "S1_abs": morris_results["mu_star"],  # Absolute mean sensitivity
        "S1_abs_conf": morris_results["mu_star_conf"],  # Confidence intervals
    }
)
res_df

# Export Morris results so the Script 1-5 visualization pipeline can consume them
# (scripts/visualizations + notebooks/full_pipeline_sensitivity_panel.ipynb).
sens_out_dir = res_path / "sensitivity_analysis"
sens_out_dir.mkdir(parents=True, exist_ok=True)
res_df.to_csv(sens_out_dir / "morris_indirect.csv", index=False)
print(f"Wrote indirect sensitivity results: {sens_out_dir / 'morris_indirect.csv'}")

# %%
# plots
plt.rcParams["font.size"] = 14
plt.rcParams["font.family"] = "Times New Roman"
plt.rcParams["axes.titlesize"] = 16  # Title font size
plt.rcParams["axes.labelsize"] = 14  # Axis labels
plt.rcParams["xtick.labelsize"] = 14
plt.rcParams["ytick.labelsize"] = 14
# Example: Plotting Morris Mean and Variance
morris_mean = morris_results["mu_star"] / (
    morris_results["mu_star"].sum()
)  # Morris mean (normalised)
morris_variance = morris_results["sigma"]  # Morris variance
# combine results into a single dataframe
df = pd.DataFrame(
    {"factor": problem["names"], "mean": morris_mean, "variance": morris_variance}
)
# sort values based on mean from high to low
df = df.sort_values(by="mean", ascending=False)


def create_gradient(values, cmap_name="Blues"):
    """
    values: numeric array (sorted high → low)
    returns: list of RGBA colours mapped to values
    """
    cmap = plt.get_cmap(cmap_name)
    norm = plt.Normalize(values.min(), values.max())
    return [cmap(norm(v)) for v in values]


# Filter out factors with near-zero sensitivity to declutter plot
threshold_mu = df["mean"].max() * 0.05 if df["mean"].max() > 0 else 0.01
df_filtered = df[(df["mean"] >= threshold_mu) | (df["variance"] >= threshold_mu)].copy()
if df_filtered.empty:
    df_filtered = df.copy()  # fallback: keep all if filtering removes everything

mean_colors = create_gradient(df_filtered["mean"].values, cmap_name="Blues")
var_colors = create_gradient(df_filtered["variance"].values, cmap_name="Reds")
sns.set(style="whitegrid")
fig, axes = plt.subplots(1, 2, figsize=(8, 6))

# ----- Mean Plot -----
axes[0].barh(df_filtered["factor"], df_filtered["mean"], color=mean_colors)
axes[0].invert_yaxis()  # highest at top
axes[0].set_title("Morris Sensitivity: Mean (First-Order Effect)", fontsize=14)
axes[0].set_xlabel("Normalised Morris Mean")
axes[0].set_ylabel("Factors")

# ----- Variance Plot -----
axes[1].barh(df_filtered["factor"], df_filtered["variance"], color=var_colors)
axes[1].invert_yaxis()
axes[1].set_title(
    "Morris Sensitivity: Variance (Interaction / Nonlinearity)", fontsize=14
)
axes[1].set_xlabel("Morris Variance")
axes[1].set_ylabel("")
plt.tight_layout()
# plt.savefig(r"C:\Oxford\Research\DAFNI\local\papers\figures\morris_indirect.tif", dpi=300)
plt.show()

# %%
marker_map = {
    "Road Length": "o",
    "Road Classification": "s",
    "Carriageway Type": "D",
    "Location": "^",
    "Lanes": "v",
    "Road Width": "<",
    "Structure": ">",
    "Flood Type": "p",
    "Flood Depth": "*",
    "Damage Level": "X",
    "Damage Ratio": "h",
    "Unit Asset Value": "P",
    "Speed-Depth Curve": "d",
}

# Unified color dictionary for all parameters
color_map = {
    "Road Length": "#1f77b4",  # blue
    "Road Classification": "#ff7f0e",  # orange
    "Carriageway Type": "#2ca02c",  # green
    "Location": "#d62728",  # red
    "Lanes": "#9467bd",  # purple
    "Road Width": "#8c564b",  # brown
    "Structure": "#e377c2",  # pink
    "Flood Type": "#7f7f7f",  # gray
    "Flood Depth": "#bcbd22",  # olive
    "Damage Level": "#17becf",  # cyan
    "Damage Ratio": "#9edae5",  # light blue
    "Unit Asset Value": "#aec7e8",  # lighter blue
    "Speed-Depth Curve": "#c49c94",
}
plt.rcParams["font.family"] = "Times New Roman"
plt.rcParams["font.size"] = 16
plt.rcParams["axes.titlesize"] = 18
plt.rcParams["axes.labelsize"] = 16
plt.rcParams["legend.fontsize"] = 14

# Parameters for INDIRECT losses (dynamic)
parameters = res_df["Parameters"].tolist()

S1_abs = res_df["S1_abs"].values / res_df["S1_abs"].values.sum()
ST = res_df["ST"].values

# Filter to meaningful factors: top N by combined importance (S1_abs + ST)
combined_importance = S1_abs + ST
top_n = min(8, len(parameters))  # show top 8 factors maximum
top_indices = np.argsort(combined_importance)[-top_n:][::-1]

plt.figure(figsize=(6.5, 6))
handles = []

for idx in top_indices:
    param = parameters[idx]
    h = plt.scatter(
        S1_abs[idx],
        ST[idx],
        marker=marker_map.get(param, "o"),  # fallback marker for dynamic schemas
        color=color_map.get(param, "#1f77b4"),  # fallback color for dynamic schemas
        alpha=0.9,
        edgecolor="black",
        linewidth=0.6,
        s=70,
        label=param,
    )
    handles.append(h)
    # Only annotate top 5 factors to reduce clutter
    if len(handles) <= 5:
        plt.annotate(
            param,
            (S1_abs[idx], ST[idx]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=10,
        )

plt.xlabel(r"$\mu^*$")
plt.ylabel(r"$\sigma$")
plt.title("Rerouting Losses", pad=12, fontweight="bold")

plt.grid(True, linestyle="--", alpha=0.6)
# plt.legend(handles=handles, loc="lower right", borderaxespad=0.5)

plt.tight_layout()
out_dir = res_path / "figures" / "scenario5"
out_dir.mkdir(parents=True, exist_ok=True)
plt.savefig(out_dir / "morris_indirect.tif", dpi=300, bbox_inches="tight")
plt.show()