"""Private worker helpers for ``hmp catalog`` actions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


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
    run_dir = catalog.run_dir_for(sid)
    removed = [run_dir] if remove_storage and run_dir.is_dir() else []
    freed = sum(_path_size(p) for p in removed)
    catalog.delete(sid, remove_storage=remove_storage)
    return {
        "sim_id": sid,
        "freed_bytes": freed,
        "removed_paths": [str(p) for p in removed],
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

    Iterates over the per-project index databases (``<project>/.hmp/index.duckdb``)
    reachable from ``workspace`` and returns a concatenated DataFrame of
    simulation rows ordered by ``created_at DESC``. A standalone project (its
    own index at the root) lists as well as a workspace holding a ``projects/``
    tree. Filters apply as substring matches on ``solver`` and ``catchment``,
    exact match on ``project``.

    Parameters
    ----------
    workspace
        Project root, or a workspace directory holding a ``projects/`` tree.
    project, solver, catchment, limit
        Optional filters.

    Returns
    -------
    pandas.DataFrame
        Combined simulation rows. Empty when nothing is indexed under
        ``workspace`` or no row matches the filters.
    """
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog, iter_project_catalog_roots

    workspace_root = Path(workspace).expanduser().resolve()
    if project:
        project_roots = [workspace_root / "projects" / project]
    else:
        project_roots = iter_project_catalog_roots(workspace_root)

    import pandas as pd

    from hydromodpy.results.errors import SchemaVersionMismatchError

    frames: list[pd.DataFrame] = []
    for project_dir in project_roots:
        if not (catalog_path_for(project_dir)).exists():
            continue
        tagged_ids: set[str] | None = None
        try:
            with Catalog(project_dir, read_only=True) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
                if tag:
                    tagged_ids = catalog.sims_with_tag(tag)
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
            from hydromodpy.results.catalog.constants import canonical_solver_code

            target = canonical_solver_code(solver)
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
        If the workspace has no project index database.
    hydromodpy.results.catalog.SimulationNotFoundError
        If ``sim_ref`` cannot be resolved.
    """
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with Catalog(workspace_root, read_only=True) as catalog:
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
            zarr_path = catalog.fields_path_for(sid)
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
        If the workspace has no project index database.
    duckdb.Error
        If the SQL statement is invalid or the catalog rejects it.
    """
    import duckdb

    from hydromodpy.core.state.paths import catalog_path_for

    workspace_root = Path(workspace).expanduser().resolve()
    catalog_path = catalog_path_for(workspace_root)
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


def gc(workspace: Any = None, *, dry_run: bool = True) -> dict:
    """Garbage-collect orphan caches, tmp parquet, and stale running sims.

    Plans by default: nothing is touched unless the caller passes
    ``dry_run=False``. Orphan run stores are never destroyed, only moved to
    ``<project>/.hmp/trash/<stamp>/``.

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
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.audit import emit_audit_event

    for project_root in _gc_iter_project_roots(workspace):
        try:
            catalog = Catalog(project_root)
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


def reindex_project(workspace: Any) -> dict:
    """Rebuild the project index from its run directories.

    Returns ``{"index": ..., "indexed": [...], "skipped": [...], "rows": {...}}``.
    Idempotent: the index is rebuilt from what the runs declare on disk, so
    running it twice describes the same project twice.
    """
    from hydromodpy.results.catalog.reindex import rebuild_index

    report = rebuild_index(Path(workspace).expanduser().resolve())
    return {
        "index": str(report.index_path),
        "indexed": list(report.indexed),
        "skipped": [{"run": item.run, "reason": item.reason} for item in report.skipped],
        "rows": dict(report.rows),
    }


def delete_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    keep_storage: bool = False,
) -> dict:
    """Delete one simulation row and (optionally) its run directory.

    Returns a dict with ``sim_id``, ``freed_bytes``, ``removed_paths``.
    """
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with Catalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        return delete_simulation_artifacts(catalog, sid, remove_storage=not keep_storage)


def _open_project_catalog(workspace: Any, *, read_only: bool = False) -> Any:
    """Open the project catalog at ``workspace`` or raise."""
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog

    root = Path(workspace).expanduser().resolve()
    if not (catalog_path_for(root)).exists():
        raise FileNotFoundError(f"No catalog at {root}")
    return Catalog(root, read_only=read_only)


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
    from hydromodpy.results.run.rerun_contract import get_rerun_provider

    with _open_project_catalog(workspace, read_only=True) as catalog:
        sid = catalog.resolve(sim_ref)
        run = catalog[sid]
        snapshot = run.config_snapshot
        base_name = run.name
    if snapshot is None:
        raise ValueError(f"Run {sid[:8]} has no config snapshot; cannot rerun.")
    requested_name = name or (f"{base_name}_rerun" if base_name else None)
    new_sid = str(
        get_rerun_provider().rerun(
            snapshot, overrides=overrides or {}, name=requested_name, source_sim_id=sid
        )
    )
    # Registration may auto-version the requested name ('x_rerun' -> 'x_rerun.v2');
    # re-read the row so the CLI reports the name that actually exists.
    final_name = requested_name
    try:
        with _open_project_catalog(workspace, read_only=True) as catalog:
            final_name = catalog[new_sid].name or requested_name
    except Exception:
        pass
    return {"sim_id": new_sid, "name": final_name}


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
    with _open_project_catalog(workspace, read_only=True) as catalog:
        return catalog.diff(ref_a, ref_b)


def export_package_run(sim_ref: str, *, workspace: Any, output: str | None = None) -> dict:
    """Export the run referenced by ``sim_ref`` as a portable ``.hmp`` archive."""
    with _open_project_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        run_name = catalog[sid].name or sid[:8]
        dest = Path(output).expanduser() if output else Path.cwd() / f"{run_name}.hmp"
        produced = catalog.export_package(sid, dest)
        catalog.record_export(sid, kind="hmp", path=produced)
        return {"sim_id": sid, "path": str(produced)}


def export_package_runs(sim_refs: list[str], *, workspace: Any, output: str | None = None) -> dict:
    """Export several runs as ONE portable multi-run ``.hmp`` container.

    Returns ``{"sim_ids": [...], "path": ...}``. Each run is a self-contained
    single-run archive nested in the container; ``import`` restores them all.
    """
    dest = Path(output).expanduser() if output else Path.cwd() / "runs.hmp"
    with _open_project_catalog(workspace) as catalog:
        sids = [catalog.resolve(ref) for ref in sim_refs]
        produced = catalog.export_package_multi(sids, dest)
        for sid in sids:
            catalog.record_export(sid, kind="hmp", path=produced)
    return {"sim_ids": sids, "path": str(produced)}


def import_package_run(package_path: Any, *, workspace: Any, force: bool = False) -> dict:
    """Import a single- or multi-run ``.hmp`` archive (catalog created if absent).

    Returns ``{"sim_ids": [...]}`` (one id for a single-run archive, one per run
    for a multi-run container).
    """
    from hydromodpy.results.catalog import Catalog

    root = Path(workspace).expanduser().resolve()
    pkg = Path(package_path).expanduser()
    if not pkg.is_file():
        raise FileNotFoundError(f"No archive at {pkg}")
    with Catalog(root) as catalog:
        return {"sim_ids": catalog.import_package_multi(pkg, force=force)}


def _read_running_sidecars(project_root: Path, cutoff_s: float) -> dict[str, dict]:
    """Read live-run heartbeat sidecars under ``project_root`` keyed by id8.

    Lets ``watch`` see liveness without touching the DuckDB catalog, which a
    live solve holds locked.
    """
    import json
    from datetime import UTC, datetime

    from hydromodpy.core.state.paths import running_sidecar_dir

    sidecar_dir = running_sidecar_dir(project_root)
    out: dict[str, dict] = {}
    if not sidecar_dir.is_dir():
        return out
    now = datetime.now(UTC)
    for path in sidecar_dir.glob("*.json"):
        sim_id: str | None = None
        ts: str | None = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sim_id = data.get("sim_id")
            ts = data.get("ts")
            age_s = max(0.0, (now - datetime.fromisoformat(ts)).total_seconds())
        except (OSError, ValueError, KeyError):
            try:
                age_s = max(0.0, now.timestamp() - path.stat().st_mtime)
            except OSError:
                continue
        out[path.stem] = {
            "sim_id": sim_id,
            "ts": ts,
            "age_s": age_s,
            "stale": age_s > cutoff_s,
        }
    return out


def watch_running(workspace: Any, *, stale_minutes: int | None = None) -> list[dict]:
    """Return running runs with heartbeat age and a staleness flag.

    A run is ``stale`` when neither its sidecar nor its newest DB heartbeat is
    fresher than ``stale_minutes``, which usually means the process died
    without finalizing. Sidecars are read first so ``watch`` stays usable even
    while a solve holds the catalog locked.
    """
    from hydromodpy.results.catalog.constants import STALE_HEARTBEAT_MINUTES

    minutes = STALE_HEARTBEAT_MINUTES if stale_minutes is None else stale_minutes
    root = Path(workspace).expanduser().resolve()
    cutoff = minutes * 60
    sidecars = _read_running_sidecars(root, cutoff)
    by_id8: dict[str, dict] = {}

    try:
        with _open_project_catalog(workspace, read_only=True) as catalog:
            rows = catalog.list_running()
        for entry in rows:
            sid = str(entry["sim_id"])
            name, created_at = entry["name"], entry["created_at"]
            last_heartbeat, age_s = entry["last_heartbeat"], entry["age_s"]
            id8 = sid.replace("-", "")[:8]
            sc = sidecars.get(id8)
            if sc is not None and not sc["stale"]:
                stale, eff_age, hb = False, sc["age_s"], sc["ts"]
            else:
                stale = age_s is None or float(age_s) > cutoff
                eff_age = None if age_s is None else float(age_s)
                hb = last_heartbeat
            by_id8[id8] = {
                "sim_id": sid,
                "name": name,
                "created_at": created_at,
                "last_heartbeat": hb,
                "age_s": eff_age,
                "stale": stale,
            }
    except Exception:
        # Catalog locked (a live solve) or absent: report from sidecars alone.
        pass

    for id8, sc in sidecars.items():
        if id8 in by_id8:
            continue
        by_id8[id8] = {
            "sim_id": sc["sim_id"],
            "name": None,
            "created_at": None,
            "last_heartbeat": sc["ts"],
            "age_s": sc["age_s"],
            "stale": sc["stale"],
        }
    return list(by_id8.values())


def list_trashed(workspace: Any) -> list[dict]:
    """Return the trashed runs in the workspace catalog."""
    with _open_project_catalog(workspace, read_only=True) as catalog:
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
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace is not None:
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace {root} does not exist.")
        return root
    # Auto-detect from cwd like the other catalog verbs (ls/show/diff) rather
    # than defaulting straight to ~/hydromodpy: walk up to the workspace root,
    # or stay on a bare project directory that carries its own catalog.
    start = Path(os.environ.get("HMP_WORKSPACE") or Path.cwd()).expanduser().resolve()
    if (catalog_path_for(start)).is_file():
        return start
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    default = Path(DEFAULT_ROOT).expanduser().resolve()
    if not default.is_dir():
        raise FileNotFoundError(
            f"No workspace found from {start} and the default {default} does not exist. "
            "Pass --workspace or run 'hmp workspace init' first."
        )
    return default


def _gc_iter_project_roots(workspace: Path) -> list[Path]:
    from hydromodpy.results.catalog import iter_project_catalog_roots

    return iter_project_catalog_roots(workspace)


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


def _read_only_catalog(project_root: Path) -> Any | None:
    """Open a read-only catalog at ``project_root`` or return None on failure.

    A read-only open never migrates or locks the file, so it is safe to run
    against a workspace with live solves. Errors (locked, missing, schema
    behind) degrade to None so gc planning stays best-effort.
    """
    from hydromodpy.results.catalog import Catalog

    try:
        return Catalog(project_root, read_only=True)
    except Exception:
        return None


def _gc_expired_trash(project_root: Path) -> list[str]:
    """Trashed, non-pinned runs older than the retention window."""
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return []
    try:
        sids = catalog.list_expired_trash()
    except Exception:
        sids = []
    finally:
        catalog.close()
    return [f"{project_root.name}:{sid}" for sid in sids]


def _gc_pending_purges(project_root: Path) -> list[str]:
    """Hard purges interrupted by a crash (a ``purge_journal`` row remains)."""
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return []
    try:
        sids = catalog.list_pending_purges()
    except Exception:
        sids = []
    finally:
        catalog.close()
    return [f"{project_root.name}:{sid}" for sid in sids]


# Artefacts younger than this are assumed to belong to a live write and are
# never swept (atomic parquet .tmp-* files and run directories being written).
_GC_STAGING_MIN_AGE_S = 3600


def _gc_recent(path: Path, min_age_s: float) -> bool:
    """Return True when ``path`` was modified more recently than ``min_age_s``."""
    import time

    try:
        return (time.time() - path.stat().st_mtime) < min_age_s
    except OSError:
        return True


def _gc_orphan_stores(project_root: Path) -> list[str]:
    """Run directories on disk with no matching index row.

    Skips sealed runs (a ``manifest.json`` makes the run re-indexable by
    ``hmp catalog reindex``, so it is missing from the index, never lost),
    dotfile-prefixed entries, and any directory younger than the staging
    grace window so an in-flight registration is never swept.
    """
    from hydromodpy.core.state.paths import runs_dir_for
    from hydromodpy.results.manifest import is_sealed
    from hydromodpy.results.storage.diagnostics import is_run_directory

    runs_dir = runs_dir_for(project_root)
    if not runs_dir.is_dir():
        return []
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return []
    try:
        known = catalog.list_run_dirnames()
    except Exception:
        known = set()
    finally:
        catalog.close()

    orphans: list[str] = []
    for entry in sorted(runs_dir.iterdir()):
        if entry.name.startswith(".") or not is_run_directory(entry):
            continue
        if entry.name in known:
            continue
        if is_sealed(entry):
            continue
        if _gc_recent(entry, _GC_STAGING_MIN_AGE_S):
            continue
        orphans.append(str(entry))
    return orphans


def _gc_orphan_calibration_sessions(project_root: Path) -> list[str]:
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return []
    try:
        sessions = catalog.list_orphan_calibration_sessions()
    except Exception:
        sessions = []
    finally:
        catalog.close()
    return [f"{project_root.name}:{session}" for session in sessions]


def stale_running_sim_ids(project_root: Path, minutes: int | None = None) -> list[str]:
    """Return sim_ids of runs stale past ``minutes``, reconciled with sidecars.

    Shared by the gc reaper and ``doctor``: reads the catalog (read-only, no
    lock) then drops any run whose heartbeat sidecar is still fresh (a live run
    holds the catalog lock, so its DB heartbeat is invisible to a read probe).
    """
    from hydromodpy.results.catalog.constants import STALE_HEARTBEAT_MINUTES

    window = STALE_HEARTBEAT_MINUTES if minutes is None else minutes
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return []
    try:
        stale = catalog.list_stale_running(window)
    except Exception:
        stale = []
    finally:
        catalog.close()
    fresh = {
        id8
        for id8, sc in _read_running_sidecars(project_root, window * 60).items()
        if not sc["stale"]
    }
    return [
        str(entry["sim_id"])
        for entry in stale
        if str(entry["sim_id"]).replace("-", "")[:8] not in fresh
    ]


def orphan_calibration_session_count(project_root: Path) -> int:
    """Count calibration sessions whose ``best_sim_id`` no longer exists."""
    catalog = _read_only_catalog(project_root)
    if catalog is None:
        return 0
    try:
        return len(catalog.list_orphan_calibration_sessions())
    except Exception:
        return 0
    finally:
        catalog.close()


def _gc_stale_running_simulations(project_root: Path) -> list[str]:
    return [f"{project_root.name}:{sid}" for sid in stale_running_sim_ids(project_root)]


def _gc_orphan_geographic_cache(workspace: Path, project_roots: list[Path]) -> list[str]:
    from hydromodpy.results.geographic_cache import CACHE_DIRNAME

    cache_dir = workspace / CACHE_DIRNAME
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
    referenced: set[str] = set()
    for project_root in project_roots:
        catalog = _read_only_catalog(project_root)
        if catalog is None:
            continue
        try:
            referenced |= catalog.list_referenced_geographic_fingerprints()
        except Exception:
            pass
        finally:
            catalog.close()
    return referenced


def _gc_tmp_parquet_files(workspace: Path) -> list[str]:
    """Stale ``*.tmp-*`` atomic-write staging files past the grace window.

    ``*.tmp-<uuid>`` is exactly the atomic-write staging name of a parquet write
    in progress; deleting one mid-write breaks a concurrent run. Only sweep
    entries older than the staging grace window.
    """
    found: list[str] = []
    if not workspace.is_dir():
        return found
    for tmp in workspace.rglob("*.tmp-*"):
        try:
            if not (tmp.is_file() or tmp.is_dir()):
                continue
            if _gc_recent(tmp, _GC_STAGING_MIN_AGE_S):
                continue
            found.append(str(tmp))
        except OSError:
            continue
    return found


def _gc_trash_stamp() -> str:
    """UTC stamp naming one gc sweep in the project trash."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _gc_quarantine_orphan_store(store: Path, *, stamp: str) -> bool:
    """Move an orphan run directory to ``<project>/.hmp/trash/<stamp>/``.

    An orphan run directory is the only remaining copy of a run's outputs, so
    gc never deletes one: it quarantines it where a human can inspect it and
    finally remove it. Returns True when the directory was moved.
    """
    from hydromodpy.core.state.paths import internal_dir

    if not store.exists():
        return False
    # Orphan run directories are collected from ``<project>/runs/<name>``.
    trash_dir = internal_dir(store.parent.parent) / "trash" / stamp
    destination = trash_dir / store.name
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(store), str(destination))
    except OSError as exc:
        logger.warning("gc could not quarantine orphan store %s: %s", store, exc)
        return False
    logger.info("gc moved orphan store %s to %s", store.name, trash_dir)
    return True


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
    stamp = _gc_trash_stamp()
    for path_str in plan["orphan_stores"]:
        if _gc_quarantine_orphan_store(Path(path_str), stamp=stamp):
            summary["orphan_stores"] += 1
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
    from hydromodpy.results.catalog import Catalog

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
        with Catalog(project_root) as catalog:
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
    from hydromodpy.core.state.paths import catalog_path_for

    candidate = workspace / "projects" / project_name
    if candidate.is_dir() and (catalog_path_for(candidate)).is_file():
        return candidate
    if workspace.name == project_name and (catalog_path_for(workspace)).is_file():
        return workspace
    return None


def _gc_delete_calibration_session(workspace: Path, project_name: str, session_id: str) -> bool:
    from hydromodpy.results.catalog import Catalog

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    with Catalog(project_root) as catalog:
        catalog.delete_calibration_session(session_id)
    return True


def _gc_mark_simulation_failed(workspace: Path, project_name: str, sim_id: str) -> bool:
    from hydromodpy.results.catalog import Catalog

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    with Catalog(project_root) as catalog:
        catalog.mark_stale_running_failed(sim_id)
    # The crashed run left a stale sidecar behind; drop it.
    from hydromodpy.core.state.paths import running_sidecar_path

    running_sidecar_path(project_root, sim_id).unlink(missing_ok=True)
    return True


def _vacuum_iter_catalog_files(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import iter_project_catalog_roots

    return [catalog_path_for(root) for root in iter_project_catalog_roots(workspace)]


def _vacuum_checkpoint_catalogs(workspace: Path) -> int:
    import duckdb

    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.audit import emit_audit_event

    count = 0
    for catalog_path in _vacuum_iter_catalog_files(workspace):
        try:
            with Catalog(catalog_path.parent) as catalog:
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

    from hydromodpy.data.registry.backend import DuckDBCacheBackend

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
    from hydromodpy.core.state.paths import runs_dir_for
    from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
    from hydromodpy.results.zarr_store import SimulationZarr

    count = 0
    for project_root in _gc_iter_project_roots(workspace):
        runs_dir = runs_dir_for(project_root)
        if not runs_dir.is_dir():
            continue
        for entry in sorted(runs_dir.glob(f"*/{FIELDS_STORE_NAME}")):
            if entry.is_dir():
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
