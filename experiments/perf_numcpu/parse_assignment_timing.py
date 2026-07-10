"""Parse Pass A/B Script 1 timing markers from a log file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PHASE_PATTERNS = {
    "lcp_pool_sec": r"least-cost path flow allocation time:\s*([0-9.]+)",
    "lcp_db_insert_sec": r"LCP DuckDB insert phase:\s*([0-9.]+)\s*seconds",
    "od_id_assign_sec": r"od_id assignment phase:\s*([0-9.]+)",
    "streaming_pass1_sec": r"Streaming realization pass 1 complete in ([0-9.]+) seconds",
    "streaming_pass2_sec": r"Streaming realization pass 2 complete in ([0-9.]+) seconds",
    "total_simulation_sec": r"total simulation time:\s*([0-9.]+)",
    "path_rows": r"for ([0-9,]+) path rows",
    "origins_completed": r"Completed ([0-9,]+) of ([0-9,]+),",
}


def parse_log(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, pattern in PHASE_PATTERNS.items():
        if key == "origins_completed":
            matches = re.findall(pattern, text)
            if matches:
                done, total = matches[-1]
                result["origins_done"] = int(done.replace(",", ""))
                result["origins_total"] = int(total.replace(",", ""))
            continue
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        if key == "path_rows":
            result[key] = int(value.replace(",", ""))
        else:
            result[key] = float(value.rstrip("."))
    return result


def read_log_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    text = read_log_text(args.log_path)
    parsed = parse_log(text)
    print(json.dumps(parsed, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
