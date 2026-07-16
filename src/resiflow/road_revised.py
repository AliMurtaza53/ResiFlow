"""Road Network Flow Model - Functions"""

# Standard library
import os
import logging
import math
import pickle
import sys
import time
import warnings
from collections import defaultdict
from multiprocessing import Pool
from typing import Dict, List, Tuple, Optional

# Third-party
import geopandas as gpd  # type: ignore
import igraph  # type: ignore
import numpy as np
import pandas as pd
from tqdm import tqdm
import gc

# Local
import resiflow.constants as cons
import duckdb

warnings.simplefilter("ignore")
tqdm.pandas()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


def _log_rss(label: str) -> None:
    """Opt-in RSS checkpoint logging (NIRD_LOG_RSS_CHECKPOINTS=1) to localize
    which phase of network_flow_model drives main-process memory growth."""
    if not _env_flag("NIRD_LOG_RSS_CHECKPOINTS"):
        return
    try:
        import psutil

        rss_gb = psutil.Process().memory_info().rss / (1024**3)
        logging.info("RSS checkpoint [%s]: %.2f GB", label, rss_gb)
    except Exception:
        logging.exception("Failed to log RSS checkpoint [%s]", label)
    if _env_flag("NIRD_MEM_PROFILE_TOP_TYPES"):
        try:
            import gc as _gc
            import sys as _sys
            from collections import Counter

            sizes: Counter = Counter()
            counts: Counter = Counter()
            for obj in _gc.get_objects():
                try:
                    sz = _sys.getsizeof(obj)
                except Exception:
                    continue
                tname = type(obj).__name__
                sizes[tname] += sz
                counts[tname] += 1
            top = sizes.most_common(15)
            logging.info(
                "Top object types by shallow size [%s]: %s",
                label,
                "; ".join(
                    f"{name}={sz/(1024**2):.1f}MB(n={counts[name]})"
                    for name, sz in top
                ),
            )
        except Exception:
            logging.exception("Failed to log top object types [%s]", label)


def select_partial_roads(
    road_links: gpd.GeoDataFrame,
    road_nodes: gpd.GeoDataFrame,
    col_name: str,
    list_of_values: List[str],
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Extract partial road network based on road types.

    Parameters
    ----------
    road_links: gpd.GeoDataFrame
        Links of the road network.
    road_nodes: gpd.GeoDataFrame
        Nodes of the road network.
    col_name: str
        The road type column.
    list_of_values:
        The road types to be extracted from the network.

    Returns
    -------
    selected_links: gpd.GeoDataFrame
        Partial road links.
    selected_nodes: gpd.GeoDataFrame
        Partial road nodes.
    """
    # road links selection
    selected_links = road_links[road_links[col_name].isin(list_of_values)].reset_index(
        drop=True
    )
    selected_links.rename(
        columns={"id": "e_id", "start_node": "from_id", "end_node": "to_id"},
        inplace=True,
    )
    # road nodes selection
    sel_node_idx = list(
        set(selected_links.from_id.tolist() + selected_links.to_id.tolist())
    )
    selected_nodes = road_nodes[road_nodes.id.isin(sel_node_idx)]
    selected_nodes.reset_index(drop=True, inplace=True)
    selected_nodes.rename(columns={"id": "nd_id"}, inplace=True)
    selected_nodes["lat"] = selected_nodes["geometry"].y
    selected_nodes["lon"] = selected_nodes["geometry"].x

    return selected_links, selected_nodes


def create_urban_mask(
    etisplus_urban_roads: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """To extract urban areas across Great Britain (GB) based on ETISPLUS datasets.

    Parameters
    ----------
    etisplus_urban_roads: gpd.GeoDataFrame
        D6 ETISplus Roads (2010)

    Returns
    -------
    urban_mask: gpd.GeoDataFrame
        A binary file that spatially identify the urban areas across GB
        with values == 1.
    """
    etisplus_urban_roads = etisplus_urban_roads[
        etisplus_urban_roads["Urban"] == 1
    ].reset_index(drop=True)
    buf_geom = etisplus_urban_roads.geometry.buffer(
        500
    )  # create a buffer of 500 meters
    uni_geom = buf_geom.unary_union  # feature union within the same layer
    temp = gpd.GeoDataFrame(geometry=[uni_geom])
    new_geom = (
        temp.explode()
    )  # explode multi-polygons into separate individual polygons
    cvx_geom = (
        new_geom.convex_hull
    )  # generate convex polygon for each individual polygon

    urban_mask = gpd.GeoDataFrame(
        geometry=cvx_geom[0], crs=etisplus_urban_roads.crs
    ).to_crs("27700")
    return urban_mask


def label_urban_roads(
    road_links: gpd.GeoDataFrame, urban_mask: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Classify road links into urban/suburban roads.

    Parameters
    ----------
    road_links: gpd.GeoDataFrame
        Links of the road network.
    urban_mask: gpd.GeoDataFrame
        A binary file that spatially identify the urban areas across GB.

    Returns
    -------
    road_links: gpd.GeoDataFrame
        Create a column "urban" to classify road links into urban/suburban links.
    """
    temp_file = road_links.sjoin(urban_mask, how="left")
    temp_file["urban"] = temp_file["index_right"].apply(
        lambda x: 0 if pd.isna(x) else 1
    )
    max_values = temp_file.groupby("e_id")["urban"].max()
    road_links = road_links.merge(max_values, on="e_id", how="left")
    return road_links


def find_nearest_node(
    zones: gpd.GeoDataFrame,
    road_nodes: gpd.GeoDataFrame,
    zone_id_column: str,
    node_id_column: str,
) -> Dict[str, str]:
    """Find the nearest road node for each admin unit.

    Parameters
    ----------
    zones: gpd.GeoDataFrame
        Admin units.
    road nodes: gpd.GeoDataFrame
        Nodes of the road network.

    Returns
    -------
    nearest_node_dict: dict
        A dictionary to convert from admin units to their attached road nodes.
    """
    nearest_nodes = gpd.sjoin_nearest(zones, road_nodes)
    nearest_nodes = nearest_nodes.drop_duplicates(subset=[zone_id_column], keep="first")
    nearest_node_dict = dict(
        zip(nearest_nodes[zone_id_column], nearest_nodes[node_id_column])
    )
    return nearest_node_dict  # zone_idx: node_idx


# %%%
# def operate_cost_func(vehicle_type, v_kmph):
#     # fuel cost
#     a, b, c, d = cons.fuel_litre_per_km[vehicle_type].values()
#     L = a / v_kmph + b + c * v_kmph + d * v_kmph**2  # litre per km
#     FC = L * 1.4  # GBP per km

#     # non-fuel cost (only counted for working purposes)
#     a1, b1 = cons.non_fuel_pence_per_km[vehicle_type].values()
#     NFC = a1 + b1 / v_kmph  # pence per km
#     NFC = NFC / 100  # GBP per km
#     return FC + NFC


# def cost_function(vehicle_type, time_hr, distance_mile, toll):
#     distance_km = distance_mile * cons.CONV_MILE_TO_KM
#     vot = cons.vot_pound_per_hour[vehicle_type]
#     if vehicle_type == "car":
#         # logging.info("Private car")
#         ave_occ = 1.1  # average occupancy (Vehicle mileage and occupancy, 2021)
#         c_time = time_hr * ave_occ * vot
#         c_operate = operate_cost_func(vehicle_type, distance_km / time_hr) * distance_km
#         total_cost = c_time + c_operate + toll
#         return total_cost, c_time, c_operate

#     elif vehicle_type == "lgv" or vehicle_type == "ogv":
#         # logging.info("Freight vehicle")
#         c_time = time_hr * vot  # asume single driver
#         c_operate = operate_cost_func(vehicle_type, distance_km / time_hr) * distance_km
#         total_cost = c_time + c_operate + toll
#         return total_cost, c_time, c_operate

#     elif vehicle_type == "psv":
#         # logging.info("Bus transport")
#         # waiting_time_hr = 0.25  # 15 minutes average waiting time
#         c_time = time_hr * vot
#         c_fare = np.minimum(2 + 0.15 * distance_km, 4.5)
#         total_cost = c_time + c_fare
#         return total_cost, c_time, c_fare

#     elif vehicle_type == "rail":
#         # logging.info("Rail transport")
#         # waiting_time_hr = 0.15  # 9 minutes average waiting time
#         c_time = time_hr * vot
#         c_fare = np.minimum(3 + 0.2 * distance_km, 250)
#         total_cost = c_time + c_fare
#         return total_cost, c_time, c_fare


#     else:
#         logging.info("Unknown vehicle type!")
#         sys.exit(1)


# %%
def compute_costs_for_links(
    road_links: pd.DataFrame,
    vehicle_type: str,
    # cols_out=("weight", "time_cost", "operating_cost"),
    cols_out=("time_cost", "operating_cost"),
    chunksize: int | None = None,
    inplace: bool = True,
    eps: float = 1e-6,
):
    def _process_block(df_block: pd.DataFrame):
        # ensure floats for numeric ops
        time_hr = df_block["time_hr"].to_numpy(dtype=float)
        distance_km = (
            df_block["length_mile"].to_numpy(dtype=float) * cons.CONV_MILE_TO_KM
        )
        # toll = df_block["average_toll_cost"].to_numpy(dtype=float)

        # safe speed
        v_kmph = distance_km / np.maximum(time_hr, eps)

        # operate_cost per mile vectorised (use values from cons)
        a, b, c, d = tuple(cons.FUEL_LITRE_PER_KM[vehicle_type].values())
        L = a / np.maximum(v_kmph, eps) + b + c * v_kmph + d * v_kmph**2
        # US fuel price (USD/litre) instead of the legacy UK pump price
        # (~1.4 GBP/L * 1.27). See constants.FUEL_USD_PER_LITRE.
        fuel_price = getattr(cons, "FUEL_USD_PER_LITRE", {}).get(
            vehicle_type, getattr(cons, "DEFAULT_FUEL_USD_PER_LITRE", 0.95)
        )
        FC = L * fuel_price  # USD per mile (fuel component)

        a1, b1 = tuple(cons.NON_FUEL_PENCE_PER_KM[vehicle_type].values())
        NFC = a1 + b1 / np.maximum(v_kmph, eps)  # cents USD per mile
        NFC = NFC / 100.0  # USD per mile

        operate_cost_per_mile = FC + NFC
        operate_cost = operate_cost_per_mile * distance_km  # USD (vector)

        # value of time: allow dict or function
        if hasattr(cons, "VOT_POUND_PER_HOUR"):
            vot = cons.VOT_POUND_PER_HOUR.get(vehicle_type, None)
        else:
            vot = None

        if vot is None:
            try:
                vot = cons.VOT_POUND_PER_HOUR(vehicle_type)
            except Exception as e:
                raise RuntimeError(
                    "Could not obtain VOT from cons (VOT_POUND_PER_HOUR)"
                ) from e

        # compute according to vehicle_type

        if vehicle_type == "car":
            ave_occ = 1.06
            c_time = time_hr * ave_occ * vot
            # total_cost = c_time + operate_cost + toll
            out = np.vstack([c_time, operate_cost]).T

        elif vehicle_type in ("lgv", "ogv"):
            c_time = time_hr * vot
            # total_cost = c_time + operate_cost + toll
            out = np.vstack([c_time, operate_cost]).T

        elif vehicle_type == "psv":
            # waiting time and fare should be counted only once per od flow
            c_time = time_hr * vot
            # c_fare = np.minimum(2 + 0.15 * distance_km, 4.5)
            # total_cost = c_time + c_fare
            out = np.vstack([c_time, np.zeros_like(c_time)]).T

        elif vehicle_type == "rail":
            # waiting time and fare should be counted only once per od flow
            c_time = time_hr * vot
            # c_fare = np.minimum(3 + 0.2 * distance_km, 250)
            # total_cost = c_time + c_fare
            out = np.vstack([c_time, np.zeros_like(c_time)]).T

        else:
            raise ValueError(f"Unknown vehicle_type: {vehicle_type}")

        return pd.DataFrame(out, index=df_block.index, columns=cols_out)

    # choose chunking strategy
    n = len(road_links)
    if chunksize is None or chunksize >= n:
        results = _process_block(road_links)
        if inplace:
            road_links.loc[:, cols_out] = results
            return None
        else:
            return results

    # chunked processing
    if inplace:
        # create columns to avoid reallocation during assignment
        for c in cols_out:
            if c not in road_links.columns:
                road_links[c] = np.nan

        for start in range(0, n, chunksize):
            end = min(start + chunksize, n)
            block_idx = slice(start, end)
            block = road_links.iloc[block_idx]
            res_block = _process_block(block)
            road_links.loc[block.index, cols_out] = res_block.values
        return None
    else:
        pieces = []
        for start in range(0, n, chunksize):
            end = min(start + chunksize, n)
            block = road_links.iloc[start:end]
            pieces.append(_process_block(block))
        return pd.concat(pieces, axis=0).sort_index()


def edge_reclassification_func(
    road_links: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize network classes and assignment tiers for the transport model."""
    from resiflow.networks import normalize_network_links

    return normalize_network_links(road_links)


def edge_initial_speed_func(
    road_links: pd.DataFrame,
    flow_breakpoint_dict: Dict[str, float],
    free_flow_speed_dict: Dict[str, float],
    urban_flow_speed_dict: Dict[str, float],
    min_flow_speed_dict: Dict[str, float],
    max_flow_speed_dict: Dict[str, float] = None,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Calculate the initial vehicle speed for network edges.

    Parameters
    ----------
    road_links: pd.DataFrame
        network link features
    flow_breakpoint_dict: Dict
        the breakpoint flow beyond which vehicle speed start to decrease
    free_flow_speed_dict: Dict
        free-flow vehicle operating speed on roads: M, A(single/dual), B
    urban_flow_speed_dict: Dict
        set the maximum vehicle speed restrictions in urban areas
    min_flow_speed_dict: Dict
        minimum vehicle operating speeds
    max_flow_speed_dict: Dict
        maximum safe vehicel operatin speeds on flooded roads

    Returns
    -------
    road_links: pd.DataFrame
        with speed information
    initial_speed_dict: Dict
        initial vehicle operating speed of existing road links
    """

    from resiflow.networks.assignment import map_tier_profile

    assert "assignment_tier" in road_links.columns or "combined_label" in road_links.columns, (
        "assignment_tier or combined_label column required"
    )
    assert "urban" in road_links.columns, "urban column not exists!"

    # Per-tier default free-flow speed (fallback for links without observed speeds).
    class_free_flow = map_tier_profile(road_links, free_flow_speed_dict)

    if "free_flow_speeds" not in road_links.columns:
        # US fidelity: prefer observed FAF5 link speeds (mph) when present
        # (AB_FinalSpeed/BA_FinalSpeed are the FAF5 model final speeds; Speed_Limit
        # is the posted speed). Fall back to the per-class default otherwise.
        observed_speed = None
        for col in ("AB_FinalSpeed", "BA_FinalSpeed", "Speed_Limit"):
            if col in road_links.columns:
                vals = pd.to_numeric(road_links[col], errors="coerce")
                vals = vals.where(vals > 0)
                observed_speed = (
                    vals if observed_speed is None else observed_speed.combine_first(vals)
                )
        if observed_speed is not None:
            road_links["free_flow_speeds"] = observed_speed.fillna(class_free_flow)
        else:
            road_links["free_flow_speeds"] = class_free_flow

    # Urban speed restriction: cap free-flow at the urban limit for urban links.
    # Use min() (rather than a hard override) so observed posted speeds cannot
    # exceed the urban cap, while sub-cap class/observed speeds are preserved.
    urban_cap = map_tier_profile(road_links, urban_flow_speed_dict)
    urban_mask = road_links["urban"] == 1
    road_links.loc[urban_mask, "free_flow_speeds"] = np.minimum(
        pd.to_numeric(road_links.loc[urban_mask, "free_flow_speeds"], errors="coerce"),
        pd.to_numeric(urban_cap[urban_mask], errors="coerce"),
    )
    road_links["min_flow_speeds"] = map_tier_profile(road_links, min_flow_speed_dict)
    road_links["initial_flow_speeds"] = road_links["free_flow_speeds"]
    road_links["breakpoint_flows"] = map_tier_profile(road_links, flow_breakpoint_dict)
    if max_flow_speed_dict is not None:
        road_links["max_speeds"] = road_links["e_id"].map(max_flow_speed_dict)
        # if max < min: close the roads
        road_links.loc[
            road_links.max_speeds < road_links.min_flow_speeds, "initial_flow_speeds"
        ] = 0.0
        # if min < max < free
        road_links.loc[
            (road_links.max_speeds >= road_links.min_flow_speeds)
            & (road_links.max_speeds < road_links.free_flow_speeds),
            "initial_flow_speeds",
        ] = road_links.max_speeds
        # if max > free: free flow speeds (by default)
        # remove the closed/damaged roads
        road_links = road_links[road_links["initial_flow_speeds"] > 0]
        road_links.reset_index(drop=True, inplace=True)

    return road_links


def edge_init(
    road_links: gpd.GeoDataFrame,
    flow_breakpoint_dict: Dict[str, float],
    capacity_plph_dict: Dict[str, float],
    free_flow_speed_dict: Dict[str, float],
    urban_flow_speed_dict: Dict[str, float],
    min_flow_speed_dict: Dict[str, float],
    max_flow_speed_dict: Dict[str, float],
) -> gpd.GeoDataFrame:
    """Network edges initialisation.

    Parameters
    ----------
    road_links: gpd.GeoDataFrame
    capacity_plph_dict: Dict
        The designed edge capacity (per lane per hour).
    free_flow_speed_dict: Dict
        The free-flow edge speed of different types of road links.
    urban_flow_speed_dict: Dict
        The maximum vehicle operating speed restriction in urban areas.
    min_flow_speed_dict: Dict
        The minimum vehicle operating speeds.
    max_flow_speed_dict: Dict
        The maximum flow speed of the flooded road links.

    Returns
    -------
    road_links: gpd.GeoDataFrame
        Road links with added attributes.
    """
    # reclassification
    road_links = edge_reclassification_func(road_links)
    road_links = edge_initial_speed_func(
        road_links,
        flow_breakpoint_dict,
        free_flow_speed_dict,
        urban_flow_speed_dict,
        min_flow_speed_dict,
        max_flow_speed_dict,
    )
    assert "assignment_tier" in road_links.columns or "combined_label" in road_links.columns, (
        "assignment_tier or combined_label column required"
    )
    assert (
        "initial_flow_speeds" in road_links.columns
    ), "initial_flow_speeds column not exists!"

    # initialise key variables
    road_links["acc_flow"] = 0.0
    if "flow_cap_plph" in road_links.columns:
        per_lane_plph = pd.to_numeric(road_links["flow_cap_plph"], errors="coerce")
        road_links["acc_capacity"] = per_lane_plph * road_links["lanes"] * 24
    else:
        from resiflow.networks.assignment import map_tier_profile

        road_links["acc_capacity"] = (
            map_tier_profile(road_links, capacity_plph_dict) * road_links["lanes"] * 24
        )
    road_links["acc_speed"] = road_links["initial_flow_speeds"]
    # current state mirrors initial state
    road_links["current_capacity"] = road_links["acc_capacity"]
    road_links["current_speed"] = road_links["acc_speed"]
    road_links["current_flow"] = road_links["acc_flow"]

    # remove invalid road links
    road_links = road_links[road_links.acc_capacity > 0.5].reset_index(drop=True)

    return road_links


def update_edge_speed(
    road_links: pd.DataFrame, inplace: bool = True
) -> pd.DataFrame | None:
    from resiflow.networks.assignment import map_tier_profile

    acc_flow = road_links["acc_flow"].to_numpy(dtype=float)  # vehicles per day
    vp = acc_flow / 24.0  # vehicles per hour
    initial_speed = road_links["initial_flow_speeds"].to_numpy(dtype=float)
    min_speed = road_links["min_flow_speeds"].to_numpy(dtype=float)
    breakpoint_flow = road_links["breakpoint_flows"].to_numpy(dtype=float)

    if "congestion_factor" in road_links.columns:
        factor = pd.to_numeric(road_links["congestion_factor"], errors="coerce").fillna(0.0)
        factor = factor.to_numpy(dtype=float)
    else:
        default_factors = {
            "freeway": 0.033,
            "arterial": 0.033,
            "collector": 0.05,
            "local_access": 0.05,
        }
        factor = map_tier_profile(road_links, default_factors).to_numpy(dtype=float)

    # compute reduction only where vp > breakpoint_flow
    excess = vp - breakpoint_flow
    excess = np.where(excess > 0.0, excess, 0.0)
    reduction = factor * excess
    speed = initial_speed - reduction

    # enforce minimum
    speed = np.maximum(speed, min_speed)

    # write result
    if inplace:
        road_links["acc_speed"] = speed
        return None
    else:
        return road_links.assign(acc_speed=speed)


def create_igraph_network(
    road_links: gpd.GeoDataFrame,
    vehicle_type: str,
) -> igraph.Graph:
    """Create an undirected igraph network."""
    # cols = road_links.columns.tolist()
    road_links["length_mile"] = road_links.geometry.length * cons.CONV_METER_TO_MILE
    road_links["time_hr"] = 1.0 * road_links.length_mile / road_links.acc_speed
    compute_costs_for_links(
        road_links=road_links,
        vehicle_type=vehicle_type,
        chunksize=np.maximum(road_links.shape[0] // 10, 100_000),
        inplace=True,
    )  # time_cost, operating_cost
    road_links["weight"] = (
        road_links.time_cost + road_links.operating_cost + road_links.average_toll_cost
    )
    graph_df = road_links[
        [
            "from_id",
            "to_id",
            "e_id",
            "weight",
            "time_cost",
            "operating_cost",
            "average_toll_cost",
            "length_mile",
        ]
    ]

    network = igraph.Graph.TupleList(
        graph_df.itertuples(index=False),
        edge_attrs=list(graph_df.columns)[2:],
        directed=False,
    )
    eids = list(network.es["e_id"])
    index_map = dict(zip(eids, range(len(eids))))
    road_links["e_idx"] = road_links["e_id"].map(index_map)
    if len(road_links[road_links.e_idx.isnull()]) > 0:
        logging.info("Error: cannot find e_id in the network!")
        sys.exit()

    return network, road_links


def update_network_structure(
    num_of_edges: int,
    network: igraph.Graph,
    temp_edge_flow: pd.DataFrame,
    road_links: gpd.GeoDataFrame,
) -> igraph.Graph:
    """Drop fully utilised edges and Update edge weights.

    Parameters
    ----------
    network: igraph network
    temp_edge_flow: the remaining edge capacity at the current iteration
    road_links: road links

    Returns
    -------
    The updated igraph network
    """
    # update remaining edge capacities
    road_links_valid = road_links.dropna(subset=["e_idx"])
    logging.info(
        f"#road_links: {len(road_links)}, #valid_links: {len(road_links_valid)}"
    )
    temp_edge_flow = temp_edge_flow.merge(
        road_links_valid[["e_id", "e_idx", "acc_capacity", "current_capacity"]],
        on="e_id",
        how="left",
    )
    temp_edge_flow["e_idx"] = temp_edge_flow["e_idx"].astype(int)
    # create mask
    ratio = temp_edge_flow["acc_capacity"] / temp_edge_flow["current_capacity"].replace(
        0, np.nan
    )
    # fully utilised if remaining capacity < 1 vehicle or < 1% of original
    # capacity (matches upstream DAFNI-NIRD df56a1d, 2026-02-25; ResiFlow had
    # been on the stricter pre-fix 0.1% threshold — see
    # notes/perf_findings/GOAL6_UPSTREAM_DRIFT_AUDIT.md)
    mask = (temp_edge_flow["acc_capacity"] < 1) | (ratio < 0.01)
    # drop fully utilised edges from the network
    zero_capacity_edges = set(
        temp_edge_flow.loc[
            mask,
            "e_idx",
        ].tolist()
    )
    network.delete_edges(list(zero_capacity_edges))
    num_of_edges_update = len(list(network.es))
    if num_of_edges_update == num_of_edges:
        logging.info("The network structure does not change!")
        return network, road_links
    logging.info(f"The remaining number of edges in the network: {num_of_edges_update}")

    # convert edge_id to edge_idx as per network edges
    index_map = {eid: idx for idx, eid in enumerate(network.es["e_id"])}
    road_links["e_idx"] = road_links["e_id"].map(index_map)  # return nan if empty

    return network, road_links


def extract_od_pairs(
    od: pd.DataFrame,
) -> Tuple[List[str], Dict[str, List[str]], Dict[str, List[int]]]:
    """Prepare the OD matrix.

    Parameters
    ----------
    od: pd.DataFrame
        Table of origin-destination passenger flows.

    Returns
    -------
    list_of_origin_nodes: list
        A list of origin nodes.
    dict_of_destination_nodes: dict[str, list[str]]
        A dictionary recording a list of destination nodes for each origin node.
    dict_of_origin_supplies: dict[str, list[int]]
        A dictionary recording a list of flows for each origin-destination pair.
    """
    list_of_origin_nodes = []
    dict_of_destination_nodes: Dict[str, List[str]] = defaultdict(list)
    dict_of_origin_supplies: Dict[str, List[float]] = defaultdict(list)
    for row in od.itertuples():
        from_node = row["origin_node"]
        to_node = row["destination_node"]
        Count: float = row["Car21"]
        list_of_origin_nodes.append(from_node)  # [nd_id...]
        dict_of_destination_nodes[from_node].append(to_node)  # {nd_id: [nd_id...]}
        dict_of_origin_supplies[from_node].append(Count)  # {nd_id: [car21...]}

    # Extract identical origin nodes
    list_of_origin_nodes = list(set(list_of_origin_nodes))
    list_of_origin_nodes.sort()

    return (
        list_of_origin_nodes,
        dict_of_destination_nodes,
        dict_of_origin_supplies,
    )


def update_od_matrix(
    temp_flow_matrix: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    """Split OD allocations into routable rows and isolated leftovers.

    Parameters
    ----------
    temp_flow_matrix : pd.DataFrame
        DataFrame with columns ``origin``, ``destination``, ``path`` (list of edge ids),
        and ``flow`` representing per-OD assignments prior to capacity checks.

    Returns
    -------
    pd.DataFrame
        Filtered copy containing only rows with a non-empty path.
    pd.DataFrame
        Rows whose ``path`` lists are empty (no feasible route found).
    float
        Total isolated flow (sum of the ``flow`` values with empty paths).
    """

    mask = temp_flow_matrix["path"].apply(lambda x: len(x) == 0)
    # isolated od
    isolated_flow_matrix = temp_flow_matrix.loc[mask].reset_index(drop=True)
    isolated_flow_matrix.drop(columns="path", inplace=True)
    temp_isolation = isolated_flow_matrix.flow.sum()  # 666
    # allocated od (before adjustment)
    temp_flow_matrix = temp_flow_matrix[~mask].reset_index(drop=True)  # 1032

    return (
        temp_flow_matrix,
        isolated_flow_matrix,
        temp_isolation,
    )


def find_least_cost_path(
    params: Tuple,
) -> Tuple[int, List[str], List[int], List[float]]:
    """Solve shortest paths for all destinations of a single origin.

    Parameters
    ----------
    params : Tuple
        Tuple of ``(origin_node, destination_nodes, flows)`` where the first entry is
        the origin vertex id (string), the second is a list of destination ids, and the
        third is the corresponding list of OD flows.

    Returns
    -------
    Tuple[int, List[str], List[List[int]], List[float]]
        The origin id, destination id list, list of edge-id paths (one per destination),
        and the list of flows matching the inputs.
    """
    origin_node, destination_nodes, flows = params
    dest_batch_size = int(os.environ.get("NIRD_SHORTEST_PATH_DEST_BATCH", "0"))
    if dest_batch_size <= 0:
        dest_batch_size = len(destination_nodes) if destination_nodes else 1

    paths = []
    for start in range(0, len(destination_nodes), dest_batch_size):
        dest_batch = destination_nodes[start : start + dest_batch_size]
        paths.extend(
            shared_network.get_shortest_paths(
                v=origin_node,
                to=dest_batch,
                weights="weight",
                mode="out",
                output="epath",
            )
        )  # paths: o - d(s)

    return (
        origin_node,
        destination_nodes,
        paths,
        flows,
    )


def worker_init_path(
    shared_network_pkl: bytes,
) -> None:
    """Load the shared igraph network inside each worker process.

    Parameters
    ----------
    shared_network_pkl : bytes
        Pickled bytes of the igraph ``Graph`` to be shared across worker processes.

    Returns
    -------
    None
        The function sets the module-level ``shared_network`` variable in-place.
    """
    global shared_network
    affinity_spec = os.environ.get("NIRD_WORKER_CPU_AFFINITY", "").strip()
    if affinity_spec:
        try:
            import psutil

            cores = [
                int(c)
                for c in affinity_spec.replace(",", " ").split()
                if c.strip() != ""
            ]
            if cores:
                psutil.Process().cpu_affinity(cores)
                logging.info("Worker pinned to CPU affinity: %s", cores)
        except Exception:
            logging.exception("Failed to set worker CPU affinity; continuing unpinned.")
    shared_network = pickle.loads(shared_network_pkl)
    return None


def refresh_worker_network(shared_network_pkl: bytes) -> None:
    """Update the module-level ``shared_network`` in a persistent pool worker.

    Used by the opt-in persistent-pool path (``NIRD_PERSISTENT_LCP_POOL``) to
    push each iteration's updated network (edges dropped by
    ``update_network_structure``) into already-running workers, instead of
    respawning the pool (and re-pinning affinity, re-importing dependencies)
    every iteration. CPU affinity is set once at worker startup in
    ``worker_init_path`` and is not touched here.
    """
    global shared_network
    shared_network = pickle.loads(shared_network_pkl)
    return None


def _append_or_create_table(
    conn,
    table_name: str,
    df: pd.DataFrame,
    registered_name: str,
) -> None:
    """Append a DataFrame into DuckDB, creating the target table on first use."""
    conn.register(registered_name, df)
    exists = (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
        > 0
    )
    if exists:
        conn.execute(f"INSERT INTO {table_name} SELECT * FROM {registered_name}")
    else:
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM {registered_name}")
    conn.unregister(registered_name)


def _sql_path(path: str) -> str:
    """Return a DuckDB-safe path for single-quoted SQL strings."""
    return str(path).replace("\\", "/").replace("'", "''")


def _safe_event_id(value) -> str:
    """Normalize event identifiers for folder names."""
    text = str(value).strip() if value is not None else "event_000001"
    if not text:
        text = "event_000001"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def load_event_damaged_edges(
    damaged_edges_path: Optional[str],
    network,
) -> Tuple[Dict[str, Dict[int, str]], Dict[int, List[str]], pd.DataFrame]:
    """Load event damaged edges and map edge IDs to igraph edge indices.

    The input may be CSV or Parquet and must contain ``e_id`` plus either
    ``event_id`` or a depth/flood key pair. Missing optional damage columns are
    tolerated because path filtering only needs edge membership.
    """
    if damaged_edges_path is None or str(damaged_edges_path).strip() == "":
        logging.info("No event damaged-edge file provided.")
        return {}, {}, pd.DataFrame(columns=["event_id", "e_id", "edge_idx"])

    damaged_path = str(damaged_edges_path)
    if not os.path.exists(damaged_path):
        raise FileNotFoundError(f"Event damaged-edge file not found: {damaged_path}")

    if damaged_path.lower().endswith((".pq", ".parquet")):
        damaged_df = pd.read_parquet(damaged_path)
    else:
        damaged_df = pd.read_csv(damaged_path)
    if damaged_df.empty:
        logging.warning("Event damaged-edge file is empty: %s", damaged_path)
        return {}, {}, pd.DataFrame(columns=["event_id", "e_id", "edge_idx"])
    if "e_id" not in damaged_df.columns:
        raise ValueError("Event damaged-edge file must contain an e_id column")

    if "event_id" not in damaged_df.columns:
        if {"depth_key", "flood_key"}.issubset(damaged_df.columns):
            damaged_df["event_id"] = (
                damaged_df["depth_key"].astype(str)
                + "_"
                + damaged_df["flood_key"].astype(str)
            )
        elif "flood_key" in damaged_df.columns:
            damaged_df["event_id"] = damaged_df["flood_key"].astype(str)
        elif "depth_key" in damaged_df.columns:
            damaged_df["event_id"] = damaged_df["depth_key"].astype(str)
        else:
            damaged_df["event_id"] = "event_000001"

    edge_idx_by_eid = {str(eid): idx for idx, eid in enumerate(network.es["e_id"])}
    damaged_df = damaged_df[["event_id", "e_id"]].copy()
    damaged_df["event_id"] = damaged_df["event_id"].map(_safe_event_id)
    damaged_df["e_id"] = damaged_df["e_id"].astype(str)
    damaged_df["edge_idx"] = damaged_df["e_id"].map(edge_idx_by_eid)
    missing_count = int(damaged_df["edge_idx"].isna().sum())
    if missing_count:
        logging.warning(
            "Event damaged-edge loader skipped %s e_id values not present in network.",
            missing_count,
        )
    damaged_df = damaged_df.dropna(subset=["edge_idx"]).drop_duplicates(
        ["event_id", "edge_idx"]
    )
    damaged_df["edge_idx"] = damaged_df["edge_idx"].astype(int)

    event_edges: Dict[str, Dict[int, str]] = defaultdict(dict)
    edge_events: Dict[int, List[str]] = defaultdict(list)
    for row in damaged_df.itertuples(index=False):
        event_edges[row.event_id][int(row.edge_idx)] = str(row.e_id)
        edge_events[int(row.edge_idx)].append(row.event_id)

    logging.info(
        "Loaded %s event(s), %s event-edge rows, %s unique damaged edges from %s.",
        len(event_edges),
        len(damaged_df),
        damaged_df["edge_idx"].nunique() if not damaged_df.empty else 0,
        damaged_path,
    )
    for event_id, edges in event_edges.items():
        logging.info("Event %s damaged edges: %s", event_id, len(edges))

    return dict(event_edges), dict(edge_events), damaged_df


def _write_candidate_part(
    event_dir: str,
    part_index: int,
    rows: List[Tuple],
    columns: List[str],
) -> str:
    part_dir = os.path.join(event_dir, "parts")
    os.makedirs(part_dir, exist_ok=True)
    part_path = os.path.join(part_dir, f"candidates_part_{part_index:06d}.pq")
    pd.DataFrame(rows, columns=columns).to_parquet(part_path, index=False)
    return part_path


def write_event_disrupted_candidates(
    conn,
    network,
    damaged_edges_path: Optional[str],
    out_dir: str,
    time_expr: str,
    fare_expr: str,
    chunk_size: int,
    iter_flag: int,
    combine_parts: bool = False,
) -> Dict[str, Dict[str, int]]:
    """Write only OD rows whose path intersects event damaged edges."""
    event_edges, edge_events, _ = load_event_damaged_edges(damaged_edges_path, network)
    if not event_edges:
        logging.warning("No event damaged edges loaded; event candidate output is empty.")
        return {}

    candidates_root = os.path.join(out_dir, "event_disrupted_candidates")
    os.makedirs(candidates_root, exist_ok=True)
    total_rows = conn.execute("SELECT COUNT(*) FROM temp_flow_matrix_input").fetchone()[0] or 0
    chunk_size = max(1, int(chunk_size))
    edge_eid = np.asarray(network.es["e_id"], dtype=object)
    candidate_columns = [
        "od_id",
        "origin_node",
        "destination_node",
        "flow",
        "path",
        "flood_links",
        "operating_cost_per_flow",
        "time_cost_per_flow",
        "toll_cost_per_flow",
        "fare_cost_per_flow",
        "length_mile",
    ]
    buffers: Dict[str, List[Tuple]] = defaultdict(list)
    summary: Dict[str, Dict[str, int]] = {
        event_id: {"rows": 0, "parts": 0} for event_id in event_edges
    }
    max_buffer_rows = int(os.environ.get("NIRD_EVENT_CANDIDATE_BUFFER_ROWS", "50000"))
    filter_start = time.time()

    def flush_event(event_id: str) -> None:
        rows = buffers[event_id]
        if not rows:
            return
        event_dir = os.path.join(candidates_root, event_id)
        part_path = _write_candidate_part(
            event_dir,
            summary[event_id]["parts"] + 1,
            rows,
            candidate_columns,
        )
        summary[event_id]["rows"] += len(rows)
        summary[event_id]["parts"] += 1
        logging.info(
            "Wrote event candidate part for event=%s rows=%s path=%s",
            event_id,
            len(rows),
            part_path,
        )
        buffers[event_id] = []

    logging.info(
        "Filtering event disrupted candidates for iteration %s over %s OD paths.",
        iter_flag,
        total_rows,
    )
    for start in tqdm(
        range(0, total_rows, chunk_size),
        desc="Writing event candidates:",
        unit="chunk",
    ):
        chunk = conn.execute(
            f"""
            SELECT
                i.od_id,
                i.origin,
                i.destination,
                i.path AS path_idx,
                m.e_id AS path,
                m.flow,
                m.fuel,
                {time_expr} AS time,
                m.toll,
                {fare_expr} AS fare,
                m.length_mile
            FROM (
                SELECT od_id, origin, destination, path
                FROM temp_flow_matrix_input
                LIMIT {chunk_size}
                OFFSET {start}
            ) i
            JOIN temp_flow_matrix m USING (od_id, origin, destination)
            """
        ).fetchdf()
        if chunk.empty:
            continue
        for row in chunk.itertuples(index=False):
            path_idx = [int(v) for v in list(row.path_idx)]
            touched: Dict[str, List[int]] = defaultdict(list)
            for idx in path_idx:
                for event_id in edge_events.get(idx, []):
                    touched[event_id].append(idx)
            if not touched:
                continue
            path_eids = [str(e) for e in list(row.path)]
            for event_id, hit_indices in touched.items():
                event_edge_lookup = event_edges[event_id]
                flood_links = [
                    event_edge_lookup[idx]
                    for idx in hit_indices
                    if idx in event_edge_lookup
                ]
                buffers[event_id].append(
                    (
                        int(row.od_id),
                        str(row.origin),
                        str(row.destination),
                        float(row.flow),
                        path_eids,
                        flood_links,
                        float(row.fuel),
                        float(row.time),
                        float(row.toll),
                        float(row.fare),
                        float(row.length_mile),
                    )
                )
                if len(buffers[event_id]) >= max_buffer_rows:
                    flush_event(event_id)
        del chunk
        gc.collect()

    for event_id in list(buffers):
        flush_event(event_id)

    for event_id in event_edges:
        event_dir = os.path.join(candidates_root, event_id)
        parts_dir = os.path.join(event_dir, "parts")
        if combine_parts and summary[event_id]["parts"] > 0:
            combined_path = os.path.join(event_dir, "disrupted_candidates.pq")
            conn.execute(
                f"""
                COPY (
                    SELECT *
                    FROM read_parquet('{_sql_path(os.path.join(parts_dir, "*.pq"))}')
                ) TO '{_sql_path(combined_path)}' (FORMAT PARQUET);
                """
            )
            logging.info("Combined event candidate parts for %s into %s", event_id, combined_path)
        output_size = 0
        if os.path.isdir(parts_dir):
            output_size = sum(
                os.path.getsize(os.path.join(parts_dir, name))
                for name in os.listdir(parts_dir)
                if name.endswith(".pq")
            )
        logging.info(
            "Event candidate summary: event=%s rows=%s parts=%s output_bytes=%s",
            event_id,
            summary[event_id]["rows"],
            summary[event_id]["parts"],
            output_size,
        )
    logging.info(
        "Event filtering complete in %.2f seconds. Full odpfc skipped; global path_index skipped.",
        time.time() - filter_start,
    )
    return summary


def realize_paths_streaming(
    network,
    road_links,
    conn,
    temp_flow_table: str = "temp_flow_matrix_input",
    od_output_table: str = "temp_flow_matrix",
    edge_output_table: str = "temp_edge_flow",
    chunk_size: int = 100_000,
    persist_debug_tables: bool = False,
    create_full_temp_flow_matrix: bool = True,
    event_candidates_out_dir: Optional[str] = None,
    damaged_edges_path: Optional[str] = None,
    combine_event_candidate_parts: bool = False,
    vehicle_type: str = "car",
) -> None:
    """Realize OD paths with streaming arrays instead of global path-edge expansion.

    This preserves the current assignment semantics: edge ratios are computed from
    unadjusted candidate edge flow, OD flow is scaled by the minimum edge ratio on
    its path, and adjusted edge flow is accumulated from those adjusted OD flows.
    """

    total_rows = (
        conn.execute(f"SELECT COUNT(*) FROM {temp_flow_table}").fetchone()[0] or 0
    )
    if total_rows == 0:
        logging.info("No rows available for streaming path realization; skipping.")
        return

    chunk_size = max(1, int(chunk_size))
    logging.info(
        "Streaming path realization over %s OD path rows in chunks of %s rows.",
        total_rows,
        chunk_size,
    )

    edges = network.es
    edge_eid = np.asarray(edges["e_id"], dtype=object)
    edge_time = np.asarray(edges["time_cost"], dtype=np.float64)
    edge_fuel = np.asarray(edges["operating_cost"], dtype=np.float64)
    edge_toll = np.asarray(edges["average_toll_cost"], dtype=np.float64)
    edge_length = np.asarray(edges["length_mile"], dtype=np.float64)
    edge_count = len(edge_eid)

    # Vectorized lookup (pandas reindex) instead of a per-edge Python dict.get
    # loop, which profiled at ~21s of ~87s in realize_paths_streaming on a
    # 200k-OD/CONUS-scale run (see notes/perf_findings/GOAL6_TEST_RESULTS.md).
    # keep="last" matches the previous dict-construction behavior for any
    # duplicate e_id rows (dict silently keeps the last value written).
    cap_by_eid = (
        road_links.drop_duplicates(subset="e_id", keep="last")
        .set_index("e_id")["acc_capacity"]
    )
    edge_capacity = (
        cap_by_eid.reindex(edge_eid).fillna(0.0).to_numpy(dtype=np.float64)
    )

    edge_total_flow = np.zeros(edge_count, dtype=np.float64)
    adjusted_edge_flow = np.zeros(edge_count, dtype=np.float64)
    pass1_start = time.time()

    for table in [
        od_output_table,
        edge_output_table,
        "od_results_iter",
        "od_adjustment",
        "temp_edge_flow",
        "temp_flow_matrix",
        "temp_od_assignment",
        "temp_iteration_costs",
    ]:
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    od_columns = [
        "od_id",
        "origin",
        "destination",
        "e_id",
        "flow",
        "fuel",
        "time",
        "toll",
        "length_mile",
    ]

    for start in tqdm(
        range(0, total_rows, chunk_size),
        desc="Streaming realization pass 1:",
        unit="chunk",
    ):
        chunk = conn.execute(
            f"""
            SELECT od_id, origin, destination, path, flow
            FROM {temp_flow_table}
            LIMIT {chunk_size}
            OFFSET {start}
            """
        ).fetchdf()
        if chunk.empty:
            continue

        out_rows = []
        for row in chunk.itertuples(index=False):
            path = np.asarray(row.path, dtype=np.int64)
            flow = float(row.flow) if row.flow is not None else 0.0
            if path.size == 0:
                continue
            np.add.at(edge_total_flow, path, flow)
            if create_full_temp_flow_matrix:
                out_rows.append(
                    (
                        int(row.od_id),
                        str(row.origin),
                        str(row.destination),
                        edge_eid[path].tolist(),
                        flow,
                        float(edge_fuel[path].sum()),
                        float(edge_time[path].sum()),
                        float(edge_toll[path].sum()),
                        float(edge_length[path].sum()),
                    )
                )

        if out_rows:
            od_df = pd.DataFrame(out_rows, columns=od_columns)
            _append_or_create_table(conn, "od_results_iter", od_df, "od_results_tmp")
        del chunk
        gc.collect()
    logging.info(
        "Streaming realization pass 1 complete in %.2f seconds. "
        "create_full_temp_flow_matrix=%s.",
        time.time() - pass1_start,
        create_full_temp_flow_matrix,
    )

    edge_ratio = np.ones(edge_count, dtype=np.float64)
    mask = edge_total_flow > 0
    edge_ratio[mask] = np.minimum(
        edge_capacity[mask] / np.where(edge_total_flow[mask] == 0, 1, edge_total_flow[mask]),
        1.0,
    )

    adj_columns = ["od_id", "origin", "destination", "adjust_r"]
    assignment_columns = ["origin", "destination", "flow"]
    event_edges: Dict[str, Dict[int, str]] = {}
    edge_events: Dict[int, List[str]] = {}
    candidate_columns = [
        "od_id",
        "origin_node",
        "destination_node",
        "flow",
        "path",
        "flood_links",
        "operating_cost_per_flow",
        "time_cost_per_flow",
        "toll_cost_per_flow",
        "fare_cost_per_flow",
        "length_mile",
    ]
    candidate_buffers: Dict[str, List[Tuple]] = defaultdict(list)
    candidate_summary: Dict[str, Dict[str, int]] = {}
    candidate_write_seconds = 0.0
    # Vectorized per-event damaged-edge lookup (boolean mask + value array per
    # event, indexed by igraph edge index) instead of a per-path, per-edge
    # Python dict.get loop, which profiled as the largest remaining hotspot
    # in this function (see notes/perf_findings/GOAL7_PROFILING_AND_STRATEGY_RESULTS.md).
    event_ids_list: List[str] = []
    event_damaged_mask: Dict[str, np.ndarray] = {}
    event_flood_link_arr: Dict[str, np.ndarray] = {}
    if not create_full_temp_flow_matrix and event_candidates_out_dir and damaged_edges_path:
        event_edges, edge_events, _ = load_event_damaged_edges(damaged_edges_path, network)
        event_ids_list = list(event_edges.keys())
        for event_id, edge_lookup in event_edges.items():
            mask_arr = np.zeros(edge_count, dtype=bool)
            val_arr = np.empty(edge_count, dtype=object)
            if edge_lookup:
                idxs = np.fromiter(edge_lookup.keys(), dtype=np.int64, count=len(edge_lookup))
                vals = np.asarray(list(edge_lookup.values()), dtype=object)
                mask_arr[idxs] = True
                val_arr[idxs] = vals
            event_damaged_mask[event_id] = mask_arr
            event_flood_link_arr[event_id] = val_arr
        candidate_summary = {
            event_id: {"rows": 0, "parts": 0} for event_id in event_edges
        }
        os.makedirs(
            os.path.join(event_candidates_out_dir, "event_disrupted_candidates"),
            exist_ok=True,
        )
        logging.info(
            "Patch 5 fused event-candidate writing enabled inside streaming pass 2."
        )
    elif not create_full_temp_flow_matrix:
        logging.info(
            "Full temp_flow_matrix is disabled and no event-candidate file was provided; "
            "streaming will write compact assignment/cost tables only."
        )

    max_buffer_rows = int(os.environ.get("NIRD_EVENT_CANDIDATE_BUFFER_ROWS", "50000"))

    def flush_candidate_event(event_id: str) -> None:
        nonlocal candidate_write_seconds
        rows = candidate_buffers[event_id]
        if not rows:
            return
        write_start = time.time()
        event_dir = os.path.join(
            event_candidates_out_dir,
            "event_disrupted_candidates",
            event_id,
        )
        part_path = _write_candidate_part(
            event_dir,
            candidate_summary[event_id]["parts"] + 1,
            rows,
            candidate_columns,
        )
        candidate_write_seconds += time.time() - write_start
        candidate_summary[event_id]["rows"] += len(rows)
        candidate_summary[event_id]["parts"] += 1
        logging.info(
            "Wrote fused event candidate part for event=%s rows=%s path=%s",
            event_id,
            len(rows),
            part_path,
        )
        candidate_buffers[event_id] = []

    cost_fuel_total = 0.0
    cost_time_total = 0.0
    cost_toll_total = 0.0
    cost_fare_total = 0.0
    assigned_flow_total = 0.0
    pass2_start = time.time()
    for start in tqdm(
        range(0, total_rows, chunk_size),
        desc="Streaming realization pass 2:",
        unit="chunk",
    ):
        chunk = conn.execute(
            f"""
            SELECT od_id, origin, destination, path, flow
            FROM {temp_flow_table}
            LIMIT {chunk_size}
            OFFSET {start}
            """
        ).fetchdf()
        if chunk.empty:
            continue

        adj_rows = []
        assignment_rows = []
        for row in chunk.itertuples(index=False):
            path = np.asarray(row.path, dtype=np.int64)
            flow = float(row.flow) if row.flow is not None else 0.0
            origin = str(row.origin)
            destination = str(row.destination)
            if path.size == 0:
                adjust_r = 1.0
                assigned_flow = flow
                fuel = time_cost = toll = length_mile = 0.0
            else:
                adjust_r = float(edge_ratio[path].min())
                assigned_flow = flow * adjust_r
                np.add.at(adjusted_edge_flow, path, assigned_flow)
                fuel = float(edge_fuel[path].sum())
                time_cost = float(edge_time[path].sum())
                toll = float(edge_toll[path].sum())
                length_mile = float(edge_length[path].sum())
            if create_full_temp_flow_matrix:
                adj_rows.append((int(row.od_id), origin, destination, adjust_r))
            else:
                assignment_rows.append((origin, destination, assigned_flow))
                if vehicle_type == "psv":
                    adjusted_time_cost = (
                        time_cost + 0.25 * cons.VOT_POUND_PER_HOUR[vehicle_type]
                    )
                    fare = min(2.0 + 0.15 * length_mile * cons.CONV_MILE_TO_KM, 4.5)
                elif vehicle_type == "rail":
                    adjusted_time_cost = (
                        time_cost + 0.15 * cons.VOT_POUND_PER_HOUR[vehicle_type]
                    )
                    fare = min(3.0 + 0.2 * length_mile * cons.CONV_MILE_TO_KM, 250.0)
                else:
                    adjusted_time_cost = time_cost
                    fare = 0.0
                assigned_flow_total += assigned_flow
                cost_fuel_total += assigned_flow * fuel
                cost_time_total += assigned_flow * adjusted_time_cost
                cost_toll_total += assigned_flow * toll
                cost_fare_total += assigned_flow * fare

                if event_ids_list and path.size > 0:
                    path_eids: Optional[List[str]] = None
                    for event_id in event_ids_list:
                        hit_mask = event_damaged_mask[event_id][path]
                        if not hit_mask.any():
                            continue
                        if path_eids is None:
                            path_eids = [str(e) for e in edge_eid[path].tolist()]
                        flood_links = event_flood_link_arr[event_id][
                            path[hit_mask]
                        ].tolist()
                        candidate_buffers[event_id].append(
                            (
                                int(row.od_id),
                                origin,
                                destination,
                                assigned_flow,
                                path_eids,
                                flood_links,
                                fuel,
                                adjusted_time_cost,
                                toll,
                                fare,
                                length_mile,
                            )
                        )
                        if len(candidate_buffers[event_id]) >= max_buffer_rows:
                            flush_candidate_event(event_id)

        if adj_rows:
            adj_df = pd.DataFrame(adj_rows, columns=adj_columns)
            _append_or_create_table(conn, "od_adjustment", adj_df, "od_adjust_tmp")
        if assignment_rows:
            assignment_df = pd.DataFrame(assignment_rows, columns=assignment_columns)
            _append_or_create_table(
                conn,
                "temp_od_assignment",
                assignment_df,
                "temp_od_assignment_tmp",
            )
        del chunk
        gc.collect()

    if create_full_temp_flow_matrix:
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE {od_output_table} AS
            SELECT
                o.od_id,
                o.origin,
                o.destination,
                o.e_id,
                o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                o.fuel,
                o.time,
                o.toll,
                o.length_mile
            FROM od_results_iter o
            LEFT JOIN od_adjustment a USING (od_id, origin, destination);
            """
        )
    else:
        for event_id in list(candidate_buffers):
            flush_candidate_event(event_id)
        for event_id in event_edges:
            event_dir = os.path.join(
                event_candidates_out_dir,
                "event_disrupted_candidates",
                event_id,
            )
            parts_dir = os.path.join(event_dir, "parts")
            if combine_event_candidate_parts and candidate_summary[event_id]["parts"] > 0:
                combined_path = os.path.join(event_dir, "disrupted_candidates.pq")
                conn.execute(
                    f"""
                    COPY (
                        SELECT *
                        FROM read_parquet('{_sql_path(os.path.join(parts_dir, "*.pq"))}')
                    ) TO '{_sql_path(combined_path)}' (FORMAT PARQUET);
                    """
                )
                logging.info(
                    "Combined fused event candidate parts for %s into %s",
                    event_id,
                    combined_path,
                )
            output_size = 0
            if os.path.isdir(parts_dir):
                output_size = sum(
                    os.path.getsize(os.path.join(parts_dir, name))
                    for name in os.listdir(parts_dir)
                    if name.endswith(".pq")
                )
            logging.info(
                "Fused event candidate summary: event=%s rows=%s parts=%s output_bytes=%s",
                event_id,
                candidate_summary[event_id]["rows"],
                candidate_summary[event_id]["parts"],
                output_size,
            )
        costs_df = pd.DataFrame(
            [
                {
                    "fuel_cost_total": cost_fuel_total,
                    "time_cost_total": cost_time_total,
                    "toll_cost_total": cost_toll_total,
                    "fare_cost_total": cost_fare_total,
                    "assigned_flow_total": assigned_flow_total,
                }
            ]
        )
        conn.register("temp_iteration_costs_df", costs_df)
        conn.execute(
            "CREATE OR REPLACE TEMP TABLE temp_iteration_costs AS SELECT * FROM temp_iteration_costs_df"
        )
        conn.unregister("temp_iteration_costs_df")
        logging.info(
            "Full temp_flow_matrix skipped. temp_od_assignment rows=%s, "
            "assigned_flow_total=%s, cost totals fuel=%s time=%s toll=%s fare=%s.",
            conn.execute("SELECT COUNT(*) FROM temp_od_assignment").fetchone()[0],
            assigned_flow_total,
            cost_fuel_total,
            cost_time_total,
            cost_toll_total,
            cost_fare_total,
        )
    logging.info(
        "Streaming realization pass 2 complete in %.2f seconds; candidate write time %.2f seconds.",
        time.time() - pass2_start,
        candidate_write_seconds,
    )

    edge_df = pd.DataFrame(
        {
            "e_id": edge_eid.tolist(),
            "flow": adjusted_edge_flow,
            "total_candidate_flow": edge_total_flow,
            "acc_capacity": edge_capacity,
            "edge_ratio": edge_ratio,
        }
    )
    edge_df = edge_df[
        (edge_df["flow"] > 0) | (edge_df["total_candidate_flow"] > 0)
    ].reset_index(drop=True)
    conn.register("temp_edge_flow_df", edge_df)
    conn.execute(
        f"CREATE OR REPLACE TEMP TABLE {edge_output_table} AS SELECT * FROM temp_edge_flow_df"
    )
    conn.unregister("temp_edge_flow_df")

    if not persist_debug_tables:
        conn.execute("DROP TABLE IF EXISTS od_adjustment")

    od_rows = (
        conn.execute(f"SELECT COUNT(*) FROM {od_output_table}").fetchone()[0]
        if create_full_temp_flow_matrix
        else conn.execute("SELECT COUNT(*) FROM temp_od_assignment").fetchone()[0]
    )
    logging.info(
        "Streaming path realization complete: %s OD rows, %s edge rows. "
        "full_temp_flow_matrix_created=%s",
        od_rows,
        conn.execute(f"SELECT COUNT(*) FROM {edge_output_table}").fetchone()[0],
        create_full_temp_flow_matrix,
    )


def itter_path(
    network,
    road_links,
    temp_flow_matrix: Optional[pd.DataFrame] = None,
    num_of_chunk: int = None,
    db_path: str = "results.duckdb",
    conn=None,
    temp_flow_table: Optional[str] = None,
    create_full_temp_flow_matrix: bool = True,
    event_candidates_out_dir: Optional[str] = None,
    damaged_edges_path: Optional[str] = None,
    combine_event_candidate_parts: bool = False,
    vehicle_type: str = "car",
) -> None:
    """Explode stored paths in chunks and accumulate edge flows in DuckDB.

    Parameters
    ----------
    network : igraph.Graph
        Graph whose edge attributes provide per-edge cost and identifiers.
    road_links : gpd.GeoDataFrame
        GeoDataFrame containing ``e_id`` plus capacity and speed attributes.
    temp_flow_matrix : Optional[pd.DataFrame], default None
        In-memory DataFrame of OD paths; used when ``temp_flow_table`` is not provided.
    num_of_chunk : Optional[int], default None
        Desired number of chunks to split ``temp_flow_matrix`` into (upper bound).
    db_path : str, default ``"results.duckdb"``
        Path to the DuckDB database for temporary tables.
    conn : Optional[duckdb.DuckDBPyConnection]
        Existing DuckDB connection; a new one is opened if ``None``.
    temp_flow_table : Optional[str], default None
        Name of a DuckDB table that stores the same columns as ``temp_flow_matrix``.

    Returns
    -------
    None
        Results are written into DuckDB tables ``temp_flow_matrix`` and related temps.
    """

    if temp_flow_table is None and temp_flow_matrix is None:
        raise ValueError("Either temp_flow_matrix or temp_flow_table must be provided.")

    if conn is None:
        conn = duckdb.connect(db_path)

    if temp_flow_table is not None:
        total_rows = (
            conn.execute(f"SELECT COUNT(*) FROM {temp_flow_table}").fetchone()[0] or 0
        )
    else:
        total_rows = len(temp_flow_matrix)

    if total_rows == 0:
        logging.info("No rows available for itter_path; skipping.")
        return

    max_chunk_size = 100_000
    if num_of_chunk is not None and num_of_chunk > 1:
        chunk_size = max(1, math.ceil(total_rows / num_of_chunk))
    elif max_chunk_size > total_rows:
        chunk_size = total_rows
    else:
        num_of_chunk = min(num_of_chunk, max(1, total_rows // max_chunk_size))
        chunk_size = max(1, total_rows // max(1, num_of_chunk))
    logging.info(
        f"Processing {total_rows} OD path rows in chunks of {chunk_size} rows."
    )

    edges = network.es
    edges_df = pd.DataFrame(
        {
            "path": range(len(edges)),
            "e_id": edges["e_id"],
            "time": edges["time_cost"],
            "fuel": edges["operating_cost"],
            "toll": edges["average_toll_cost"],
            "length_mile": edges["length_mile"],
        }
    ).set_index(
        "path"
    )  # network attributes
    conn.execute("DROP TABLE IF EXISTS od_results_iter")  # reset table
    conn.execute("DROP TABLE IF EXISTS edge_flows")  # reset table
    conn.execute("DROP TABLE IF EXISTS total")
    conn.execute("DROP TABLE IF EXISTS edge_total_parts")
    conn.execute("DROP TABLE IF EXISTS od_adjustment_parts")
    conn.execute("DROP TABLE IF EXISTS temp_flow_indexed")
    conn.execute("DROP TABLE IF EXISTS temp_flow_matrix")

    if temp_flow_table is not None:
        path_strategy = os.environ.get(
            "NIRD_PATH_REALIZATION_STRATEGY", "legacy_compact_sql"
        ).strip().lower()
        if path_strategy in {"streaming_arrays", "streaming"}:
            realize_paths_streaming(
                network,
                road_links,
                conn,
                temp_flow_table=temp_flow_table,
                od_output_table="temp_flow_matrix",
                edge_output_table="temp_edge_flow",
                chunk_size=chunk_size,
                create_full_temp_flow_matrix=create_full_temp_flow_matrix,
                event_candidates_out_dir=event_candidates_out_dir,
                damaged_edges_path=damaged_edges_path,
                combine_event_candidate_parts=combine_event_candidate_parts,
                vehicle_type=vehicle_type,
            )
            # Keep compact output tables available for downstream assignment updates.
            return

        edges_sql = edges_df.reset_index()
        road_caps_sql = road_links[["e_id", "acc_capacity"]].copy()
        conn.register("edges_sql", edges_sql)
        conn.register("road_caps_sql", road_caps_sql)
        conn.execute("CREATE OR REPLACE TEMP TABLE edge_attrs AS SELECT * FROM edges_sql")
        conn.execute("CREATE OR REPLACE TEMP TABLE road_caps AS SELECT * FROM road_caps_sql")
        conn.unregister("edges_sql")
        conn.unregister("road_caps_sql")

        compact_duckdb = os.environ.get(
            "NIRD_DUCKDB_COMPACT_PATH_AGG", "1"
        ).strip().lower() in {"1", "true", "yes"}
        if path_strategy in {"legacy_compact_sql", "compact_sql", "compact_duckdb", "option1"} and compact_duckdb:
            logging.info(
                "Aggregating path costs and edge totals in DuckDB without "
                "materializing exploded_paths..."
            )
            conn.execute(
                f"""
                CREATE TABLE total AS
                SELECT
                    e.e_id,
                    MAX(r.acc_capacity) AS acc_capacity,
                    SUM(t.flow) AS total_flow
                FROM {temp_flow_table} t
                CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                JOIN edge_attrs e
                  ON e.path = u.path_idx
                LEFT JOIN road_caps r
                  ON r.e_id = e.e_id
                GROUP BY e.e_id;
                """
            )
            logging.info("Computed compact edge total-flow table.")

            conn.execute(
                f"""
                CREATE TABLE od_results_iter AS
                SELECT
                    FIRST(t.od_id) AS od_id,
                    t.origin,
                    t.destination,
                    LIST(e.e_id ORDER BY u.ord) AS e_id,
                    FIRST(t.flow) AS flow,
                    SUM(e.fuel) AS fuel,
                    SUM(e.time) AS time,
                    SUM(e.toll) AS toll,
                    SUM(e.length_mile) AS length_mile
                FROM {temp_flow_table} t
                CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                JOIN edge_attrs e
                  ON e.path = u.path_idx
                GROUP BY t.od_id, t.origin, t.destination;
                """
            )
            logging.info("Computed compact OD path-cost table.")

            conn.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE od_adjustment AS
                SELECT
                    t.origin,
                    t.destination,
                    t.od_id,
                    MIN(LEAST(total.acc_capacity / NULLIF(total.total_flow, 0), 1.0)) AS adjust_r
                FROM {temp_flow_table} t
                CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                JOIN edge_attrs e
                  ON e.path = u.path_idx
                JOIN total
                  ON total.e_id = e.e_id
                GROUP BY t.od_id, t.origin, t.destination;
                """
            )
            logging.info("Computed compact OD capacity-adjustment table.")

            conn.execute(
                """
        CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
        SELECT
            o.od_id,
            o.origin,
            o.destination,
                    o.e_id,
                    o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                    o.fuel,
                    o.time,
                    o.toll,
                    o.length_mile
                FROM od_results_iter o
                LEFT JOIN od_adjustment a USING (od_id, origin, destination);
                """
            )
            logging.info("Complete creating temp_flow_matrix table in Duckdb!")
            if not create_full_temp_flow_matrix:
                costs_df = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(flow * fuel), 0.0) AS fuel_cost_total,
                        COALESCE(SUM(flow * time), 0.0) AS time_cost_total,
                        COALESCE(SUM(flow * toll), 0.0) AS toll_cost_total,
                        0.0 AS fare_cost_total,
                        COALESCE(SUM(flow), 0.0) AS assigned_flow_total
                    FROM temp_flow_matrix
                    """
                ).fetchdf()
                conn.register("temp_iteration_costs_df", costs_df)
                conn.execute(
                    "CREATE OR REPLACE TEMP TABLE temp_iteration_costs AS "
                    "SELECT * FROM temp_iteration_costs_df"
                )
                conn.unregister("temp_iteration_costs_df")
            conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")
            return

        if path_strategy in {"duckdb_chunked_compact", "option2"}:
            logging.info(
                "Aggregating path costs and edge totals in chunked DuckDB compact mode..."
            )
            conn.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE temp_flow_indexed AS
                SELECT
                    ROW_NUMBER() OVER () AS rn,
                    od_id,
                    origin,
                    destination,
                    path,
                    flow
                FROM {temp_flow_table};
                """
            )
            conn.execute(
                """
                CREATE TABLE edge_total_parts (
                    e_id VARCHAR,
                    acc_capacity DOUBLE,
                    total_flow DOUBLE
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE od_results_iter (
                    od_id BIGINT,
                    origin VARCHAR,
                    destination VARCHAR,
                    e_id VARCHAR[],
                    flow DOUBLE,
                    fuel DOUBLE,
                    time DOUBLE,
                    toll DOUBLE,
                    length_mile DOUBLE
                );
                """
            )
            for start in tqdm(
                range(1, total_rows + 1, chunk_size),
                desc="DuckDB compact pass 1:",
                unit="chunk",
            ):
                end = min(start + chunk_size - 1, total_rows)
                conn.execute(
                    f"""
                    INSERT INTO edge_total_parts
                    SELECT
                        e.e_id,
                        MAX(r.acc_capacity) AS acc_capacity,
                        SUM(t.flow) AS total_flow
                    FROM temp_flow_indexed t
                    CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                    JOIN edge_attrs e
                      ON e.path = u.path_idx
                    LEFT JOIN road_caps r
                      ON r.e_id = e.e_id
                    WHERE t.rn BETWEEN {start} AND {end}
                    GROUP BY e.e_id;
                    """
                )
                conn.execute(
                    f"""
                    INSERT INTO od_results_iter
                    SELECT
                        FIRST(t.od_id) AS od_id,
                        t.origin,
                        t.destination,
                        LIST(e.e_id ORDER BY u.ord) AS e_id,
                        FIRST(t.flow) AS flow,
                        SUM(e.fuel) AS fuel,
                        SUM(e.time) AS time,
                        SUM(e.toll) AS toll,
                        SUM(e.length_mile) AS length_mile
                    FROM temp_flow_indexed t
                    CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                    JOIN edge_attrs e
                      ON e.path = u.path_idx
                    WHERE t.rn BETWEEN {start} AND {end}
                    GROUP BY t.od_id, t.origin, t.destination;
                    """
                )

            conn.execute(
                """
                CREATE TABLE total AS
                SELECT
                    e_id,
                    MAX(acc_capacity) AS acc_capacity,
                    SUM(total_flow) AS total_flow
                FROM edge_total_parts
                GROUP BY e_id;
                """
            )
            logging.info("DuckDB compact pass 1 complete.")

            conn.execute(
                """
                CREATE TABLE od_adjustment_parts (
                    od_id BIGINT,
                    origin VARCHAR,
                    destination VARCHAR,
                    adjust_r DOUBLE
                );
                """
            )
            for start in tqdm(
                range(1, total_rows + 1, chunk_size),
                desc="DuckDB compact pass 2:",
                unit="chunk",
            ):
                end = min(start + chunk_size - 1, total_rows)
                conn.execute(
                    f"""
                    INSERT INTO od_adjustment_parts
                    SELECT
                        t.od_id,
                        t.origin,
                        t.destination,
                        MIN(LEAST(total.acc_capacity / NULLIF(total.total_flow, 0), 1.0)) AS adjust_r
                    FROM temp_flow_indexed t
                    CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                    JOIN edge_attrs e
                      ON e.path = u.path_idx
                    JOIN total
                      ON total.e_id = e.e_id
                    WHERE t.rn BETWEEN {start} AND {end}
                    GROUP BY t.od_id, t.origin, t.destination;
                    """
                )

            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE od_adjustment AS
                SELECT od_id, origin, destination, MIN(adjust_r) AS adjust_r
                FROM od_adjustment_parts
                GROUP BY od_id, origin, destination;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
                SELECT
                    o.origin,
                    o.destination,
                    o.e_id,
                    o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                    o.fuel,
                    o.time,
                    o.toll,
                    o.length_mile
                FROM od_results_iter o
                LEFT JOIN od_adjustment a USING (od_id, origin, destination);
                """
            )
            logging.info("Complete creating temp_flow_matrix table in Duckdb!")
            conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")
            return

        if path_strategy in {"pandas_chunked", "option3"}:
            logging.info("Aggregating path costs and edge totals in pandas chunks...")
            pandas_chunk_size = min(
                chunk_size,
                int(os.environ.get("NIRD_PANDAS_PATH_CHUNK_SIZE", "50000")),
            )
            road_caps_df = road_links[["e_id", "acc_capacity"]].copy()
            first_od = True
            first_edge = True
            for start in tqdm(
                range(0, total_rows, pandas_chunk_size),
                desc="Pandas compact pass 1:",
                unit="chunk",
            ):
                chunk = conn.execute(
                    f"""
                    SELECT *
                    FROM {temp_flow_table}
                    LIMIT {pandas_chunk_size}
                    OFFSET {start}
                    """
                ).fetchdf()
                if chunk.empty:
                    continue
                chunk = chunk.explode("path")
                chunk = chunk.join(edges_df, on="path")
                chunk = chunk.merge(road_caps_df, on="e_id", how="left")
                od_df = chunk.groupby(["origin", "destination"], as_index=False).agg(
                    {
                        "e_id": list,
                        "flow": "first",
                        "fuel": "sum",
                        "time": "sum",
                        "toll": "sum",
                        "length_mile": "sum",
                    }
                )
                edge_df = chunk.groupby("e_id", as_index=False).agg(
                    {"acc_capacity": "max", "flow": "sum"}
                )
                edge_df.rename(columns={"flow": "total_flow"}, inplace=True)
                conn.register("od_df_tmp", od_df)
                conn.register("edge_df_tmp", edge_df)
                if first_od:
                    conn.execute("CREATE TABLE od_results_iter AS SELECT * FROM od_df_tmp")
                    first_od = False
                else:
                    conn.execute("INSERT INTO od_results_iter SELECT * FROM od_df_tmp")
                if first_edge:
                    conn.execute("CREATE TABLE edge_total_parts AS SELECT * FROM edge_df_tmp")
                    first_edge = False
                else:
                    conn.execute("INSERT INTO edge_total_parts SELECT * FROM edge_df_tmp")
                conn.unregister("od_df_tmp")
                conn.unregister("edge_df_tmp")
                del chunk, od_df, edge_df
                gc.collect()

            conn.execute(
                """
                CREATE TABLE total AS
                SELECT
                    e_id,
                    MAX(acc_capacity) AS acc_capacity,
                    SUM(total_flow) AS total_flow
                FROM edge_total_parts
                GROUP BY e_id;
                """
            )
            total_df = conn.execute("SELECT * FROM total").fetchdf()
            total_df["ratio"] = (
                total_df["acc_capacity"] / total_df["total_flow"].replace(0, pd.NA)
            ).clip(upper=1.0).fillna(1.0)
            ratios = total_df[["e_id", "ratio"]]
            first_adj = True
            for start in tqdm(
                range(0, total_rows, pandas_chunk_size),
                desc="Pandas compact pass 2:",
                unit="chunk",
            ):
                chunk = conn.execute(
                    f"""
                    SELECT origin, destination, path
                    FROM {temp_flow_table}
                    LIMIT {pandas_chunk_size}
                    OFFSET {start}
                    """
                ).fetchdf()
                if chunk.empty:
                    continue
                chunk = chunk.explode("path")
                chunk = chunk.join(edges_df[["e_id"]], on="path")
                chunk = chunk.merge(ratios, on="e_id", how="left")
                adj_df = (
                    chunk.groupby(["origin", "destination"], as_index=False)["ratio"]
                    .min()
                    .rename(columns={"ratio": "adjust_r"})
                )
                conn.register("adj_df_tmp", adj_df)
                if first_adj:
                    conn.execute(
                        "CREATE TABLE od_adjustment_parts AS SELECT * FROM adj_df_tmp"
                    )
                    first_adj = False
                else:
                    conn.execute("INSERT INTO od_adjustment_parts SELECT * FROM adj_df_tmp")
                conn.unregister("adj_df_tmp")
                del chunk, adj_df
                gc.collect()

            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE od_adjustment AS
                SELECT origin, destination, MIN(adjust_r) AS adjust_r
                FROM od_adjustment_parts
                GROUP BY origin, destination;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
                SELECT
                    o.origin,
                    o.destination,
                    o.e_id,
                    o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                    o.fuel,
                    o.time,
                    o.toll,
                    o.length_mile
                FROM od_results_iter o
                LEFT JOIN od_adjustment a USING (origin, destination);
                """
            )
            logging.info("Complete creating temp_flow_matrix table in Duckdb!")
            conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")
            return

        chunked_duckdb = os.environ.get(
            "NIRD_DUCKDB_CHUNKED_PATH_EXPANSION", "0"
        ).strip().lower() in {"1", "true", "yes"}
        if chunked_duckdb:
            first_chunk = True
            for start in tqdm(
                range(0, total_rows, chunk_size),
                desc="Expanding OD paths in DuckDB chunks:",
                unit="chunk",
            ):
                conn.execute(
                    f"""
                    CREATE OR REPLACE TEMP TABLE path_chunk AS
                    SELECT *
                    FROM {temp_flow_table}
                    LIMIT {chunk_size}
                    OFFSET {start};
                    """
                )
                conn.execute(
                    """
                    CREATE OR REPLACE TEMP TABLE exploded_paths_chunk AS
                    SELECT
                        t.origin,
                        t.destination,
                        t.flow,
                        u.ord,
                        e.e_id,
                        e.time,
                        e.fuel,
                        e.toll,
                        e.length_mile,
                        r.acc_capacity
                    FROM path_chunk t
                    CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                    JOIN edge_attrs e
                      ON e.path = u.path_idx
                    LEFT JOIN road_caps r
                      ON r.e_id = e.e_id;
                    """
                )
                if first_chunk:
                    conn.execute(
                        """
                        CREATE TABLE od_results_iter AS
                        SELECT
                            origin,
                            destination,
                            LIST(e_id ORDER BY ord) AS e_id,
                            FIRST(flow) AS flow,
                            SUM(fuel) AS fuel,
                            SUM(time) AS time,
                            SUM(toll) AS toll,
                            SUM(length_mile) AS length_mile
                        FROM exploded_paths_chunk
                        GROUP BY origin, destination;
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE edge_flows AS
                        SELECT
                            e_id,
                            origin,
                            destination,
                            MAX(acc_capacity) AS acc_capacity,
                            SUM(flow) AS flow
                        FROM exploded_paths_chunk
                        GROUP BY e_id, origin, destination;
                        """
                    )
                    first_chunk = False
                else:
                    conn.execute(
                        """
                        INSERT INTO od_results_iter
                        SELECT
                            origin,
                            destination,
                            LIST(e_id ORDER BY ord) AS e_id,
                            FIRST(flow) AS flow,
                            SUM(fuel) AS fuel,
                            SUM(time) AS time,
                            SUM(toll) AS toll,
                            SUM(length_mile) AS length_mile
                        FROM exploded_paths_chunk
                        GROUP BY origin, destination;
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO edge_flows
                        SELECT
                            e_id,
                            origin,
                            destination,
                            MAX(acc_capacity) AS acc_capacity,
                            SUM(flow) AS flow
                        FROM exploded_paths_chunk
                        GROUP BY e_id, origin, destination;
                        """
                    )
                conn.execute("DROP TABLE IF EXISTS exploded_paths_chunk")
                conn.execute("DROP TABLE IF EXISTS path_chunk")
            logging.info("Chunked DuckDB path expansion complete. Aggregating final results...")

            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE total AS
                SELECT e_id, SUM(flow) AS total_flow
                FROM edge_flows
                GROUP BY e_id;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE od_adjustment AS
                SELECT
                    e.origin,
                    e.destination,
                    MIN(LEAST(e.acc_capacity / NULLIF(t.total_flow, 0), 1.0)) AS adjust_r
                FROM edge_flows e
                JOIN total t USING (e_id)
                GROUP BY e.origin, e.destination;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
                SELECT
                    o.origin,
                    o.destination,
                    o.e_id,
                    o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                    o.fuel,
                    o.time,
                    o.toll,
                    o.length_mile
                FROM od_results_iter o
                LEFT JOIN od_adjustment a USING (origin, destination);
                """
            )
            logging.info("Complete creating temp_flow_matrix table in Duckdb!")
            conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")
            return

        conn.execute("DROP TABLE IF EXISTS exploded_paths")
        conn.execute(
            f"""
            CREATE TABLE exploded_paths AS
            SELECT
                t.origin,
                t.destination,
                t.flow,
                u.ord,
                e.e_id,
                e.time,
                e.fuel,
                e.toll,
                e.length_mile,
                r.acc_capacity
            FROM {temp_flow_table} t
            CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
            JOIN edge_attrs e
              ON e.path = u.path_idx
            LEFT JOIN road_caps r
              ON r.e_id = e.e_id;
            """
        )

        conn.execute(
            """
            CREATE TABLE od_results_iter AS
            SELECT
                origin,
                destination,
                LIST(e_id ORDER BY ord) AS e_id,
                FIRST(flow) AS flow,
                SUM(fuel) AS fuel,
                SUM(time) AS time,
                SUM(toll) AS toll,
                SUM(length_mile) AS length_mile
            FROM exploded_paths
            GROUP BY origin, destination;
            """
        )

        conn.execute(
            """
            CREATE TABLE edge_flows AS
            SELECT
                e_id,
                origin,
                destination,
                MAX(acc_capacity) AS acc_capacity,
                SUM(flow) AS flow
            FROM exploded_paths
            GROUP BY e_id, origin, destination;
            """
        )

        conn.execute("DROP TABLE IF EXISTS exploded_paths")
        logging.info("All paths expanded in DuckDB. Aggregating final results...")

        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE total AS
            SELECT e_id, SUM(flow) AS total_flow
            FROM edge_flows
            GROUP BY e_id;
            """
        )
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE od_adjustment AS
            SELECT
                e.origin,
                e.destination,
                MIN(LEAST(e.acc_capacity / NULLIF(t.total_flow, 0), 1.0)) AS adjust_r
            FROM edge_flows e
            JOIN total t USING (e_id)
            GROUP BY e.origin, e.destination;
            """
        )
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
            SELECT
                o.origin,
                o.destination,
                o.e_id,
                o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
                o.fuel,
                o.time,
                o.toll,
                o.length_mile
            FROM od_results_iter o
            LEFT JOIN od_adjustment a USING (origin, destination);
            """
        )
        logging.info("Complete creating temp_flow_matrix table in Duckdb!")
        conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")
        return

    first = True
    for start in tqdm(
        range(0, total_rows, chunk_size),
        desc="Processing chunks:",
        unit="chunk",
    ):
        if temp_flow_table is not None:
            chunk = conn.execute(
                f"""
                SELECT *
                FROM {temp_flow_table}
                LIMIT {chunk_size}
                OFFSET {start}
                """
            ).fetchdf()
        else:
            chunk = temp_flow_matrix.iloc[start : start + chunk_size]
        chunk = chunk.explode("path")
        chunk = chunk.join(edges_df, on="path")
        chunk = chunk.merge(
            road_links[["e_id", "acc_capacity"]],
            on="e_id",
            how="left",
        )
        # aggregate OD results
        od_df = chunk.groupby(["origin", "destination"], as_index=False).agg(
            {
                "e_id": list,
                "flow": "first",
                "fuel": "sum",
                "time": "sum",
                "toll": "sum",
                "length_mile": "sum",
            }
        )

        # edge flows
        edge_df = (
            chunk.groupby(by=["e_id", "origin", "destination"])
            .agg(
                {
                    "acc_capacity": "first",
                    "flow": "sum",
                }
            )
            .reset_index()
        )
        if first:
            conn.register("od_df_tmp", od_df)
            conn.execute("CREATE TABLE od_results_iter AS SELECT * FROM od_df_tmp")
            conn.unregister("od_df_tmp")
            conn.register("edge_df_tmp", edge_df)
            conn.execute("CREATE TABLE edge_flows AS SELECT * FROM edge_df_tmp")
            conn.unregister("edge_df_tmp")
            first = False
        else:
            conn.append("od_results_iter", od_df)
            conn.append("edge_flows", edge_df)

        del chunk, od_df, edge_df
        gc.collect()

    logging.info("All chunks processed. Aggregating final results...")

    # od results
    # origin, destination, path, flow, cost
    # 1) create base
    conn.execute(
        """
    CREATE OR REPLACE TEMP TABLE base AS
    SELECT
        e_id,
        origin,
        destination,
        MAX(acc_capacity) AS acc_capacity,
        SUM(flow) AS flow
    FROM edge_flows
    GROUP BY e_id, origin, destination;
    """
    )

    # 2) create total (per e_id)
    conn.execute(
        """
    CREATE OR REPLACE TEMP TABLE total AS
    SELECT e_id, SUM(flow) AS total_flow
    FROM base
    GROUP BY e_id;
    """
    )

    # 3) create od_adjustment
    conn.execute(
        """
    CREATE OR REPLACE TEMP TABLE od_adjustment AS
    SELECT
        b.origin,
        b.destination,
        MIN(LEAST(b.acc_capacity / NULLIF(t.total_flow, 0), 1.0)) AS adjust_r
    FROM base b
    JOIN total t USING (e_id)
    GROUP BY b.origin, b.destination;
    """
    )

    # 4) final result
    conn.execute(
        """
    CREATE OR REPLACE TEMP TABLE temp_flow_matrix AS
    SELECT
        o.origin,
        o.destination,
        o.e_id,
        o.flow * COALESCE(a.adjust_r, 1.0) AS flow,
        o.fuel,
        o.time,
        o.toll,
        o.length_mile
    FROM od_results_iter o
    LEFT JOIN od_adjustment a USING (origin, destination);
    """
    )
    logging.info("Complete creating temp_flow_matrix table in Duckdb!")

    if temp_flow_table is not None:
        conn.execute(f"DROP TABLE IF EXISTS {temp_flow_table}")

    return


def network_flow_model(
    road_links: gpd.GeoDataFrame,
    network: igraph.Graph,
    remain_od: pd.DataFrame,
    flow_breakpoint_dict: Dict[str, float],
    num_of_chunk: int,
    num_of_cpu: int,
    db_path: str = "results.duckdb",
    iso_out_path: str = None,
    odpfc_out_path: str = None,
    vehicle_type: str = "car",
) -> Tuple[gpd.GeoDataFrame, List[float]]:
    """Iteratively assign OD demand, update road attributes, and export results.

    Parameters
    ----------
    road_links : gpd.GeoDataFrame
        Road network edges with geometry and accumulated metrics.
    network : igraph.Graph
        Directed network used for least-cost path searches.
    remain_od : pd.DataFrame
        Input OD matrix with columns ``origin_node``, ``destination_node``, ``Car21``.
    flow_breakpoint_dict : Dict[str, float]
        Dictionary mapping combined labels to breakpoint flows for speed updates.
    num_of_chunk : int
        Number of chunks to split per-iteration path results when exploding paths.
    num_of_cpu : int
        Number of worker processes used for path finding (>=1).
    db_path : str, default ``"results.duckdb"``
        Location of the DuckDB database for temporaries and final tables.
    iso_out_path : str
        File path where the final isolated OD Parquet file will be written.
    odpfc_out_path : str
        File path where the per-path flow/cost Parquet file will be written.
    vehicle_type : str, default ``"car"``
        Vehicle type for cost calculations; one of ``["car", "lgv", "ogv", "psv", "rail"]``.

    Returns
    -------
    gpd.GeoDataFrame
        Road links with updated accumulated flow, capacity, and speed attributes.
    List[float]
        Aggregate costs in the order ``[cost_time, cost_fuel, cost_toll, total_cost]``.
    """

    road_links_columns = road_links.columns.tolist()
    total_remain = float(pd.to_numeric(remain_od["Car21"], errors="coerce").fillna(0).sum())
    logging.info(f"The initial supply is {total_remain}")
    number_of_edges = len(list(network.es))
    logging.info(f"The initial number of edges in the network: {number_of_edges}")
    number_of_origins = remain_od["origin_node"].unique().shape[0]
    logging.info(f"The initial number of origins: {number_of_origins}")
    number_of_destinations = remain_od["destination_node"].unique().shape[0]
    logging.info(f"The initial number of destinations: {number_of_destinations}")

    # starts
    total_cost = cost_time = cost_fuel = cost_toll = cost_fare = 0
    initial_sumod = float(pd.to_numeric(remain_od["Car21"], errors="coerce").fillna(0).sum())
    assigned_sumod = 0
    iter_flag = 1
    next_od_id_base = 0
    from resiflow.config import get_env

    max_iterations = int(get_env("RESIFLOW_MAX_FLOW_ITERATIONS", "NIRD_MAX_FLOW_ITERATIONS", "0") or "0")
    min_progress_rel = float(os.environ.get("NIRD_MIN_FLOW_PROGRESS_REL", "1e-6"))
    stagnant_limit = int(os.environ.get("NIRD_STAGNANT_ITERATIONS", "3"))
    stagnant_iterations = 0
    remain_assign_mode = (
        get_env("RESIFLOW_REMAIN_ASSIGN_FRACTION", "NIRD_REMAIN_ASSIGN_FRACTION", "") or ""
    ).strip().lower()
    path_strategy = os.environ.get(
        "NIRD_PATH_REALIZATION_STRATEGY", "legacy_compact_sql"
    ).strip().lower()
    direct_output_mode = odpfc_out_path is not None
    odpfc_mode_env = os.environ.get("NIRD_ODPFC_OUTPUT_MODE")
    if odpfc_mode_env is not None:
        odpfc_output_mode = odpfc_mode_env.strip().lower()
    elif direct_output_mode and path_strategy in {"streaming_arrays", "streaming"}:
        odpfc_output_mode = "iteration_parquet"
    else:
        odpfc_output_mode = "duckdb_table"
    if odpfc_output_mode not in {"duckdb_table", "iteration_parquet", "skip"}:
        raise ValueError(
            "NIRD_ODPFC_OUTPUT_MODE must be one of duckdb_table, "
            "iteration_parquet, or skip"
        )
    combine_env = os.environ.get("NIRD_COMBINE_ODPFC_PARTS")
    if combine_env is None:
        combine_odpfc_parts = not (
            direct_output_mode
            and path_strategy in {"streaming_arrays", "streaming"}
            and odpfc_output_mode == "iteration_parquet"
        )
    else:
        combine_odpfc_parts = combine_env.strip().lower() in {"1", "true", "yes"}
    odpfc_parts_dir = None
    if odpfc_out_path is not None and odpfc_output_mode == "iteration_parquet":
        odpfc_parts_dir = os.path.join(os.path.dirname(odpfc_out_path), "odpfc_parts")
        os.makedirs(odpfc_parts_dir, exist_ok=True)
    baseline_mode_env = os.environ.get("NIRD_BASELINE_PATH_OUTPUT_MODE")
    if baseline_mode_env is not None:
        baseline_path_output_mode = baseline_mode_env.strip().lower()
    elif direct_output_mode and path_strategy in {"streaming_arrays", "streaming"}:
        baseline_path_output_mode = "path_index"
    else:
        baseline_path_output_mode = "full_odpfc"
    if baseline_path_output_mode not in {
        "none",
        "od_meta_only",
        "path_index",
        "event_candidates",
        "full_odpfc",
    }:
        raise ValueError(
            "NIRD_BASELINE_PATH_OUTPUT_MODE must be one of none, "
            "od_meta_only, path_index, event_candidates, or full_odpfc"
        )
    write_full_odpfc = baseline_path_output_mode == "full_odpfc"
    baseline_out_dir = os.path.dirname(odpfc_out_path) if odpfc_out_path is not None else None
    od_meta_parts_dir = None
    path_index_parts_dir = None
    edge_lookup_path = None
    event_candidates_root = None
    combine_event_candidate_parts = os.environ.get(
        "NIRD_COMBINE_EVENT_CANDIDATE_PARTS", "0"
    ).strip().lower() in {"1", "true", "yes"}
    damaged_edges_path = os.environ.get("NIRD_EVENT_DAMAGED_EDGES_PATH")
    if baseline_out_dir and baseline_path_output_mode in {"od_meta_only", "path_index"}:
        od_meta_parts_dir = os.path.join(baseline_out_dir, "baseline_od_meta_parts")
        os.makedirs(od_meta_parts_dir, exist_ok=True)
    if baseline_out_dir and baseline_path_output_mode == "path_index":
        path_index_parts_dir = os.path.join(baseline_out_dir, "baseline_path_index_parts")
        os.makedirs(path_index_parts_dir, exist_ok=True)
        edge_lookup_path = os.path.join(baseline_out_dir, "edge_lookup.pq")
    if baseline_out_dir and baseline_path_output_mode == "event_candidates":
        event_candidates_root = os.path.join(baseline_out_dir, "event_disrupted_candidates")
        os.makedirs(event_candidates_root, exist_ok=True)
    create_full_temp_env = os.environ.get("NIRD_CREATE_FULL_TEMP_FLOW_MATRIX")
    if create_full_temp_env is None:
        create_full_temp_flow_matrix = baseline_path_output_mode != "event_candidates"
    else:
        create_full_temp_flow_matrix = create_full_temp_env.strip().lower() in {
            "1",
            "true",
            "yes",
        }
    logging.info(
        "Iteration controls: "
        f"max_iterations={'unbounded' if max_iterations <= 0 else max_iterations}, "
        f"min_progress_rel={min_progress_rel}, "
        f"stagnant_limit={stagnant_limit}, "
        f"remain_assign_mode={remain_assign_mode or 'full'}"
    )
    logging.info(
        "OD path output controls: "
        f"path_strategy={path_strategy}, "
        f"odpfc_output_mode={odpfc_output_mode}, "
        f"combine_odpfc_parts={combine_odpfc_parts}, "
        f"odpfc_parts_dir={odpfc_parts_dir}, "
        f"baseline_path_output_mode={baseline_path_output_mode}, "
        f"combine_event_candidate_parts={combine_event_candidate_parts}, "
        f"damaged_edges_path={damaged_edges_path}, "
        f"create_full_temp_flow_matrix={create_full_temp_flow_matrix}"
    )

    # create db (remove the pre-exist one)
    if os.path.exists(db_path):
        os.remove(db_path)
    # create isolated_od table
    conn = duckdb.connect(db_path)
    # DuckDB's own query engine can parallelize the (dominant) streaming/
    # aggregation phase internally; mirrors upstream DAFNI-NIRD's fix for the
    # NumCpu regression (see notes/perf_findings/GOAL6_UPSTREAM_DRIFT_AUDIT.md).
    conn.execute(f"PRAGMA threads={max(1, int(num_of_cpu))}")
    # Bound DuckDB's buffer-pool memory explicitly. Without this it defaults
    # to ~80% of system RAM; on a long-lived connection that repeatedly
    # creates/drops large temp tables over many hours/iterations (national
    # scale), RSS ratchets toward that ceiling and the OS starts swapping
    # long before DuckDB itself would call it OOM (Goal 14 overnight run:
    # RSS hit ~46.6GB / 625MB free, iteration time grew ~4x from swap
    # thrashing -- see notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md).
    # Capping memory_limit forces DuckDB to spill to temp_directory instead.
    duckdb_memory_limit = os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "24GB")
    conn.execute(f"PRAGMA memory_limit='{duckdb_memory_limit}'")
    duckdb_temp_dir = os.environ.get("NIRD_DUCKDB_TEMP_DIRECTORY")
    if duckdb_temp_dir:
        conn.execute(f"PRAGMA temp_directory='{_sql_path(duckdb_temp_dir)}'")
    if edge_lookup_path is not None:
        edge_lookup_df = pd.DataFrame(
            {"edge_idx": np.arange(number_of_edges, dtype=np.int32), "e_id": network.es["e_id"]}
        )
        conn.register("edge_lookup_df", edge_lookup_df)
        conn.execute(
            f"""
            COPY (
                SELECT edge_idx, e_id
                FROM edge_lookup_df
            ) TO '{_sql_path(edge_lookup_path)}' (FORMAT PARQUET);
            """
        )
        conn.unregister("edge_lookup_df")
        logging.info(
            "Wrote edge_lookup.pq with %s rows to %s",
            len(edge_lookup_df),
            edge_lookup_path,
        )
        del edge_lookup_df
    conn.execute(
        """
        CREATE OR REPLACE TABLE isolated_od (
            origin_node VARCHAR,
            destination_node VARCHAR,
            flow DOUBLE
        );
    """
    )
    # create odpfc table
    conn.execute(
        """
        CREATE OR REPLACE TABLE odpfc (
            od_id BIGINT,
            origin VARCHAR,
            destination VARCHAR,
            path VARCHAR[],
            flow DOUBLE,
            fuel DOUBLE,
            time DOUBLE,
            toll DOUBLE,
            fare DOUBLE,
        )
        """
    )
    # create remain_od table
    conn.execute("DROP TABLE IF EXISTS remain_od")
    conn.register(
        "remain_od_tmp",
        remain_od[["origin_node", "destination_node", "Car21"]],
    )
    conn.execute(
        """
        CREATE TABLE remain_od AS
        SELECT
            origin_node,
            destination_node,
            Car21
        FROM remain_od_tmp;
        """
    )
    conn.unregister("remain_od_tmp")
    total_remain = (
        conn.execute("SELECT COALESCE(SUM(Car21), 0.0) FROM remain_od").fetchone()[0]
        or 0.0
    )
    del remain_od
    gc.collect()

    # Opt-in persistent worker pool: create once and refresh each worker's
    # network reference per iteration instead of respawning the pool every
    # iteration (spawn+reimport cost scaled linearly with worker count; see
    # notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md Goal 11). Falls back to
    # the existing per-iteration Pool() when disabled (default).
    persistent_pool_enabled = _env_flag("NIRD_PERSISTENT_LCP_POOL") and num_of_cpu > 1
    persistent_pool = None
    if persistent_pool_enabled:
        initial_pkl = pickle.dumps(network)
        persistent_pool_kwargs = {
            "processes": num_of_cpu,
            "initializer": worker_init_path,
            "initargs": (initial_pkl,),
        }
        _persistent_max_tasks = int(os.environ.get("NIRD_POOL_MAX_TASKS_PER_CHILD", "0"))
        if _persistent_max_tasks > 0:
            persistent_pool_kwargs["maxtasksperchild"] = _persistent_max_tasks
        persistent_pool = Pool(**persistent_pool_kwargs)
        logging.info(
            "Persistent LCP worker pool created once (num_of_cpu=%s).", num_of_cpu
        )

    while total_remain > 0:
        previous_total_remain = total_remain
        logging.info(f"No.{iter_flag} iteration starts:")
        _log_rss(f"iter{iter_flag}_start")
        # remove OD pairs whose nodes are not present in the current network
        conn.register("current_valid_nodes", pd.DataFrame({"node": network.vs["name"]}))
        conn.execute("DROP TABLE IF EXISTS isolated_tmp")
        conn.execute(
            """
        CREATE TEMP TABLE isolated_tmp AS
        SELECT
            origin_node,
            destination_node,
            Car21 AS flow
        FROM remain_od
        WHERE origin_node NOT IN (SELECT node FROM current_valid_nodes)
           OR destination_node NOT IN (SELECT node FROM current_valid_nodes);
        """
        )
        temp_isolation = (
            conn.execute(
                "SELECT COALESCE(SUM(flow), 0.0) FROM isolated_tmp"
            ).fetchone()[0]
            or 0.0
        )
        if temp_isolation > 0:
            conn.execute("INSERT INTO isolated_od SELECT * FROM isolated_tmp")
            conn.execute(
                """
            DELETE FROM remain_od
            WHERE origin_node NOT IN (SELECT node FROM current_valid_nodes)
               OR destination_node NOT IN (SELECT node FROM current_valid_nodes);
            """
            )
        conn.unregister("current_valid_nodes")
        conn.execute("DROP TABLE IF EXISTS isolated_tmp")
        logging.info(f"Initial isolated flows: {temp_isolation}")

        # dump the network and edge weight for shared use in multiprocessing
        # (only needed when actually spawning worker processes; skip the
        # pickle entirely at num_of_cpu=1, where shared_network is assigned
        # directly instead -- was previously computed unconditionally)
        shared_network_pkl = None
        if num_of_cpu > 1:
            pickle_st = time.time()
            shared_network_pkl = pickle.dumps(network)
            logging.info(
                "Network pickle time for worker init: %.3f seconds.",
                time.time() - pickle_st,
            )

        # find the least-cost path for each OD trip
        args_df = conn.execute(
            """
        SELECT
            origin_node,
            LIST(destination_node ORDER BY destination_node) AS destinations,
            LIST(Car21 ORDER BY destination_node) AS flows
        FROM remain_od
        GROUP BY origin_node
        """
        ).fetchdf()
        args = [
            (
                row.origin_node,
                list(row.destinations) if row.destinations is not None else [],
                list(row.flows) if row.flows is not None else [],
            )
            for row in tqdm(
                args_df.itertuples(index=False),
                total=len(args_df),
                desc="Creating argument list: ",
            )
        ]
        # Split each origin's destination list into bounded-size sub-tasks
        # (opt-in; Goal 15). Origin count is roughly fixed regardless of OD
        # sample size (~2975 on the VA-priority CONUS run), while
        # destinations-per-origin scales with total OD volume -- at 5M OD
        # that meant ~1680 destinations bundled into a single task/result,
        # which drove main-process RSS to ~45GB (vs ~5GB at 500k OD; see
        # notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md Goal 15). Chunking
        # bounds peak per-task/result memory independent of OD scale, at the
        # cost of re-running the single-source Dijkstra tree once per chunk
        # for origins split across multiple tasks (igraph's
        # get_shortest_paths recomputes the tree per call regardless of
        # destination count) -- the same tradeoff already exercised by
        # NIRD_SHORTEST_PATH_DEST_BATCH, just applied at task-construction
        # time instead of inside find_least_cost_path.
        dest_chunk_size = int(os.environ.get("NIRD_LCP_DEST_CHUNK_SIZE", "0"))
        if dest_chunk_size > 0:
            pre_chunk_task_count = len(args)
            chunked_args = []
            for origin, destinations, flows in args:
                if len(destinations) <= dest_chunk_size:
                    chunked_args.append((origin, destinations, flows))
                else:
                    for start in range(0, len(destinations), dest_chunk_size):
                        chunked_args.append(
                            (
                                origin,
                                destinations[start : start + dest_chunk_size],
                                flows[start : start + dest_chunk_size],
                            )
                        )
            logging.info(
                "Chunked LCP dispatch: %s origin-tasks split into %s tasks "
                "(dest_chunk_size=%s).",
                pre_chunk_task_count,
                len(chunked_args),
                dest_chunk_size,
            )
            args = chunked_args
            del chunked_args

        # Sort tasks by descending destination-list length before Pool
        # dispatch (longest-job-first load balancing): imap_unordered
        # returns results out of order regardless, so this only affects
        # scheduling, not correctness. Avoids one worker getting stuck on a
        # single huge-origin task while others sit idle on small ones.
        if _env_flag("NIRD_LCP_SORT_BY_DEST_COUNT", True) and num_of_cpu > 1:
            args.sort(key=lambda a: len(a[1]), reverse=True)
        if remain_assign_mode == "msa":
            alpha = 1.0 / max(1, iter_flag)
            args = [
                (origin, destinations, [flow * alpha for flow in flows])
                for origin, destinations, flows in args
            ]
            logging.info(
                "MSA remain assignment: alpha=%.8f (1/%s) for iteration %s",
                alpha,
                iter_flag,
                iter_flag,
            )
        del args_df
        gc.collect()
        _log_rss(f"iter{iter_flag}_args_built")

        conn.execute("DROP TABLE IF EXISTS temp_flow_matrix_input")
        od_id_at_insert = _env_flag("NIRD_OD_ID_AT_INSERT")
        lcp_collect_pool = _env_flag("NIRD_LCP_COLLECT_POOL_RESULTS")
        if od_id_at_insert:
            conn.execute(
                """
                CREATE TABLE temp_flow_matrix_input (
                    od_id BIGINT,
                    origin VARCHAR,
                    destination VARCHAR,
                    path INT[],
                    flow DOUBLE
                );
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE temp_flow_matrix_input (
                    origin VARCHAR,
                    destination VARCHAR,
                    path INT[],
                    flow DOUBLE
                );
                """
            )
        conn.execute("DROP TABLE IF EXISTS temp_isolated_flow_matrix")
        conn.execute(
            """
            CREATE TEMP TABLE temp_isolated_flow_matrix (
                origin VARCHAR,
                destination VARCHAR,
                flow DOUBLE
            );
            """
        )

        flow_batch: List[Tuple[str, str, List[int], float]] = []
        isolated_batch: List[Tuple[str, str, float]] = []
        batch_size = int(os.environ.get("NIRD_FLOW_DB_BATCH_SIZE", "100000"))
        logging.info(f"Flow DB insert batch size: {batch_size:,}")

        def flush_flow_batch() -> None:
            nonlocal flow_batch, next_od_id_base
            if not flow_batch:
                return
            if od_id_at_insert:
                rows = []
                for origin, destination, path, flow in flow_batch:
                    rows.append((next_od_id_base, origin, destination, path, flow))
                    next_od_id_base += 1
                batch_df = pd.DataFrame(
                    rows,
                    columns=["od_id", "origin", "destination", "path", "flow"],
                )
            else:
                batch_df = pd.DataFrame(
                    flow_batch, columns=["origin", "destination", "path", "flow"]
                )
            conn.register("temp_flow_batch", batch_df)
            conn.execute(
                "INSERT INTO temp_flow_matrix_input SELECT * FROM temp_flow_batch"
            )
            conn.unregister("temp_flow_batch")
            flow_batch = []

        def flush_isolated_batch() -> None:
            nonlocal isolated_batch
            if not isolated_batch:
                return
            iso_df = pd.DataFrame(
                isolated_batch, columns=["origin", "destination", "flow"]
            )
            conn.register("temp_isolated_batch", iso_df)
            conn.execute(
                "INSERT INTO temp_isolated_flow_matrix SELECT * FROM temp_isolated_batch"
            )
            conn.unregister("temp_isolated_batch")
            isolated_batch = []

        def handle_shortest_path(
            shortest_path: Tuple[str, List[str], List[List[int]], List[float]],
        ) -> None:
            origin_node, destinations, paths, flows = shortest_path
            for dest, path, flow in zip(destinations, paths, flows):
                flow_val = float(flow) if flow is not None else 0.0
                if not path:  # if no path between OD -> isolation
                    isolated_batch.append((origin_node, dest, flow_val))
                else:
                    flow_batch.append((origin_node, dest, path, flow_val))
                if len(flow_batch) >= batch_size:
                    flush_flow_batch()
                if len(isolated_batch) >= batch_size:
                    flush_isolated_batch()

        def _log_lcp_progress(i: int, total: int) -> None:
            if i == 1 or i % 10 == 0 or i == total:
                logging.info(
                    f"Completed {i} of {total}, {100 * i / total:.2f}%"
                )

        # batch-processing
        lcp_pool_st = time.time()

        # imap_unordered default chunksize is 1 (one IPC round-trip per
        # origin-task); raising it batches multiple tasks per round-trip,
        # cutting IPC overhead at the cost of coarser load balancing. Opt-in
        # via env; combined with the size-descending sort above, large tasks
        # still get their own round-trip early while small ones batch later.
        pool_chunksize = max(1, int(os.environ.get("NIRD_LCP_POOL_CHUNKSIZE", "1")))

        def _run_pool_dispatch(pool) -> None:
            dispatch_st = time.time()
            if lcp_collect_pool:
                nonlocal pool_results
                pool_results = list(
                    pool.imap_unordered(
                        find_least_cost_path, args, chunksize=pool_chunksize
                    )
                )
            else:
                for i, shortest_path in enumerate(
                    pool.imap_unordered(
                        find_least_cost_path, args, chunksize=pool_chunksize
                    ),
                    start=1,
                ):
                    handle_shortest_path(shortest_path)
                    _log_lcp_progress(i, len(args))
            logging.info(
                "Pool dispatch (imap_unordered consumption) time: %.3f seconds "
                "(chunksize=%s).",
                time.time() - dispatch_st,
                pool_chunksize,
            )

        pool_results = None
        if persistent_pool_enabled:
            refresh_st = time.time()
            persistent_pool.map(
                refresh_worker_network, [shared_network_pkl] * num_of_cpu
            )
            logging.info(
                "Persistent pool worker refresh time: %.3f seconds "
                "(num_of_cpu=%s).",
                time.time() - refresh_st,
                num_of_cpu,
            )
            _run_pool_dispatch(persistent_pool)
        elif num_of_cpu > 1:
            pool_kwargs = {
                "processes": num_of_cpu,
                "initializer": worker_init_path,
                "initargs": (shared_network_pkl,),
            }
            max_tasks_per_child = int(
                os.environ.get("NIRD_POOL_MAX_TASKS_PER_CHILD", "0")
            )
            if max_tasks_per_child > 0:
                pool_kwargs["maxtasksperchild"] = max_tasks_per_child

            pool_spawn_st = time.time()
            with Pool(**pool_kwargs) as pool:
                pool_spawn_sec = time.time() - pool_spawn_st
                logging.info(
                    "Pool construction (spawn+initializer) time: %.3f seconds "
                    "(num_of_cpu=%s).",
                    pool_spawn_sec,
                    num_of_cpu,
                )
                _run_pool_dispatch(pool)
        else:
            global shared_network
            shared_network = network
            if lcp_collect_pool:
                pool_results = [find_least_cost_path(arg) for arg in args]
            else:
                for i, shortest_path in enumerate(
                    (find_least_cost_path(arg) for arg in args), start=1
                ):
                    handle_shortest_path(shortest_path)
                    _log_lcp_progress(i, len(args))

        lcp_pool_sec = time.time() - lcp_pool_st
        logging.info(f"The least-cost path flow allocation time: {lcp_pool_sec}.")
        _log_rss(f"iter{iter_flag}_lcp_pool_done")

        if lcp_collect_pool:
            lcp_db_st = time.time()
            for i, shortest_path in enumerate(pool_results, start=1):
                handle_shortest_path(shortest_path)
                _log_lcp_progress(i, len(pool_results))
            flush_flow_batch()
            flush_isolated_batch()
            logging.info(
                f"LCP DuckDB insert phase: {time.time() - lcp_db_st:.2f} seconds"
            )
        else:
            flush_flow_batch()
            flush_isolated_batch()

        temp_isolation = (
            conn.execute(
                "SELECT COALESCE(SUM(flow), 0.0) FROM temp_isolated_flow_matrix"
            ).fetchone()[0]
            or 0.0
        )
        logging.info(f"Non_allocated_flow: {temp_isolation}")
        if temp_isolation > 0:
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE temp_isolated_flow_matrix_agg AS
                SELECT
                    origin,
                    destination,
                    SUM(flow) AS flow
                FROM temp_isolated_flow_matrix
                GROUP BY origin, destination;
                """
            )
            conn.execute(
                "INSERT INTO isolated_od SELECT * FROM temp_isolated_flow_matrix_agg"
            )
            conn.execute(
                """
                DELETE FROM remain_od
                USING temp_isolated_flow_matrix_agg i
                WHERE CAST(remain_od.origin_node AS VARCHAR) = i.origin
                  AND CAST(remain_od.destination_node AS VARCHAR) = i.destination;
                """
            )
            conn.execute("DROP TABLE IF EXISTS temp_isolated_flow_matrix_agg")
        conn.execute("DROP TABLE IF EXISTS temp_isolated_flow_matrix")

        temp_flow_count = (
            conn.execute("SELECT COUNT(*) FROM temp_flow_matrix_input").fetchone()[0]
            or 0
        )
        if temp_flow_count == 0:
            logging.info("Stop: no remaining flows!")
            conn.execute("DROP TABLE IF EXISTS temp_flow_matrix_input")
            break
        od_id_st = time.time()
        if od_id_at_insert:
            logging.info(
                "Assigning od_id during LCP inserts; skipping ROW_NUMBER rewrite for %s path rows.",
                f"{temp_flow_count:,}",
            )
        else:
            logging.info(
                "Assigning stable od_id values %s to %s for %s path rows.",
                next_od_id_base,
                next_od_id_base + temp_flow_count - 1,
                temp_flow_count,
            )
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE temp_flow_matrix_input_indexed AS
                SELECT
                    CAST({next_od_id_base} + ROW_NUMBER() OVER (
                        ORDER BY origin, destination
                    ) - 1 AS BIGINT) AS od_id,
                    origin,
                    destination,
                    path,
                    flow
                FROM temp_flow_matrix_input;
                """
            )
            conn.execute("DROP TABLE temp_flow_matrix_input")
            conn.execute(
                "ALTER TABLE temp_flow_matrix_input_indexed RENAME TO temp_flow_matrix_input"
            )
            next_od_id_base += temp_flow_count
        logging.info(
            "od_id assignment phase: %.2f seconds",
            time.time() - od_id_st,
        )

        # %%
        _log_rss(f"iter{iter_flag}_before_itter_path")
        logging.info("Create temp_flow_matrix table in duckdb...")
        # origin (name), destination(name), path(idx), flow(int)
        itter_path(
            network,
            road_links,
            temp_flow_matrix=None,
            num_of_chunk=num_of_chunk,
            db_path=db_path,
            conn=conn,
            temp_flow_table="temp_flow_matrix_input",
            create_full_temp_flow_matrix=create_full_temp_flow_matrix,
            event_candidates_out_dir=baseline_out_dir,
            damaged_edges_path=damaged_edges_path,
            combine_event_candidate_parts=combine_event_candidate_parts,
            vehicle_type=vehicle_type,
        )  # -> xxx, fuel, time, toll

        if create_full_temp_flow_matrix:
            assigned_iter_sum = (
                conn.execute(
                    "SELECT COALESCE(SUM(flow), 0.0) FROM temp_flow_matrix"
                ).fetchone()[0]
                or 0.0
            )
        else:
            assigned_iter_sum = (
                conn.execute(
                    "SELECT COALESCE(assigned_flow_total, 0.0) FROM temp_iteration_costs"
                ).fetchone()[0]
                or 0.0
            )
        logging.info(
            "Post-realization assigned_iter_sum for iteration %s: %s",
            iter_flag,
            assigned_iter_sum,
        )

        # assign flows (scalar) for this iteration
        assigned_sumod += assigned_iter_sum
        percentage_sumod = assigned_sumod / initial_sumod if initial_sumod > 0 else 1.0

        # append the adjusted per-OD rows (e_id) into odpfc (-> path)
        # conn.execute(
        #     """
        #     INSERT INTO odpfc (
        #         origin,
        #         destination,
        #         path,
        #         flow,
        #         fuel,
        #         time,
        #         toll,
        #         length_mile
        #     )
        #     SELECT
        #         origin,
        #         destination,
        #         e_id,
        #         flow,
        #         fuel,
        #         time,
        #         toll,
        #         length_mile
        #     FROM temp_flow_matrix
        #     """
        # )
        if vehicle_type == "psv":
            time_expr = f"time + 0.25 * {cons.VOT_POUND_PER_HOUR[vehicle_type]}"
            fare_expr = f"LEAST(2.0 + 0.15 * length_mile * {cons.CONV_MILE_TO_KM}, 4.5)"
        elif vehicle_type == "rail":
            time_expr = f"time + 0.15 * {cons.VOT_POUND_PER_HOUR[vehicle_type]}"
            fare_expr = (
                f"LEAST(3.0 + 0.2  * length_mile * {cons.CONV_MILE_TO_KM}, 250.0)"
            )
        else:
            time_expr = "time"
            fare_expr = "0.0"

        logging.info(
            "Writing OD path output for iteration %s with mode=%s...",
            iter_flag,
            baseline_path_output_mode,
        )
        if write_full_odpfc:
            if odpfc_output_mode == "duckdb_table":
                conn.execute(
                    f"""
                    INSERT INTO odpfc (
                        od_id,
                        origin,
                        destination,
                        path,
                        flow,
                        fuel,
                        time,
                        toll,
                        fare
                    )
                    SELECT
                        od_id,
                        origin,
                        destination,
                        e_id AS path,
                        flow,
                        fuel,
                        {time_expr} AS time,
                        toll,
                        {fare_expr} AS fare
                    FROM temp_flow_matrix
                    """
                )
                logging.info("Finished INSERT INTO odpfc for iteration %s.", iter_flag)
            elif odpfc_output_mode == "iteration_parquet":
                if odpfc_parts_dir is None:
                    raise ValueError(
                        "iteration_parquet mode requires odpfc_out_path so an "
                        "odpfc_parts directory can be derived"
                    )
                part_path = os.path.join(odpfc_parts_dir, f"odpfc_iter_{iter_flag:06d}.pq")
                conn.execute(
                    f"""
                    COPY (
                        SELECT
                            od_id,
                            origin AS origin_node,
                            destination AS destination_node,
                            e_id AS path,
                            flow,
                            fuel AS operating_cost_per_flow,
                            {time_expr} AS time_cost_per_flow,
                            toll AS toll_cost_per_flow,
                            {fare_expr} AS fare_cost_per_flow
                        FROM temp_flow_matrix
                    ) TO '{_sql_path(part_path)}' (FORMAT PARQUET);
                    """
                )
                logging.info("Wrote OD path output part: %s", part_path)
            else:
                logging.info(
                    "Skipping full OD path output for iteration %s; profiling mode only.",
                    iter_flag,
                )
        elif baseline_path_output_mode in {"od_meta_only", "path_index"}:
            if od_meta_parts_dir is None:
                raise ValueError(
                    "OD metadata output requires odpfc_out_path so an output "
                    "directory can be derived"
                )
            meta_part_path = os.path.join(
                od_meta_parts_dir, f"baseline_od_meta_iter_{iter_flag:06d}.pq"
            )
            conn.execute(
                f"""
                COPY (
                    SELECT
                        od_id,
                        origin AS origin_node,
                        destination AS destination_node,
                        flow,
                        fuel AS operating_cost_per_flow,
                        {time_expr} AS time_cost_per_flow,
                        toll AS toll_cost_per_flow,
                        {fare_expr} AS fare_cost_per_flow,
                        length_mile
                    FROM temp_flow_matrix
                ) TO '{_sql_path(meta_part_path)}' (FORMAT PARQUET);
                """
            )
            meta_rows = (
                conn.execute("SELECT COUNT(*) FROM temp_flow_matrix").fetchone()[0] or 0
            )
            logging.info(
                "Wrote baseline OD metadata part %s with %s rows.",
                meta_part_path,
                meta_rows,
            )
            if baseline_path_output_mode == "path_index":
                if path_index_parts_dir is None:
                    raise ValueError("path_index mode requires path_index_parts_dir")
                logging.info(
                    "Writing narrow path-index parts for iteration %s...",
                    iter_flag,
                )
                min_max = conn.execute(
                    "SELECT MIN(od_id), MAX(od_id) FROM temp_flow_matrix_input"
                ).fetchone()
                min_od_id, max_od_id = min_max
                part_count = 0
                path_index_rows = 0
                if min_od_id is not None:
                    path_index_chunk_size = max(
                        1,
                        math.ceil(
                            (int(max_od_id) - int(min_od_id) + 1)
                            / max(1, int(num_of_chunk))
                        ),
                    )
                    for start_od in tqdm(
                        range(int(min_od_id), int(max_od_id) + 1, path_index_chunk_size),
                        desc="Writing path-index parts:",
                        unit="part",
                    ):
                        end_od = min(start_od + path_index_chunk_size - 1, int(max_od_id))
                        index_part_path = os.path.join(
                            path_index_parts_dir,
                            f"path_index_iter_{iter_flag:06d}_{part_count:04d}.pq",
                        )
                        conn.execute(
                            f"""
                            COPY (
                                SELECT
                                    od_id,
                                    CAST(u.path_idx AS INTEGER) AS edge_idx,
                                    CAST(u.ord - 1 AS INTEGER) AS path_pos
                                FROM (
                                    SELECT od_id, path
                                    FROM temp_flow_matrix_input
                                    WHERE od_id BETWEEN {start_od} AND {end_od}
                                ) t
                                CROSS JOIN UNNEST(t.path) WITH ORDINALITY AS u(path_idx, ord)
                            ) TO '{_sql_path(index_part_path)}' (FORMAT PARQUET);
                            """
                        )
                        part_rows = (
                            conn.execute(
                                f"""
                                SELECT COALESCE(SUM(LEN(path)), 0)
                                FROM temp_flow_matrix_input
                                WHERE od_id BETWEEN {start_od} AND {end_od}
                                """
                            ).fetchone()[0]
                            or 0
                        )
                        path_index_rows += int(part_rows)
                        part_count += 1
                logging.info(
                    "Wrote %s path-index parts with %s rows to %s.",
                    part_count,
                    path_index_rows,
                    path_index_parts_dir,
                )
        elif baseline_path_output_mode == "event_candidates":
            if create_full_temp_flow_matrix:
                if baseline_out_dir is None:
                    raise ValueError(
                        "event_candidates mode requires odpfc_out_path so an output "
                        "directory can be derived"
                    )
                if not damaged_edges_path:
                    raise ValueError(
                        "event_candidates mode requires NIRD_EVENT_DAMAGED_EDGES_PATH"
                    )
                logging.info(
                    "Patch 4 post-streaming event-candidate scan is active because "
                    "NIRD_CREATE_FULL_TEMP_FLOW_MATRIX=1."
                )
                write_event_disrupted_candidates(
                    conn=conn,
                    network=network,
                    damaged_edges_path=damaged_edges_path,
                    out_dir=baseline_out_dir,
                    time_expr=time_expr,
                    fare_expr=fare_expr,
                    chunk_size=max(1, math.ceil(temp_flow_count / max(1, int(num_of_chunk)))),
                    iter_flag=iter_flag,
                    combine_parts=combine_event_candidate_parts,
                )
            else:
                logging.info(
                    "Event candidates were written inside streaming pass 2; "
                    "post-streaming event-candidate scan was not triggered."
                )
        elif baseline_path_output_mode == "none":
            logging.info("Skipping baseline OD path artifacts for iteration %s.", iter_flag)
        else:
            raise ValueError(f"Unhandled baseline output mode: {baseline_path_output_mode}")

        # compute costs
        logging.info("Computing cost components for iteration %s...", iter_flag)
        if create_full_temp_flow_matrix:
            iter_cost_fuel = (
                conn.execute(
                    "SELECT COALESCE(SUM(flow * fuel), 0.0) FROM temp_flow_matrix"
                ).fetchone()[0]
                or 0.0
            )
            iter_cost_time = (
                conn.execute(
                    f"SELECT COALESCE(SUM(flow * {time_expr}), 0.0) FROM temp_flow_matrix"
                ).fetchone()[0]
                or 0.0
            )
            iter_cost_toll = (
                conn.execute(
                    "SELECT COALESCE(SUM(flow * toll), 0.0) FROM temp_flow_matrix"
                ).fetchone()[0]
                or 0.0
            )
            iter_cost_fare = (
                conn.execute(
                    f"SELECT COALESCE(SUM(flow * {fare_expr}), 0.0) FROM temp_flow_matrix"
                ).fetchone()[0]
                or 0.0
            )
        else:
            (
                iter_cost_fuel,
                iter_cost_time,
                iter_cost_toll,
                iter_cost_fare,
            ) = conn.execute(
                """
                SELECT
                    COALESCE(fuel_cost_total, 0.0),
                    COALESCE(time_cost_total, 0.0),
                    COALESCE(toll_cost_total, 0.0),
                    COALESCE(fare_cost_total, 0.0)
                FROM temp_iteration_costs
                """
            ).fetchone()

        cost_fuel += iter_cost_fuel
        cost_time += iter_cost_time
        cost_toll += iter_cost_toll
        cost_fare += iter_cost_fare
        total_cost = cost_fuel + cost_time + cost_toll + cost_fare
        logging.info(
            "Iteration %s cost components: fuel=%s, time=%s, toll=%s, fare=%s, total_so_far=%s",
            iter_flag,
            iter_cost_fuel,
            iter_cost_time,
            iter_cost_toll,
            iter_cost_fare,
            total_cost,
        )

        # aggregate edge flows from realized paths
        if path_strategy in {"streaming_arrays", "streaming"}:
            logging.info(
                "Loading edge flows directly from temp_edge_flow for iteration %s.",
                iter_flag,
            )
            temp_edge_flow = conn.execute(
                """
                SELECT e_id, flow
                FROM temp_edge_flow
                WHERE flow > 0
                """
            ).fetchdf()
            logging.info(
                "Loaded %s temp_edge_flow rows directly; UNNEST(e_id) not triggered.",
                len(temp_edge_flow),
            )
        else:
            logging.info(
                "Computing edge flows with UNNEST(e_id) for iteration %s.",
                iter_flag,
            )
            temp_edge_flow = conn.execute(
                """
                SELECT
                    e AS e_id,
                    SUM(flow) AS flow
                FROM (
                    SELECT
                        flow,
                        UNNEST(e_id) AS e
                    FROM temp_flow_matrix
                ) AS t
                GROUP BY e
            """
            ).fetchdf()
            logging.info("Loaded %s edge-flow rows from UNNEST path.", len(temp_edge_flow))

        # merge edge flows into road_links and update accumulators
        logging.info("Updating road_links with iteration %s edge flows...", iter_flag)
        road_links = road_links.merge(
            temp_edge_flow[["e_id", "flow"]], on="e_id", how="left"
        )
        road_links["flow"] = road_links["flow"].fillna(0.0)
        road_links["acc_flow"] += road_links["flow"]
        road_links["acc_capacity"] = road_links["acc_capacity"] - road_links["flow"]

        # Recalculate edge speeds for edges that changed (vectorized if possible)
        logging.info("Updating edge speeds: ")
        update_edge_speed(road_links, inplace=True)
        road_links.drop(columns=["flow"], inplace=True)
        logging.info("Finished road_links update for iteration %s.", iter_flag)

        # update remain od using DuckDB
        logging.info("Updating remain_od for iteration %s...", iter_flag)
        assignment_table = None
        for candidate_table in ("temp_od_assignment", "temp_flow_matrix"):
            try:
                conn.execute(f"SELECT 1 FROM {candidate_table} LIMIT 1").fetchone()
                assignment_table = candidate_table
                break
            except Exception:
                continue
        if assignment_table is None:
            raise RuntimeError(
                "No assignment temp table was created before remain_od update; "
                "expected temp_od_assignment or temp_flow_matrix."
            )
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE remain_od_updated AS
            SELECT
                r.origin_node,
                r.destination_node,
                GREATEST((r.Car21 - COALESCE(a.flow_assigned, 0.0)), 0.0) AS Car21
            FROM remain_od r
            LEFT JOIN (
                SELECT
                    origin,
                    destination,
                    SUM(flow) AS flow_assigned
                FROM {assignment_table}
                GROUP BY origin, destination
            ) a
            ON r.origin_node = a.origin AND r.destination_node = a.destination;
            """
        )

        conn.execute("DELETE FROM remain_od")
        conn.execute(
            """
        INSERT INTO remain_od
        SELECT origin_node, destination_node, Car21
        FROM remain_od_updated
        WHERE Car21 > 0;
        """
        )

        total_remain = (
            conn.execute("SELECT COALESCE(SUM(Car21), 0.0) FROM remain_od").fetchone()[
                0
            ]
            or 0.0
        )
        logging.info(f"The total remain flow (after adjustment) is: {total_remain}.")
        remain_fraction = total_remain / initial_sumod if initial_sumod > 0 else 0.0
        logging.info(
            "Pass A convergence: remain_fraction=%.8f assigned_fraction=%.8f iteration=%s",
            remain_fraction,
            1.0 - remain_fraction,
            iter_flag,
        )
        progress = max(previous_total_remain - total_remain, 0.0)
        progress_rel = progress / initial_sumod if initial_sumod > 0 else 0.0
        if progress_rel < min_progress_rel:
            stagnant_iterations += 1
        else:
            stagnant_iterations = 0
        logging.info(
            f"Iteration progress: assigned_delta={progress}, "
            f"progress_rel={progress_rel:.8%}, "
            f"stagnant_iterations={stagnant_iterations}/{stagnant_limit}."
        )
        logging.info("Cleaning transient path-realization tables for iteration %s...", iter_flag)
        for transient_table in [
            "od_results_iter",
            "od_adjustment",
            "temp_flow_matrix_input",
            "temp_flow_matrix",
            "temp_od_assignment",
            "temp_iteration_costs",
            "temp_edge_flow",
            "temp_edge_flow_df",
            "edge_total_parts",
            "od_adjustment_parts",
            "temp_flow_indexed",
            "total",
            "remain_od_updated",
        ]:
            conn.execute(f"DROP TABLE IF EXISTS {transient_table}")
        logging.info("Finished cleanup for iteration %s.", iter_flag)
        gc.collect()
        _log_rss(f"iter{iter_flag}_end")

        # %%
        # check point for next iteration
        if percentage_sumod >= 0.99:
            temp_isolation = (
                conn.execute(
                    "SELECT COALESCE(SUM(Car21), 0.0) FROM remain_od"
                ).fetchone()[0]
                or 0.0
            )
            if temp_isolation > 0:
                conn.execute(
                    """
                    INSERT INTO isolated_od
                    SELECT
                        origin_node,
                        destination_node,
                        Car21 AS flow
                    FROM remain_od;
                    """
                )
            logging.info(
                f"Stop: {percentage_sumod*100}% of flows have been allocated with "
                f"{temp_isolation} extra isolated flows."
            )
            break

        if max_iterations > 0 and iter_flag >= max_iterations:
            temp_isolation = (
                conn.execute(
                    "SELECT COALESCE(SUM(Car21), 0.0) FROM remain_od"
                ).fetchone()[0]
                or 0.0
            )
            if temp_isolation > 0:
                conn.execute(
                    """
                    INSERT INTO isolated_od
                    SELECT
                        origin_node,
                        destination_node,
                        Car21 AS flow
                    FROM remain_od;
                    """
                )
            logging.info(
                f"Stop: Maximum iterations reached ({max_iterations}) with "
                f"{temp_isolation} extra isolated flows. "
            )
            logging.info(f"Stop: Maximum iterations reached ({max_iterations})!")
            break

        if stagnant_limit > 0 and stagnant_iterations >= stagnant_limit:
            temp_isolation = (
                conn.execute(
                    "SELECT COALESCE(SUM(Car21), 0.0) FROM remain_od"
                ).fetchone()[0]
                or 0.0
            )
            if temp_isolation > 0:
                conn.execute(
                    """
                    INSERT INTO isolated_od
                    SELECT
                        origin_node,
                        destination_node,
                        Car21 AS flow
                    FROM remain_od;
                    """
                )
            logging.info(
                "Stop: Insufficient progress for "
                f"{stagnant_iterations} consecutive iterations with "
                f"{temp_isolation} extra isolated flows. "
            )
            break

        # %%
        # update network structure (nodes and edges) for next iteration
        network, road_links = update_network_structure(
            number_of_edges, network, temp_edge_flow, road_links
        )

        del temp_edge_flow
        gc.collect()

        iter_flag += 1

    if persistent_pool is not None:
        persistent_pool.close()
        persistent_pool.join()
        logging.info("Persistent LCP worker pool closed.")

    cList = [cost_time, cost_fuel, cost_toll, total_cost]
    road_links = road_links[road_links_columns]

    # create isolation and odpfc from db
    if iso_out_path is not None:
        conn.execute(
            f"""
            COPY (
                SELECT
                    origin_node,
                    destination_node,
                    SUM(flow) AS flow
                FROM isolated_od
                WHERE origin_node != destination_node
                  AND flow > 0
                GROUP BY origin_node, destination_node
            ) TO '{iso_out_path}' (FORMAT PARQUET);
        """
        )
    if (
        odpfc_out_path is not None
        and write_full_odpfc
        and odpfc_output_mode == "duckdb_table"
    ):
        logging.info("Writing final odpfc output from DuckDB table to %s", odpfc_out_path)
        conn.execute(
            f"""
            COPY (
                SELECT
                    origin AS origin_node,
                    destination AS destination_node,
                    MIN(od_id) AS od_id,
                    path,
                    SUM(flow) AS flow,
                    MIN(fuel) AS operating_cost_per_flow,
                    MIN(time) AS time_cost_per_flow,
                    MIN(toll) AS toll_cost_per_flow,
                    MIN(fare) AS fare_cost_per_flow
                FROM odpfc
                GROUP BY origin, destination, path
            ) TO '{odpfc_out_path}' (FORMAT PARQUET);
        """
        )
        logging.info("Finished final odpfc DuckDB table export.")
    elif (
        odpfc_out_path is not None
        and write_full_odpfc
        and odpfc_output_mode == "iteration_parquet"
    ):
        if combine_odpfc_parts:
            logging.info(
                "Combining odpfc_parts from %s into %s",
                odpfc_parts_dir,
                odpfc_out_path,
            )
            conn.execute(
                f"""
                COPY (
                    SELECT
                        origin_node,
                        destination_node,
                        path,
                        SUM(flow) AS flow,
                        MIN(operating_cost_per_flow) AS operating_cost_per_flow,
                        MIN(time_cost_per_flow) AS time_cost_per_flow,
                        MIN(toll_cost_per_flow) AS toll_cost_per_flow,
                        MIN(fare_cost_per_flow) AS fare_cost_per_flow
                    FROM read_parquet('{_sql_path(os.path.join(odpfc_parts_dir, "*.pq"))}')
                    GROUP BY origin_node, destination_node, path
                ) TO '{_sql_path(odpfc_out_path)}' (FORMAT PARQUET);
                """
            )
            logging.info("Finished combined odpfc part export.")
        else:
            logging.info(
                "Leaving partitioned OD path output under %s; "
                "NIRD_COMBINE_ODPFC_PARTS=0.",
                odpfc_parts_dir,
            )
    elif (
        odpfc_out_path is not None
        and baseline_path_output_mode in {"od_meta_only", "path_index"}
    ):
        baseline_od_meta_path = os.path.join(
            os.path.dirname(odpfc_out_path), "baseline_od_meta.pq"
        )
        logging.info(
            "Combining baseline OD metadata parts from %s into %s",
            od_meta_parts_dir,
            baseline_od_meta_path,
        )
        conn.execute(
            f"""
            COPY (
                SELECT *
                FROM read_parquet('{_sql_path(os.path.join(od_meta_parts_dir, "*.pq"))}')
            ) TO '{_sql_path(baseline_od_meta_path)}' (FORMAT PARQUET);
            """
        )
        od_meta_rows = (
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM read_parquet('{_sql_path(os.path.join(od_meta_parts_dir, "*.pq"))}')
                """
            ).fetchone()[0]
            or 0
        )
        logging.info(
            "Wrote baseline_od_meta.pq with %s rows. Full odpfc skipped.",
            od_meta_rows,
        )
        if baseline_path_output_mode == "path_index":
            part_count = len(
                [
                    name
                    for name in os.listdir(path_index_parts_dir)
                    if name.endswith(".pq")
                ]
            )
            path_index_rows = (
                conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM read_parquet('{_sql_path(os.path.join(path_index_parts_dir, "*.pq"))}')
                    """
                ).fetchone()[0]
                or 0
            )
            logging.info(
                "Path-index artifact summary: parts=%s, rows=%s, edge_lookup=%s.",
                part_count,
                path_index_rows,
                edge_lookup_path,
            )
    elif odpfc_out_path is not None:
        logging.info(
            "OD path output was skipped; no odpfc output written to %s.",
            odpfc_out_path,
        )
    conn.close()

    logging.info("The flow simulation is completed!")
    logging.info(f"total travel cost is ($): {total_cost}")
    logging.info(f"total time-equiv cost is ($): {cost_time}")
    logging.info(f"total operating cost is ($): {cost_fuel}")
    logging.info(f"total toll cost is ($): {cost_toll}")

    return road_links, cList
