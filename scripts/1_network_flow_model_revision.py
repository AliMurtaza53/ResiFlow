from pathlib import Path
import os
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import geopandas as gpd  # type: ignore
import duckdb

from resiflow.utils import get_results_variant, load_config
from resiflow.demand import (
    align_od_node_dtype,
    demand_spec_from_env,
    load_assignment_demand,
    passenger_od_disabled,
)
from resiflow.networks import load_assignment_profiles, normalize_network_links
import resiflow.road_revised as func

import logging
import json
import warnings

warnings.simplefilter("ignore")
base_path = Path(load_config()["paths"]["soge_clusters"])


def first_existing(paths):
    """Return the first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


def main(
    num_of_chunk: int,
    num_of_cpu: int,
    sample_stride=1,
):
    """
    Main function to validate the network flow model.

    Model Inputs:
        - Model parameters:
            - Flow breakpoints, capacity, free-flow speeds, minimum speeds,
            and urban speed limits.
        - faf5_road_links.gpq:
            GeoDataFrame containing FAF5 road network data with attributes.
        - faf5_od_matrix.pq:
            Origin-destination matrix containing FAF5 traffic flow data.

    Model Outputs:
        - edge_flows_validation.gpq:
            GeoDataFrame of road network data enriched with validation results.
        - trip_isolation_validation.csv:
            CSV file containing data on isolated trips resulting from network
            disruptions.

    Parameters:
        num_of_cpu (int): Number of CPUs to use for parallel processing.
        sample_stride (int): Stride length to use on OD. Defaults to using
            entire matrix.

    Returns:
        None: Outputs are saved to files.
    """
    start_time = time.time()
    db_path = Path(
        os.environ.get("NIRD_BASELINE_DB_PATH") or base_path / "dbs" / "baseline.duckdb"
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Database path is: {db_path}")

    # model parameters

    params_root = first_existing(
        [
            base_path / "parameters",
            base_path / "inputs" / "parameters",
        ]
    )
    if params_root is None:
        raise FileNotFoundError(
            "Could not find parameter folder. Checked base_path/parameters and base_path/inputs/parameters"
        )

    profiles = load_assignment_profiles(params_root)
    flow_breakpoint_dict = profiles["flow_breakpoint"]
    flow_capacity_dict = profiles["flow_cap_plph"]
    free_flow_speed_dict = profiles["free_flow_speed"]
    min_speed_dict = profiles["min_speed_cap"]
    urban_speed_dict = profiles["urban_speed_cap"]
    logging.info(flow_capacity_dict)

    # network links -> network links with bridges (SUBNETWORK)
    road_links_path = first_existing(
        [
            base_path / "networks" / "faf5" / "faf5_road_links.gpq",
            base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
        ]
    )
    if road_links_path is None:
        raise FileNotFoundError("Could not find faf5_road_links.gpq in standard or toy input paths")
    road_link_file = gpd.read_parquet(road_links_path)
    road_link_file = normalize_network_links(road_link_file, params_root=str(params_root))

    demand_result = load_assignment_demand(base_path, demand_spec_from_env(base_path))
    od_node_2021 = demand_result.assignment_od.copy()
    od_flow_col = "Car21"
    logging.info(
        "Assignment demand (%s): freight=%.3f passenger=%.3f total=%.3f",
        demand_result.stats.get("source", "faf5_parquet"),
        demand_result.stats.get("freight_flow", 0.0),
        demand_result.stats.get("passenger_flow", 0.0),
        demand_result.stats.get("combined_flow", 0.0),
    )
    if passenger_od_disabled():
        logging.info("Passenger OD not configured; using freight-only assignment demand.")

    if sample_stride > 1:
        logging.info(f"For testing, sampling every {sample_stride} flows")
        od_node_2021 = od_node_2021.iloc[::sample_stride]
    sample_od_n = int(os.environ.get("NIRD_SAMPLE_OD_N", "0"))
    if sample_od_n > 0:
        logging.info(f"For testing, taking first {sample_od_n:,} OD rows")
        od_node_2021 = od_node_2021.head(sample_od_n)

    # Smoke-test cap: when sampling, also bound the *combined* OD so passenger demand
    # (merged in full above) does not blow the row count back up. Random sample keeps a
    # representative freight+passenger mix for validating the integrated assignment.
    if sample_od_n > 0 and len(od_node_2021) > sample_od_n:
        logging.info(f"Capping combined OD to first {sample_od_n:,} rows for smoke test")
        od_node_2021 = od_node_2021.sample(
            n=sample_od_n, random_state=42
        ).reset_index(drop=True)

    od_node_2021[od_flow_col] = pd.to_numeric(
        od_node_2021[od_flow_col], errors="coerce"
    ).fillna(0.0)
    od_node_2021 = align_od_node_dtype(od_node_2021, road_link_file)
    total_flow = od_node_2021[od_flow_col].sum()
    self_pair_flow = od_node_2021.loc[
        od_node_2021["origin_node"] == od_node_2021["destination_node"],
        od_flow_col,
    ].sum()
    duplicate_pair_count = int(
        od_node_2021.groupby(["origin_node", "destination_node"]).size().gt(1).sum()
    )

    logging.info(f"\n{od_node_2021}")
    logging.info(
        f"OD totals ({od_flow_col}): rows={len(od_node_2021):,}, "
        f"total={total_flow:,.3f}, self_pair_flow={self_pair_flow:,.3f}, "
        f"duplicate_pairs={duplicate_pair_count:,}"
    )

    # initialise road links
    logging.info("Generate road links")
    road_links = func.edge_init(
        road_link_file,
        flow_breakpoint_dict,
        flow_capacity_dict,
        free_flow_speed_dict,
        urban_speed_dict,
        min_speed_dict,
        max_flow_speed_dict=None,
    )
    # create igraph network
    logging.info("Create igraph network")
    network, road_links = func.create_igraph_network(road_links, vehicle_type="car")

    out_path = Path(
        os.environ.get(
            "NIRD_BASE_SCENARIO_OUT_DIR",
            base_path.parent / "results" / "base_scenario" / get_results_variant(),
        )
    )
    out_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NIRD_DUCKDB_CHUNKED_PATH_EXPANSION", "0")
    os.environ.setdefault("NIRD_PATH_REALIZATION_STRATEGY", "legacy_compact_sql")
    direct_duckdb_outputs = os.environ.get("NIRD_DIRECT_DUCKDB_OUTPUTS", "1").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    path_strategy = os.environ.get(
        "NIRD_PATH_REALIZATION_STRATEGY", "legacy_compact_sql"
    ).strip().lower()
    if (
        direct_duckdb_outputs
        and path_strategy in {"streaming_arrays", "streaming"}
        and "NIRD_BASELINE_PATH_OUTPUT_MODE" not in os.environ
    ):
        if os.environ.get("NIRD_EVENT_DAMAGED_EDGES_PATH"):
            os.environ["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "event_candidates"
        else:
            os.environ["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "none"
    if (
        direct_duckdb_outputs
        and path_strategy in {"streaming_arrays", "streaming"}
        and os.environ.get("NIRD_BASELINE_PATH_OUTPUT_MODE", "").strip().lower()
        == "full_odpfc"
        and "NIRD_ODPFC_OUTPUT_MODE" not in os.environ
    ):
        os.environ["NIRD_ODPFC_OUTPUT_MODE"] = "iteration_parquet"
    if (
        direct_duckdb_outputs
        and path_strategy in {"streaming_arrays", "streaming"}
        and os.environ.get("NIRD_ODPFC_OUTPUT_MODE", "").strip().lower()
        == "iteration_parquet"
        and "NIRD_COMBINE_ODPFC_PARTS" not in os.environ
    ):
        os.environ["NIRD_COMBINE_ODPFC_PARTS"] = "0"
    logging.info(
        "Direct output controls: "
        f"direct_duckdb_outputs={direct_duckdb_outputs}, "
        f"path_strategy={path_strategy}, "
        f"baseline_path_output_mode={os.environ.get('NIRD_BASELINE_PATH_OUTPUT_MODE', 'full_odpfc')}, "
        f"odpfc_output_mode={os.environ.get('NIRD_ODPFC_OUTPUT_MODE', 'duckdb_table')}, "
        f"combine_odpfc_parts={os.environ.get('NIRD_COMBINE_ODPFC_PARTS', 'default')}"
    )
    iso_out_path = out_path / "trip_isolations.pq"
    odpfc_out_path = out_path / "odpfc.pq"

    # run flow simulation
    logging.info("Run simulation")
    (
        road_links,
        cList,
    ) = func.network_flow_model(
        road_links,
        network,
        od_node_2021,
        flow_breakpoint_dict,
        num_of_chunk,
        num_of_cpu,
        db_path,
        iso_out_path=str(iso_out_path) if direct_duckdb_outputs else None,
        odpfc_out_path=str(odpfc_out_path) if direct_duckdb_outputs else None,
    )

    if direct_duckdb_outputs:
        road_links.to_parquet(out_path / "edge_flows.gpq")
        logging.info(
            "Direct DuckDB output mode wrote edge_flows.gpq and "
            "trip_isolations.pq. Baseline path artifact mode: "
            f"{os.environ.get('NIRD_BASELINE_PATH_OUTPUT_MODE', 'full_odpfc')}."
        )
        logging.info(f"The total simulation time: {time.time() - start_time}")
        return
    
    # Read isolation and odpfc from database
    conn = duckdb.connect(db_path)
    isolation = conn.execute("SELECT * FROM isolated_od").fetchall()
    odpfc = conn.execute("SELECT * FROM odpfc").fetchall()
    conn.close()
    
    # isolation
    isolation_df = pd.DataFrame(
        isolation,
        columns=[
            "origin_node",
            "destination_node",
            "flow",
        ],
    )
    isolation_df = isolation_df[
        (isolation_df.origin_node != isolation_df.destination_node)
        & (isolation_df.flow > 0)
    ].reset_index(drop=True)

    # odpfc
    odpfc_df = pd.DataFrame(
        odpfc,
        columns=[
            "origin_node",
            "destination_node",
            "path",
            "flow",
            "operating_cost_per_flow",
            "time_cost_per_flow",
            "toll_cost_per_flow",
            "fare_cost_per_flow",
        ],
    )
    odpfc_df.path = odpfc_df.path.apply(tuple)
    odpfc_df = odpfc_df.groupby(
        by=["origin_node", "destination_node", "path"], as_index=False
    ).agg(
        {
            "flow": "sum",
            "operating_cost_per_flow": "first",
            "time_cost_per_flow": "first",
            "toll_cost_per_flow": "first",
        }
    )

    # export files
    road_links.to_parquet(out_path / "edge_flows.gpq")
    isolation_df.to_parquet(out_path / "trip_isolations.pq")
    odpfc_df.to_parquet(out_path / "odpfc.pq")
    logging.info(f"The total simulation time: {time.time() - start_time}")


if __name__ == "__main__":
    """
    Entry point of the script. Reads the number of CPUs from command-line arguments
    and calls the main function.

    Command-line Arguments:
        num_of_cpu (int): Number of CPUs to use for parallel processing.
        sample_stride (int): Stride length to use on OD.

    Returns:
        None: Prints a message if the required argument is missing.
    """
    logging.basicConfig(
        format="%(asctime)s %(process)d %(filename)s %(message)s", level=logging.INFO
    )
    try:  # in bash inputs will be str by default
        num_of_chunk = sys.argv[1]
        num_of_cpu = sys.argv[2]
        sample_stride = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        main(int(num_of_chunk), int(num_of_cpu), sample_stride)
    except (IndexError, NameError):
        logging.info("Please enter num_of_chunk, num_of_cpu!")
