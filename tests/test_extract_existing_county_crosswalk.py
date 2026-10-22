import pandas as pd

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "extract_existing_county_crosswalk",
    Path(__file__).resolve().parents[1] / "scripts" / "extract_existing_county_crosswalk.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

extract_crosswalk = _MODULE.extract_crosswalk


def test_extract_crosswalk_combines_origin_and_destination_sides():
    od_by_sctg = pd.DataFrame(
        {
            "origin_detail_zone": ["00001", "00002"],
            "destination_detail_zone": ["00002", "00003"],
            "origin_node": ["n1", "n2"],
            "destination_node": ["n2", "n3"],
        }
    )

    crosswalk = extract_crosswalk(od_by_sctg)

    mapping = dict(zip(crosswalk["county_id"], crosswalk["node_id"]))
    assert mapping == {"00001": "n1", "00002": "n2", "00003": "n3"}


def test_extract_crosswalk_dedupes_consistent_repeats():
    od_by_sctg = pd.DataFrame(
        {
            "origin_detail_zone": ["00001", "00001"],
            "destination_detail_zone": ["00002", "00002"],
            "origin_node": ["n1", "n1"],
            "destination_node": ["n2", "n2"],
        }
    )

    crosswalk = extract_crosswalk(od_by_sctg)

    assert len(crosswalk) == 2
