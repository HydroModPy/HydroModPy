"""Private worker helpers for ``hmp catalog`` actions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def delete_simulation_artifacts(
    catalog: Any,
    sid: str,
    *,
    remove_storage: bool = True,
) -> dict[str, object]:
    """Delete one simulation through an already-open catalog.

    Used by ``hydromodpy.cli.commands.dev.manage`` when iterating over many
    sims inside a single catalog session. ``delete_simulation`` is the
    open-and-delete variant exposed via ``hmp catalog delete``.
    """
    zarr_path = catalog.zarr_path_for(sid)
    parquet_dir = catalog.parquet_dir_for(sid)
    existing_paths = [path for path in (zarr_path, parquet_dir) if path.exists()]
    freed = sum(_path_size(p) for p in existing_paths) if remove_storage else 0
    catalog.delete(sid, remove_storage=remove_storage)
    return {
        "sim_id": sid,
        "freed_bytes": freed,
        "removed_paths": [str(p) for p in existing_paths] if remove_storage else [],
    }


def list_simulations(
    workspace: Any,
    *,
    project: str | None = None,
    solver: str | None = None,
    catchment: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
) -> Any:
    """List simulations recorded in a workspace catalog.

    Iterates over per-project ``catalog.duckdb`` files inside ``workspace``
    and returns a concatenated DataFrame of simulation rows ordered by
    ``created_at DESC``. Filters apply as substring matches on ``solver``
    and ``catchment``, exact match on ``project``.

    Parameters
    ----------
    workspace
        Workspace directory containing a ``projects/`` tree.
    project, solver, catchment, limit
        Optional filters.

    Returns
    -------
    pandas.DataFrame
        Combined simulation rows. Empty when the workspace has no project
        catalog or no row matches the filters.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    projects_dir = workspace_root / "projects"
    if not projects_dir.is_dir():
        import pandas as pd

        return pd.DataFrame()

    if project:
        project_roots = [projects_dir / project]
    else:
        project_roots = sorted(
            p for p in projects_dir.iterdir() if p.is_dir() and (p / CATALOG_FILENAME).exists()
        )

    import pandas as pd

    from hydromodpy.results.errors import SchemaVersionMismatchError

    frames: list[pd.DataFrame] = []
    for project_dir in project_roots:
        if not (project_dir / CATALOG_FILENAME).exists():
            continue
        tagged_ids: set[str] | None = None
        try:
            with SimulationCatalog(project_dir, read_only=True) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
                if tag:
                    rows = catalog.backend.fetch_all(
                        "SELECT CAST(sim_id AS VARCHAR) FROM tags WHERE tag = ?", [tag]
                    )
                    tagged_ids = {r[0] for r in rows}
        except SchemaVersionMismatchError:
            import sys

            print(
                f"skipping {project_dir.name}: schema behind (run 'hmp doctor --migrate')",
                file=sys.stderr,
            )
            continue
        if sims.empty:
            continue
        if solver:
            alias = {"mf6": "modflow6", "nwt": "modflow_nwt"}
            target = alias.get(solver.strip().lower(), solver.strip().lower())
            sims = sims[sims["solver"].fillna("").str.lower() == target]
        if catchment:
            col = "study_area_name" if "study_area_name" in sims.columns else None
            if col is not None:
                sims = sims[sims[col].fillna("").str.contains(catchment, case=False)]
        if status:
            sims = sims[sims["status"].fillna("") == status]
        if tagged_ids is not None:
            sims = sims[sims["sim_id"].astype(str).isin(tagged_ids)]
        sims = sims.assign(project=project_dir.name)
        frames.append(sims)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if limit is not None:
        out = out.head(int(limit))
    return _stable_listing_projection(out, drop_trashed=(status != "trashed"))


_LISTING_COLUMNS: tuple[str, ...] = (
    "sim_id",
    "name",
    "project",
    "solver",
    "status",
    "created_at",
    "started_at",
    "duration_s",
    "n_cells",
    "n_layers",
    "config_hash",
    "version_int",
)


def _stable_listing_projection(df: Any, *, drop_trashed: bool = True) -> Any:
    """Return a scriptable 12-column projection (string ids, ISO dates).

    Keeps the listing cheap and JSON/CSV safe: ``sim_id`` and timestamps are
    cast to strings (raw ``uuid.UUID`` objects break ``DataFrame.to_json``) and
    config blobs are dropped so ``ls`` never moves megabytes to print a page.
    Trashed runs are hidden unless ``drop_trashed`` is False.
    """
    if drop_trashed and "status" in df.columns:
        df = df[df["status"] != "trashed"]
    cols = [c for c in _LISTING_COLUMNS if c in df.columns]
    out = df[cols].copy()
    if "sim_id" in out.columns:
        out["sim_id"] = out["sim_id"].astype(str)
    for time_col in ("created_at", "started_at"):
        if time_col in out.columns:
            out[time_col] = out[time_col].astype(str)
    return out


def show_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    detail: bool = False,
) -> dict:
    """Return a metadata dict describing one simulation.

    Parameters
    ----------
    sim_ref
        Full sim id, unique prefix (>= 4 chars), or simulation name.
    workspace
        Project catalog root.
    detail
        When ``True``, also reports the Zarr store layout (groups, paths).

    Returns
    -------
    dict
        Simulation metadata. Includes ``zarr_path``, ``zarr_exists`` and
        ``zarr_groups`` when ``detail=True``.

    Raises
    ------
    FileNotFoundError
        If the workspace has no ``catalog.duckdb``.
    hydromodpy.results.catalog.SimulationNotFoundError
        If ``sim_ref`` cannot be resolved.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root, read_only=True) as catalog:
        sid = catalog.resolve(sim_ref)
        sim = catalog[sid]
        payload: dict = {
            "sim_id": sim.sim_id,
            "name": sim.name,
            "project": sim.project,
            "solver": sim.solver,
            "status": sim.status,
            "duration_s": sim.duration_s,
            "n_cells": sim.n_cells,
            "n_timesteps": sim.n_timesteps,
            "exports": catalog.list_exports(sid),
        }
        if detail:
            zarr_path = catalog.zarr_path_for(sid)
            payload["zarr_path"] = str(zarr_path)
            payload["zarr_exists"] = zarr_path.exists()
            groups: list[str] = []
            if zarr_path.exists() and zarr_path.is_dir():
                try:
                    groups = sorted(p.name for p in zarr_path.iterdir() if p.is_dir())[:20]
                except OSError:
                    groups = []
            payload["zarr_groups"] = groups
        return payload


def query_catalog(
    sql: str,
    *,
    workspace: Any,
    limit: int | None = None,
) -> Any:
    """Run a read-only SQL statement against the workspace catalog DuckDB.

    Parameters
    ----------
    sql
        SQL statement (SELECT, PRAGMA, ...).
    workspace
        Project catalog root.
    limit
        Optional outer ``LIMIT`` wrapped around the statement.

    Returns
    -------
    pandas.DataFrame
        Result rows.

    Raises
    ------
    FileNotFoundError
        If the workspace has no ``catalog.duckdb``.
    duckdb.Error
        If the SQL statement is invalid or the catalog rejects it.
    """
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = Path(workspace).expanduser().resolve()
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    statement = sql.strip()
    if limit is not None:
        statement = f"SELECT * FROM ({statement}) LIMIT {int(limit)}"
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        return conn.execute(statement).fetchdf()
    finally:
        conn.close()


def gc(workspace: Any = None, *, dry_run: bool = False) -> dict:
    """Garbage-collect orphan caches, tmp parquet, and stale running sims.

    Returns a dict with ``plan`` (mapping category -> candidate list) and
    ``summary`` (mapping category -> applied count, empty when ``dry_run``).
    """
    workspace_root = _gc_resolve_workspace(workspace)
    plan = _gc_collect_plan(workspace_root)
    summary: dict[str, int] = {}
    if not dry_run:
        summary = _gc_apply_plan(workspace_root, plan)
        _emit_gc_audit_events(workspace_root, summary)
    return {"workspace": str(workspace_root), "plan": plan, "summary": summary, "dry_run": dry_run}


def _emit_gc_audit_events(workspace: Path, summary: dict[str, int]) -> None:
    """Emit one ``gc`` audit row per project catalog reflecting the sweep summary."""
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.catalog.audit import emit_audit_event

    for project_root in _gc_iter_project_roots(workspace):
        try:
            catalog = SimulationCatalog(project_root)
        except Exception:
            continue
        try:
            emit_audit_event(
                catalog.connection,
                event_type="gc",
                actor_kind="cli",
                project=project_root.name,
                payload={"summary": dict(summary)},
            )
        except Exception:
            pass
        finally:
            catalog.close()


def adopt_store(store_path: Any, *, workspace: Any) -> dict:
    """Re-register an orphan store into the workspace catalog.

    Returns ``{"sim_id": ...}``. Raises ``FileNotFoundError`` when the
    catalog or the snapshot is missing, ``ValueError`` on a bad store.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        return {"sim_id": catalog.adopt(store_path)}


def delete_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    keep_storage: bool = False,
) -> dict:
    """Delete one simulation row and (optionally) its Zarr / Parquet store.

    Returns a dict with ``sim_id``, ``freed_bytes``, ``removed_paths``.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        zarr_path = catalog.zarr_path_for(sid)
        parquet_dir = catalog.parquet_dir_for(sid)
        existing = [path for path in (zarr_path, parquet_dir) if path.exists()]
        freed_bytes = sum(_path_size(path) for path in existing) if not keep_storage else 0
        catalog.delete(sid, remove_storage=not keep_storage)
        return {
            "sim_id": sid,
            "freed_bytes": freed_bytes,
            "removed_paths": [str(p) for p in existing] if not keep_storage else [],
        }


def _open_project_catalog(workspace: Any, *, read_only: bool = False) -> Any:
    """Open the project catalog at ``workspace`` or raise."""
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    root = Path(workspace).expanduser().resolve()
    if not (root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {root}")
    return SimulationCatalog(root, read_only=read_only)


def rerun_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    overrides: dict | None = None,
    name: str | None = None,
) -> dict:
    """Re-launch a run from its config snapshot with dotted-path overrides.

    Reads the snapshot through a short-lived read-only catalog (closed before
    launching) so the fresh run's writable catalog never contends in-process.
    """
    from hydromodpy.results.rerun_contract import get_rerun_provider

    with _open_project_catalog(workspace, read_only=True) as catalog:
        sid = catalog.resolve(sim_ref)
        run = catalog[sid]
        snapshot = run.config_snapshot
        base_name = run.name
    if snapshot is None:
        raise ValueError(f"Run {sid[:8]} has no config snapshot; cannot rerun.")
    new_name = name or (f"{base_name}_rerun" if base_name else None)
    new_sid = get_rerun_provider().rerun(snapshot, overrides=overrides or {}, name=new_name)
    return {"sim_id": str(new_sid), "name": new_name}


def tag_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    add: tuple[str, ...] = (),
    remove: tuple[str, ...] = (),
) -> dict:
    """Add and/or remove tags on the run referenced by ``sim_ref``."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        added = [t for t in add if catalog.add_tag(sid, t)]
        removed = [t for t in remove if catalog.remove_tag(sid, t)]
        return {"sim_id": sid, "added": added, "removed": removed}


def note_simulation(sim_ref: str, *, workspace: Any, note: str) -> dict:
    """Append a timestamped note to the run referenced by ``sim_ref``."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        catalog.add_note(sid, note)
        return {"sim_id": sid}


def rename_simulation(sim_ref: str, *, workspace: Any, new_name: str) -> dict:
    """Rename the run referenced by ``sim_ref`` to ``new_name``."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        catalog.rename_simulation(sid, new_name)
        return {"sim_id": sid, "name": new_name}


def trash_simulation(sim_ref: str, *, workspace: Any, force: bool = False) -> dict:
    """Move the run referenced by ``sim_ref`` to the trash (storage stays)."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        catalog.trash(sid, force=force)
        return {"sim_id": sid}


def restore_simulation(sim_ref: str, *, workspace: Any) -> dict:
    """Restore a trashed run, returning its (possibly versioned) name."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        name = catalog.restore(sid)
        return {"sim_id": sid, "name": name}


def diff_simulations(ref_a: str, ref_b: str, *, workspace: Any) -> dict:
    """Compare two runs' parameters and outlet metrics."""
    with _open_project_catalog(workspace) as catalog:
        return catalog.diff(ref_a, ref_b)


def export_package_run(sim_ref: str, *, workspace: Any, output: str | None = None) -> dict:
    """Export the run referenced by ``sim_ref`` as a portable ``.hmp`` archive."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        run_name = catalog[sid].name or sid[:8]
        dest = Path(output).expanduser() if output else Path.cwd() / f"{run_name}.hmp"
        produced = catalog.export_package(sid, dest)
        return {"sim_id": sid, "path": str(produced)}


def export_package_runs(
    sim_refs: list[str], *, workspace: Any, output_dir: str | None = None
) -> list[dict]:
    """Export several runs as one ``.hmp`` archive each (v1 multi-run export).

    Each archive is named ``<run-name>.hmp`` under ``output_dir`` (default: the
    current directory). A true single-container multi-run archive is a later
    format bump; for now N references produce N archives.
    """
    out_dir = Path(output_dir).expanduser() if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with _open_project_catalog(workspace) as catalog:
        for ref in sim_refs:
            sid = catalog.resolve(ref)
            run_name = catalog[sid].name or sid[:8]
            produced = catalog.export_package(sid, out_dir / f"{run_name}.hmp")
            results.append({"sim_id": sid, "path": str(produced)})
    return results


def import_package_run(package_path: Any, *, workspace: Any, force: bool = False) -> dict:
    """Import a ``.hmp`` archive into the workspace catalog (created if absent)."""
    from hydromodpy.results.catalog import SimulationCatalog

    root = Path(workspace).expanduser().resolve()
    pkg = Path(package_path).expanduser()
    if not pkg.is_file():
        raise FileNotFoundError(f"No archive at {pkg}")
    with SimulationCatalog(root) as catalog:
        sid = catalog.import_package(pkg, force=force)
        return {"sim_id": sid}


def watch_running(workspace: Any, *, stale_minutes: int = 10) -> list[dict]:
    """Return running runs with heartbeat age and a staleness flag.

    A run is ``stale`` when its newest heartbeat is older than
    ``stale_minutes`` (or it never emitted one), which usually means the
    process died without finalizing.
    """
    with _open_project_catalog(workspace) as catalog:
        rows = catalog._backend.fetch_all(
            "SELECT CAST(s.sim_id AS VARCHAR), s.name, s.created_at, wh.last_heartbeat, "
            "CASE WHEN wh.last_heartbeat IS NULL THEN NULL "
            "ELSE EXTRACT(EPOCH FROM (current_timestamp - wh.last_heartbeat)) END "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN v_workflow_heartbeats wh ON wh.run_id = CAST(s.sim_id AS VARCHAR) "
            "WHERE st.code = 'running' ORDER BY s.created_at DESC",
        )
        cutoff = stale_minutes * 60
        out = []
        for sid, name, created_at, last_heartbeat, age_s in rows:
            stale = age_s is None or float(age_s) > cutoff
            out.append(
                {
                    "sim_id": sid,
                    "name": name,
                    "created_at": created_at,
                    "last_heartbeat": last_heartbeat,
                    "age_s": None if age_s is None else float(age_s),
                    "stale": stale,
                }
            )
        return out


def list_trashed(workspace: Any) -> list[dict]:
    """Return the trashed runs in the workspace catalog."""
    with _open_project_catalog(workspace) as catalog:
        return catalog.list_trash()


def empty_trashed(workspace: Any, *, force: bool = False) -> list[str]:
    """Hard-delete trashed runs (pinned skipped unless ``force``)."""
    with _open_project_catalog(workspace) as catalog:
        return catalog.empty_trash(force=force)


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total


def _gc_resolve_workspace(workspace: Any) -> Path:
    import sys as _sys

    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws

    if workspace is not None:
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace {root} does not exist.")
        return root
    try:
        return _resolve_ws(None)
    except SystemExit:  # pragma: no cover - defensive
        print("Workspace resolution failed", file=_sys.stderr)
        raise


def _gc_iter_project_roots(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    roots: list[Path] = []
    if (workspace / CATALOG_FILENAME).is_file():
        roots.append(workspace)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if entry.is_dir() and (entry / CATALOG_FILENAME).is_file():
                roots.append(entry)
    return roots


def _gc_collect_plan(workspace: Path) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {
        "calibration_sessions": [],
        "geographic_cache": [],
        "tmp_parquet": [],
        "stale_running_sims": [],
        "expired_trash": [],
        "pending_purges": [],
        "orphan_stores": [],
    }
    project_roots = _gc_iter_project_roots(workspace)
    for project_root in project_roots:
        plan["calibration_sessions"].extend(_gc_orphan_calibration_sessions(project_root))
        plan["stale_running_sims"].extend(_gc_stale_running_simulations(project_root))
        plan["expired_trash"].extend(_gc_expired_trash(project_root))
        plan["pending_purges"].extend(_gc_pending_purges(project_root))
        plan["orphan_stores"].extend(_gc_orphan_stores(project_root))
    plan["geographic_cache"].extend(_gc_orphan_geographic_cache(workspace, project_roots))
    plan["tmp_parquet"].extend(_gc_tmp_parquet_files(workspace))
    return plan


def _gc_expired_trash(project_root: Path) -> list[str]:
    """Trashed, non-pinned runs older than the retention window."""
    from datetime import UTC, datetime, timedelta

    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog.constants import TRASH_RETENTION_DAYS

    catalog_path = project_root / CATALOG_FILENAME
    cutoff = datetime.now(UTC) - timedelta(days=TRASH_RETENTION_DAYS)
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT CAST(s.sim_id AS VARCHAR)
              FROM simulations s
              JOIN statuses st ON s.status_id = st.id
         LEFT JOIN tags t ON t.sim_id = s.sim_id AND t.tag = 'pinned'
             WHERE st.code = 'trashed'
               AND s.trashed_at IS NOT NULL AND s.trashed_at < ?
               AND t.sim_id IS NULL
            """,
            [cutoff],
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{r[0]}" for r in rows]


def _gc_pending_purges(project_root: Path) -> list[str]:
    """Hard purges interrupted by a crash (a ``purge_journal`` row remains)."""
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalog_path = project_root / CATALOG_FILENAME
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute("SELECT CAST(sim_id AS VARCHAR) FROM purge_journal").fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{r[0]}" for r in rows]


def _gc_orphan_stores(project_root: Path) -> list[str]:
    """Zarr/Parquet stores on disk with no matching ``storage_basename`` row."""
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    simulations_dir = project_root / "simulations"
    if not simulations_dir.is_dir():
        return []
    catalog_path = project_root / CATALOG_FILENAME
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        known = {
            r[0]
            for r in conn.execute(
                "SELECT storage_basename FROM simulations WHERE storage_basename IS NOT NULL"
            ).fetchall()
        }
    except duckdb.Error:
        known = set()
    finally:
        conn.close()

    orphans: list[str] = []
    for entry in sorted(simulations_dir.iterdir()):
        basename = _gc_store_basename(entry.name)
        if basename is None or basename in known:
            continue
        orphans.append(str(entry))
    return orphans


def _gc_store_basename(entry_name: str) -> str | None:
    """Strip a store suffix (.zarr / .zarr.zip / .parquet) to its basename."""
    for suffix in (".zarr.zip", ".zarr", ".parquet"):
        if entry_name.endswith(suffix):
            return entry_name[: -len(suffix)]
    return None


def _gc_orphan_calibration_sessions(project_root: Path) -> list[str]:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

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
    return [f"{project_root.name}:{r[0]!s}" for r in rows]


def _gc_stale_running_simulations(project_root: Path) -> list[str]:
    from datetime import UTC, datetime, timedelta

    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalog_path = project_root / CATALOG_FILENAME
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
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
         LEFT JOIN v_workflow_heartbeats wh ON wh.run_id = s.sim_id
             WHERE st.code = 'running'
               AND (wh.last_heartbeat IS NULL OR wh.last_heartbeat < ?)
            """,
            [cutoff],
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{r[0]!s}" for r in rows]


def _gc_orphan_geographic_cache(workspace: Path, project_roots: list[Path]) -> list[str]:
    cache_dir = workspace / "geographic"
    if not cache_dir.is_dir():
        return []
    referenced = _gc_referenced_geographic_fingerprints(project_roots)
    orphans: list[str] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in referenced:
            continue
        orphans.append(str(entry))
    return orphans


def _gc_referenced_geographic_fingerprints(project_roots: list[Path]) -> set[str]:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

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


def _gc_tmp_parquet_files(workspace: Path) -> list[str]:
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


def _gc_apply_plan(workspace: Path, plan: dict[str, list[str]]) -> dict[str, int]:

    summary: dict[str, int] = dict.fromkeys(plan, 0)
    for ref in plan["calibration_sessions"]:
        project_name, session_id = ref.split(":", 1)
        if _gc_delete_calibration_session(workspace, project_name, session_id):
            summary["calibration_sessions"] += 1
    for ref in plan["stale_running_sims"]:
        project_name, sim_id = ref.split(":", 1)
        if _gc_mark_simulation_failed(workspace, project_name, sim_id):
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
                summary["tmp_parquet"] += 1
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                summary["tmp_parquet"] += 1
        except OSError:
            continue
    for path_str in plan["orphan_stores"]:
        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
                summary["orphan_stores"] += 1
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                summary["orphan_stores"] += 1
        except OSError:
            continue
    summary["expired_trash"], summary["pending_purges"] = _gc_apply_per_project_purges(
        workspace, plan["expired_trash"], plan["pending_purges"]
    )
    # Absorbed maintenance (the old `vacuum` verb): checkpoint catalogs and the
    # data cache, then consolidate Zarr metadata. Safe to run every sweep.
    summary["catalog_checkpoints"] = _vacuum_checkpoint_catalogs(workspace)
    summary["cache_checkpoints"] = _vacuum_checkpoint_data_cache(workspace)
    summary["zarr_consolidated"] = _vacuum_consolidate_zarr_stores(workspace)
    return summary


def _gc_apply_per_project_purges(
    workspace: Path, expired_refs: list[str], pending_refs: list[str]
) -> tuple[int, int]:
    """Purge expired trash and replay interrupted purges, one catalog open per project."""
    from hydromodpy.results.catalog import SimulationCatalog

    expired_by_project: dict[str, list[str]] = {}
    for ref in expired_refs:
        project_name, sim_id = ref.split(":", 1)
        expired_by_project.setdefault(project_name, []).append(sim_id)
    pending_projects = {ref.split(":", 1)[0] for ref in pending_refs}

    expired_count = 0
    pending_count = 0
    for project_name in sorted(set(expired_by_project) | pending_projects):
        project_root = _gc_project_root_by_name(workspace, project_name)
        if project_root is None:
            continue
        with SimulationCatalog(project_root) as catalog:
            for sim_id in expired_by_project.get(project_name, []):
                try:
                    catalog.delete(sim_id, audit_event_type="sim.purge")
                    expired_count += 1
                except Exception:
                    continue
            if project_name in pending_projects:
                try:
                    pending_count += len(catalog.replay_purge_journal())
                except Exception:
                    pass
    return expired_count, pending_count


def _gc_project_root_by_name(workspace: Path, project_name: str) -> Path | None:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    candidate = workspace / "projects" / project_name
    if candidate.is_dir() and (candidate / CATALOG_FILENAME).is_file():
        return candidate
    if workspace.name == project_name and (workspace / CATALOG_FILENAME).is_file():
        return workspace
    return None


def _gc_delete_calibration_session(workspace: Path, project_name: str, session_id: str) -> bool:
    from hydromodpy.results.catalog import SimulationCatalog

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    with SimulationCatalog(project_root) as catalog:
        catalog.connection.execute(
            "DELETE FROM calibration_iterations WHERE session_id = ?", [session_id]
        )
        catalog.connection.execute(
            "DELETE FROM calibration_sessions WHERE session_id = ?", [session_id]
        )
    return True


def _gc_mark_simulation_failed(workspace: Path, project_name: str, sim_id: str) -> bool:
    from hydromodpy.results.catalog import SimulationCatalog

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    with SimulationCatalog(project_root) as catalog:
        catalog.connection.execute(
            """
            UPDATE simulations
               SET status_id = (SELECT id FROM statuses WHERE code = 'failed'),
                   ended_at = current_timestamp,
                   updated_at = current_timestamp
             WHERE sim_id = ?
            """,
            [sim_id],
        )
    return True


def _vacuum_iter_catalog_files(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalogs: list[Path] = []
    candidate = workspace / CATALOG_FILENAME
    if candidate.is_file():
        catalogs.append(candidate)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            cat = entry / CATALOG_FILENAME
            if cat.is_file():
                catalogs.append(cat)
    return catalogs


def _vacuum_checkpoint_catalogs(workspace: Path) -> int:
    import duckdb

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.catalog.audit import emit_audit_event

    count = 0
    for catalog_path in _vacuum_iter_catalog_files(workspace):
        try:
            with SimulationCatalog(catalog_path.parent) as catalog:
                catalog.connection.execute("CHECKPOINT")
                try:
                    emit_audit_event(
                        catalog.connection,
                        event_type="vacuum",
                        actor_kind="cli",
                        project=catalog_path.parent.name,
                        payload={"scope": "catalog"},
                    )
                except Exception:
                    pass
            count += 1
        except duckdb.Error:
            continue
    return count


def _vacuum_checkpoint_data_cache(workspace: Path) -> int:
    import duckdb

    from hydromodpy.data.registry._backend import DuckDBCacheBackend

    cache_path = workspace / "data" / "cache.duckdb"
    if not cache_path.is_file():
        return 0
    backend = DuckDBCacheBackend(cache_path)
    try:
        backend.connection.execute("CHECKPOINT")
        return 1
    except duckdb.Error:
        return 0
    finally:
        backend.close()


def _vacuum_consolidate_zarr_stores(workspace: Path) -> int:
    try:
        import zarr  # noqa: F401
    except ImportError:
        return 0
    from hydromodpy.results.zarr_store import SimulationZarr

    count = 0
    for sim_dir in workspace.rglob("simulations"):
        if not sim_dir.is_dir():
            continue
        for entry in sorted(sim_dir.iterdir()):
            if entry.is_dir() and entry.suffix == ".zarr":
                try:
                    sz = SimulationZarr(entry)
                    try:
                        sz.consolidate_metadata()
                    finally:
                        sz.close()
                    count += 1
                except Exception:
                    continue
    return count
