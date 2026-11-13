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

    from hydromodpy.display.request import FigureRequest


@dataclass(frozen=True, slots=True)
class Shown:
    """One value of ``what``: the subjects it reads, the reader and what it gives."""

    subjects: tuple[str, ...]
    read: Callable[[Any, Mapping[str, Any]], Any]
    gives: str


@dataclass(frozen=True, slots=True)
class Target:
    """What a reference names: the directory, and whether it is a run, a session or the project."""

    directory: Path
    kind: str


def _as_path(ref: str) -> str:
    """Return a reference that is a folder written with a slash as an absolute path."""
    given = Path(ref).expanduser()
    return str(given.resolve()) if "/" in ref and given.is_dir() else ref


def _project_named(workspace: str | None, ref: str) -> Path | None:
    """Return ``projects/<ref>`` of the workspace, when *ref* names one."""
    from hydromodpy.core.state.layout import PROJECTS_DIRNAME
    from hydromodpy.core.workspace.resolve import find_workspace

    if "/" in ref:
        return None
    found = find_workspace(workspace)
    if found is None:
        return None
    candidate = found / PROJECTS_DIRNAME / ref
    return candidate if candidate.is_dir() else None


def _is_a_project(directory: Path) -> bool:
    from hydromodpy.core.state.layout import RUNS_DIRNAME, SESSIONS_DIRNAME, is_project_root

    return (
        is_project_root(directory)
        or (directory / RUNS_DIRNAME).is_dir()
        or (directory / SESSIONS_DIRNAME).is_dir()
    )


def show_target(
    ref: str, root: Path, workspace: str | None = None, *, session_first: bool = False
) -> Target:
    """Return what *ref* names, read from the directories of the project *root*, never from the index.

    A bare name that is no run and no session may be a project under ``projects/``
    of the workspace *workspace* names (the ``-w`` of a command). With
    ``session_first``, a bare name that a session and a run both carry is the
    session. Raises what :func:`hydromodpy.project.api.status` raises when the
    reference names nothing.
    """
    from hydromodpy.core.exceptions import ConfigMissingError, HydroModPyError
    from hydromodpy.project.api import status

    if session_first and "/" not in ref and not ref.startswith("@"):
        from hydromodpy.results.session.descriptor import resolve_session_dir

        try:
            return Target(resolve_session_dir(root, ref), "session")
        except ConfigMissingError:
            pass
    try:
        found = status(_as_path(ref), workspace=root)
    except (HydroModPyError, FileNotFoundError):
        named = _project_named(workspace, ref)
        if named is not None:
            return Target(named, "project")
        raise
    if isinstance(found, list):
        directory = Path(_as_path(ref)).expanduser().resolve()
        if _is_a_project(directory):
            return Target(directory, "project")
        # A run copied out of its project sits in no project: it is its own folder.
        return Target(directory, "run")
    return Target(found.run_dir, found.kind)


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


def _sealed_display(subject: Any) -> Any:
    """Return the ``DisplayConfig`` a run was sealed with, or None for any other subject."""
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import sealed_display_values

    written = sealed_display_values(getattr(subject, "config_snapshot", None))
    if written is None:
        return None
    try:
        return DisplayConfig.model_validate(written)
    except ValueError:
        return None


def project_presets(subject: Any) -> dict[str, FigureRequest]:
    """Return the shipped presets, with the ``[display.presets]`` the run was drawn with.

    A session or a set of runs holds no sealed ``[display]``, so it has the shipped ones.
    """
    from hydromodpy.display.presets import PRESETS

    sealed = _sealed_display(subject)
    return {**PRESETS, **({} if sealed is None else sealed.presets)}


def project_theme(subject: Any) -> str:
    """Return the theme a figure of *subject* takes when none is asked.

    A run takes the ``theme`` of its sealed ``[display]``, else its former ``preset``. A
    session or a set of runs has no sealed ``[display]`` and takes ``default``.
    """
    sealed = _sealed_display(subject)
    return "default" if sealed is None else sealed.theme_name


def takes_request(name: object, presets: Mapping[str, Any], options: Mapping[str, Any]) -> bool:
    """Return whether the figure goes to the request path, else to the registered figures.

    A request given as a mapping, a ``draw`` function, a variable name, a table column
    or a preset name go to the request path, and so does a name both paths know. So
    ``run.figure(name)``, ``session.figure(name)`` and ``hmp show --figure name`` draw the
    preset, not the registered figure of that name. The key ``[display].figures = [name]``
    is the other way in and keeps drawing the registered figure. Any other name is a
    registered figure.
    """
    from hydromodpy.display.request import BUDGET, is_column, is_registered

    if isinstance(name, Mapping) or options.get("draw") is not None:
        return True
    return isinstance(name, str) and (
        name in presets or name == BUDGET or is_column(name) or is_registered(name)
    )


def render(
    subject: Run | Session | RunSet, name: str | Mapping[str, Any], options: Mapping[str, Any]
) -> Figure | Path | dict[str, Any]:
    """Draw the figure *name* of *subject*, or write its report when *name* is ``report``.

    *options* holds ``save`` (a file, or a folder that receives ``<name>.png``),
    ``dpi``, ``time`` and the figure's own options. A figure drawn without
    ``dpi`` keeps the resolution of the figure itself. With ``save`` the figure is
    written and its path comes back, else the figure itself. ``report`` takes
    the options of ``REPORT_OPTIONS`` for a run, and gives the first page of the
    report.

    A variable, a preset, a request given as a mapping or a ``draw`` function go to
    the request path (:func:`takes_request`). With ``data`` it gives the tables.
    """
    given = {key: value for key, value in options.items() if value is not None}
    if name == REPORT:
        return _report(subject, given)
    if takes_request(name, project_presets(subject), given):
        return _render_request(subject, name, given)
    if given.pop("data", False):
        raise CommandUsageError(
            f"{name!r} is a registered figure and gives no tables. Ask for a variable or a preset."
        )
    from hydromodpy.display.runs import render_figure

    save = given.pop("save", None)
    dpi = given.pop("dpi", None)
    # A set of runs has no directory; only a run stamps its identity on the PNG.
    run_dir = getattr(subject, "dir", None) if save is not None else None
    try:
        drawn = render_figure(name, subject, save=save, dpi=dpi, run_dir=run_dir, **given)
    except KeyError as error:
        if str(error).strip("'\"").startswith("unknown figure"):
            raise _unknown_figure(name, project_presets(subject)) from None
        raise
    if save is None:
        return drawn
    target = Path(save).expanduser()
    return target / f"{name}.png" if target.is_dir() else target


def _unknown_figure(name: object, presets: Mapping[str, Any]) -> CommandUsageError:
    """Return the refusal for a name that is no variable, preset or registered figure."""
    import difflib

    from hydromodpy.display.figure_registry import names
    from hydromodpy.display.request import BUDGET
    from hydromodpy.results.field_registry import FIELD_REGISTRY, TIME_SERIES_REGISTRY

    known = [*FIELD_REGISTRY, *TIME_SERIES_REGISTRY, BUDGET, *presets, *names()]
    close = difflib.get_close_matches(str(name), known, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    return CommandUsageError(
        f"Unknown figure {name!r}.{hint} It is not a variable, a preset or a registered figure."
    )


def _write_tables(tables: Mapping[str, Any], stem: str, folder: Path) -> list[Path]:
    """Write each table of a figure as ``<folder>/<stem>_<key>.csv`` and return the paths."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for key, table in tables.items():
        path = folder / f"{stem}_{key.replace(':', '_').replace('/', '_')}.csv"
        table.to_csv(path, index=False)
        paths.append(path)
    return paths


def _against_runs(subject: Any, figure: Any) -> dict[str, Run]:
    """Return the runs of the project of *subject* that the panels of *figure* subtract.

    A name given to ``against`` is a run of the same project, found by its name or by its
    directory. ``observed`` is no run, and a set of runs holds its reference itself.
    """
    names = {p.against for p in figure.panels if p.against not in (None, "observed")}
    if not names or not isinstance(subject, Run):
        return {}
    from hydromodpy.project.facade import open_project

    found = project_root_of(subject.dir)
    if found is None:
        raise CommandUsageError(
            f"against = {sorted(names)} names a run of the project, and the run in "
            f"{subject.dir} sits in no project."
        )
    held = list(open_project(found[0]).runs())
    resolved: dict[str, Run] = {}
    for name in sorted(names):
        hit = [run for run in held if name in (run.name, run.dir.name)]
        if not hit:
            known = ", ".join(sorted(run.name for run in held))
            raise CommandUsageError(f"against = {name!r} is no run of the project. Runs: {known}.")
        resolved[name] = hit[0]
    return resolved


def _render_request(
    subject: Any, name: str | Mapping[str, Any], given: dict[str, Any]
) -> Figure | Path | dict[str, Any]:
    """Draw a request: expand it once, render it, and write it when ``save`` is given."""
    from dataclasses import replace

    from hydromodpy.display.output import write
    from hydromodpy.display.render import render as render_figure
    from hydromodpy.display.request import ENGINES, FORMATS, FigureRequest, expand, request_of
    from hydromodpy.display.theme import get_theme

    save = given.pop("save", None)
    dpi = given.pop("dpi", None)
    theme = given.pop("theme", None) or project_theme(subject)
    engine = given.pop("engine", None)
    data = bool(given.pop("data", False))
    data_dir = given.pop("data_dir", None)
    draw = given.pop("draw", None)
    presets = project_presets(subject)
    if isinstance(name, str):
        if draw is not None:
            raise CommandUsageError("Give a figure name or a draw function, not both.")
        request = request_of(name, presets, **given)
    else:
        request = FigureRequest.model_validate(
            {**name, **given, **({} if draw is None else {"draw": draw})}
        )
    if engine is not None and engine not in ENGINES:
        raise CommandUsageError(f"engine={engine!r} is not one of {', '.join(ENGINES)}.")
    figure = expand(request, presets)
    if data:
        tables = render_figure(
            figure,
            subject,
            theme=theme,
            engine=engine,
            data=True,
            runs=_against_runs(subject, figure),
        )
        return tables if data_dir is None else _write_tables(tables, figure.stem, Path(data_dir))
    chosen = get_theme(theme) if isinstance(theme, str) else theme
    if dpi is not None:
        chosen = replace(chosen or get_theme("default"), dpi=int(dpi))
    drawn = render_figure(
        figure, subject, theme=chosen, engine=engine, runs=_against_runs(subject, figure)
    )
    if save is None:
        return drawn
    target = Path(save).expanduser()
    directory = target if target.is_dir() or target.suffix == "" else target.parent
    if directory is not target:
        suffix = target.suffix.lstrip(".").lower()
        if suffix not in FORMATS:
            raise CommandUsageError(
                f"save = {str(save)!r}: a figure is written as {', '.join(FORMATS)}, not {suffix!r}."
            )
        figure = replace(figure, stem=target.stem, formats=(suffix,))
    run = subject if isinstance(subject, Run) else None
    return write(drawn, figure, run, directory, chosen or get_theme("default"))[0]


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
