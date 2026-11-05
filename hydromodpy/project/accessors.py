"""Read-only views of a project, its sessions and its workspace.

Split from :mod:`hydromodpy.project.facade` to keep the facade focused on
its verbs. ``project.data`` and ``project.runs`` are accessor objects; the
campaign reads of :class:`~hydromodpy.project.Project` (``cases``,
``sites``, ``best``) are the functions below, applied to the index of the
project; ``project.sessions`` is :class:`ProjectSessions`; a workspace root
opened by ``hmp.open`` or ``hmp.index`` is a :class:`Workspace`.

Everything here reads. The index is derived from the run directories, so a
reader that wants it current refreshes it first
(:func:`hydromodpy.results.catalog.indexer.index_new_runs`); the facade does
that before handing the index over.
"""

from __future__ import annotations

import builtins
import dataclasses
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    is_workspace_root,
    project_roots_under,
    sessions_dir_for,
)
from hydromodpy.results.catalog.constants import metric_sense
from hydromodpy.results.plan_store import current_plan_hash, read_plan
from hydromodpy.results.session.descriptor import list_session_dirs
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.validity_rules import CALIBRATED_LABELS

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.project.facade import Project
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run
    from hydromodpy.results.run.group import RunSet

logger = get_logger(__name__)

CASE_KINDS: tuple[str, ...] = ("run", "session")
"""Kinds of result directory that stand for a case; a kept trial is not one."""


class ProjectDataAccessor:
    """Helper exposed as ``project.data``.

    Lists input-data cache entries used by the project and reports missing variables.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def list(self, variable: str | None = None) -> pd.DataFrame:
        loaded = self._project.data_loaded
        if variable is not None:
            loaded = {v for v in loaded if v == variable}
        return pd.DataFrame({"variable": sorted(loaded)})

    def missing(self) -> builtins.list[str]:
        plan_types = getattr(self._project._ctx.data_plan, "types", ()) or ()
        loaded = self._project.data_loaded
        return [t for t in plan_types if t not in loaded]


class ProjectRunsAccessor:
    """Helper exposed as ``project.runs``.

    Called, it gives the completed runs of the project as a
    :class:`~hydromodpy.results.run.group.RunSet`: ``project.runs(site="J0014010")``.
    Its methods are thin wrappers around the index
    :class:`~hydromodpy.results.catalog.Catalog` that pre-filter queries by
    the current project name.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def __call__(
        self,
        *,
        site: str | None = None,
        case: str | None = None,
        recipe: str | None = None,
        label: str | None = None,
    ) -> RunSet:
        """Return the completed runs of the project, newest first, narrowed by each filter.

        A run is a directory under ``runs/``; the trials a session kept are
        read through ``project.sessions``. The metrics of the set
        (``RunSet.metrics``) are named by the metric alone and carry the
        window they were scored on.
        """
        from hydromodpy.results.run.group import RunSet

        store = self._project._store
        frame = case_rows(store)
        frame = frame[(frame["kind"] == "run") & (frame["status"] == "completed")]
        for column, value in (("site", site), ("case_id", case), ("recipe", recipe)):
            if value is not None:
                frame = frame[frame[column] == value]
        if label is not None:
            frame = frame[frame["label"] == label]
        return RunSet([str(sid) for sid in frame["sim_id"]], store)

    def list(self) -> pd.DataFrame:
        store = self._project._store
        if store is None:
            return pd.DataFrame()
        return store.list_simulations(project=self._project._project_name)

    def find(self, **filters: Any) -> builtins.list[Run]:
        store = self._project._store
        if store is None:
            return []
        return store.find(project=self._project._project_name, **filters)

    def latest(self) -> Run | None:
        df = self.list()
        if df.empty:
            return None
        return self._project._store[df.iloc[-1]["sim_id"]]

    def best(self, metric: str, *, mixed_windows: bool = False) -> Run | None:
        """Return the completed run of the project with the best ``metric``, ``None`` without index.

        Runs scored under different rules (station, variable, window or rule
        version) are refused with
        :class:`~hydromodpy.results.run.sealed.MixedWindowsError` unless
        ``mixed_windows`` is true.
        """
        store = self._project._store
        if store is None:
            return None
        return store.best(self._project._project_name, metric=metric, mixed_windows=mixed_windows)

    def delete(self, sim_id: str, *, remove_storage: bool = True) -> None:
        """Delete a simulation from the catalog (and optionally its artifacts)."""
        store = self._project._store
        if store is None:
            return
        store.delete(sim_id, remove_storage=remove_storage)


# -- Campaign reads ------------------------------------------------------------


def case_rows(catalog: Catalog) -> pd.DataFrame:
    """Return the rows of ``v_cases`` that stand for a case: runs and sessions."""
    frame = catalog.cases
    return frame[frame["kind"].isin(CASE_KINDS)].reset_index(drop=True)


def cases_frame(catalog: Catalog, project_root: Path) -> pd.DataFrame:
    """Return the cases of a project: the plan joined to what the disk says.

    Without a plan, every run and session of the index, one row each. With a
    plan, every case of the current plan first, with its status from
    :func:`hydromodpy.project.launch.project_status` (planned, invalid,
    skipped and stale_plan included), then the sealed facts, the label, the
    headline metric and the global parameters of the directory that holds it
    (the promoted run of a calibration once its session completed); the
    result directories of cases the plan does not hold follow.
    """
    rows = case_rows(catalog)
    if current_plan_hash(project_root) is None:
        return rows
    from hydromodpy.project.launch import project_status

    status = pd.DataFrame(
        [dataclasses.asdict(row) for row in project_status(project_root).rows],
        columns=["case_id", "site", "recipe", "status", "rel_dir"],
    )
    facts = rows.drop(columns=["case_id", "site", "recipe", "status"])
    # rel_dir is the key of v_cases, never empty: a case without directory gets no facts.
    planned = status.merge(facts, on="rel_dir", how="left")
    others = rows[~rows["case_id"].isin(status["case_id"])]
    if others.empty:
        return planned
    return pd.concat([planned, others], ignore_index=True)


def sites_frame(catalog: Catalog, project_root: Path) -> gpd.GeoDataFrame:
    """Return the sites of a project, one row each, with their outlet as a point.

    A project with a plan reads the site table the plan resolved; any other
    reads the sites its runs and sessions name. The outlet is the point of
    ``x_outlet`` and ``y_outlet``, in the ``crs`` the rows carry, else in the
    ``[geographic] crs_project`` of ``project.toml``.
    """
    import geopandas as gpd

    stored = readable(read_plan, project_root) if current_plan_hash(project_root) else None
    frame = catalog.sites if stored is None else stored.sites.to_pandas()
    if not {"x_outlet", "y_outlet"} <= set(frame.columns):
        return gpd.GeoDataFrame(frame)
    x = pd.to_numeric(frame["x_outlet"], errors="coerce")
    y = pd.to_numeric(frame["y_outlet"], errors="coerce")
    return gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(x, y), crs=_sites_crs(frame, project_root)
    )


def _sites_crs(frame: pd.DataFrame, project_root: Path) -> str | None:
    """Return the one CRS the site rows carry, else the CRS of the project file."""
    if "crs" in frame.columns:
        declared = {str(value) for value in frame["crs"].dropna()}
        if len(declared) == 1:
            return declared.pop()
        if len(declared) > 1:
            raise ValueError(
                f"the sites carry {len(declared)} CRS ({', '.join(sorted(declared))}); "
                "read the table without a geometry, or write one crs for every site"
            )
    marker = project_root / PROJECT_MARKER_FILENAME
    if not marker.is_file():
        return None
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    geographic = load_toml_with_base_config(marker).get("geographic")
    crs = geographic.get("crs_project") if isinstance(geographic, Mapping) else None
    return None if crs is None else str(crs)


def best_frame(
    catalog: Catalog,
    metric: str = "nse",
    *,
    by: Literal["site", "recipe"] | None = "site",
    label: str | Sequence[str] | None = CALIBRATED_LABELS,
    mixed_windows: bool = False,
) -> pd.DataFrame:
    """Return the best completed run of each group, one row per group.

    The metric is read at the gauge of each run, in the window of its rule
    (``RunSet.metrics``); best follows its direction. ``label`` keeps the
    runs of that label, or of those labels, only: the calibrated runs by
    default, ``calibrated`` and ``evaluated`` (an evaluated run is a calibrated
    run scored out of its calibration window); ``None`` ranks every completed
    run. Runs of one group scored under different rules are
    refused with :class:`~hydromodpy.results.run.sealed.MixedWindowsError`
    unless ``mixed_windows`` is true.

    The frame carries the group column, ``case_id``, ``rel_dir``,
    ``sim_id``, ``label``, the global parameters of the run, the metric
    under its own name, and the window it was scored on
    (``window_start``, ``window_end``, ``station``).

    A group of completed runs that yields no row is named once in a
    warning of the logger, with the reason: no run scored (no ``[metrics]
    window``), none with the metric, or none of ``label``.
    """
    from hydromodpy.results.run.group import RunSet

    metric_sense(metric)
    rows = case_rows(catalog)
    rows = rows[(rows["kind"] == "run") & (rows["status"] == "completed")]
    if rows.empty:
        logger.warning("best(%r): no completed run in the index of this project.", metric)
    labels = (label,) if isinstance(label, str) else tuple(label or ())
    out: list[dict[str, Any]] = []
    left_out: list[tuple[str, pd.DataFrame, bool]] = []
    for key, completed in _groups_of(rows, by):
        group = completed if label is None else completed[completed["label"].isin(labels)]
        sim_ids = [str(sid) for sid in group["sim_id"]]
        ranked = RunSet(sim_ids, catalog).compare(metric, mixed_windows=mixed_windows)
        if ranked.empty:
            every = [str(sid) for sid in completed["sim_id"]]
            scored = not RunSet(every, catalog).compare(metric, mixed_windows=True).empty
            name = "the project" if by is None else f"no {by}" if key is None else str(key)
            left_out.append((name, completed, scored))
            continue
        top = ranked.iloc[0]
        case = group[group["sim_id"].astype(str) == str(top["sim_id"])].iloc[0]
        row: dict[str, Any] = {} if by is None else {by: key}
        row.update(
            case_id=case["case_id"],
            rel_dir=case["rel_dir"],
            sim_id=str(top["sim_id"]),
            label=case["label"],
        )
        row.update(_parameters_of(case))
        row.update(
            {
                metric: top["value"],
                "station": top["station"],
                "window_start": top["window_start"],
                "window_end": top["window_end"],
            }
        )
        out.append(row)
    _warn_left_out(metric, left_out, " or ".join(labels))
    return pd.DataFrame(out)


def _groups_of(
    rows: pd.DataFrame, by: Literal["site", "recipe"] | None
) -> list[tuple[str | None, pd.DataFrame]]:
    """Return the rows of each value of *by*, by name, then the rows with no value under ``None``."""
    if by is None:
        return [(None, rows)]
    missing = rows[by].isna()
    groups: list[tuple[str | None, pd.DataFrame]] = [
        (str(key), group) for key, group in rows[~missing].groupby(by, sort=True)
    ]
    return [*groups, (None, rows[missing])] if missing.any() else groups


def _warn_left_out(metric: str, left_out: list[tuple[str, pd.DataFrame, bool]], label: str) -> None:
    """Name once the groups :func:`best_frame` left out, by reason."""
    from hydromodpy.results.run.ranking import names_text, unscored_reason

    unscored = [(name, frame) for name, frame, scored in left_out if not scored]
    reasons: list[str] = []
    if unscored:
        names = names_text([name for name, _ in unscored])
        frame = pd.concat([frame for _, frame in unscored], ignore_index=True)
        reasons.append(unscored_reason(names, frame, metric))
    unlabelled = [name for name, _, scored in left_out if scored]
    if unlabelled:
        reasons.append(
            f"no {label} run of {names_text(unlabelled)} is scored; label=None ranks every "
            "completed run"
        )
    if reasons:
        logger.warning("best(%r): %s.", metric, "; ".join(reasons))


def _parameters_of(case: pd.Series) -> dict[str, Any]:
    """Return the global parameter columns ``v_cases`` adds after its fixed columns."""
    from hydromodpy.results.catalog.views import V_CASES_FIXED_COLUMNS

    fixed = set(V_CASES_FIXED_COLUMNS)
    return {name: case[name] for name in case.index if name not in fixed}


# -- Sessions -------------------------------------------------------------------


class ProjectSessions(Mapping[str, Session]):
    """The calibration sessions of a project, by directory name.

    ``project.sessions["J0014010-calage"]`` is the session directory of that
    name, or, for a case calibrated more than once, its newest version
    (``J0014010-calage.v3``). Iterating gives the directory names.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = Path(project_root)

    def _names(self) -> list[str]:
        return [directory.name for directory in list_session_dirs(self._root)]

    def __getitem__(self, name: str) -> Session:
        from hydromodpy.results.catalog.registration import split_stem_version

        names = self._names()
        if name in names:
            return Session(sessions_dir_for(self._root) / name)
        versions = [
            (version or 1, candidate)
            for candidate in names
            for stem, version in [split_stem_version(candidate)]
            if stem == name
        ]
        if not versions:
            held = ", ".join(names) or "none"
            raise KeyError(f"no calibration session {name!r} in {self._root}: {held}")
        return Session(sessions_dir_for(self._root) / max(versions)[1])

    def __iter__(self) -> Iterator[str]:
        return iter(self._names())

    def __len__(self) -> int:
        return len(self._names())

    def __repr__(self) -> str:
        return f"ProjectSessions({self._names()!r})"


# -- Workspace ------------------------------------------------------------------


class Workspace:
    """Read-only view of a workspace: its projects and the sealed runs they hold.

    The runs are read from the ``tables.parquet/simulation.parquet`` row each
    sealed run carries (:func:`hydromodpy.results.catalog.federation.read_workspace_runs`),
    so no project index is needed. ``workspace["<project>"]`` opens one
    project as ``hmp.open`` does.

    Parameters
    ----------
    root
        The workspace root, the folder of ``workspace.toml`` or of ``projects/``.

    Raises
    ------
    FileNotFoundError
        If ``root`` holds neither ``workspace.toml`` nor ``projects/``.
    """

    def __init__(self, root: str | Path) -> None:
        resolved = Path(root).expanduser().resolve()
        if not is_workspace_root(resolved):
            raise FileNotFoundError(
                f"{resolved} is not a workspace: it holds neither workspace.toml nor "
                f"{PROJECTS_DIRNAME}/"
            )
        self._root = resolved

    @property
    def root(self) -> Path:
        """The workspace root."""
        return self._root

    @property
    def projects(self) -> builtins.list[str]:
        """Names of the projects of the workspace, by name."""
        return [path.name for path in project_roots_under(self._root) if path != self._root]

    def __getitem__(self, name: str) -> Project:
        from hydromodpy.project.opening import open_project

        target = self._root / PROJECTS_DIRNAME / name
        if name not in self.projects:
            held = ", ".join(self.projects) or "none"
            raise KeyError(f"no project {name!r} in {self._root}: {held}")
        return open_project(target)

    def runs(self, *, site: str | None = None, project: str | None = None) -> pd.DataFrame:
        """Return the sealed runs of every project, one row each, narrowed by each filter.

        Columns are those of ``simulation.parquet`` plus ``project_root``.
        The label is computed by a project index, so it is not a column here.
        """
        from hydromodpy.results.catalog.federation import PROJECT_ROOT_COLUMN, read_workspace_runs

        frame = read_workspace_runs(self._root)
        if frame.empty:
            return frame
        if site is not None:
            frame = frame[frame["site"] == site]
        if project is not None:
            wanted = str((self._root / PROJECTS_DIRNAME / project).resolve())
            frame = frame[frame[PROJECT_ROOT_COLUMN] == wanted]
        return frame.reset_index(drop=True)

    def __repr__(self) -> str:
        return f"Workspace({str(self._root)!r}, projects={len(self.projects)})"


__all__ = [
    "CASE_KINDS",
    "ProjectDataAccessor",
    "ProjectRunsAccessor",
    "ProjectSessions",
    "Workspace",
    "best_frame",
    "case_rows",
    "cases_frame",
    "sites_frame",
]
