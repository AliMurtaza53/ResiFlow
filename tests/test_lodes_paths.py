import os
from pathlib import Path

from resiflow import lodes_paths as paths


def test_od_file_path_builds_expected_url():
    url = paths.od_file_path("va", job_type="JT00", year=2022, part="main")
    assert url.endswith("/va/od/va_od_main_JT00_2022.csv.gz")
    assert url.startswith("https://lehd.ces.census.gov/data/lodes/LODES8/")


def test_lodes_base_url_prefers_local_root(tmp_path):
  local = tmp_path / "lodes_mirror"
  local.mkdir()
  base = paths.lodes_base_url(local)
  assert base.startswith(str(local).replace("\\", "/").rstrip("/"))


def test_resolve_lodes_data_root_from_env(monkeypatch, tmp_path):
    root = tmp_path / "lodes_data"
    root.mkdir()
    monkeypatch.setenv("NIRD_LODES_DATA_ROOT", str(root))
    assert paths.resolve_lodes_data_root() == root
