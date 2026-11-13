"""Figure requests: what a figure shows, in the same words for TOML, the CLI and Python.

A figure is a short list of panels. A panel names a frame and the variables it
receives. A request names one variable, a preset, a list of panels or a Python
function. ``expand`` turns it into its panels with every hole filled, and nothing
here reads a run.

A preset is a request whose panels list their ``holes``: the panel fields a user may
give at the figure level. The value a preset writes in a hole is its default.

Each closed vocabulary is written once, here or below this module: ``FRAMES``,
``ENGINES``, ``WHEN``, ``WIDTHS_MM``, ``FORMATS``, ``ZONES`` and ``OVERLAY_FIELDS``
here, ``LAYER_REDUCTIONS`` in ``core/units/kinds.py`` and ``STEP_NAMES`` in
``core/pipeline_steps.py``. ``theme``, ``static``, ``subject`` and ``overlays`` read
them from here. A value whose drawing comes in a later version is accepted here,
and ``render`` refuses it.

The configuration imports this module at every load, so it reads only the standard
library, pydantic, ``hydromodpy.core`` and ``results/field_registry.py``: no
matplotlib, no pandas, no run reader.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.pipeline_steps import STEP_NAMES
from hydromodpy.core.time.instant import instant
from hydromodpy.core.units.kinds import LAYER_REDUCTIONS
from hydromodpy.results.field_registry import (
    BUDGET_GROUP,
    FIELD_REGISTRY,
    NOT_AQUIFER_TERMS,
    SHAPE_FACE,
    SHAPE_LAYER_FACE,
    SHAPE_TIME,
    SHAPE_TIME_FACE,
    SHAPE_TIME_LAYER_FACE,
    TIME_SERIES_REGISTRY,
    FieldDescriptor,
    TimeSeriesDescriptor,
    kind_of,
)

WIDTHS_MM = {"single": 85, "medium": 120, "double": 180}
"""Printed widths of a figure, in mm: one column, one and a half, two."""

FORMATS = ("png", "svg", "pdf")
"""File formats of the static engine."""

ZONE_PREFIX = "zone:"
ZONES = ("catchment", "domain")
"""Zone stations: ``zone:catchment`` is the basin of the outlet, ``zone:domain`` every active cell."""

OVERLAY_FIELDS: dict[str, tuple[str, ...]] = {
    "relief": ("topography",),
    "outline": (),
    "network": (),
    "generated_network": (),
    "outlet": (),
    "stations": (),
    "lake": ("lake",),
    "barrier": (),
    "wells": ("well",),
    "scale_bar": (),
    "mesh": (),
}
"""Context layers a map or a section may draw, and the registered fields each one reads.
``overlays.py`` holds one function per name."""

Instant = str | int
"""One instant: an ISO date, ``"first"``, ``"last"`` or a period index (negative from the end)."""

BUDGET = "budget"
"""The family of budget terms a run kept. ``read_budget`` lists them."""

COLUMN_SEPARATOR = "."
"""A table column is written ``table.column``."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One frame, drawn by the module ``hydromodpy.display.frames.<name>``.

    ``shapes`` are the registry shapes whose natural frame this is, the first frame
    in table order winning. ``overlays`` are drawn when a panel names none. ``ready``
    is false until the module of the frame exists.
    """

    shapes: tuple[str, ...] = ()
    overlays: tuple[str, ...] = ()
    ready: bool = False


FRAMES: dict[str, Frame] = {
    "map": Frame(
        (SHAPE_TIME_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_LAYER_FACE, SHAPE_FACE),
        ("outline", "outlet", "scale_bar"),
        ready=True,
    ),
    "series": Frame((SHAPE_TIME,), ready=True),
    "section": Frame(),
    "xy": Frame(),
    "distribution": Frame(),
    "groups": Frame(),
    "table": Frame(),
    "volume": Frame(),
}
TABLE = "table"
MAP, SERIES = "map", "series"
MAP_TABLE = "sfr_reaches"
"""The one table a map draws a column of, as lines from each reach to its downstream cell."""


@dataclass(frozen=True, slots=True)
class Engine:
    """One drawing engine: the file formats it writes and whether it draws yet."""

    formats: tuple[str, ...]
    ready: bool = False


STATIC, INTERACTIVE = "static", "interactive"
ENGINES: dict[str, Engine] = {
    STATIC: Engine(FORMATS, ready=True),
    INTERACTIVE: Engine(("html",)),
}

END, SESSION, TRIAL, AFTER = "end", "session", "trial", "after:"
WHEN: dict[str, bool] = {END: True, SESSION: False, TRIAL: False, AFTER: False}
"""When a figure is drawn, and whether this version draws it then. ``after:`` takes a step."""

AGAINST_OBSERVED = "observed"
DRAW_KEYWORDS = ("station", "time")
"""The panel fields a figure drawn by a function receives, when its signature declares them."""

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def _closest(value: str, known: Iterable[str], what: str) -> str:
    known = list(known)
    close = difflib.get_close_matches(value, known, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    names = f" Known {what}s: {', '.join(known)}." if known else f" No {what} is defined yet."
    return f"Unknown {what} {value!r}.{hint}{names}"


def is_column(name: str) -> bool:
    """Return True when ``name`` is written as a table column, ``table.column``."""
    return COLUMN_SEPARATOR in name


def is_registered(name: str) -> bool:
    """Return True when ``name`` is a registered field or station series."""
    return name in FIELD_REGISTRY or name in TIME_SERIES_REGISTRY


def unknown_variable(name: str) -> str:
    """Return the refusal sentence for a variable no registry knows, with the closest names."""
    known = [*FIELD_REGISTRY, *TIME_SERIES_REGISTRY, BUDGET]
    close = difflib.get_close_matches(name, known, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    return (
        f"Unknown variable {name!r}.{hint} A variable is a name of the field or series "
        "registry (results/field_registry.py), 'budget', or a 'table.column' in a table panel."
    )


def descriptor(name: str) -> FieldDescriptor | TimeSeriesDescriptor:
    """Return the descriptor of a field or a series, the series first as the registry does."""
    if name in TIME_SERIES_REGISTRY:
        return TIME_SERIES_REGISTRY[name]
    if name in FIELD_REGISTRY:
        return FIELD_REGISTRY[name]
    raise ValueError(unknown_variable(name))


def shape_of(name: str) -> str:
    """Return the registry shape of ``name``, which decides its natural frame.

    ``budget`` takes the shape of its terms. A table column has no shape until its
    row in the column registry exists, so it is refused here and needs a ``type``.
    An ``index`` kind is never drawn and is refused too.
    """
    if name == BUDGET:
        return SHAPE_TIME_LAYER_FACE
    if is_column(name):
        raise ValueError(
            f"{name!r} is a table column and has no natural frame yet; write the frame "
            "with type, for example type = 'table'."
        )
    found = descriptor(name)
    if not kind_of(name).drawable:
        raise ValueError(f"{name!r} is an index of the store and is never drawn.")
    return found.shape


def _listed(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


class ReferenceValue(HydroModelBase):
    """A horizontal reference line at ``value``, in the display unit, with its label."""

    value: float
    label: str


class PanelFields(HydroModelBase):
    """The fields of one panel: a frame, the variables it receives and their options."""

    type: str | None = Field(
        default=None, description="Frame of the panel. Unset, the natural frame of the variable."
    )
    variable: list[str] | None = Field(
        default=None,
        description="Variable name or list. 'budget' is the budget terms the run kept. In a "
        "table panel, 'table.column' names.",
    )
    time: Instant | list[Instant] | None = Field(
        default=None,
        description="A date (YYYY-MM-DD), 'first', 'last', a period index, or a list of them. A "
        "date picks the period (start, end] that holds it. On a series, two values keep the "
        "periods whose start lies between them.",
    )
    layer: int | str | None = Field(
        default=None, description="Layer index from 0 at the top, or 'sum' over the layers."
    )
    station: str | list[str] | None = Field(
        default=None,
        description="A station of the run (lake:1, a reach, a gauge), or zone:catchment, "
        "zone:domain.",
    )
    overlays: list[str] | None = Field(
        default=None, description="Context layers drawn over a map or a section."
    )
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="Map window (xmin, ymin, xmax, ymax), in m in the mesh CRS."
    )
    line: list[tuple[float, float]] | None = Field(
        default=None, description="Trace of a section, points (x, y) in m in the mesh CRS."
    )
    contours: bool | None = Field(
        default=None, description="Draw isolines. Unset, the quantity decides."
    )
    observed: bool = Field(default=False, description="Draw the observed record when it exists.")
    scores: bool = Field(default=False, description="Write the scores of the run on the panel.")
    scale: Literal["linear", "log"] | None = Field(
        default=None, description="Value scale. Unset, the variable decides."
    )
    stack: bool = Field(default=False, description="Stack the variables.")
    by: str | None = Field(default=None, description="Category key of a groups panel.")
    reference: list[Literal["one_to_one", "zero"] | ReferenceValue] | None = Field(
        default=None, description="Reference lines: 'one_to_one', 'zero', or {value, label}."
    )
    share: bool = Field(default=False, description="One colour norm for every small multiple.")
    reduce: Literal["mean", "max", "frequency"] | None = Field(
        default=None, description="Reduce over time before drawing."
    )
    change: tuple[Instant, Instant] | None = Field(
        default=None, description="Draw the change between two instants."
    )
    against: str | None = Field(
        default=None, description="Draw the difference to 'observed' or to another run by name."
    )
    cumulative: bool = Field(
        default=False, description="Cumulate along the ordered axis of the frame."
    )

    @field_validator("type")
    @classmethod
    def _known_frame(cls, value: str | None) -> str | None:
        if value is not None and value not in FRAMES:
            raise ValueError(_closest(value, FRAMES, "frame"))
        return value

    @field_validator("variable", "overlays", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return _listed(value)

    @field_validator("overlays")
    @classmethod
    def _known_overlays(cls, value: list[str] | None) -> list[str] | None:
        for name in value or ():
            if name not in OVERLAY_FIELDS:
                raise ValueError(_closest(name, OVERLAY_FIELDS, "overlay"))
        return value

    @field_validator("time", mode="before")
    @classmethod
    def _time_shape(cls, value: Any) -> Any:
        if isinstance(value, list | tuple):
            return [instant(item, "time") for item in value]
        return None if value is None else instant(value, "time")

    @field_validator("change", mode="before")
    @classmethod
    def _change_shape(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, list | tuple) or len(value) != 2:
            raise ValueError(f"change = {value!r}: write two instants, [before, after].")
        return tuple(instant(item, "change") for item in value)

    @field_validator("layer", mode="before")
    @classmethod
    def _layer_shape(cls, value: Any) -> Any:
        words = [word for word in LAYER_REDUCTIONS if word is not None]
        if isinstance(value, str) and value not in words:
            raise ValueError(f"layer = {value!r}: write a layer index or one of {words}.")
        if isinstance(value, bool) or (isinstance(value, int) and value < 0):
            raise ValueError(f"layer = {value!r}: write a layer index or one of {words}.")
        return value

    @field_validator("station", mode="after")
    @classmethod
    def _known_zone(cls, value: str | list[str] | None) -> str | list[str] | None:
        for name in _listed(value) or ():
            if name.startswith(ZONE_PREFIX) and name[len(ZONE_PREFIX) :] not in ZONES:
                zones = ", ".join(ZONE_PREFIX + zone for zone in ZONES)
                raise ValueError(f"station = {name!r} is no zone. Known zones: {zones}.")
        return value

    @field_validator("bbox")
    @classmethod
    def _bbox_order(cls, value: tuple[float, ...] | None) -> tuple[float, ...] | None:
        if value is not None and not (value[0] < value[2] and value[1] < value[3]):
            raise ValueError(f"bbox = {list(value)}: write [xmin, ymin, xmax, ymax].")
        return value

    @field_validator("line")
    @classmethod
    def _line_points(cls, value: list | None) -> list | None:
        if value is not None and len(value) < 2:
            raise ValueError("line needs two points or more, [[x0, y0], [x1, y1]].")
        return value


PANEL_FIELDS = tuple(PanelFields.model_fields)


class PanelRequest(PanelFields):
    """One panel of a figure, with the ``holes`` it leaves to the user when it is in a preset."""

    holes: list[str] | None = Field(
        default=None,
        description="In a preset, the panel fields a user may give. The value written is "
        "the default.",
    )

    @field_validator("holes", mode="before")
    @classmethod
    def _holes_as_list(cls, value: Any) -> Any:
        return _listed(value)

    @field_validator("holes")
    @classmethod
    def _known_holes(cls, value: list[str] | None) -> list[str] | None:
        for name in value or ():
            if name not in PANEL_FIELDS:
                raise ValueError(_closest(name, PANEL_FIELDS, "panel field"))
        return value


class FigureRequest(PanelFields):
    """One figure: a variable, a preset, a list of panels or a Python function.

    With ``variable`` or ``preset`` the panel fields describe the one panel or fill
    the holes of the preset. ``draw`` takes a Python callable
    ``draw(subject, ax, theme)``. A TOML value is never callable, and a mapping that
    carries ``draw`` is refused, so no file can name code. ``draw`` stays out of the
    JSON schema and of every dump, so a ledger never records it.
    """

    preset: str | None = Field(default=None, description="Name of a preset.")
    panels: list[PanelRequest] | None = Field(default=None, description="The panels, in order.")
    draw: SkipJsonSchema[Callable[..., Any] | None] = Field(default=None, exclude=True)
    name: str | None = Field(default=None, description="File name of the figure, no suffix.")
    title: str | None = Field(default=None, description="Title above the figure.")
    width: str | None = Field(
        default=None,
        description="Printed width: 'single', 'medium' or 'double' column. Unset, single for "
        "one panel, double for more panels or a facet.",
    )
    facet: Literal["time", "run", "variable", "layer", "parameter"] | None = Field(
        default=None, description="Repeat the one panel over this key."
    )
    when: str = Field(
        default=END,
        description="When the figure is drawn: 'end', 'session', 'trial' or 'after:<step>'.",
    )
    every: int | None = Field(
        default=None, ge=1, description="With when = 'trial', draw every this many trials."
    )
    engine: list[str] = Field(default_factory=lambda: [STATIC], description="Engines.")
    formats: list[str] = Field(default_factory=lambda: ["png"], description="File formats.")

    @field_validator("draw", mode="before")
    @classmethod
    def _callable_only(cls, value: Any) -> Any:
        if value is not None and not callable(value):
            raise ValueError(
                "draw takes a Python function and is never written in a file. To draw "
                "a figure from a function in a TOML file, name the preset that carries it."
            )
        return value

    @field_validator("width")
    @classmethod
    def _known_width(cls, value: str | None) -> str | None:
        if value is not None and value not in WIDTHS_MM:
            raise ValueError(_closest(value, WIDTHS_MM, "width"))
        return value

    @field_validator("name")
    @classmethod
    def _file_name(cls, value: str | None) -> str | None:
        if value is not None and not _NAME.match(value):
            raise ValueError(f"name = {value!r}: write letters, digits, '_' or '-' only.")
        return value

    @field_validator("when")
    @classmethod
    def _known_when(cls, value: str) -> str:
        if value.startswith(AFTER):
            step = value[len(AFTER) :]
            if step not in STEP_NAMES:
                raise ValueError(f"when = {value!r}: " + _closest(step, STEP_NAMES, "step"))
        elif value not in WHEN:
            raise ValueError(_closest(value, [*WHEN][:-1] + [AFTER + "<step>"], "when value"))
        return value

    @field_validator("engine", "formats", mode="before")
    @classmethod
    def _as_list_too(cls, value: Any) -> Any:
        return _listed(value)

    @field_validator("engine")
    @classmethod
    def _known_engines(cls, value: list[str]) -> list[str]:
        for name in value:
            if name not in ENGINES:
                raise ValueError(_closest(name, ENGINES, "engine"))
        return value

    @model_validator(mode="after")
    def _one_kind(self) -> FigureRequest:
        given = [key for key in ("preset", "panels", "draw") if getattr(self, key) is not None]
        if len(given) > 1:
            raise ValueError(f"Write one of preset, panels or draw, not {' and '.join(given)}.")
        if not given and not self.variable:
            raise ValueError("A figure needs a variable, a preset, panels or draw.")
        written = [key for key in PANEL_FIELDS if key in self.model_fields_set]
        if given == ["draw"]:
            written = [key for key in written if key not in DRAW_KEYWORDS]
        if given and given[0] in ("panels", "draw") and written:
            raise ValueError(
                f"{', '.join(written)} belong inside a panel when the figure is given by "
                f"{given[0]}; move them into each panel."
            )
        if self.facet and self.panels is not None and len(self.panels) > 1:
            raise ValueError("facet repeats one panel; a figure of several panels cannot take it.")
        if self.every is not None and self.when != TRIAL:
            raise ValueError("every counts trials; write it with when = 'trial'.")
        allowed = [fmt for name in self.engine for fmt in ENGINES[name].formats]
        for fmt in self.formats:
            if fmt not in allowed:
                raise ValueError(
                    f"Format {fmt!r} is not written by the engines {self.engine}. "
                    f"They write: {', '.join(allowed)}."
                )
        if self.draw is not None and self.engine != [STATIC]:
            raise ValueError("A figure drawn by a function has the static engine only.")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedFigure:
    """A request with every hole filled: its panels in order, frames named, defaults set."""

    stem: str
    panels: tuple[PanelRequest, ...]
    width: str
    when: str
    engine: tuple[str, ...]
    formats: tuple[str, ...]
    title: str | None = None
    facet: str | None = None
    every: int | None = None
    preset: str | None = None
    draw: Callable[..., Any] | None = None
    draw_keywords: Mapping[str, Any] = field(default_factory=dict)


FIGURE_FIELDS = ("name", "title", "width", "facet", "when", "every", "engine", "formats")


def request_of(name: str, presets: Mapping[str, FigureRequest], **fields: Any) -> FigureRequest:
    """Return the request a bare name gives: a preset when ``presets`` holds it, else a variable."""
    key = "preset" if name in presets else "variable"
    return FigureRequest.model_validate({key: name, **fields})


def natural_frame(names: list[str]) -> str:
    """Return the frame of the shape of the variables, the first of ``FRAMES`` that takes it."""
    frames = []
    for name in names:
        shape = shape_of(name)
        found = next((key for key, frame in FRAMES.items() if shape in frame.shapes), None)
        if found is None:
            raise ValueError(
                f"No frame draws {name!r} of shape {shape!r}. Write type, or a preset, "
                "or draw a function in Python."
            )
        frames.append(found)
    if len(set(frames)) > 1:
        raise ValueError(f"{names} fall in different frames {frames}; write type.")
    return frames[0]


def _check_variables(panel: PanelRequest, where: str) -> None:
    for name in panel.variable or ():
        if is_column(name):
            table = name.split(COLUMN_SEPARATOR, 1)[0]
            if panel.type == MAP and table != MAP_TABLE:
                raise ValueError(
                    f"{where}: a map draws a column of the table {MAP_TABLE!r}, not {name!r}."
                )
            if panel.type not in (TABLE, MAP):
                raise ValueError(f"{where}: {name!r} is a table column. Write type = 'table'.")
        elif panel.type == TABLE:
            raise ValueError(f"{where}: a table panel takes 'table.column' names, not {name!r}.")
        elif name != BUDGET:
            shape_of(name)


def _check_budget(panel: PanelRequest, where: str) -> None:
    """Refuse a budget that is not a series over a zone: the terms are summed over cells."""
    stations = [panel.station] if isinstance(panel.station, str) else panel.station or []
    zones = bool(stations) and all(str(item).startswith(ZONE_PREFIX) for item in stations)
    if not zones:
        raise ValueError(
            f"{where}: variable = 'budget' is the cell terms summed over a zone. Write "
            "station = 'zone:catchment', or list the variables of a lake or a reach by name."
        )
    if panel.type not in (None, SERIES):
        raise ValueError(f"{where}: the budget is drawn by a series, not by type = {panel.type!r}.")


def _resolved_panel(panel: PanelRequest, where: str) -> PanelRequest:
    if not panel.variable:
        raise ValueError(f"{where} has no variable; write variable = '<name>'.")
    if BUDGET in panel.variable:
        _check_budget(panel, where)
    frame = panel.type or (SERIES if BUDGET in panel.variable else natural_frame(panel.variable))
    resolved = panel.model_copy(update={"type": frame, "holes": None})
    _check_variables(resolved, where)
    if resolved.overlays is None:
        resolved = resolved.model_copy(update={"overlays": list(FRAMES[frame].overlays)})
    return resolved


def _given(request: PanelRequest) -> dict[str, Any]:
    return {key: getattr(request, key) for key in PANEL_FIELDS if key in request.model_fields_set}


def _filled(base: FigureRequest, preset: str, given: dict[str, Any]) -> list[PanelRequest]:
    panels = base.panels if base.panels is not None else [PanelRequest(**_given(base))]
    holes = sorted({hole for panel in panels for hole in panel.holes or ()})
    for key in given:
        if key not in holes:
            raise ValueError(
                f"Preset {preset!r} has no hole {key!r}. Its holes are: "
                f"{', '.join(holes) or 'none'}. Write panels to change more."
            )
    return [
        panel.model_copy(update={k: v for k, v in given.items() if k in (panel.holes or ())})
        for panel in panels
    ]


def expand(request: FigureRequest, presets: Mapping[str, FigureRequest]) -> ResolvedFigure:
    """Return the figure a request asks for, its panels resolved in order.

    A preset gives its panels, the user fills their holes, and the figure fields the
    user wrote win over those of the preset. A panel without ``type`` takes the
    natural frame of its variables, and a map without ``overlays`` the frame default.
    Each refusal names what is wrong and what to write.
    """
    base, preset, given = request, None, _given(request)
    if request.preset is not None:
        preset = request.preset
        if preset not in presets:
            raise ValueError(_closest(preset, presets, "preset"))
        base = presets[preset]
        if base.preset is not None:
            raise ValueError(f"Preset {preset!r} names another preset; a preset is one request.")
    figure = {key: getattr(base, key) for key in FIGURE_FIELDS}
    figure.update(
        {key: getattr(request, key) for key in FIGURE_FIELDS if key in request.model_fields_set}
    )
    draw, keywords, panels = base.draw, {}, []
    if draw is not None:
        extra = [key for key in given if key not in DRAW_KEYWORDS]
        if extra:
            raise ValueError(
                f"Preset {preset!r} draws one fixed figure and takes only "
                f"{', '.join(DRAW_KEYWORDS)}, not {', '.join(extra)}."
            )
        keywords = given
    elif preset is not None:
        panels = _filled(base, preset, given)
    else:
        panels = base.panels if base.panels is not None else [PanelRequest(**given)]
    resolved = tuple(
        _resolved_panel(panel, f"panel {chr(97 + i)}" if len(panels) > 1 else "the panel")
        for i, panel in enumerate(panels)
    )
    if figure["facet"] and len(resolved) > 1:
        raise ValueError(
            f"facet repeats one panel, and this figure has {len(resolved)}; drop facet "
            "or ask for one panel."
        )
    return ResolvedFigure(
        stem=file_stem(request),
        panels=resolved,
        width=figure["width"] or ("double" if len(resolved) > 1 or figure["facet"] else "single"),
        when=figure["when"],
        engine=tuple(figure["engine"]),
        formats=tuple(figure["formats"]),
        title=figure["title"],
        facet=figure["facet"],
        every=figure["every"],
        preset=preset,
        draw=draw,
        draw_keywords=keywords,
    )


def file_stem(request: FigureRequest) -> str:
    """Return the file name of a figure without suffix: its name, else its preset, else its variables."""
    if request.name:
        return request.name
    if request.preset:
        return request.preset
    if request.variable:
        return "-".join(name.replace(COLUMN_SEPARATOR, "_") for name in request.variable)
    if request.draw is not None:
        return request.draw.__name__
    raise ValueError("A figure given by panels needs a name; write name = '<file name>'.")


def check_stems(requests: Iterable[FigureRequest]) -> None:
    """Refuse two requests of one list that would write the same file."""
    seen: dict[str, int] = {}
    for request in requests:
        stem = file_stem(request)
        seen[stem] = seen.get(stem, 0) + 1
    twice = sorted(stem for stem, count in seen.items() if count > 1)
    if twice:
        raise ValueError(
            f"Several figures would be written as {', '.join(twice)}. Give each one its own name."
        )


def required_variables(
    request: FigureRequest, presets: Mapping[str, FigureRequest]
) -> tuple[str, ...]:
    """Return the registered variables a request reads, overlay fields included, sorted.

    The run planner keeps these. ``budget`` adds every per-cell budget term of an
    aquifer. A figure drawn by a function declares nothing here.
    """
    names: set[str] = set()
    for panel in expand(request, presets).panels:
        names.update(name for name in panel.variable or () if is_registered(name))
        if BUDGET in (panel.variable or ()):
            names.update(
                name
                for name, field in FIELD_REGISTRY.items()
                if field.zarr_path.startswith(BUDGET_GROUP) and name not in NOT_AQUIFER_TERMS
            )
        for overlay in panel.overlays or ():
            names.update(OVERLAY_FIELDS[overlay])
    return tuple(sorted(names))


def replay_request(figure: ResolvedFigure) -> FigureRequest:
    """Return the request that draws ``figure`` again, as the ledger records it.

    A figure drawn by a function replays through its preset. A function given in
    Python without a preset has no record to replay and is refused.
    """
    common = {
        "name": figure.stem,
        "title": figure.title,
        "width": figure.width,
        "when": figure.when,
        "every": figure.every,
        "engine": list(figure.engine),
        "formats": list(figure.formats),
    }
    if figure.draw is not None:
        if figure.preset is None:
            raise ValueError(
                f"{figure.stem!r} was drawn by a Python function; draw it again in Python."
            )
        return FigureRequest(preset=figure.preset, **common, **figure.draw_keywords)
    return FigureRequest(panels=list(figure.panels), facet=figure.facet, **common)
