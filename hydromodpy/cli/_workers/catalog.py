"""Private worker helpers for the ``hmp catalog`` verbs that read.

``ls``, ``show``, ``query``, ``point`` and ``diff`` read the index through
:class:`~hydromodpy.results.catalog.Catalog`. ``reindex`` writes it through
the indexer. ``watch``, and the counts ``hmp doctor`` prints, read the
``outcome.json`` and ``logs/heartbeat.json`` of the directories and never
open the index: a status page must answer while the index is being rebuilt
or when a project has none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S

logger = get_logger(__name__)

ABANDONED_SESSION_MINUTES = 24 * 60
"""How long a session may sit ``running`` before it is counted as abandoned.

A day, deliberately generous: a calibration on a daily chronicle runs for
hours, and counting a live one would be worse than missing a dead one.
"""

_LISTING_COLUMNS: tuple[str, ...] = (
    "sim_id",
    "name",
    "project",
    "site",
    "case_id",
    "rel_dir",
    "solver",
    "status",
    "label",
    "nse",
    "created_at",
    "started_at",
    "duration_s",
    "n_cells",
    "n_layers",
    "mesh_engine",
    "config_hash",
    "version_int",
)


def _open_catalog(workspace: Any) -> Any:
    """Open the index of the project at ``workspace`` or raise ``FileNotFoundError``."""
    from hydromodpy.results.catalog import Catalog

    root = Path(workspace).expanduser().resolve()
    if not catalog_path_for(root).is_file():
        raise FileNotFoundError(
            f"No index at {catalog_path_for(root)}. Run `hmp catalog reindex` first."
        )
    return Catalog(root)


def list_simulations(
    workspace: Any,
    *,
    project: str | None = None,
    solver: str | None = None,
    site: str | None = None,
    status: str | None = None,
    label: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
) -> Any:
    """List the sealed runs of the projects reachable from ``workspace``.

    Iterates over the per-project indexes (``<project>/.hmp/index.duckdb``)
    under ``workspace`` and returns one frame ordered by ``created_at DESC``.
    ``project`` names one project directory; the other filters are exact
    matches on the listed column.
    """
    import pandas as pd

    from hydromodpy.results.catalog import Catalog, iter_project_catalog_roots
    from hydromodpy.results.catalog.constants import canonical_solver_code

    workspace_root = Path(workspace).expanduser().resolve()
    if project:
        project_roots = [workspace_root / "projects" / project]
    else:
        project_roots = iter_project_catalog_roots(workspace_root)

    frames: list[pd.DataFrame] = []
    for project_dir in project_roots:
        if not catalog_path_for(project_dir).is_file():
            continue
        with Catalog(project_dir) as catalog:
            sims = catalog.list_simulations(order_by="created_at DESC")
            tagged = catalog.sims_with_tag(tag) if tag else None
        if sims.empty:
            continue
        if solver:
            sims = sims[sims["solver"].fillna("").str.lower() == canonical_solver_code(solver)]
        if site:
            sims = sims[sims["site"].fillna("") == site]
        if status:
            sims = sims[sims["status"].fillna("") == status]
        if label:
            sims = sims[sims["label"].fillna("") == label]
        if tagged is not None:
            sims = sims[sims["sim_id"].astype(str).isin(tagged)]
        frames.append(sims.assign(project=project_dir.name))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if limit is not None:
        out = out.head(int(limit))
    return _stable_listing_projection(out)


def _stable_listing_projection(df: Any) -> Any:
    """Return a scriptable projection: string ids, ISO dates, no config blob."""
    cols = [c for c in _LISTING_COLUMNS if c in df.columns]
    out = df[cols].copy()
    if "sim_id" in out.columns:
        out["sim_id"] = out["sim_id"].astype(str)
    for time_col in ("created_at", "started_at"):
        if time_col in out.columns:
            out[time_col] = out[time_col].astype(str)
    return out


def show_simulation(sim_ref: str, *, workspace: Any, detail: bool = False) -> dict:
    """Return the facts of one sealed run: its row, its label and its exports.

    Raises ``FileNotFoundError`` without an index and
    :class:`~hydromodpy.results.catalog.SimulationNotFoundError` when
    ``sim_ref`` names nothing.
    """
    from hydromodpy.results.ledger import Ledger
    from hydromodpy.results.storage.contract import RUN_EXPORTS_DIRNAME, RUN_FIGURES_DIRNAME

    with _open_catalog(workspace) as catalog:
        sid = catalog.resolve(sim_ref)
        sim = catalog[sid]
        row = catalog.list_simulations(sim_id=sid).iloc[0].to_dict()
        run_dir = catalog.run_dir_for(sid)
        payload: dict = {
            "sim_id": sim.sim_id,
            "name": sim.name,
            "project": sim.project,
            "site": row.get("site"),
            "case_id": row.get("case_id"),
            "rel_dir": row.get("rel_dir"),
            "solver": sim.solver,
            "status": sim.status,
            "label": row.get("label"),
            "label_date": None if row.get("label_date") is None else str(row["label_date"])[:10],
            "nse": row.get("nse"),
            "duration_s": row.get("duration_s"),
            "n_cells": sim.n_cells,
            "n_timesteps": sim.n_timesteps,
            "version_int": row.get("version_int"),
            "config_hash": row.get("config_hash"),
            "exports": [
                {"file": entry.file, "producer": entry.producer, "sha256": entry.sha256}
                for entry in Ledger.read(run_dir / RUN_EXPORTS_DIRNAME).entries
            ],
            "figures": [
                {"file": entry.file, "producer": entry.producer}
                for entry in Ledger.read(run_dir / RUN_FIGURES_DIRNAME).entries
            ],
        }
        if detail:
            zarr_path = catalog.fields_path_for(sid)
            payload["zarr_path"] = str(zarr_path)
            payload["zarr_exists"] = zarr_path.exists()
            groups: list[str] = []
            if zarr_path.is_dir():
                try:
                    groups = sorted(p.name for p in zarr_path.iterdir() if p.is_dir())[:20]
                except OSError:
                    groups = []
            payload["zarr_groups"] = groups
        return payload


def query_catalog(sql: str, *, workspace: Any, limit: int | None = None) -> Any:
    """Run one read-only SQL statement against the index of a project.

    Raises ``FileNotFoundError`` without an index and ``duckdb.Error`` when
    the statement is refused.
    """
    statement = sql.strip()
    if limit is not None:
        statement = f"SELECT * FROM ({statement}) LIMIT {int(limit)}"
    with _open_catalog(workspace) as catalog:
        return catalog.sql(statement)


def point_simulations(
    sim_refs: list[str],
    *,
    workspace: Any,
    variables: list[str],
    x: float | None = None,
    y: float | None = None,
    cell: int | None = None,
    layer: int | None = None,
    depth: float | None = None,
    label: str | None = None,
    timestep: int | None = None,
    output: Any = None,
) -> Any:
    """Read one variable in one precise cell, on one or several runs.

    ``x, y`` are coordinates in the simulation CRS and exclude ``cell``, a
    zero-based cell index. ``layer`` and ``depth`` (metres below the local
    top) exclude each other. ``output`` is an optional ``.csv`` or
    ``.parquet`` path written with the table.
    """
    from hydromodpy.results.run.point import PointRequest, read_points, write_point_table

    request = PointRequest(x=x, y=y, cell=cell, layer=layer, depth=depth, label=label)
    with _open_catalog(workspace) as catalog:
        runs = [catalog[catalog.resolve(ref)] for ref in sim_refs]
        frame = read_points(runs, variables, request, timestep=timestep)
    if output is not None:
        write_point_table(frame, output)
    return frame


def diff_simulations(ref_a: str, ref_b: str, *, workspace: Any) -> dict:
    """Compare the parameters and metrics of two runs."""
    with _open_catalog(workspace) as catalog:
        return catalog.diff(ref_a, ref_b)


def delete_simulation_artifacts(
    catalog: Any, sid: str, *, force: bool = False
) -> dict[str, object]:
    """Move one run of an open catalog to the project trash and return what moved.

    Used by ``hmp dev manage`` when iterating over the runs of a project. The
    bytes stay in ``trash/`` until ``hmp catalog gc --apply`` frees them.
    """
    from hydromodpy.results.trash import trash_run

    rel_dir = catalog.rel_dir_of(sid)
    run_dir = catalog.project_path / rel_dir
    size = _path_size(run_dir)
    moved = trash_run(catalog.project_path, rel_dir, now=datetime.now(UTC), force=force)
    return {"sim_id": sid, "rel_dir": rel_dir, "trashed_to": str(moved), "bytes": size}


def _path_size(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                total += int(child.stat().st_size)
    except OSError:
        return total
    return total


def reindex_project(workspace: Any, *, incremental: bool = False) -> dict:
    """Rebuild the index of a project, or bring it up to date with ``incremental``.

    Returns ``{"index", "full", "indexed", "sessions", "removed", "skipped",
    "rows"}``. A full rebuild is idempotent: the index is built from what the
    directories declare, so running it twice describes the same project.
    """
    from hydromodpy.results.catalog.indexer import index_new_runs, rebuild_index

    root = Path(workspace).expanduser().resolve()
    report = index_new_runs(root) if incremental else rebuild_index(root)
    return {
        "index": str(report.index_path),
        "full": report.full,
        "indexed": list(report.indexed),
        "sessions": list(report.sessions),
        "removed": list(report.removed),
        "skipped": [{"rel_dir": item.rel_dir, "reason": item.reason} for item in report.skipped],
        "rows": dict(report.rows),
    }


# ---------------------------------------------------------------------------
# Liveness, from the directories
# ---------------------------------------------------------------------------


def _attempt_dirs(project_root: Path) -> list[tuple[str, Path]]:
    """Return ``(rel_dir, path)`` of every directory carrying an outcome."""
    from hydromodpy.results.catalog.indexer import scan_tree

    return [
        (entry.rel_dir, entry.path)
        for entry in scan_tree(project_root).values()
        if entry.kind != "session"
    ]


def watch_running(workspace: Any, *, stale_minutes: float | None = None) -> list[dict]:
    """Return the running attempts of a project with the age of their pulse.

    Reads ``outcome.json`` and ``logs/heartbeat.json`` only, never the index.
    An attempt is ``stale`` when its pulse is older than ``stale_minutes``
    (default :data:`~hydromodpy.results.outcome.DEFAULT_STALE_AFTER_S`),
    which is a display word: only a proven death lets another attempt take
    the directory.
    """
    from hydromodpy.results.heartbeat import read_heartbeat
    from hydromodpy.results.outcome import effective_status, read_outcome
    from hydromodpy.results.storage.json_io import readable

    root = Path(workspace).expanduser().resolve()
    stale_after_s = DEFAULT_STALE_AFTER_S if stale_minutes is None else stale_minutes * 60.0
    now = datetime.now(UTC)
    rows: list[dict] = []
    for rel_dir, path in _attempt_dirs(root):
        status = effective_status(path, now=now, stale_after_s=stale_after_s)
        if status not in ("running", "stale"):
            continue
        outcome = readable(read_outcome, path)
        if outcome is None:
            continue
        beat = readable(read_heartbeat, path)
        age_s = None if beat is None else max(0.0, (now - beat.at).total_seconds())
        rows.append(
            {
                "rel_dir": rel_dir,
                "case_id": outcome.case_id,
                "sim_id": outcome.sim_id,
                "attempt": outcome.attempt,
                "attempt_id": outcome.attempt_id,
                "host": outcome.host,
                "pid": outcome.pid,
                "step": None if beat is None else beat.step or outcome.step,
                "started_at": outcome.started_at,
                "heartbeat_at": None if beat is None else beat.at,
                "age_s": age_s,
                "stale": status == "stale",
            }
        )
    rows.sort(key=lambda row: row["rel_dir"])
    return rows


def stale_running_sim_ids(project_root: Path, minutes: float | None = None) -> list[str]:
    """Return the ``rel_dir`` of every attempt whose pulse is older than ``minutes``."""
    return [
        row["rel_dir"] for row in watch_running(project_root, stale_minutes=minutes) if row["stale"]
    ]


def _session_descriptors(project_root: Path) -> list[tuple[Path, Any]]:
    from hydromodpy.results.session.descriptor import list_session_dirs, read_session
    from hydromodpy.results.storage.json_io import readable_documents

    return list(readable_documents(read_session, list_session_dirs(project_root)))


def abandoned_calibration_session_count(project_root: Path) -> int:
    """Count the sessions still ``running`` more than a day after they started."""
    cutoff = datetime.now(UTC) - timedelta(minutes=ABANDONED_SESSION_MINUTES)
    return sum(
        1
        for _path, descriptor in _session_descriptors(project_root)
        if descriptor.status == "running" and descriptor.started_at < cutoff
    )


def orphan_calibration_session_count(project_root: Path) -> int:
    """Count the sessions whose best run directory no longer exists."""
    root = Path(project_root)
    count = 0
    for _path, descriptor in _session_descriptors(root):
        best = descriptor.best
        if best is not None and best.rel_dir is not None and not (root / best.rel_dir).is_dir():
            count += 1
    return count


__all__ = [
    "ABANDONED_SESSION_MINUTES",
    "abandoned_calibration_session_count",
    "delete_simulation_artifacts",
    "diff_simulations",
    "list_simulations",
    "orphan_calibration_session_count",
    "point_simulations",
    "query_catalog",
    "reindex_project",
    "show_simulation",
    "stale_running_sim_ids",
    "watch_running",
]
