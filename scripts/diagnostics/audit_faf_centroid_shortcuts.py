"""Audit positive-flow path records for traversal through a third FAF centroid."""

import argparse
from pathlib import Path

import duckdb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connector_csv", type=Path, help="CSV with e_id and centroid_node")
    parser.add_argument("paths", nargs="+", help="Parquet paths or glob patterns")
    args = parser.parse_args()
    with duckdb.connect() as db:
        connectors = db.read_csv(str(args.connector_csv), all_varchar=True)
        connectors.create_view("connectors")
        count, distinct = db.sql("SELECT count(*), count(DISTINCT e_id) FROM connectors").fetchone()
        if not count or count != distinct:
            raise ValueError("Connector IDs must be present and unique")
        for path in args.paths:
            rows = db.read_parquet(path)
            rows.create_view("paths", replace=True)
            missing = db.sql("SELECT count(*) FROM paths WHERE flow > 0 AND path IS NULL").fetchone()[0]
            if missing:
                raise ValueError(f"{path}: {missing} positive-flow rows lack path data")
            result = db.sql("""
                WITH flagged AS (
                    SELECT flow, EXISTS (
                        SELECT 1 FROM unnest(path) AS edge(edge_id)
                        JOIN connectors ON connectors.e_id = CAST(edge.edge_id AS VARCHAR)
                        WHERE centroid_node NOT IN (
                            CAST(origin_node AS VARCHAR), CAST(destination_node AS VARCHAR)
                        )
                    ) AS shortcut
                    FROM paths WHERE flow > 0 AND array_length(path) > 0
                )
                SELECT count(*), count(*) FILTER (WHERE shortcut),
                       sum(flow), sum(flow) FILTER (WHERE shortcut)
                FROM flagged
            """).fetchone()
            total, shortcuts, flow, shortcut_flow = result
            share = shortcuts / total if total else None
            print(f"{path}: paths={total}, shortcuts={shortcuts}, share={share}, "
                  f"flow={flow or 0:.6f}, shortcut_flow={shortcut_flow or 0:.6f}, "
                  f"escalate={share is not None and share > 0.001}")


if __name__ == "__main__":
    main()
