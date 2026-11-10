"""List, show, query, point, diff and rank the runs of a project from its index.

``ls``, ``show``, ``query``, ``point``, ``diff`` and ``rank`` read the index
through :class:`~hydromodpy.results.catalog.Catalog`. They sit in a module of
their own so the SQL of a listing stays apart from the reads of the catalog
itself (:mod:`hydromodpy.results.catalog.reads`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.core.state.result_dirs import project_root_at
from hydromodpy.results.storage.run_profile import Profile, read_profile

SEALED_SOLVE_METRIC = "flow_solve_time_seconds"
"""Metric of a 2.0 run that holds the wall time of the solve, in the seal and in ``metrics.parquet``."""

NO_PROFILE_TEXT = "no profile.json, solve time from the seal"
"""What ``show`` says of a run that has no ``profile.json``, a run of HydroModPy 2.0."""

LONGEST_STEPS = 3
"""How many of the longest steps the profile block of ``show`` names."""

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
    "solution_key",
    "request_id",
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
            sims = sims[_runs_with_solver(sims["solver"], solver)]
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


def _runs_with_solver(stored: Any, wanted: str) -> Any:
    """Mask of the runs whose solver list holds ``wanted``, such as "modflow6,modpath".

    The name the run carries is compared as it stands: one name per backend,
    no shorthand.
    """
    return stored.fillna("").map(lambda text: wanted in set(str(text).split(",")))


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


def solve_seconds(run_dir: Path) -> float | None:
    """Return the wall time of the first solve of the run, from its ``profile.json``.

    The plan runs a flow first, so its first ``solve`` line is the flow solve. A
    resumed run has lines in several attempts, and the last attempt that solved
    gives the line. ``None`` when the run has no profile or no finished solve:
    the caller then reads the row a 2.0 run holds (:data:`SEALED_SOLVE_METRIC`).
    """
    profile = read_profile(run_dir)
    if profile is None:
        return None
    return _first_solve_s(profile)


def _first_solve_s(profile: Profile) -> float | None:
    solves = [
        line for line in profile.lines if line.kind == "solve" and line.duration_s is not None
    ]
    if not solves:
        return None
    last = max(line.attempt for line in solves)
    return next(line.duration_s for line in solves if line.attempt == last)


def profile_of_run(run_dir: Path) -> dict[str, Any]:
    """Return what ``show`` says of the time of a run, read from its folder.

    With a ``profile.json`` the dict holds ``present = True``, ``total_s`` (the time of
    every step of every attempt, a rebuilt step included), ``attempts``, ``start_s``
    (the age of the process of the first attempt when its pipeline began),
    ``solve`` (one entry per solve line), ``longest_steps`` (the longest steps that
    were computed or read from the store, rebuilt ones left out), ``reused`` (every line
    not computed, with its source) and ``max_rss_mb``. Without one, ``present`` is
    ``False``, ``message`` is :data:`NO_PROFILE_TEXT` and ``solve_s`` is the row the
    seal of a 2.0 run holds, or ``None``.
    """
    profile = read_profile(run_dir)
    if profile is None:
        return {
            "present": False,
            "message": NO_PROFILE_TEXT,
            "solve_s": _sealed_solve_s(run_dir),
        }
    steps = [line for line in profile.lines if line.kind == "step"]
    computed = [line for line in steps if line.reused != "prefix" and line.duration_s is not None]
    longest = sorted(computed, key=lambda line: line.duration_s, reverse=True)[:LONGEST_STEPS]
    first = min(profile.process_age_s) if profile.process_age_s else None
    peaks = [line.max_rss_mb for line in profile.lines if line.max_rss_mb is not None]
    return {
        "present": True,
        "attempts": len({line.attempt for line in profile.lines}),
        "total_s": sum(line.duration_s or 0.0 for line in steps),
        "start_s": None if first is None else profile.process_age_s[first],
        "solve": [
            {"name": line.name, "attempt": line.attempt, "duration_s": line.duration_s}
            for line in profile.lines
            if line.kind == "solve"
        ],
        "longest_steps": [
            {"name": line.name, "attempt": line.attempt, "duration_s": line.duration_s}
            for line in longest
        ],
        "reused": [
            {"name": line.name, "attempt": line.attempt, "reused": line.reused, "key": line.key}
            for line in profile.lines
            if line.reused != "no"
        ],
        "max_rss_mb": max(peaks) if peaks else None,
    }


def _sealed_solve_s(run_dir: Path) -> float | None:
    """Return the solve time row of the seal of a 2.0 run, ``None`` when it has none."""
    from hydromodpy.results.record.label import read_sealed_manifest

    manifest = read_sealed_manifest(run_dir)
    if manifest is None:
        return None
    return next((row.value for row in manifest.metrics if row.metric == SEALED_SOLVE_METRIC), None)


def show_simulation(sim_ref: str, *, workspace: Any, detail: bool = False) -> dict:
    """Return the facts of one sealed run: its row, its label, its exports and its profile.

    ``profile`` is read from the run folder, not from the index (:func:`profile_of_run`).

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
            "solution_key": row.get("solution_key"),
            "request_id": row.get("request_id"),
            "exports": [
                {"file": entry.file, "producer": entry.producer, "sha256": entry.sha256}
                for entry in Ledger.read(run_dir / RUN_EXPORTS_DIRNAME).entries
            ],
            "figures": [
                {"file": entry.file, "producer": entry.producer}
                for entry in Ledger.read(run_dir / RUN_FIGURES_DIRNAME).entries
            ],
            "profile": profile_of_run(run_dir),
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
    zero-based cell index. ``layer`` and ``depth`` (meters below the local
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


def rank_simulations(
    project: str,
    *,
    workspace: Any = None,
    metric: str = "nse",
    station: str | None = None,
    best: bool = True,
    n: int = 5,
    mixed_windows: bool = False,
) -> Any:
    """Rank the scores of the completed runs of one project. Returns a DataFrame.

    One row per run and station scored on ``metric``, with the window and the
    rule version of the score; ``station`` keeps the rows of one station only.
    ``best=True`` puts the best values first, ``best=False`` the worst ones.
    The direction of the metric comes from
    :data:`hydromodpy.core.scoring.metric_table.METRIC_SENSE`: a metric missing
    from it raises :class:`~hydromodpy.results.catalog.constants.UnrankedMetricError`.
    A missing or non-finite value never ranks. The scores must share one rule
    (station, variable, window, rule version): otherwise
    :class:`~hydromodpy.results.run.sealed.MixedWindowsError` is raised, unless
    ``mixed_windows`` is true.
    """
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.constants import metric_rank_sql
    from hydromodpy.results.metric_rule import HEADLINE_WINDOW
    from hydromodpy.results.run.sealed import METRICS_RULE, check_one_rule

    order = metric_rank_sql(metric, best=best)
    workspace_root = project_root_at(workspace)
    station_clause = "" if station is None else "AND m.station_id = ? "
    with Catalog(workspace_root) as catalog:
        sql = (
            "SELECT s.sim_id, s.name, s.rel_dir, sv.code AS solver, m.station_id AS station, "
            "m.variable, m.metric_name, m.value, m.window_start, m.window_end, "
            "m.metric_rule_version "
            "FROM simulations s "
            "JOIN solvers sv ON s.solver_id = sv.id "
            "JOIN statuses st ON s.status_id = st.id "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND st.code = 'completed' "
            f"AND m.window_name = '{HEADLINE_WINDOW}' "
            f"AND m.metric_name = ? {station_clause}"
            "AND m.value IS NOT NULL AND isfinite(m.value) "
            f"ORDER BY {order}"
        )
        params: list[Any] = [project, metric]
        if station is not None:
            params.append(station)
        frame = catalog.connection.execute(sql, params).fetchdf()
    if not mixed_windows:
        rule = frame.rename(columns={"station": METRICS_RULE.station})
        check_one_rule(
            rule.to_dict("records"),
            metric,
            names=list(frame["rel_dir"]),
            columns=METRICS_RULE,
        )
    return frame.head(int(n)).drop(columns="rel_dir")


__all__ = [
    "diff_simulations",
    "list_simulations",
    "point_simulations",
    "query_catalog",
    "rank_simulations",
    "show_simulation",
]
