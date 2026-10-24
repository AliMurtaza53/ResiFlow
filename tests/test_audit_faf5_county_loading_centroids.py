import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "audit_faf5_county_loading_centroids",
    Path(__file__).resolve().parents[1] / "scripts" / "audit_faf5_county_loading_centroids.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

audit = _MODULE.audit


@pytest.fixture
def crosswalk_csv(tmp_path):
    df = pd.DataFrame({
        "detail_zone_id": ["06037", "36061", "36061"],
        "assigned_centroid": ["6037", "36061a", "36061b"],
        "assigned_node_id": ["6811", "1001", "1002"],
        "assignment_method": ["exact_match", "exact_match", "exact_match"],
        "distance_miles": ["0.0", "0.0", "0.0"],
        "warning_flag": [None, None, None],
    })
    path = tmp_path / "crosswalk.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def summary_json(tmp_path):
    data = {
        "network_centroids_path": "faf5_network_loading_centroids.gpq",
        "unmatched_zones_before_nearest_fallback": 1,
        "unmapped_after_fallback": 0,
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_audit_counts_centroids_per_detail_zone(crosswalk_csv, summary_json):
    result = audit(crosswalk_csv, summary_json)
    assert result["total_detail_zones"] == 2
    assert result["zones_with_1_centroid"] == 1
    assert result["zones_with_2plus_centroids"] == 1
    assert result["centroid_count_distribution"] == {"1": 1, "2": 1}


def test_audit_surfaces_la_county_row(crosswalk_csv, summary_json):
    result = audit(crosswalk_csv, summary_json)
    assert len(result["la_county_06037"]) == 1
    assert result["la_county_06037"][0]["assigned_node_id"] == "6811"


def test_audit_reports_unknown_mapping_method_when_not_recorded(crosswalk_csv, summary_json):
    # The live pipeline's summary JSON is written to disk BEFORE
    # build_conus_freight_od.py adds "mapping_method" to the in-memory
    # dict, so the file itself never has that key -- the audit must say so
    # honestly rather than guess.
    result = audit(crosswalk_csv, summary_json)
    assert "unknown" in result["mapping_method_used"]
