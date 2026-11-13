"""The one door of the figures: a request and a subject in, a figure or its tables out.

``project`` hands ``render`` to ``Run``, ``RunSet`` and ``Session`` through their
``_render`` hook, so ``results`` never imports ``display``. Writing files is the
job of ``output.write``.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import frames, static
from hydromodpy.display.overlays import OVERLAYS
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import (
    AFTER,
    ENGINES,
    FRAMES,
    WHEN,
    ZONE_PREFIX,
    FigureRequest,
    PanelRequest,
    ResolvedFigure,
    expand,
    is_registered,
    shape_of,
)
from hydromodpy.display.subject import FigureNotApplicable, read_mesh
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
    ``facet = "run"`` in this version.

    ``data = True``: returns ``dict[str, pandas.DataFrame]``, the ``table`` of each
    panel's data, keyed ``"a"``, ``"b"``... and ``"a:<facet value>"`` per small
    multiple. Nothing is drawn and no matplotlib object is made.

    ``draw``: calls ``request.draw(subject, ax, theme)`` on one axes of a static
    figure, adding ``station`` and ``time`` from ``draw_keywords`` when the
    function's signature declares them. It returns the figure, and refuses
    ``data = True`` because a function gives no tables.

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
    if figure.draw is not None:
        if data:
            raise DisplayError(
                f"{figure.stem!r} is drawn by a function, which gives no tables. "
                "Ask for the figure, not its data."
            )
        return _draw_function(figure, subject, look)
    cells = _cells(figure, subject)
    loaded = []
    for key, panel, sub in cells:
        module = _frame_module(panel)
        with _panel(key):
            loaded.append((key, panel, sub, module, module.data(sub, panel)))
    if data:
        return {key: found.table for key, _, _, _, found in loaded}
    loaded = _share_limits(loaded)
    columns = min(len(loaded), MAX_COLUMNS)
    fig = static.new_figure(
        look, width=figure.width, nrows=-(-len(loaded) // columns), ncols=columns
    )
    axes = list(fig.axes)
    for spare in axes[len(loaded) :]:
        spare.remove()
    axes = axes[: len(loaded)]
    for ax, (key, panel, sub, module, found) in zip(axes, loaded, strict=True):
        with _panel(key):
            module.draw(ax, found, look)
            for name in panel.overlays or ():
                OVERLAYS[name](ax, sub, look)
        if figure.facet:
            ax.set_title(key.split(":", 1)[1], **static.text_style(look))
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


def _not_ready(what: str, name: str, table: str) -> DisplayError:
    return DisplayError(
        f"The {what} {name!r} is accepted by the request but not drawn in this version. "
        f"Its code comes in a later lot of the figure work, and its flag in {table} "
        "is false until then."
    )


def _check_ready(figure: ResolvedFigure, engine: str) -> None:
    if engine not in ENGINES:
        raise DisplayError(f"Unknown engine {engine!r}. Known engines: {', '.join(ENGINES)}.")
    if not ENGINES[engine].ready:
        raise _not_ready("engine", engine, "request.ENGINES")
    when = AFTER if figure.when.startswith(AFTER) else figure.when
    if not WHEN[when]:
        raise _not_ready("moment", figure.when, "request.WHEN")
    for panel in figure.panels:
        frame = FRAMES[panel.type]
        if not frame.ready:
            raise _not_ready("frame", panel.type, "request.FRAMES")
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
    return importlib.import_module(f"{frames.__name__}.{panel.type}")


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
    raise _not_ready("facet", figure.facet, "the frames of the later lots")


def _cells(figure: ResolvedFigure, subject: Any) -> list[tuple[str, PanelRequest, Any]]:
    """Return one ``(key, panel, subject)`` per drawn panel, small multiples split."""
    if isinstance(subject, RunSet) != (figure.facet == "run"):
        raise DisplayError(
            "A set of runs is drawn with facet = 'run', and facet = 'run' needs a set of runs."
        )
    if isinstance(subject, Session):
        raise DisplayError("A session panel comes with the trial columns of a later lot.")
    letters = [chr(97 + i) for i in range(len(figure.panels))]
    if not figure.facet:
        return [(key, panel, subject) for key, panel in zip(letters, figure.panels, strict=True)]
    (panel,) = figure.panels
    cells = []
    for value in _facet_values(figure, panel, subject):
        if figure.facet == "run":
            cells.append((f"a:{value.dir.name}", panel, value))
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


def _draw_function(figure: ResolvedFigure, subject: Any, theme: Theme) -> Figure:
    declared = inspect.signature(figure.draw).parameters
    takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in declared.values())
    keywords = {
        key: value for key, value in figure.draw_keywords.items() if takes_all or key in declared
    }
    fig = static.new_figure(theme, width=figure.width)
    with _panel("a"):
        figure.draw(subject, fig.axes[0], theme, **keywords)
    if figure.title:
        fig.suptitle(figure.title, **static.text_style(theme, small=False))
    return fig
