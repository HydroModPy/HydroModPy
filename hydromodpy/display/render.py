"""The one door of the figures: a request and a subject in, a figure or its tables out.

``project`` hands ``render`` to ``Run``, ``RunSet`` and ``Session`` through their
``_render`` hook, so ``results`` never imports ``display``. Writing files is the
job of ``output.write``.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import frames, special, static
from hydromodpy.display.overlays import OVERLAYS
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import (
    AFTER,
    ENGINES,
    FRAMES,
    PARAMETER_TOKEN,
    SPECIALS,
    TRIAL_FRAMES,
    TRIALS,
    WHEN,
    ZONE_PREFIX,
    FigureRequest,
    PanelRequest,
    ResolvedFigure,
    expand,
    is_registered,
    is_trial_column,
    shape_of,
)
from hydromodpy.display.subject import (
    AGAINST_RUN_FRAMES,
    PHASE_SEPARATOR,
    Compared,
    FigureNotApplicable,
    compare,
    is_trial_cost,
    read_mesh,
    read_table,
    trial_phases,
)
from hydromodpy.display.theme import Theme, get_theme
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session

MAX_COLUMNS = 3
"""Panels and small multiples sit in one row up to this many, then wrap."""


def render(
    request: FigureRequest | ResolvedFigure,
    subject: Run | RunSet | Session,
    *,
    theme: Theme | str | None = None,
    engine: str | None = None,
    presets: dict[str, FigureRequest] | None = None,
    data: bool = False,
    runs: Mapping[str, Run] | None = None,
) -> Figure | dict[str, pd.DataFrame]:
    """Draw ``request`` from ``subject`` and return the figure, or its tables with ``data``.

    A ``FigureRequest`` is first expanded with ``presets``, by default ``PRESETS``.
    ``theme`` is a ``Theme``, a name of ``THEMES`` or None for ``default``.
    ``engine`` overrides the first engine of the request.

    Static engine: returns a ``matplotlib.figure.Figure`` built by ``static.new_figure``
    at the request width, one axes per panel or small multiple, in one row up to three
    and then on a grid of three columns. For each panel it imports
    ``hydromodpy.display.frames.<type>`` by name from the ``frames`` package, calls
    ``data`` then ``draw``, then each overlay of ``OVERLAYS`` the panel names. A
    shared norm (``share``) sets ``limits`` on every ``MapData`` before drawing.
    Panel labels (a), (b) go on a figure of more than one axes.

    Small multiples: ``facet = "time"`` repeats the panel per instant of its
    ``time`` list, ``"variable"`` per name, ``"layer"`` per layer of ``read_mesh``,
    ``"run"`` per run of a ``RunSet``. A ``RunSet`` subject requires
    ``facet = "run"``.

    ``against = "<run name>"`` on a map subtracts a reference run. A ``RunSet`` holds it, the
    member called so by ``name`` or by directory, and draws one map per other member. A
    ``Run`` takes it from ``runs``, a mapping of names to runs its caller resolved. Runs on
    two meshes are refused.

    A ``Session`` is drawn by ``series``, ``xy`` and ``distribution`` panels of
    ``trials.<column>`` names. ``facet = "parameter"`` replaces ``trials.parameter`` by each
    searched parameter in turn.

    ``data = True``: returns ``dict[str, pandas.DataFrame]``, the ``table`` of each
    panel's data, keyed ``"a"``, ``"b"``... and ``"a:<facet value>"`` per small
    multiple. Nothing is drawn and no matplotlib object is made.

    ``draw``: calls ``request.draw(subject, ax, theme)`` on one axes of a static
    figure, adding ``station`` and ``time`` from ``draw_keywords`` when the
    function's signature declares them. A special figure does the same with the ``draw``
    of the module ``hydromodpy.display.special.<name>``, imported when it draws, after
    the row of ``SPECIALS`` has checked the kind of subject. Both return the figure, and
    refuse ``data = True`` because a drawn function gives no tables.

    Refuses with ``DisplayError`` naming what is missing: a frame whose
    ``Frame.ready`` is false, an engine whose ``Engine.ready`` is false, a ``when``
    whose ``WHEN`` value is false, a subject the frame does not read. Any read that
    fails raises ``FigureNotApplicable`` with the panel letter in its message, and
    the whole figure is refused.
    """
    figure = request
    if isinstance(request, FigureRequest):
        figure = expand(request, PRESETS if presets is None else presets)
    look = theme if isinstance(theme, Theme) else get_theme(theme or "default")
    _check_ready(figure, engine or figure.engine[0])
    if figure.draw is not None or figure.special is not None:
        if data:
            what = "a special figure" if figure.special else "a figure drawn by a function"
            raise DisplayError(
                f"{figure.stem!r} is {what}, and it gives no table of numbers. "
                "Ask for the figure itself."
            )
        return _draw_function(figure, subject, look)
    cells = _cells(figure, subject, runs or {})
    loaded = []
    for key, panel, sub in cells:
        module = _frame_module(panel)
        with _panel(key):
            loaded.append((key, panel, sub, module, module.data(sub, panel)))
    if data:
        return {key: found.table for key, _, _, _, found in loaded}
    loaded = _share_limits(loaded)
    columns = min(len(loaded), MAX_COLUMNS)
    width = "double" if len(loaded) > 1 and figure.width == "single" else figure.width
    fig = static.new_figure(look, width=width, nrows=-(-len(loaded) // columns), ncols=columns)
    axes = list(fig.axes)
    for spare in axes[len(loaded) :]:
        spare.remove()
    axes = axes[: len(loaded)]
    for ax, (key, panel, sub, module, found) in zip(axes, loaded, strict=True):
        with _panel(key):
            module.draw(ax, found, look)
            for name in (panel.overlays or ()) if panel.type == "map" else ():
                OVERLAYS[name](ax, sub.run if isinstance(sub, Compared) else sub, look)
        title = [key.split(":", 1)[1]] if ":" in key else []
        if getattr(found, "trials", None):
            title.append("{} of {} trials".format(*found.trials))
        if title:
            ax.set_title(", ".join(title), **static.text_style(look))
    if len(loaded) > 1:
        static.panel_labels(axes, look)
    if figure.title:
        fig.suptitle(figure.title, **static.text_style(look, small=False))
    return fig


@contextmanager
def _panel(key: str) -> Iterator[None]:
    """Turn a ``FigureNotApplicable`` of one panel into a refusal that names the panel."""
    try:
        yield
    except FigureNotApplicable as error:
        raise FigureNotApplicable(f"Panel {key}: {error}") from error


def _not_drawn(what: str, name: str, instead: str) -> DisplayError:
    return DisplayError(f"The {what} {name!r} is not available. {instead}")


def _check_ready(figure: ResolvedFigure, engine: str) -> None:
    if engine not in ENGINES:
        raise DisplayError(f"Unknown engine {engine!r}. Known engines: {', '.join(ENGINES)}.")
    if not ENGINES[engine].ready:
        ready = [name for name, known in ENGINES.items() if known.ready]
        raise _not_drawn("engine", engine, f"Use engine = {ready[0]!r}.")
    when = AFTER if figure.when.startswith(AFTER) else figure.when
    if not WHEN[when]:
        ready = [name for name, drawn in WHEN.items() if drawn]
        raise _not_drawn("moment", figure.when, f"Use when = {ready[0]!r}.")
    for panel in figure.panels:
        frame = FRAMES[panel.type]
        if not frame.ready:
            ready = [name for name, known in FRAMES.items() if known.ready]
            raise _not_drawn("frame", panel.type, f"Use type = one of {', '.join(ready)}.")
        stations = [panel.station] if isinstance(panel.station, str) else panel.station or []
        zone = any(str(station).startswith(ZONE_PREFIX) for station in stations)
        for name in panel.variable or ():
            if zone and panel.type == "series":
                continue
            if frame.shapes and is_registered(name) and shape_of(name) not in frame.shapes:
                raise DisplayError(
                    f"The frame {panel.type!r} draws the shapes {', '.join(frame.shapes)}, "
                    f"and {name!r} has the shape {shape_of(name)!r}. Write another type."
                )


def _frame_module(panel: PanelRequest) -> ModuleType:
    try:
        return importlib.import_module(f"{frames.__name__}.{panel.type}")
    except ModuleNotFoundError as error:
        if error.name != f"{frames.__name__}.{panel.type}":
            raise
        raise ModuleNotFoundError(
            f"Frame {panel.type!r} has no module in hydromodpy/display/frames/. Add one.",
            name=error.name,
        ) from None


def _facet_values(figure: ResolvedFigure, panel: PanelRequest, subject: Any) -> list[Any]:
    if figure.facet == "time":
        times = panel.time if isinstance(panel.time, list) else [panel.time]
        if None in times:
            raise DisplayError("facet = 'time' needs a list of instants in time.")
        return times
    if figure.facet == "variable":
        return list(panel.variable)
    if figure.facet == "layer":
        return list(range(read_mesh(subject).n_layers))
    if figure.facet == "run":
        return list(subject)
    if figure.facet == "parameter":
        if not isinstance(subject, Session):
            raise DisplayError("facet = 'parameter' draws the searched parameters of a session.")
        names = list(read_table(subject, "bounds").index)
        if not names:
            raise FigureNotApplicable("The session holds no searched parameter.")
        return names
    raise _not_drawn("facet", figure.facet, "Write another facet or none.")


def _check_subject(figure: ResolvedFigure, subject: Any) -> None:
    """Refuse trial columns on a run and any other panel on a session."""
    for panel in figure.panels:
        trials = [name for name in panel.variable or () if is_trial_column(name)]
        if isinstance(subject, Session):
            if panel.type not in TRIAL_FRAMES or len(trials) != len(panel.variable or ()):
                raise DisplayError(
                    f"A session is drawn by {', '.join(TRIAL_FRAMES)} panels of "
                    f"{TRIALS}.<column> names, not by a {panel.type} panel of {panel.variable}."
                )
            if panel.against is not None or figure.facet not in (None, "parameter", "variable"):
                raise DisplayError("A session has no run to subtract and no instant to repeat.")
        elif trials:
            raise DisplayError(f"{', '.join(trials)} are columns of the trials of a session.")


def _reference(members: list[Run], name: str, key: str) -> Run:
    """Return the member of a run set called ``name``, by its name else by its directory."""
    for held in (
        [run for run in members if run.name == name],
        [run for run in members if run.dir.name == name],
    ):
        if len(held) == 1:
            return held[0]
        if held:
            break
    names = ", ".join(sorted(run.name for run in members))
    raise FigureNotApplicable(
        f"Panel {key}: against = {name!r} names {'several runs' if held else 'no run'} of the "
        f"set. Runs held: {names}."
    )


def _compared(panel: PanelRequest, subject: Any, runs: Mapping[str, Run], key: str) -> Any:
    """Return the subject of a map panel that gives a run name to ``against``, else ``subject``."""
    if panel.type not in AGAINST_RUN_FRAMES or panel.against in (None, "observed"):
        return subject
    if panel.against not in runs:
        held = ", ".join(runs) or "none"
        raise FigureNotApplicable(
            f"Panel {key}: against = {panel.against!r} needs that run, and none was given "
            f"under this name. Runs given: {held}. Draw the figure with run.figure."
        )
    with _panel(key):
        return compare(subject, runs[panel.against])


def _by_phase(figure: ResolvedFigure, subject: Any) -> list[tuple[str, PanelRequest, Any]]:
    """Split a lone ``trials.cost`` panel of a session of several phases into one per phase.

    Each phase was scored on its own output, so one axis never carries two costs.
    """
    if not isinstance(subject, Session) or figure.facet or len(figure.panels) != 1:
        return []
    (panel,) = figure.panels
    names = list(panel.variable or ())
    phases = trial_phases(subject) if names and is_trial_cost(names[0]) else []
    if len(phases) < 2 or names != [f"{TRIALS}.cost"]:
        return []
    return [
        (
            f"a:{phase}",
            panel.model_copy(update={"variable": [f"{TRIALS}.cost{PHASE_SEPARATOR}{phase}"]}),
            subject,
        )
        for phase in phases
    ]


def _cells(
    figure: ResolvedFigure, subject: Any, runs: Mapping[str, Run]
) -> list[tuple[str, PanelRequest, Any]]:
    """Return one ``(key, panel, subject)`` per drawn panel, small multiples split."""
    by_run = all(panel.type == "groups" and panel.by == "run" for panel in figure.panels)
    if isinstance(subject, RunSet) != (figure.facet == "run" or by_run):
        raise DisplayError(
            "A set of runs is drawn with facet = 'run' or with groups by = 'run', "
            "and facet = 'run' needs a set of runs."
        )
    _check_subject(figure, subject)
    letters = [chr(97 + i) for i in range(len(figure.panels))]
    phased = _by_phase(figure, subject)
    if phased:
        return phased
    if not figure.facet:
        return [
            (key, panel, _compared(panel, subject, runs, key))
            for key, panel in zip(letters, figure.panels, strict=True)
        ]
    (panel,) = figure.panels
    cells = []
    values = _facet_values(figure, panel, subject)
    reference = None
    if figure.facet == "run" and panel.type in AGAINST_RUN_FRAMES:
        if panel.against not in (None, "observed"):
            reference = _reference(values, panel.against, "a")
    for value in values:
        if figure.facet == "run":
            if reference is not None:
                if value.sim_id != reference.sim_id:
                    with _panel(f"a:{value.dir.name}"):
                        cells.append((f"a:{value.dir.name}", panel, compare(value, reference)))
                continue
            cells.append((f"a:{value.dir.name}", panel, value))
            continue
        if figure.facet == "parameter":
            token = f"{TRIALS}.{PARAMETER_TOKEN}"
            update = {"variable": [n.replace(token, f"{TRIALS}.{value}") for n in panel.variable]}
            if token not in panel.variable:
                raise DisplayError(f"facet = 'parameter' needs {token!r} in variable.")
            cells.append((f"a:{value}", panel.model_copy(update=update), subject))
            continue
        field = {"time": "time", "variable": "variable", "layer": "layer"}[figure.facet]
        update = [value] if field == "variable" else value
        cells.append((f"a:{value}", panel.model_copy(update={field: update}), subject))
    return cells


def _share_limits(loaded: list[tuple]) -> list[tuple]:
    """Give every map of a ``share`` panel the colour limits of all of them."""
    rows = [
        i
        for i, item in enumerate(loaded)
        if item[1].share and hasattr(item[4], "limits") and "value" in item[4].table
    ]
    values = []
    for i in rows:
        found = loaded[i][4]
        column = found.table["value"].to_numpy(float)
        values.append(column[column > 0] if found.log else column[np.isfinite(column)])
    values = np.concatenate(values) if values else np.array([])
    if values.size == 0:
        return loaded
    limits = (float(values.min()), float(values.max()))
    shared = list(loaded)
    for i in rows:
        shared[i] = (*loaded[i][:4], dataclasses.replace(loaded[i][4], limits=limits))
    return shared


SUBJECTS = {"run": Run, "session": Session, "runset": RunSet}
"""The kinds of subject a special figure may read, as ``SPECIALS`` names them."""


def _special_module(name: str) -> ModuleType:
    return importlib.import_module(f"{special.__name__}.{name}")


def _subject_of_special(figure: ResolvedFigure, subject: Any) -> Any:
    """Return the subject a special figure draws, refusing a kind it does not read.

    The row of ``SPECIALS`` gives the kind. A run given to a session figure stands for
    the session that promoted it. A function written in Python takes any subject.
    """
    kind = SPECIALS[figure.special].subject
    if isinstance(subject, SUBJECTS[kind]):
        return subject
    if kind == "session" and isinstance(subject, Run):
        session = Session.of_run(subject)
        if session is not None:
            return session
        raise DisplayError(
            f"{figure.stem!r} draws a calibration session, and the run {subject.name!r} "
            "was not promoted by one. Pass a Session."
        )
    given = next(name for name, cls in SUBJECTS.items() if isinstance(subject, cls))
    raise DisplayError(
        f"{figure.stem!r} draws a {kind}, not a {given}. Pass a {SUBJECTS[kind].__name__}."
    )


def _draw_function(figure: ResolvedFigure, subject: Any, theme: Theme) -> Figure:
    if figure.special is not None:
        subject = _subject_of_special(figure, subject)
        draw = _special_module(figure.special).draw
    else:
        draw = figure.draw
    declared = inspect.signature(draw).parameters
    takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in declared.values())
    keywords = {
        key: value for key, value in figure.draw_keywords.items() if takes_all or key in declared
    }
    fig = static.new_figure(theme, width=figure.width)
    with _panel("a"):
        draw(subject, fig.axes[0], theme, **keywords)
    if figure.title:
        fig.suptitle(figure.title, **static.text_style(theme, small=False))
    return fig
