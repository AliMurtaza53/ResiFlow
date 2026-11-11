"""Opt-in per-iteration audit dump for ``network_flow_model`` (phase 1: ``summary`` and ``binding``).

Spec: ``docs/ASSIGNMENT_DUMP_SPEC.md``.  Off unless ``RESIFLOW_AUDIT_DUMP_DIR`` is set.
``RESIFLOW_AUDIT_DUMP_LEVEL`` is ``summary`` or ``binding`` (default); ``zonepair`` and ``full`` are
not implemented yet and fall back to ``binding`` with a warning.

Nothing here may change assignment results or stop the run: every public method is guarded; the first
exception logs one ``AUDIT_DUMP warning ...`` line and disables the dump for the rest of the run.

Files (``iter`` zero padded to 4 digits)::

    manifest.json
    iteration_summary.parquet          rewritten every iteration (one row per iteration so far)
    edge_iter/iter=0007.parquet        binding and deleted edges only            (level binding)
    ratio_iter/iter=0007.parquet       adjust_r distribution, long format        (level binding)
    binding_od_iter/iter=0007.parquet  per binding edge, ODs it throttled        (binding, streaming only)
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
CONNECTOR_TIER = "centroid_connector"  # assignment_tier set by preprocess/network_connector_insertion.py
LEVELS = ("summary", "binding", "zonepair", "full")
IMPLEMENTED_LEVELS = ("summary", "binding")
NBINS = 1000  # adjust_r histogram resolution; bin NBINS holds adjust_r == 1 (unconstrained)
QUANTILES = (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 1.0)
SHARE_THRESHOLDS = (0.1, 0.5, 1.0)  # share of candidate flow with adjust_r < threshold
_SECRET_HINTS = ("TOKEN", "KEY", "SECRET", "PASSWORD")

# first existing column wins; the chosen source column is recorded in the manifest
ATTR_CANDIDATES: Dict[str, List[str]] = {
    "road_name": ["Road_Name", "road_name", "ROAD_NAME"],
    "state": ["STATE", "state", "State", "state_fips", "STATEFIPS", "STFIPS", "state_abbr"],
    "county": ["county_fips", "COUNTY", "county", "County", "COUNTYFIPS", "CTFIPS", "CNTYFIPS", "county_name", "County_Name"],
    "tier": ["assignment_tier"],
    "lanes": ["lanes"],
    "road_class": ["network_class", "road_classification", "Class", "FAF_Class"],
}

# Which fields each path strategy can supply (recorded in the manifest; nothing is faked).
STRATEGY_CAPABILITIES = {
    "streaming_arrays": {
        "edge_iter": True,
        "ratio_iter": "inline from the realization loop (candidate-flow weighted)",
        "binding_od_iter": "inline: argmin edge ratio on each OD path",
    },
    "duckdb_chunked_compact": {
        "edge_iter": True,
        "ratio_iter": "SQL over od_results_iter x od_adjustment (candidate-flow weighted)",
        "binding_od_iter": "unavailable: needs an argmin over exploded paths, too costly in SQL",
    },
    "legacy_compact_sql": {
        "edge_iter": True,
        "ratio_iter": "SQL over od_results_iter x od_adjustment (candidate-flow weighted)",
        "binding_od_iter": "unavailable: needs an argmin over exploded paths, too costly in SQL",
    },
}


def _canonical_strategy(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in {"streaming_arrays", "streaming"}:
        return "streaming_arrays"
    if s in {"duckdb_chunked_compact", "option2"}:
        return "duckdb_chunked_compact"
    if s in {"legacy_compact_sql", "compact_sql", "compact_duckdb", "option1"}:
        return "legacy_compact_sql"
    return s or "unknown"


# --- ratio sink (filled inline by realize_paths_streaming) ---------------------------------------

_SINK: Optional["RatioSink"] = None


def get_sink() -> Optional["RatioSink"]:
    return _SINK


def set_sink(sink: Optional["RatioSink"]) -> None:
    global _SINK
    _SINK = sink


def _bin_stats_to_records(
    iteration: int,
    n: np.ndarray,
    w: np.ndarray,
    wr: np.ndarray,
    r_min: float,
    r_max: float,
    source: str,
) -> pd.DataFrame:
    """Long-format ratio distribution from per-bin counts, candidate flow and adjusted flow."""
    total_w = float(w.sum())
    rows: List[tuple] = [
        ("n_od", float(n.sum()), "exact"),
        ("flow_candidate", total_w, "exact"),
        ("flow_adjusted", float(wr.sum()), "exact"),
    ]
    if total_w > 0:
        cum = np.cumsum(w) / total_w
        for q in QUANTILES:
            if q <= 0.0:
                value, res = r_min, "exact"
            elif q >= 1.0:
                value, res = r_max, "exact"
            else:
                b = int(np.searchsorted(cum, q - 1e-12, side="left"))
                value, res = min((b + 1) / NBINS, 1.0), f"upper_edge_of_{1 / NBINS:g}_wide_bin"
            rows.append((f"q{q:g}", float(value), res))
        for thr in SHARE_THRESHOLDS:
            k = int(round(thr * NBINS))  # bins 0..k-1 are adjust_r < thr
            rows.append((f"share_flow_r_lt_{thr:g}", float(w[:k].sum() / total_w), "exact_to_bin_edge"))
    df = pd.DataFrame(rows, columns=["metric", "value", "resolution"])
    df.insert(0, "iteration", iteration)
    df["source"] = source
    return df


class RatioSink:
    """Collects (adjust_r, candidate flow, binding edge) per OD from the streaming realization loop."""

    def __init__(self) -> None:
        self.failed = False
        self.reset()

    def reset(self) -> None:
        self._r: List[float] = []
        self._w: List[float] = []
        self._e: List[Optional[str]] = []
        self.n = np.zeros(NBINS + 1)
        self.w = np.zeros(NBINS + 1)
        self.wr = np.zeros(NBINS + 1)
        self.r_min = float("inf")
        self.r_max = float("-inf")
        self._binding: List[pd.DataFrame] = []

    def add(self, adjust_r: float, flow: float, binding_e_id: Optional[str] = None) -> None:
        if self.failed:
            return
        self._r.append(adjust_r)
        self._w.append(flow)
        self._e.append(binding_e_id)
        if len(self._r) >= 500_000:
            self.flush()

    def flush(self) -> None:
        if self.failed or not self._r:
            return
        try:
            r = np.asarray(self._r, dtype=np.float64)
            w = np.asarray(self._w, dtype=np.float64)
            e = np.asarray(self._e, dtype=object)
            self._r, self._w, self._e = [], [], []
            b = np.minimum(np.floor(r * NBINS).astype(np.int64), NBINS)
            self.n += np.bincount(b, minlength=NBINS + 1)
            self.w += np.bincount(b, weights=w, minlength=NBINS + 1)
            self.wr += np.bincount(b, weights=w * r, minlength=NBINS + 1)
            self.r_min = min(self.r_min, float(r.min()))
            self.r_max = max(self.r_max, float(r.max()))
            m = np.array([x is not None for x in e], dtype=bool)
            if m.any():
                part = pd.DataFrame({"e_id": e[m].astype(str), "w": w[m], "wr": (w * r)[m]})
                self._binding.append(part.groupby("e_id", sort=False).agg(
                    n_od_bound=("w", "size"), flow_candidate=("w", "sum"), flow_adjusted=("wr", "sum")
                ).reset_index())
        except Exception as exc:  # never break the assignment
            self.failed = True
            logging.warning("AUDIT_DUMP warning: ratio sink failed (%s: %s); ratio data dropped", type(exc).__name__, exc)

    def ratio_records(self, iteration: int) -> pd.DataFrame:
        self.flush()
        return _bin_stats_to_records(iteration, self.n, self.w, self.wr, self.r_min, self.r_max, "streaming_inline")

    def binding_od(self, iteration: int) -> pd.DataFrame:
        self.flush()
        cols = ["iteration", "e_id", "n_od_bound", "flow_candidate", "flow_adjusted", "flow_lost"]
        if not self._binding:
            return pd.DataFrame(columns=cols)
        df = pd.concat(self._binding, ignore_index=True)
        df = df.groupby("e_id", sort=False).sum().reset_index()
        df["flow_lost"] = df["flow_candidate"] - df["flow_adjusted"]
        df.insert(0, "iteration", iteration)
        return df.sort_values("flow_lost", ascending=False).reset_index(drop=True)[cols]


# --- the dump -------------------------------------------------------------------------------------

_USES_PER_DIR: Dict[str, int] = {}  # a repeat use of one dir in a process goes to call_NN/


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _write_json(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))
    os.replace(tmp, path)


def _git_commit() -> Optional[str]:
    env = os.environ.get("RESIFLOW_GIT_COMMIT")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _guarded(method):
    def wrapper(self, *args, **kwargs):
        if self.disabled:
            return None
        t0 = time.time()
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self.disabled = True
            set_sink(None)
            logging.warning(
                "AUDIT_DUMP warning: %s failed (%s: %s); audit dump disabled for the rest of this run",
                method.__name__, type(exc).__name__, exc,
            )
            return None
        finally:
            self.wall_s_iter += time.time() - t0
    wrapper.__name__ = method.__name__
    return wrapper


class AuditDump:
    def __init__(self, out_dir: Path, level: str, level_requested: str) -> None:
        self.out_dir = out_dir
        self.level = level
        self.level_requested = level_requested
        self.disabled = False
        self.wall_s_iter = 0.0
        self.wall_s_total = 0.0
        self.strategy = "unknown"
        self.initial = 0.0
        self.manifest: Dict[str, Any] = {}
        self.summary_rows: List[Dict[str, Any]] = []
        self.sink: Optional[RatioSink] = None
        self.prev_remain: Optional[float] = None
        self.attr_sources: Dict[str, Optional[str]] = {}
        self.iter_edge_counts: Dict[str, Any] = {}

    # -- construction --
    @classmethod
    def from_env(cls) -> Optional["AuditDump"]:
        """Return a dump if ``RESIFLOW_AUDIT_DUMP_DIR`` is set, else None.  Never raises."""
        raw_dir = os.environ.get("RESIFLOW_AUDIT_DUMP_DIR", "").strip()
        if not raw_dir:
            return None
        try:
            requested = os.environ.get("RESIFLOW_AUDIT_DUMP_LEVEL", "binding").strip().lower() or "binding"
            if requested not in LEVELS:
                logging.warning(
                    "AUDIT_DUMP warning: RESIFLOW_AUDIT_DUMP_LEVEL=%r is not one of %s; audit dump disabled",
                    requested, LEVELS,
                )
                return None
            level = requested
            if level not in IMPLEMENTED_LEVELS:
                logging.warning(
                    "AUDIT_DUMP warning: level %r is not implemented yet; writing level 'binding'", level
                )
                level = "binding"
            key = str(Path(raw_dir).resolve())
            _USES_PER_DIR[key] = _USES_PER_DIR.get(key, 0) + 1
            out = Path(raw_dir)
            if _USES_PER_DIR[key] > 1:  # a later network_flow_model call in this process: do not overwrite
                out = out / f"call_{_USES_PER_DIR[key]:02d}"
            out.mkdir(parents=True, exist_ok=True)
            return cls(out, level, requested)
        except Exception as exc:
            logging.warning("AUDIT_DUMP warning: could not initialise (%s: %s); audit dump disabled", type(exc).__name__, exc)
            return None

    @property
    def want_binding(self) -> bool:
        return self.level == "binding"

    # -- lifecycle --
    @_guarded
    def start(self, *, strategy: str, initial_demand: float, n_edges: int, n_od: int,
              road_links: pd.DataFrame, demand_class: Optional[str] = None) -> None:
        self.strategy = _canonical_strategy(strategy)
        self.initial = float(initial_demand)
        self.attr_sources = {
            field: next((c for c in cands if c in road_links.columns), None)
            for field, cands in ATTR_CANDIDATES.items()
        }
        env = {k: v for k, v in sorted(os.environ.items())
               if k.startswith(("RESIFLOW_", "NIRD_")) and not any(h in k for h in _SECRET_HINTS)}
        self.manifest = {
            "schema_version": SCHEMA_VERSION,
            "git_commit": _git_commit(),
            "started_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "level": self.level,
            "level_requested": self.level_requested,
            "strategy": self.strategy,
            "strategy_capabilities": STRATEGY_CAPABILITIES.get(self.strategy, {"edge_iter": True, "ratio_iter": "unavailable", "binding_od_iter": "unavailable"}),
            "initial_demand": self.initial,
            "n_edges": int(n_edges),
            "n_od_pairs": int(n_od),
            "demand_class": demand_class,
            "env": env,
            "edge_attribute_source_columns": self.attr_sources,
            "ratio_histogram_bins": NBINS,
            "edge_iter_rows": "edges with edge_ratio < 1 (is_binding) or meeting the prune rule (is_deleted)",
            "files": {},
            "iterations_written": 0,
            "finished": False,
        }
        if self.want_binding and self.strategy == "streaming_arrays":
            self.sink = RatioSink()
            set_sink(self.sink)
        self._write_manifest()

    def _write_manifest(self) -> None:
        _write_json(self.manifest, self.out_dir / "manifest.json")

    @_guarded
    def begin_iteration(self, iteration: int) -> None:
        self.wall_s_iter = 0.0
        if self.sink is not None:
            self.sink.reset()

    @_guarded
    def write_binding(self, *, iteration: int, conn, temp_edge_flow: pd.DataFrame,
                      road_links: pd.DataFrame, prune_frame_fn) -> None:
        """Write edge_iter, ratio_iter, binding_od_iter.  Call before the transient tables are dropped.

        ``prune_frame_fn(temp_edge_flow, road_links_valid) -> (merged, ratio, mask)`` is the same
        function ``update_network_structure`` uses, so ``is_deleted`` is exactly its prune rule.
        """
        if not self.want_binding:
            return
        loaded = self._loaded_edges(conn, temp_edge_flow)
        valid = road_links.dropna(subset=["e_idx"])
        merged, ratio, mask = prune_frame_fn(temp_edge_flow[["e_id", "flow"]], valid)
        after = pd.DataFrame({
            "e_id": merged["e_id"].astype(str).to_numpy(),
            "acc_capacity_after": merged["acc_capacity"].to_numpy(),
            "current_capacity": merged["current_capacity"].to_numpy(),
            "remaining_ratio": ratio.to_numpy(),
            "is_deleted": mask.to_numpy(),
        })
        df = loaded.merge(after, on="e_id", how="left")
        df["is_deleted"] = df["is_deleted"].fillna(False).astype(bool)
        df["is_binding"] = df["edge_ratio"] < 1.0
        self.iter_edge_counts = {
            "edges_loaded": int((df["flow"] > 0).sum()),
            "edges_binding": int(df["is_binding"].sum()),
            "edges_meeting_prune_rule": int(df["is_deleted"].sum()),
        }
        keep = df[df["is_binding"] | df["is_deleted"]].copy()
        attrs = valid.copy()
        attrs["e_id"] = attrs["e_id"].astype(str)
        attrs = attrs.drop_duplicates("e_id").set_index("e_id")
        for field, col in self.attr_sources.items():
            keep[field] = keep["e_id"].map(attrs[col]) if col is not None else None
        keep.insert(0, "iteration", iteration)
        cols = ["iteration", "e_id", "flow", "total_candidate_flow", "edge_ratio", "acc_capacity_before",
                "acc_capacity_after", "current_capacity", "remaining_ratio", "is_binding", "is_deleted",
                "road_name", "state", "county", "tier", "lanes", "road_class", "is_connector"]
        keep["is_connector"] = keep["tier"].astype("string").eq(CONNECTOR_TIER).fillna(False).astype(bool)
        keep = keep.sort_values(["is_deleted", "total_candidate_flow"], ascending=False)[cols]
        for col in ("road_name", "state", "county", "tier", "road_class"):
            keep[col] = keep[col].astype("string") if keep[col].notna().any() else keep[col].astype("object")
        _write_parquet(keep, self.out_dir / "edge_iter" / f"iter={iteration:04d}.parquet")

        ratio_df = self._ratio_records(conn, iteration)
        if ratio_df is not None:
            _write_parquet(ratio_df, self.out_dir / "ratio_iter" / f"iter={iteration:04d}.parquet")
        if self.sink is not None:
            _write_parquet(self.sink.binding_od(iteration), self.out_dir / "binding_od_iter" / f"iter={iteration:04d}.parquet")

    def _loaded_edges(self, conn, temp_edge_flow: pd.DataFrame) -> pd.DataFrame:
        """e_id, flow, total_candidate_flow, edge_ratio, acc_capacity_before for edges loaded or wanted."""
        if self.strategy == "streaming_arrays":
            df = conn.execute(
                "SELECT CAST(e_id AS VARCHAR) AS e_id, flow, total_candidate_flow, "
                "edge_ratio, acc_capacity AS acc_capacity_before FROM temp_edge_flow"
            ).fetchdf()
            return df
        tot = conn.execute(
            "SELECT CAST(e_id AS VARCHAR) AS e_id, total_flow AS total_candidate_flow, "
            "acc_capacity AS acc_capacity_before, "
            "LEAST(acc_capacity / NULLIF(total_flow, 0), 1.0) AS edge_ratio FROM total"
        ).fetchdf()
        flow = temp_edge_flow[["e_id", "flow"]].copy()
        flow["e_id"] = flow["e_id"].astype(str)
        df = tot.merge(flow, on="e_id", how="left")
        df["flow"] = df["flow"].fillna(0.0)
        df["edge_ratio"] = df["edge_ratio"].fillna(1.0)
        return df[["e_id", "flow", "total_candidate_flow", "edge_ratio", "acc_capacity_before"]]

    def _ratio_records(self, conn, iteration: int) -> Optional[pd.DataFrame]:
        if self.strategy == "streaming_arrays":
            return self.sink.ratio_records(iteration) if self.sink is not None else None
        try:
            hist = conn.execute(
                f"""
                SELECT LEAST(CAST(FLOOR(COALESCE(a.adjust_r, 1.0) * {NBINS}) AS BIGINT), {NBINS}) AS b,
                       COUNT(*) AS n, SUM(o.flow) AS w, SUM(o.flow * COALESCE(a.adjust_r, 1.0)) AS wr,
                       MIN(COALESCE(a.adjust_r, 1.0)) AS rmin, MAX(COALESCE(a.adjust_r, 1.0)) AS rmax
                FROM od_results_iter o
                JOIN od_adjustment a USING (od_id, origin, destination)
                GROUP BY b
                """
            ).fetchdf()
        except Exception as exc:  # a strategy variant without these tables: say so, do not fake
            logging.warning("AUDIT_DUMP warning: ratio_iter unavailable for strategy %s (%s)", self.strategy, type(exc).__name__)
            self.manifest.setdefault("ratio_iter_unavailable_iterations", []).append(iteration)
            return None
        n, w, wr = (np.zeros(NBINS + 1) for _ in range(3))
        idx = hist["b"].to_numpy(dtype=np.int64)
        n[idx], w[idx], wr[idx] = hist["n"].to_numpy(), hist["w"].to_numpy(), hist["wr"].to_numpy()
        return _bin_stats_to_records(
            iteration, n, w, wr, float(hist["rmin"].min()), float(hist["rmax"].max()), "sql_od_adjustment"
        )

    @_guarded
    def record_summary(self, row: Dict[str, Any]) -> None:
        """Append the ITER_AUDIT fields (plus dump fields) and rewrite iteration_summary + manifest."""
        row = dict(row)
        remain = row["remain"]
        row["requested_flow"] = self.initial if self.prev_remain is None else self.prev_remain
        self.prev_remain = remain
        row["legacy_assigned_fraction"] = 1.0 - remain / self.initial if self.initial > 0 else 0.0
        row.update(self.iter_edge_counts)
        self.iter_edge_counts = {}
        row["dump_wall_s"] = self.wall_s_iter
        self.summary_rows.append(row)
        _write_parquet(pd.DataFrame(self.summary_rows), self.out_dir / "iteration_summary.parquet")
        self.wall_s_total += self.wall_s_iter
        self.manifest["iterations_written"] = len(self.summary_rows)
        self.manifest["dump_wall_s_total"] = self.wall_s_total
        self.manifest["files"] = self._file_inventory()
        self._write_manifest()

    def _file_inventory(self) -> Dict[str, Any]:
        inv: Dict[str, Any] = {}
        for sub in ("edge_iter", "ratio_iter", "binding_od_iter"):
            d = self.out_dir / sub
            files = list(d.glob("iter=*.parquet")) if d.exists() else []
            inv[sub] = {"files": len(files), "bytes": int(sum(f.stat().st_size for f in files))}
        return inv

    @_guarded
    def finalize(self, stop_reason: str) -> None:
        self.manifest.update(
            finished=True, stop_reason=stop_reason,
            iterations_completed=int(self.summary_rows[-1]["iteration"]) if self.summary_rows else 0,
            finished_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            files=self._file_inventory(),
        )
        self._write_manifest()
        set_sink(None)

    def close(self) -> None:
        set_sink(None)
