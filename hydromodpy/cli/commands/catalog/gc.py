"""``hmp gc`` - garbage-collect orphan caches, tmp parquet, and stale running sims.

Sweeps four classes of orphans in a workspace:

* ``calibration_sessions`` rows whose ``best_sim_id`` references a missing
  simulation (or the table is otherwise empty of live sims);
* ``geographic_cache`` fingerprints no longer referenced by any
  ``simulations.geographic_fingerprint``;
* atomic-write temporary Parquet files (``*.tmp-*.parquet`` and
  ``*.tmp-*`` companions left by interrupted writes);
* ``simulations`` rows still marked ``status='running'`` whose
  ``last_heartbeat`` is older than 10 minutes (the run is presumed dead).

With ``--dry-run`` the command only prints the candidate set; otherwise it
performs the cleanup and reports the count per category.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    EXIT_OK,
    resolve_workspace,
)
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "gc"
HELP: str = "Garbage-collect orphan caches, tmp parquet, and stale running simulations"

STALE_HEARTBEAT_MINUTES = 10


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: current dir auto-detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates without removing or updating anything",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    workspace = _resolve_workspace_root(args.workspace)
    plan = _collect_plan(workspace)
    _print_plan(plan, dry_run=args.dry_run)

    if args.dry_run:
        sys.exit(EXIT_OK)

    summary = _apply_plan(workspace, plan)
    print()
    print("Summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    sys.exit(EXIT_OK)


def _resolve_workspace_root(workspace_arg: str | None) -> Path:
    """Resolve a workspace path that contains either a catalog or a projects/ tree."""
    if workspace_arg is not None:
        root = Path(workspace_arg).expanduser().resolve()
        if not root.is_dir():
            print(f"Workspace {root} does not exist.", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        return root
    return resolve_workspace(workspace_arg)


def _iter_project_roots(workspace: Path) -> list[Path]:
    roots: list[Path] = []
    if (workspace / CATALOG_FILENAME).is_file():
        roots.append(workspace)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if entry.is_dir() and (entry / CATALOG_FILENAME).is_file():
                roots.append(entry)
    return roots


def _collect_plan(workspace: Path) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {
        "calibration_sessions": [],
        "geographic_cache": [],
        "tmp_parquet": [],
        "stale_running_sims": [],
    }

    project_roots = _iter_project_roots(workspace)
    for project_root in project_roots:
        plan["calibration_sessions"].extend(_orphan_calibration_sessions(project_root))
        plan["stale_running_sims"].extend(_stale_running_simulations(project_root))

    plan["geographic_cache"].extend(_orphan_geographic_cache(workspace, project_roots))
    plan["tmp_parquet"].extend(_tmp_parquet_files(workspace))

    return plan


def _orphan_calibration_sessions(project_root: Path) -> list[str]:
    import duckdb

    catalog_path = project_root / CATALOG_FILENAME
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT cs.session_id
              FROM calibration_sessions cs
         LEFT JOIN simulations s ON s.sim_id = cs.best_sim_id
             WHERE cs.best_sim_id IS NOT NULL AND s.sim_id IS NULL
            """,
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{str(r[0])}" for r in rows]


def _stale_running_simulations(project_root: Path) -> list[str]:
    import duckdb

    catalog_path = project_root / CATALOG_FILENAME
    cutoff = datetime.now(UTC) - timedelta(minutes=STALE_HEARTBEAT_MINUTES)
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT s.sim_id
              FROM simulations s
              JOIN statuses st ON s.status_id = st.id
             WHERE st.code = 'running'
               AND (s.last_heartbeat IS NULL OR s.last_heartbeat < ?)
            """,
            [cutoff],
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{str(r[0])}" for r in rows]


def _orphan_geographic_cache(workspace: Path, project_roots: list[Path]) -> list[str]:
    cache_dir = workspace / "geographic"
    if not cache_dir.is_dir():
        return []

    referenced = _referenced_geographic_fingerprints(project_roots)
    orphans: list[str] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in referenced:
            continue
        orphans.append(str(entry))
    return orphans


def _referenced_geographic_fingerprints(project_roots: list[Path]) -> set[str]:
    import duckdb

    referenced: set[str] = set()
    for project_root in project_roots:
        catalog_path = project_root / CATALOG_FILENAME
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            continue
        try:
            rows = conn.execute(
                "SELECT DISTINCT geographic_fingerprint FROM simulations "
                "WHERE geographic_fingerprint IS NOT NULL"
            ).fetchall()
        except duckdb.Error:
            rows = []
        finally:
            conn.close()
        for (fp,) in rows:
            referenced.add(str(fp))
    return referenced


def _tmp_parquet_files(workspace: Path) -> list[str]:
    found: list[str] = []
    if not workspace.is_dir():
        return found
    for tmp in workspace.rglob("*.tmp-*"):
        try:
            if tmp.is_file() or tmp.is_dir():
                found.append(str(tmp))
        except OSError:
            continue
    return found


def _print_plan(plan: dict[str, list[str]], *, dry_run: bool) -> None:
    label = "[dry-run] " if dry_run else ""
    for key, items in plan.items():
        header = f"{label}{key}: {len(items)} candidate(s)"
        print(header)
        for item in items:
            print(f"  - {item}")


def _apply_plan(workspace: Path, plan: dict[str, list[str]]) -> dict[str, int]:
    summary = {key: 0 for key in plan}

    for ref in plan["calibration_sessions"]:
        project_name, session_id = ref.split(":", 1)
        if _delete_calibration_session(workspace, project_name, session_id):
            summary["calibration_sessions"] += 1

    for ref in plan["stale_running_sims"]:
        project_name, sim_id = ref.split(":", 1)
        if _mark_simulation_failed(workspace, project_name, sim_id):
            summary["stale_running_sims"] += 1

    for path_str in plan["geographic_cache"]:
        path = Path(path_str)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            summary["geographic_cache"] += 1

    for path_str in plan["tmp_parquet"]:
        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            summary["tmp_parquet"] += 1
        except OSError:
            continue

    return summary


def _project_root_by_name(workspace: Path, project_name: str) -> Path | None:
    candidate = workspace / "projects" / project_name
    if candidate.is_dir() and (candidate / CATALOG_FILENAME).is_file():
        return candidate
    if workspace.name == project_name and (workspace / CATALOG_FILENAME).is_file():
        return workspace
    return None


def _delete_calibration_session(workspace: Path, project_name: str, session_id: str) -> bool:
    import duckdb

    project_root = _project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    conn = duckdb.connect(str(project_root / CATALOG_FILENAME))
    try:
        conn.execute(
            "DELETE FROM calibration_iterations WHERE session_id = ?",
            [session_id],
        )
        conn.execute(
            "DELETE FROM calibration_sessions WHERE session_id = ?",
            [session_id],
        )
    finally:
        conn.close()
    return True


def _mark_simulation_failed(workspace: Path, project_name: str, sim_id: str) -> bool:
    import duckdb

    project_root = _project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    conn = duckdb.connect(str(project_root / CATALOG_FILENAME))
    try:
        conn.execute(
            """
            UPDATE simulations
               SET status_id = (SELECT id FROM statuses WHERE code = 'failed'),
                   ended_at = current_timestamp,
                   updated_at = current_timestamp
             WHERE sim_id = ?
            """,
            [sim_id],
        )
    finally:
        conn.close()
    return True


__all__ = ("NAME", "HELP", "register", "run")
