"""``hmp migrate`` — move legacy per-sim rows into the Parquet layout.

Before v0.6, the catalog stored ``timeseries``, ``budgets`` and
``mass_balance`` as regular DuckDB tables inside ``hydromodpy.duckdb``. The
lakehouse refactor moves them to per-simulation Parquet files under
``simulations/<uuid>.parquet/``. This command walks an existing workspace,
groups the rows by ``sim_id``, writes one Parquet file per sim and per view
name, verifies row counts, then drops the legacy tables so the Parquet
views can be installed.

The command is idempotent: running it twice on the same workspace is a
no-op once the tables are gone.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

from hydromodpy._cli.helpers import EXIT_CONFIG
from hydromodpy.data.scaffold import DEFAULT_ROOT
from hydromodpy.results.catalog_schema import (
    PARQUET_VIEW_NAMES,
    ensure_parquet_views,
)

NAME = "migrate"
HELP = "Migrate legacy per-sim tables (timeseries/budgets/mass_balance) from DuckDB to Parquet."


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace path (default: ~/hydromodpy/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be migrated without writing anything.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else Path(DEFAULT_ROOT)
    db_path = ws / "hydromodpy.duckdb"
    if not db_path.is_file():
        print(f"No catalog at {db_path}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    conn = duckdb.connect(str(db_path))
    try:
        report = _migrate(conn, ws, dry_run=args.dry_run)
    finally:
        conn.close()

    _print_report(report, dry_run=args.dry_run)


def _migrate(
    conn: duckdb.DuckDBPyConnection,
    workspace_path: Path,
    *,
    dry_run: bool,
) -> dict:
    """Core migration routine. Returns a dict with per-view counts."""
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
    }
    legacy = [name for name in PARQUET_VIEW_NAMES if name in tables]

    report: dict = {
        "workspace": str(workspace_path),
        "dry_run": dry_run,
        "views": {},
        "dropped": [],
        "status": "noop",
    }
    if not legacy:
        return report

    sims_root = workspace_path / "simulations"
    sims_root.mkdir(exist_ok=True)

    for view in legacy:
        sim_rows = conn.execute(f"SELECT DISTINCT sim_id FROM {view}").fetchall()
        total_rows = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        per_view: dict = {
            "sim_count": len(sim_rows),
            "row_count": int(total_rows),
            "written": [],
        }
        if dry_run:
            report["views"][view] = per_view
            continue
        written_rows = 0
        for (sid,) in sim_rows:
            target_dir = sims_root / f"{sid}.parquet"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{view}.parquet"
            tmp = target.with_name(target.name + ".tmp")
            conn.execute(
                f"COPY (SELECT * FROM {view} WHERE sim_id = ?) TO '{tmp}' (FORMAT PARQUET)",
                [str(sid)],
            )
            per_sim_rows = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{tmp}')").fetchone()[0]
            os.replace(tmp, target)
            written_rows += int(per_sim_rows)
            per_view["written"].append({"sim_id": str(sid), "rows": int(per_sim_rows)})
        if written_rows != total_rows:
            raise RuntimeError(
                f"Row-count mismatch for view {view!r}: "
                f"source={total_rows} parquet={written_rows}. "
                "Leaving legacy table in place."
            )
        report["views"][view] = per_view

    if not dry_run:
        for view in legacy:
            conn.execute(f"DROP TABLE {view}")
            report["dropped"].append(view)
        ensure_parquet_views(conn, workspace_path)
        report["status"] = "migrated"
    else:
        report["status"] = "dry_run"
    return report


def _print_report(report: dict, *, dry_run: bool) -> None:
    ws = report["workspace"]
    if report["status"] == "noop":
        print(f"{ws}: no legacy tables to migrate.")
        return
    print(f"Workspace: {ws}")
    print(f"Mode: {'dry-run' if dry_run else 'apply'}")
    for view, info in report["views"].items():
        print(f"  {view:<14} sims={info['sim_count']:>5} rows={info['row_count']:>9}")
    if not dry_run:
        print(f"Dropped tables: {', '.join(report['dropped'])}")
        print("Parquet views refreshed.")
