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
them from here. A value that no engine draws yet is accepted here, and ``render`` refuses it
in a sentence that says so.

``SPECIALS`` is the table of facts of the special figures: the kind of subject each one
reads, its width, its keywords and what it reads. The modules of ``display/special`` hold
the drawing only, and ``render`` imports one by its name when it draws.

The configuration imports this module at every load, so it reads only the standard
library, pydantic, ``hydromodpy.core`` and ``results/field_registry.py``: no
matplotlib, no pandas, no run reader.
"""

from __future__ import annotations

import difflib
import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.pipeline_steps import STEP_NAMES
from hydromodpy.core.time.instant import instant
from hydromodpy.core.units.kinds import LAYER_REDUCTIONS
from hydromodpy.results.field_registry import (
    BUDGET_GROUP,
    COLUMN_REGISTRY,
    FIELD_REGISTRY,
    NOT_AQUIFER_TERMS,
    REBUILT_FIELDS,
    SHAPE_FACE,
    SHAPE_LAYER_FACE,
    SHAPE_TIME,
    SHAPE_TIME_FACE,
    SHAPE_TIME_LAYER_FACE,
    TIME_SERIES_REGISTRY,
    ColumnDescriptor,
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

TRIALS = "trials"
"""The pseudo table of a session: ``trials.cost``, ``trials.<parameter>`` and ``trials.parameter``."""
PARAMETER_TOKEN = "parameter"
"""``trials.parameter`` stands for each searched parameter, which ``facet = "parameter"`` fills."""


STATIC, INTERACTIVE = "static", "interactive"


@dataclass(frozen=True, slots=True)
class Frame:
    """One frame, drawn by the module ``hydromodpy.display.frames.<name>``.

    ``shapes`` are the registry shapes whose natural frame this is, the first frame
    in table order winning. ``overlays`` are drawn when a panel names none. ``ready``
    is true when the module of the frame exists. ``engines`` are the engines whose
    function the module holds, ``draw`` for the static one and ``draw_interactive`` for
    the interactive one.
    """

    shapes: tuple[str, ...] = ()
    overlays: tuple[str, ...] = ()
    ready: bool = False
    engines: tuple[str, ...] = (STATIC,)


_XY_SHAPES = (
    SHAPE_TIME,
    SHAPE_TIME_FACE,
    SHAPE_TIME_LAYER_FACE,
    SHAPE_LAYER_FACE,
    SHAPE_FACE,
)

FRAMES: dict[str, Frame] = {
    "map": Frame(
        (SHAPE_TIME_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_LAYER_FACE, SHAPE_FACE),
        ("outline", "outlet", "scale_bar"),
        ready=True,
        engines=(STATIC, INTERACTIVE),
    ),
    "series": Frame((SHAPE_TIME,), ready=True, engines=(STATIC, INTERACTIVE)),
    "section": Frame(
        (SHAPE_TIME_LAYER_FACE, SHAPE_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_FACE), ready=True
    ),
    "xy": Frame(_XY_SHAPES, ready=True),
    "distribution": Frame(_XY_SHAPES, ready=True),
    "groups": Frame(_XY_SHAPES, ready=True),
    "table": Frame(ready=True),
    "volume": Frame(ready=True, engines=(INTERACTIVE,)),
}
TABLE = "table"
MAP, SERIES, GROUPS = "map", "series", "groups"
TRIAL_FRAMES = (SERIES, "xy", "distribution")
"""The frames that draw the trial columns of a session."""
GROUP_KEYS = ("month", "time", "run")
"""The keys a groups panel splits its values by."""
MAP_TABLE = "sfr_reaches"
"""The one table a map draws a column of, as lines from each reach to its downstream cell."""


@dataclass(frozen=True, slots=True)
class Engine:
    """One drawing engine: the file formats it writes and whether it draws yet."""

    formats: tuple[str, ...]
    ready: bool = False


ENGINES: dict[str, Engine] = {
    STATIC: Engine(FORMATS, ready=True),
    INTERACTIVE: Engine(("html",), ready=True),
}

END, SESSION, TRIAL, AFTER = "end", "session", "trial", "after:"
WHEN: dict[str, bool] = {END: True, SESSION: False, TRIAL: False, AFTER: False}
"""When a figure is drawn, and whether it is drawn then yet. ``after:`` takes a step."""

AGAINST_OBSERVED = "observed"
DRAW_KEYWORDS = ("station", "time")
"""The panel fields a figure drawn by a function receives, when its signature declares them."""


@dataclass(frozen=True, slots=True)
class Special:
    """The facts of one special figure, drawn by ``hydromodpy.display.special.<name>``.

    ``subject`` is ``run``, ``session`` or ``runset``. ``width`` is the printed width when
    the request gives none. ``keywords`` are the ``DRAW_KEYWORDS`` its ``draw`` declares.
    ``variables`` and ``tables`` are what it reads, so that the run planner keeps them.
    """

    subject: str
    width: str | None = None
    keywords: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()


SPECIALS: dict[str, Special] = {
    "calibration_landscape": Special("session", "double", tables=("trials", "bounds")),
    "calibration_progress": Special("session", "double", tables=("trials",)),
    "ensemble_band": Special("runset", "double", ("station",), ("discharge",)),
    "flow_directions": Special("run", "double", variables=("topography",)),
    "lake_abacus_comparison": Special("run", None, ("station",)),
    "network_comparison": Special("run", "double"),
    "observed_network_heads": Special("run", "double"),
    "particle_tracks": Special("run", "double"),
    "recession": Special(
        "run", "medium", ("station",), ("discharge", "hydraulic_conductivity", "specific_yield")
    ),
    "residence_time_distribution": Special("run", variables=("head",)),
    "root_search": Special("session", tables=("trials",)),
    "sfr_longitudinal_profile": Special(
        "run", "double", ("time",), ("head",), ("sfr_reaches", "timeseries")
    ),
}
"""The twelve special figures, keyed by the name of their module. The table is closed."""

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
    """Return True when ``name`` is a registered or rebuilt field, or a station series."""
    return name in FIELD_REGISTRY or name in REBUILT_FIELDS or name in TIME_SERIES_REGISTRY


def is_trial_column(name: str) -> bool:
    """Return True when ``name`` is written ``trials.<column>``, a column of a session."""
    return name.split(COLUMN_SEPARATOR, 1)[0] == TRIALS and is_column(name)


def unknown_column(name: str) -> str:
    """Return the refusal sentence for a table column without a row in the column registry."""
    table, _, column = name.partition(COLUMN_SEPARATOR)
    held = [key for key in COLUMN_REGISTRY if key.startswith(f"{table}.")]
    where = f" Known columns of {table!r}: {', '.join(held)}." if held else ""
    return (
        f"{name!r} has no row in COLUMN_REGISTRY (results/field_registry.py).{where} Add a "
        f"row {name!r} there, with its quantity kind and its label, to draw {column!r}."
    )


def unknown_variable(name: str) -> str:
    """Return the refusal sentence for a variable no registry knows, with the closest names."""
    known = [*FIELD_REGISTRY, *REBUILT_FIELDS, *TIME_SERIES_REGISTRY, BUDGET]
    close = difflib.get_close_matches(name, known, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    return (
        f"Unknown variable {name!r}.{hint} A variable is a name of the field or series "
        "registry (results/field_registry.py), 'budget', or a 'table.column' in a table panel."
    )


def descriptor(name: str) -> FieldDescriptor | TimeSeriesDescriptor | ColumnDescriptor:
    """Return the descriptor of a field, a rebuilt field, a table column or a series, series first."""
    if name in TIME_SERIES_REGISTRY:
        return TIME_SERIES_REGISTRY[name]
    if name in FIELD_REGISTRY:
        return FIELD_REGISTRY[name]
    if name in REBUILT_FIELDS:
        return REBUILT_FIELDS[name]
    if name in COLUMN_REGISTRY:
        return COLUMN_REGISTRY[name]
    raise ValueError(unknown_variable(name))


def shape_of(name: str) -> str:
    """Return the registry shape of ``name``, which decides its natural frame.

    ``budget`` takes the shape of its terms. A table column has no shape, so it is
    refused here and needs a ``type``.
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

    value: float = Field(
        description="Value of the line, in the display unit of the variable.",
        json_schema_extra=field_metadata(unit="display unit"),
    )
    label: str = Field(description="Text written next to the line.")


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
        default=None,
        description="Value scale. Unset, the variable decides.",
        json_schema_extra=field_metadata(
            value_docs={
                "linear": "Values are placed on an even scale.",
                "log": "Values are placed on a logarithmic scale, for positive values.",
            }
        ),
    )
    stack: bool = Field(
        default=False, description="Stack the variables one over the other, in the order given."
    )
    by: str | None = Field(default=None, description="Category key of a groups panel.")
    reference: list[Literal["one_to_one", "zero"] | ReferenceValue] | None = Field(
        default=None, description="Reference lines: 'one_to_one', 'zero', or {value, label}."
    )
    share: bool = Field(default=False, description="One colour norm for every small multiple.")
    reduce: Literal["mean", "max", "frequency"] | None = Field(
        default=None,
        description="Reduce over time before drawing. Unset, the time asked for is drawn.",
        json_schema_extra=field_metadata(
            value_docs={
                "mean": "Draws the mean over time.",
                "max": "Draws the largest value over time.",
                "frequency": "Draws the share of time steps where the value is set.",
            }
        ),
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

    @property
    def window(self) -> tuple[Instant, Instant] | None:
        """The two instants of a ``time`` pair, the window of a series, else None."""
        if isinstance(self.time, list) and len(self.time) == 2:
            return self.time[0], self.time[1]
        return None

    @field_validator("type")
    @classmethod
    def _known_frame(cls, value: str | None) -> str | None:
        if value is not None and value not in FRAMES:
            raise ValueError(_closest(value, FRAMES, "frame"))
        return value

    @field_validator("by")
    @classmethod
    def _known_group_key(cls, value: str | None) -> str | None:
        if value is not None and value not in GROUP_KEYS:
            raise ValueError(_closest(value, GROUP_KEYS, "group key"))
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
    JSON schema and of every dump, so a ledger never records it. ``special`` names a row
    of ``SPECIALS``, which only a shipped preset carries.
    """

    preset: str | None = Field(
        default=None, description="Name of a shipped preset or of one of your own presets."
    )
    panels: list[PanelRequest] | None = Field(default=None, description="The panels, in order.")
    draw: SkipJsonSchema[Callable[..., Any] | None] = Field(
        default=None,
        exclude=True,
        description="Python function that draws the figure, draw(subject, ax, theme). Never "
        "written in a file.",
    )
    special: SkipJsonSchema[str | None] = Field(
        default=None,
        exclude=True,
        description="Name of a special figure of SPECIALS. A preset carries it, so a file "
        "names the preset and never code.",
    )
    name: str | None = Field(default=None, description="File name of the figure, no suffix.")
    title: str | None = Field(
        default=None, description="Title written above the whole figure. Unset, none is written."
    )
    width: str | None = Field(
        default=None,
        description="Printed width: 'single', 'medium' or 'double' column. Unset, single for "
        "one panel, double for more panels or a facet.",
    )
    facet: Literal["time", "run", "variable", "layer", "parameter"] | None = Field(
        default=None,
        description="Repeat the one panel over this key.",
        json_schema_extra=field_metadata(
            value_docs={
                "time": "One small panel for each instant of the list given in time.",
                "run": "One small panel for each run of the set.",
                "variable": "One small panel for each variable of the panel.",
                "layer": "One small panel for each layer of the mesh.",
                "parameter": "One small panel for each searched parameter of a session.",
            }
        ),
    )
    when: str = Field(
        default=END,
        description="When the figure is drawn: 'end', 'session', 'trial' or 'after:<step>'.",
    )
    every: int | None = Field(
        default=None,
        ge=1,
        description="With when = 'trial', draw every this many trials.",
        json_schema_extra=field_metadata(unit="trials"),
    )
    engine: list[str] = Field(
        default_factory=lambda: [STATIC],
        description="Drawing engines to use for the figure, one file per engine.",
    )
    formats: list[str] = Field(
        default_factory=lambda: ["png"],
        description="File formats written for the figure, such as png or svg.",
    )

    @field_validator("draw", mode="before")
    @classmethod
    def _callable_only(cls, value: Any) -> Any:
        if value is not None and not callable(value):
            raise ValueError(
                "draw takes a Python function and is never written in a file. To draw "
                "a figure from a function in a TOML file, name the preset that carries it."
            )
        return value

    @field_validator("special")
    @classmethod
    def _known_special(cls, value: str | None) -> str | None:
        if value is not None and value not in SPECIALS:
            raise ValueError(_closest(value, SPECIALS, "special figure"))
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
        given = [
            key for key in ("preset", "panels", "draw", "special") if getattr(self, key) is not None
        ]
        if len(given) > 1:
            raise ValueError(f"Write one of preset, panels or draw, not {' and '.join(given)}.")
        if not given and not self.variable:
            raise ValueError("A figure needs a variable, a preset, panels or draw.")
        written = [key for key in PANEL_FIELDS if key in self.model_fields_set]
        if given in (["draw"], ["special"]):
            written = [key for key in written if key not in DRAW_KEYWORDS]
        if given and given[0] in ("panels", "draw", "special") and written:
            raise ValueError(
                f"{', '.join(written)} belong inside a panel when the figure is given by "
                f"{given[0]}; move them into each panel."
            )
        if self.facet and self.panels is not None and len(self.panels) > 1:
            raise ValueError("facet repeats one panel; a figure of several panels cannot take it.")
        if self.every is not None and self.when != TRIAL:
            raise ValueError("every counts trials; write it with when = 'trial'.")
        allowed = [fmt for name in self.engine for fmt in ENGINES[name].formats]
        if "formats" not in self.model_fields_set:
            self.formats = [ENGINES[name].formats[0] for name in self.engine]
        for fmt in self.formats:
            if fmt not in allowed:
                raise ValueError(
                    f"Format {fmt!r} is not written by the engines {self.engine}. "
                    f"They write: {', '.join(allowed)}."
                )
        if (self.draw or self.special) and self.engine != [STATIC]:
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
    special: str | None = None
    draw_keywords: Mapping[str, Any] = field(default_factory=dict)


FIGURE_FIELDS = ("name", "title", "width", "facet", "when", "every", "engine", "formats")


OLD_OPTIONS: dict[str, tuple[str, str] | None] = {
    "log": ("scale", 'scale = "log"'),
    "log_y": ("scale", 'scale = "log"'),
    "figsize": ("width", 'width = "single", "medium" or "double"'),
    "lake_id": ("station", 'station = "lake:<id>"'),
    "observed_station": ("station", "station = <name>"),
    "variable": ("variable", "variable = <name>"),
    "show_run_name": None,
    "show_model": None,
}
"""Options of the figures that kept their name, and what replaces each one: the field that
takes its place and how to write it, or None when nothing does."""


def no_option(name: str, unknown: list[str], accepted: Iterable[str]) -> str:
    """Return the refusal of options a figure does not take, with what replaces each old one."""
    accepted = tuple(accepted)
    words = ", ".join((*accepted, *FIGURE_FIELDS))
    text = f"{name!r} takes no option {', '.join(unknown)}. It accepts {words}."
    for key in unknown:
        if key not in OLD_OPTIONS:
            continue
        new = OLD_OPTIONS[key]
        if new is not None and (new[0] in accepted or new[0] in FIGURE_FIELDS):
            text += f" To replace {key}, write {new[1]}."
        else:
            text += f" The option {key} has no equivalent here."
    return text


def request_of(name: str, presets: Mapping[str, FigureRequest], **fields: Any) -> FigureRequest:
    """Return the request a bare name gives: a preset when ``presets`` holds it, else a variable."""
    key = "preset" if name in presets else "variable"
    try:
        return FigureRequest.model_validate({key: name, **fields})
    except ValidationError as error:
        unknown = [str(e["loc"][0]) for e in error.errors() if e["type"] == "extra_forbidden"]
        if not unknown:
            raise
        base = presets[name] if key == "preset" else None
        if base is None:
            accepted = PANEL_FIELDS
        elif base.special is not None:
            accepted = SPECIALS[base.special].keywords
        elif base.draw is not None:
            declared = inspect.signature(base.draw).parameters
            accepted = tuple(key for key in DRAW_KEYWORDS if key in declared)
        else:
            accepted = tuple(dict.fromkeys(h for p in base.panels or () for h in p.holes or ()))
        raise ValueError(no_option(name, unknown, accepted)) from None


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


def _check_column(panel: PanelRequest, name: str, where: str) -> None:
    table = name.split(COLUMN_SEPARATOR, 1)[0]
    if is_trial_column(name):
        if panel.type not in TRIAL_FRAMES:
            raise ValueError(
                f"{where}: {name!r} is a column of the trials of a session, drawn by "
                f"{', '.join(TRIAL_FRAMES)}, not by type = {panel.type!r}."
            )
        return
    if panel.type == MAP and table != MAP_TABLE:
        raise ValueError(f"{where}: a map draws a column of the table {MAP_TABLE!r}, not {name!r}.")
    if panel.type not in (TABLE, MAP, SERIES):
        raise ValueError(f"{where}: {name!r} is a table column. Write type = 'table'.")
    if name not in COLUMN_REGISTRY:
        raise ValueError(f"{where}: {unknown_column(name)}")


def _check_variables(panel: PanelRequest, where: str) -> None:
    for name in panel.variable or ():
        if is_column(name):
            _check_column(panel, name, where)
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
    if panel.type not in (None, SERIES, GROUPS):
        raise ValueError(
            f"{where}: the budget is drawn by a series or by groups, not by type = {panel.type!r}."
        )


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
    draw, special, keywords, panels = base.draw, base.special, {}, []
    if special is not None:
        wrong = [key for key in given if key not in SPECIALS[special].keywords]
        if wrong:
            raise ValueError(no_option(preset or special, wrong, SPECIALS[special].keywords))
        keywords = given
    elif draw is not None:
        extra = [key for key in given if key not in DRAW_KEYWORDS]
        if extra:
            raise ValueError(
                f"{preset or 'This figure'!r} is drawn by a function and takes only "
                f"{', '.join(DRAW_KEYWORDS)}, not {', '.join(extra)}."
            )
        declared = inspect.signature(draw).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in declared.values()):
            declared = dict.fromkeys(DRAW_KEYWORDS)
        ignored = [key for key in given if key not in declared]
        if ignored:
            takes = ", ".join(key for key in DRAW_KEYWORDS if key in declared) or "no keyword"
            raise ValueError(
                f"The function of {preset or 'this figure'!r} takes {takes} beyond subject, "
                f"ax and theme, so {', '.join(ignored)} cannot be given. Add the keyword to "
                "the function or drop the option."
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
        width=figure["width"]
        or (
            "double"
            if len(resolved) > 1 or figure["facet"] or any(p.type == "section" for p in resolved)
            else "single"
        ),
        when=figure["when"],
        engine=tuple(figure["engine"]),
        formats=tuple(figure["formats"]),
        title=figure["title"],
        facet=figure["facet"],
        every=figure["every"],
        preset=preset,
        draw=draw,
        special=special,
        draw_keywords=keywords,
    )


def named(presets: Mapping[str, FigureRequest]) -> dict[str, FigureRequest]:
    """Return the presets with the key of each one as its name, unless it writes a name."""
    return {
        key: request if request.name else request.model_copy(update={"name": key})
        for key, request in presets.items()
    }


def file_stem(request: FigureRequest) -> str:
    """Return the file name of a figure without suffix: its name, else its preset, else its variables."""
    if request.name:
        return request.name
    if request.preset:
        return request.preset
    if request.variable:
        return "-".join(name.replace(COLUMN_SEPARATOR, "_") for name in request.variable)
    if request.special is not None:
        return request.special
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


def budget_terms() -> tuple[str, ...]:
    """Return the per-cell budget terms of an aquifer, the ones ``budget`` draws."""
    return tuple(
        name
        for name, field in FIELD_REGISTRY.items()
        if field.zarr_path.startswith(BUDGET_GROUP) and name not in NOT_AQUIFER_TERMS
    )


def required_variables(
    request: FigureRequest, presets: Mapping[str, FigureRequest], *, terms: bool = True
) -> tuple[str, ...]:
    """Return the registered variables a request reads, overlay fields included, sorted.

    The run planner keeps these. ``budget`` adds every per-cell budget term of an
    aquifer, or with ``terms=False`` the name ``budget`` alone. A special figure declares what its row of ``SPECIALS`` lists, and a figure
    drawn by a Python function declares nothing.
    """
    names: set[str] = set()
    figure = expand(request, presets)
    if figure.special is not None:
        names.update(name for name in SPECIALS[figure.special].variables if is_registered(name))
    for panel in figure.panels:
        names.update(name for name in panel.variable or () if is_registered(name))
        if BUDGET in (panel.variable or ()):
            names.update(budget_terms() if terms else (BUDGET,))
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
    if figure.draw is not None or figure.special is not None:
        if figure.preset is None:
            raise ValueError(
                f"{figure.stem!r} was drawn by a Python function; draw it again in Python."
            )
        return FigureRequest(preset=figure.preset, **common, **figure.draw_keywords)
    return FigureRequest(panels=list(figure.panels), facet=figure.facet, **common)
