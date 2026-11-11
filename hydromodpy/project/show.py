"""What ``show`` reads, one line per value of ``what``, and the function that draws.

:data:`SHOWN` is the table of the verb :func:`hydromodpy.project.api.show`. Each
line names the subjects it reads (a run, a session, a set of runs, a project),
the function that reads and what it gives. ``ShowWhat`` is made from the keys
of the table, so a new line is a new value of ``what`` and nothing else.

:func:`render` draws one figure, or writes the report, of a run, a session or a
set of runs. ``open`` gives it to the objects it opens, so ``Run.figure`` and
``show(..., what="figure")`` have one body. The objects live in ``results``,
under ``display`` and ``project``, and read neither: they call what they were
given. This module imports neither ``project.facade`` nor ``display`` at its top,
so the facade can import :func:`render` from here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from hydromodpy.core.exceptions import CommandUsageError, NothingThereError
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import REPORT, REPORT_OPTIONS, Run, project_root_of
from hydromodpy.results.session.view import Session

if TYPE_CHECKING:
    from matplotlib.figure import Figure


@dataclass(frozen=True, slots=True)
class Shown:
    """One value of ``what``: the subjects it reads, the reader and what it gives."""

    subjects: tuple[str, ...]
    read: Callable[[Any, Mapping[str, Any]], Any]
    gives: str


def kind_of(subject: object) -> str:
    """Return what *subject* is for :data:`SHOWN`: run, session, set, project or its type."""
    from hydromodpy.project.facade import Project

    if isinstance(subject, Run):
        return "run"
    if isinstance(subject, Session):
        return "session"
    if isinstance(subject, RunSet):
        return "set"
    if isinstance(subject, Project):
        return "project"
    return type(subject).__name__


def render(subject: Run | Session | RunSet, name: str, options: Mapping[str, Any]) -> Figure | Path:
    """Draw the figure *name* of *subject*, or write its report when *name* is ``report``.

    *options* holds ``save`` (a file, or a folder that receives ``<name>.png``),
    ``dpi``, ``time`` and the figure's own options. A figure drawn without
    ``dpi`` keeps the resolution of the figure itself. With ``save`` the figure is
    written and its path comes back, else the figure itself. ``report`` takes
    the options of ``REPORT_OPTIONS`` for a run, and gives the first page of the
    report.
    """
    given = {key: value for key, value in options.items() if value is not None}
    if name == REPORT:
        return _report(subject, given)
    from hydromodpy.display.runs import render_figure

    save = given.pop("save", None)
    dpi = given.pop("dpi", None)
    # A set of runs has no directory; only a run stamps its identity on the PNG.
    run_dir = getattr(subject, "dir", None) if save is not None else None
    drawn = render_figure(name, subject, save=save, dpi=dpi, run_dir=run_dir, **given)
    if save is None:
        return drawn
    target = Path(save).expanduser()
    return target / f"{name}.png" if target.is_dir() else target


def _report(subject: Any, options: Mapping[str, Any]) -> Path:
    from hydromodpy.project.report import report_run, report_session

    if isinstance(subject, Session):
        return report_session(subject.dir)
    if not isinstance(subject, Run):
        raise CommandUsageError(
            f"A report is written for a run or a session, not a {kind_of(subject)}."
        )
    named = {key: options[key] for key in REPORT_OPTIONS if key in options}
    return report_run(subject.dir, **named)


def project_summary(project_root: Path) -> dict[str, Any]:
    """Return what a project holds, read from its directories and never from the index.

    The counts come from ``runs/``, ``sessions/``, ``plan/``, ``summary/`` and
    ``trash/``; the index is only said present or missing.
    """
    from collections import Counter

    from hydromodpy.core.state.layout import (
        PROJECT_MARKER_FILENAME,
        catalog_path_for,
        summary_dir_for,
    )
    from hydromodpy.results.catalog.indexer import scan_tree
    from hydromodpy.results.outcome import effective_status
    from hydromodpy.results.plan_store import current_plan_hash
    from hydromodpy.results.session.descriptor import list_session_dirs, read_session
    from hydromodpy.results.storage.json_io import readable
    from hydromodpy.results.trash import list_trash

    root = Path(project_root)
    entries = scan_tree(root)
    runs = Counter(effective_status(e.path) for e in entries.values() if e.kind == "run")
    n_trials = sum(1 for e in entries.values() if e.kind == "trial")
    descriptors = (readable(read_session, path) for path in list_session_dirs(root))
    sessions = Counter("unreadable" if each is None else each.status for each in descriptors)
    return {
        "name": root.name,
        "path": str(root),
        "has_project_toml": (root / PROJECT_MARKER_FILENAME).is_file(),
        "configs": sorted(
            path.name for path in root.glob("*.toml") if path.name != PROJECT_MARKER_FILENAME
        ),
        "n_runs": sum(runs.values()),
        "runs": dict(sorted(runs.items())),
        "n_sessions": sum(sessions.values()),
        "sessions": dict(sorted(sessions.items())),
        "n_trials": n_trials,
        "plan": current_plan_hash(root),
        "has_summary": summary_dir_for(root).is_dir(),
        "n_trashed": len(list_trash(root)),
        "has_index": catalog_path_for(root).is_file(),
    }


def _project_of_run(run: Run, what: str) -> Path:
    located = project_root_of(run.dir)
    if located is None:
        raise NothingThereError(
            f"{run.dir} sits in no project, and {what} reads the index of its project."
        )
    return located[0]


def _summary(subject: Any, options: Mapping[str, Any]) -> dict[str, Any]:
    kind = kind_of(subject)
    if kind == "project":
        return project_summary(subject.root)
    if kind == "session":
        from hydromodpy.results.session.summary import session_summary

        summary = session_summary(subject)
        payload = asdict(summary)
        payload["report"] = None if summary.report is None else str(summary.report)
        return payload
    from hydromodpy.results.catalog.discovery import SimulationNotFoundError
    from hydromodpy.results.catalog.indexer import index_after_run
    from hydromodpy.results.catalog.listing import (
        copy_entries,
        delivery_entries,
        profile_of_run,
        show_simulation,
    )

    located = project_root_of(subject.dir)
    if located is None:
        # A run copied out of its project has no index: its folder says the rest.
        return {
            "sim_id": subject.sim_id,
            "name": subject.dir.name,
            "rel_dir": None,
            "deliveries": delivery_entries(subject.dir),
            "copies": copy_entries(subject.dir),
            "profile": profile_of_run(subject.dir),
        }
    workspace = located[0]
    detail = bool(options.get("detail"))
    try:
        return show_simulation(subject.sim_id, workspace=workspace, detail=detail)
    except SimulationNotFoundError:
        # The disk is the truth: a sealed run the index has not met yet is indexed now.
        index_after_run(workspace)
        return show_simulation(subject.sim_id, workspace=workspace, detail=detail)


def _profile(subject: Any, options: Mapping[str, Any]) -> Any:
    return subject.show("profile")


def _named(options: Mapping[str, Any], what: str, of: str) -> Any:
    name = options.get("name")
    if name is None:
        raise CommandUsageError(f"show(what={what!r}) needs name=, {of}.")
    return name


def _table(subject: Any, options: Mapping[str, Any]) -> Any:
    name = _named(options, "table", "the table to read")
    return subject.table(name)


def _read(subject: Any, options: Mapping[str, Any]) -> Any:
    name = _named(options, "field", "the variable to read")
    return subject.read(
        name,
        time=options.get("time"),
        layer=options.get("layer"),
        sel=options.get("sel"),
        bbox=options.get("bbox"),
    )


def _point(subject: Any, options: Mapping[str, Any]) -> Any:
    from hydromodpy.results.catalog.listing import point_simulations

    named = _named(options, "point", "the variable or variables to read")
    place = dict(options.get("point") or {})
    unknown = sorted(set(place) - {"x", "y", "cell", "depth", "label"})
    if unknown:
        raise CommandUsageError(
            f"point= takes x, y, cell, depth and label, not {', '.join(unknown)}."
        )
    return point_simulations(
        [subject.sim_id],
        workspace=_project_of_run(subject, "a point"),
        variables=[named] if isinstance(named, str) else list(named),
        layer=options.get("layer"),
        timestep=options.get("time"),
        **place,
    )


def _rank(subject: Any, options: Mapping[str, Any]) -> Any:
    from hydromodpy.results.catalog.listing import rank_simulations

    limit = options.get("limit")
    return rank_simulations(
        subject.root.name,
        workspace=subject.root,
        metric=options.get("metric") or "nse",
        station=options.get("station"),
        best=bool(options.get("best", True)),
        n=5 if limit is None else int(limit),
        mixed_windows=bool(options.get("mixed_windows")),
    )


def _figure(subject: Any, options: Mapping[str, Any]) -> Any:
    name = _named(options, "figure", "the figure to draw")
    drawn = {
        **dict(options.get("options") or {}),
        "save": options.get("save"),
        "dpi": options.get("dpi"),
        "time": options.get("time"),
    }
    return render(subject, name, drawn)


def _report_of(subject: Any, options: Mapping[str, Any]) -> Any:
    return render(subject, REPORT, {**dict(options.get("options") or {}), **options})


SHOWN: dict[str, Shown] = {
    "summary": Shown(("run", "session", "project"), _summary, "dict"),
    "profile": Shown(("run", "session"), _profile, "dict for a run, DataFrame for a session"),
    "table": Shown(("run", "session", "set"), _table, "DataFrame"),
    "field": Shown(("run",), _read, "DataArray"),
    "series": Shown(("run",), _read, "Series"),
    "point": Shown(("run",), _point, "DataFrame"),
    "rank": Shown(("project",), _rank, "DataFrame"),
    "figure": Shown(("run", "session", "set"), _figure, "Figure, or Path with save"),
    "report": Shown(("run", "session"), _report_of, "Path"),
}
"""What ``show`` reads: one line per value of ``what``."""

ShowWhat = Literal[tuple(SHOWN)]  # type: ignore[valid-type]
"""The values of ``what``, made from the keys of :data:`SHOWN`."""

_WRITES_ITSELF: Final[frozenset[str]] = frozenset({"figure", "report"})


def shown(subject: Any, what: str, options: Mapping[str, Any]) -> Any:
    """Return what *subject* shows for *what*, or the file it was written to with ``save``.

    Raises
    ------
    CommandUsageError
        When *what* is no line of :data:`SHOWN`, or names a line the subject
        does not have. The message names the values the subject takes.
    """
    line = SHOWN.get(what)
    if line is None:
        raise CommandUsageError(f"what={what!r} is not one of {', '.join(SHOWN)}.")
    kind = kind_of(subject)
    if kind not in line.subjects:
        allowed = [key for key, each in SHOWN.items() if kind in each.subjects]
        takes = ", ".join(allowed) if allowed else "nothing"
        raise CommandUsageError(
            f"show(what={what!r}) reads a {' or a '.join(line.subjects)}, not a {kind}. "
            f"A {kind} shows {takes}."
        )
    value = line.read(subject, options)
    save = options.get("save")
    if save is None or what in _WRITES_ITSELF:
        return value
    return write_shown(value, save)


def write_shown(value: Any, path: str | Path) -> Path:
    """Write what ``show`` read to *path*, by its suffix, and return the path.

    A mapping is written as JSON. A table is written as ``.csv`` or ``.parquet``,
    a geographic table also as ``.gpkg`` or ``.geojson``. A field is written as
    ``.nc``, or as a table.
    """
    import pandas as pd
    import xarray as xr

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    if isinstance(value, Mapping):
        target.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
        return target
    if isinstance(value, xr.DataArray):
        if suffix == ".nc":
            value.to_netcdf(target)
            return target
        value = value.to_dataframe()
    if isinstance(value, pd.Series):
        value = value.to_frame()
    if isinstance(value, pd.DataFrame):
        if suffix in (".gpkg", ".geojson") and hasattr(value, "to_file"):
            value.to_file(target)
            return target
        index = not isinstance(value.index, pd.RangeIndex)
        if suffix == ".parquet":
            value.to_parquet(target, index=index)
            return target
        if suffix == ".csv":
            value.to_csv(target, index=index)
            return target
    raise CommandUsageError(
        f"save={str(target)!r} cannot hold a {type(value).__name__}: a table is written "
        "as .csv or .parquet, a geographic table also as .gpkg or .geojson, a field as "
        ".nc, and a summary as .json."
    )
