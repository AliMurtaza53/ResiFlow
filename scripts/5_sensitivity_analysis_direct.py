"""
temp_Xs:
- exposure portfolio: length, road_classification, form_of_way, trunk_road,
urban, lanes, averageWidth, road_label
- hazard characteristics: flood_type, flood_depth
- vulnerability: damage_level, damage_ratio
- unit repairing/maintenance cost: damage_value
Y: damage_cost
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

import warnings

warnings.simplefilter("ignore")
# Use soge_clusters path and keep outputs aligned with scripts 1-4
base_path = Path(load_config()["paths"]["soge_clusters"])
# Results root + variant: default to the CONUS "revision" layout, but allow the
# testbed runners to point Script 5 at a variant layout
# (<results_root>/damage_analysis/<variant>/...) via env, matching Scripts 1-4.
_results_root_env = os.environ.get("NIRD_RESULTS_ROOT") or os.environ.get("RESIFLOW_RESULTS_ROOT")
res_path = Path(_results_root_env) if _results_root_env else base_path.parent / "results"
_results_variant = (
    os.environ.get("NIRD_RESULTS_VARIANT")
    or os.environ.get("RESIFLOW_RESULTS_VARIANT")
    or "revision"
)


def first_existing(paths):
    """Return first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


# %%
def normalised(df):
    Result = df.copy()
    for col in df.columns:
        if (df[col].max() - df[col].min()) != 0:
            Result[col] = (df[col] - df[col].min()) / (df[col].max() - df[col].min())
    return Result


def preprocess(intersections, road_links, lad_shp=None):
    # add geometry to intersections
    joined = intersections.copy()
    # intersections = intersections.copy()
    # # intersections = intersections.head(10)
    # intersections["_orig_index"] = np.arange(len(intersections))
    # intersections = intersections.merge(
    #     road_links[["e_id", "geometry"]],
    #     on="e_id",
    #     how="left",
    #     suffixes=("", "_road"),
    # )
    # intersections = gpd.GeoDataFrame(intersections, geometry="geometry")
    # # add admin info via spatial join
    # # ensure LAD shapefile has centroids
    # if "centroid" not in lad_shp.columns:
    #     lad_shp = lad_shp.assign(centroid=lad_shp.geometry.centroid)
    # else:
    #     # if centroid exists but not a geometry type, recompute to be safe
    #     if not isinstance(lad_shp.loc[0, "centroid"].__class__.__name__, str):
    #         lad_shp["centroid"] = lad_shp.geometry.centroid
    # joined = gpd.sjoin(
    #     intersections,
    #     lad_shp[["LAD21CD", "geometry", "centroid"]],
    #     how="left",
    #     predicate="intersects",
    # )
    # # compute distance from intersection geometry to LAD centroid — vectorized
    # joined["dist_to_centroid"] = joined.geometry.distance(
    #     joined["centroid"].fillna(joined.geometry)
    # )
    # # sort so the nearest centroid is first for each original intersection
    # joined = joined.sort_values(["_orig_index", "dist_to_centroid"])

    # # keep only the first match per original intersection (deterministic)
    # joined = (
    #     joined.drop_duplicates(subset="_orig_index", keep="first").reset_index(
    #         drop=False
    #     )
    # ).rename(columns={"index": "_orig_index"})

    # divide them into two sub-dataframes (surface, river)
    road_cols = [
        "length",
        "road_classification",
        "form_of_way",
        "trunk_road",
        "urban",
        "lanes",
        "averageWidth",
        "road_label",
        # "LAD21CD",
    ]
    road_cols = [c for c in road_cols if c in joined.columns]

    # helper to build the surface/river DF
    def build_hazard_df(
        df: gpd.GeoDataFrame,
        hazard_prefix: str,
        depth_col: str,
        damage_level_col: str,
    ) -> pd.DataFrame:
        # base columns
        base = df[road_cols].copy()
        # include the depth and damage level if present
        extra_cols = [c for c in (depth_col, damage_level_col) if c in df.columns]
        if extra_cols:
            base = pd.concat([base, df[extra_cols]], axis=1)
        # unit costs
        uc_min_col = f"{hazard_prefix}_unit_cost_min"
        uc_max_col = f"{hazard_prefix}_unit_cost_max"
        uc_min = (
            df[uc_min_col]
            if uc_min_col in df.columns
            else pd.Series([np.nan] * len(df), index=df.index)
        )
        uc_max = (
            df[uc_max_col]
            if uc_max_col in df.columns
            else pd.Series([np.nan] * len(df), index=df.index)
        )
        base["damage_value"] = list(zip(uc_min, uc_max))

        # damage fraction columns (pattern matching)
        frac_cols = [
            c
            for c in df.columns
            if c.endswith(f"_{hazard_prefix}_damage_fraction")
            or f"_{hazard_prefix}_damage_fraction" in c
        ]
        # fallback: as in original, use filter(like=)
        if not frac_cols:
            frac_cols = [
                c for c in df.columns if f"_{hazard_prefix}_damage_fraction" in c
            ]

        if frac_cols:
            frac_df = df[frac_cols].replace(0, np.nan)
            frac_min = frac_df.min(axis=1, skipna=True)
            frac_max = frac_df.max(axis=1, skipna=True)
        else:
            frac_min = pd.Series([np.nan] * len(df), index=df.index)
            frac_max = pd.Series([np.nan] * len(df), index=df.index)
        base["damage_ratio"] = list(zip(frac_min, frac_max))

        # damage cost columns
        val_cols = [c for c in df.columns if f"_{hazard_prefix}_damage_value_" in c]
        if val_cols:
            val_df = df[val_cols].replace(0, np.nan)
            val_min = val_df.min(axis=1, skipna=True)
            val_max = val_df.max(axis=1, skipna=True)
        else:
            val_min = pd.Series([np.nan] * len(df), index=df.index)
            val_max = pd.Series([np.nan] * len(df), index=df.index)
        base["damage_cost"] = list(zip(val_min, val_max))
        base = base.reset_index(drop=True)
        base = base.explode(
            ["damage_value", "damage_ratio", "damage_cost"], ignore_index=True
        )
        return base

    # build surface and river dataframes
    surface_df = build_hazard_df(
        joined, "surface", "flood_depth_surface", "damage_level_surface"
    )
    surface_df.rename(
        columns={
            "flood_depth_surface": "flood_depth",
            "damage_level_surface": "damage_level",
        },
        inplace=True,
    )
    river_df = build_hazard_df(
        joined, "river", "flood_depth_river", "damage_level_river"
    )
    river_df.rename(
        columns={
            "flood_depth_river": "flood_depth",
            "damage_level_river": "damage_level",
        },
        inplace=True,
    )
    # Label each hazard type
    surface_df["flood_type"] = "surface"
    river_df["flood_type"] = "river"

    # Combine them into one DataFrame
    combined_df = pd.concat([surface_df, river_df], ignore_index=True)
    combined_df = combined_df[combined_df["damage_cost"].notnull()].reset_index(
        drop=True
    )
    combined_df.drop_duplicates(inplace=True)
    combined_df.trunk_road = combined_df.trunk_road.astype(str)

    return combined_df


# %%
# Load datasets (SUBNETWORK - note: uses base_path which is different from other scripts)
path = res_path / "damage_analysis" / _results_variant
# Prefer toy/FAF5 links, fallback to UK subnetwork
road_links_path = first_existing(
    [
        base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
        base_path / "networks" / "faf5" / "faf5_road_links.gpq",
        base_path / "networks" / "test_subnetwork" / "GB_road_links_with_bridges_subnetwork.gpq",
    ]
)
lad_path = (
    base_path
    / "census_datasets"
    / "admin_census_boundary_stats"
    / "gb_lad_2021_estimates.geoparquet"
)

if road_links_path is None or not road_links_path.exists():
    print(
        "Direct sensitivity analysis skipped: road links file not found in toy/FAF5/UK paths."
    )
    sys.exit(0)

road_links = gpd.read_parquet(road_links_path)
lad_shp = gpd.read_parquet(lad_path) if lad_path.exists() else None

intersections = pd.DataFrame()
for root, dirs, files in os.walk(path):
    for file in files:
        if file.endswith("_with_damage_values.csv") or file.startswith("intersections"):
            temp = pd.read_csv(os.path.join(root, file))
            intersections = pd.concat([intersections, temp], axis=0, ignore_index=True)

if intersections.empty:
    print(f"No damage-analysis CSVs found under {path}. Run script 3 first. Skipping.")
    sys.exit(0)

Xs = preprocess(intersections, road_links, lad_shp)
# %%
# temp_Xs = Xs.copy()
# remove damage level
temp_Xs = Xs[Xs.damage_level == "severe"].reset_index(drop=True)  #!!! update
damage_focus = os.environ.get("NIRD_DIRECT_DAMAGE_LEVEL", "all").strip().lower()
if damage_focus in {"no", "minor", "moderate", "extensive", "severe"}:
    temp_Xs = Xs[Xs.damage_level.astype(str).str.lower() == damage_focus].reset_index(drop=True)
else:
    temp_Xs = Xs.copy().reset_index(drop=True)

if temp_Xs.empty:
    temp_Xs = Xs.copy().reset_index(drop=True)
# convert string objects to numeric values for sensitivity analysis
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

# admin_mapping = {v: idx for idx, v in enumerate(lad_shp["LAD21CD"].unique())}
flood_type_mapping = {"surface": 0, "river": 1}
damage_level_mapping = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}

if "road_classification" in temp_Xs.columns:
    temp_Xs["road_classification"] = temp_Xs["road_classification"].map(road_classification_mapping)
if "form_of_way" in temp_Xs.columns:
    temp_Xs["form_of_way"] = temp_Xs["form_of_way"].map(form_of_way_mapping)
if "trunk_road" in temp_Xs.columns:
    temp_Xs["trunk_road"] = temp_Xs["trunk_road"].map(trunk_road_mapping)
if "road_label" in temp_Xs.columns:
    temp_Xs["road_label"] = temp_Xs["road_label"].map(road_label_mapping)
if "flood_type" in temp_Xs.columns:
    temp_Xs["flood_type"] = temp_Xs["flood_type"].map(flood_type_mapping)
if "damage_level" in temp_Xs.columns:
    temp_Xs["damage_level"] = temp_Xs["damage_level"].map(damage_level_mapping)
temp_Xs = normalised(temp_Xs)  # nomralize all input features between 0 and 1
temp_Xs = temp_Xs.fillna(0)

# Morris (dynamic: only keep features supported by current data schema)
feature_name_map = {
    "length": "Road Length",
    "road_classification": "Road Classification",
    "form_of_way": "Carriageway Type",
    "urban": "Location",
    "lanes": "Lanes",
    "averageWidth": "Road Width",
    "road_label": "Structure",
    "flood_type": "Flood Type",
    "flood_depth": "Flood Depth",
    "damage_ratio": "Damage Ratio",
    "damage_value": "Unit Asset Value",
}

feature_cols = [c for c in feature_name_map.keys() if c in temp_Xs.columns]
D = len(feature_cols)
if D == 0:
    print("No supported direct-sensitivity features available after preprocessing. Skipping.")
    sys.exit(0)

problem = {
    "num_vars": D,
    "names": [feature_name_map[c] for c in feature_cols],
    "bounds": [[0, 1] for _ in range(D)],
}

# Convert input and output data to NumPy arrays
inputs = temp_Xs[feature_cols].to_numpy().astype(np.float64)  # Input variables
outputs = (
    temp_Xs["damage_cost"].to_numpy().astype(np.float64)
)  # Target variable (damage costs)

# Filter inputs and outputs to exclude NaN values
valid_indices = ~np.isnan(outputs)
inputs = inputs[valid_indices, :]
outputs = outputs[valid_indices]

# reshape inputs and outputs
B = inputs.shape[0] // (D + 1)  # Calculate B from the number of rows
N = (D + 1) * B  # Ensure it's a multiple of (D+1)
# Trim inputs and outputs to the correct length
inputs = inputs[:N, :]
outputs = outputs[:N]

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
res_df.to_csv(sens_out_dir / "morris_direct.csv", index=False)
print(f"Wrote direct sensitivity results: {sens_out_dir / 'morris_direct.csv'}")
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
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

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
# plt.savefig(r"C:\Oxford\Research\DAFNI\local\papers\figures\morris_direct.tif", dpi=300)
plt.show()

# %%
# Data
parameters = res_df["Parameters"].tolist()
S1_abs = res_df["S1_abs"].to_numpy(dtype=float)
S1_abs = S1_abs / S1_abs.sum() if S1_abs.sum() else S1_abs
ST = res_df["ST"].to_numpy(dtype=float)

# Create scatter plot
plt.figure(figsize=(6, 5))
plt.scatter(S1_abs, ST, color="b", alpha=0.7, marker="x")

# Annotate points
for i, param in enumerate(parameters):
    plt.annotate(
        param,
        (S1_abs[i], ST[i]),
        # fontsize=10,
        xytext=(5, 5),
        textcoords="offset points",
    )

# Labels and title
plt.xlabel(r"$\mu^*$")
plt.ylabel(r"$\sigma$")
plt.title(
    "Morris Sensitivity Analysis: Mean (abs) and Variance",
    pad=10,
    fontweight="bold",
)
plt.grid(True, linestyle="--", alpha=0.6)

# Show plot
plt.tight_layout()
# plt.savefig(r"C:\Oxford\Research\DAFNI\local\papers\figures\mean_var_direct.tif", dpi=300)
plt.show()


# %%
# Unified marker dictionary for all parameters
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
}
plt.rcParams["font.family"] = "Times New Roman"
plt.rcParams["font.size"] = 16
plt.rcParams["axes.titlesize"] = 18
plt.rcParams["axes.labelsize"] = 16
plt.rcParams["legend.fontsize"] = 14


# Parameters for DIRECT damages
parameters = res_df["Parameters"].tolist()
S1_abs = res_df["S1_abs"].to_numpy(dtype=float)
S1_abs = S1_abs / S1_abs.sum() if S1_abs.sum() else S1_abs
ST = res_df["ST"].to_numpy(dtype=float)

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
        marker=marker_map[param],
        color=color_map[param],  # ← unified color mapping
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
plt.title("Severe Damage", pad=12, fontweight="bold")

plt.grid(True, linestyle="--", alpha=0.6)
# plt.legend(handles=handles, loc="lower right", borderaxespad=0.5)

plt.tight_layout()
out_dir = res_path / "figures" / "scenario5"
out_dir.mkdir(parents=True, exist_ok=True)
plt.savefig(out_dir / "morris_direct_severe.tif", dpi=300, bbox_inches="tight")
plt.show()