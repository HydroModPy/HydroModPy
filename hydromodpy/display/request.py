"""Figure requests: what a figure shows, in the same words for TOML, the CLI and Python.

A figure is a short list of panels. A panel names a frame and the variables it
receives. A request names one variable, a preset, a list of panels or a Python
function, and ``expand`` turns it into its panels with every hole filled. A preset
lists the ``holes`` of its panels, the fields a user may give, and writes their default.
Each closed vocabulary is written once, here or in ``core``. Nothing here reads a run.
"""

from __future__ import annotations

import difflib
import functools
import inspect
import json
import re
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from itertools import takewhile
from typing import Any, Literal

from pydantic import (
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.types import Names, listed
from hydromodpy.core.pipeline_steps import FIGURE_STEPS, STEP_NAMES
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
    "seepage": ("seepage_mask",),
    "pathlines": (),
    "scale_bar": (),
    "mesh": (),
}
"""Context layers a map or a section may draw, and the registered fields each one reads."""

NETWORK_CELL_FIELDS = ("simulated_active_network", "network_agreement", "downslope_distance")
"""Fields whose cells are the stream network: the mapped reaches drawn over them hide them."""

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
    """One frame, drawn by ``hydromodpy.display.frames.<name>``.

    ``shapes`` are the registry shapes it is the natural frame of, the first frame in
    table order winning. ``overlays`` are drawn when a panel names none. ``kept`` are the
    ones of them that stay, in their place, when a panel names its own. ``height`` is the
    height of one panel as a share of its width.
    """

    shapes: tuple[str, ...] = ()
    overlays: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    engines: tuple[str, ...] = (STATIC,)
    height: float = 0.75


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
        ("relief", "outline", "network", "outlet", "scale_bar"),
        # A map has no coordinates, so it always carries its scale, and its relief.
        kept=("relief", "scale_bar"),
        engines=(STATIC, INTERACTIVE),
    ),
    "series": Frame((SHAPE_TIME,), engines=(STATIC, INTERACTIVE)),
    "section": Frame(
        (SHAPE_TIME_LAYER_FACE, SHAPE_LAYER_FACE, SHAPE_TIME_FACE, SHAPE_FACE),
        ("seepage",),
        height=0.45,
    ),
    "xy": Frame(_XY_SHAPES),
    "distribution": Frame(_XY_SHAPES),
    "groups": Frame(_XY_SHAPES),
    "table": Frame(),
    "volume": Frame(engines=(INTERACTIVE,)),
}
TABLE = "table"
MAP, SERIES, GROUPS = "map", "series", "groups"
TRIAL_FRAMES = (SERIES, "xy", "distribution")
"""The frames that draw the trial columns of a session."""
GROUP_KEYS = ("month", "time", "run")
"""The keys a groups panel splits its values by."""
MAP_TABLE = "sfr_reaches"
"""The one table a map draws a column of, as lines from each reach to its downstream cell."""


ENGINES = {STATIC: FORMATS, INTERACTIVE: ("html",)}
"""The drawing engines and the file formats each one writes."""

END, SESSION, AFTER = "end", "session", "after:"
WHEN = (END, SESSION, AFTER)
"""When a figure is drawn. ``after:`` takes a step of ``FIGURE_STEPS`` that stores its data."""

AGAINST_OBSERVED = "observed"
DRAW_KEYWORDS = ("station", "time", "variable")
"""The panel fields a figure drawn by a function receives, when its signature declares them."""


@dataclass(frozen=True, slots=True)
class Special:
    """The facts of one special figure, drawn by ``hydromodpy.display.special.<name>``."""

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
    "particle_tracks": Special("run", "double", ("time", "variable")),
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


@functools.cache
def retired_table() -> dict[str, dict[str, Any]]:
    """Read the table of the former figure names once."""
    text = resources.files("hydromodpy.display").joinpath("retired_figures.toml").read_text("utf-8")
    return tomllib.loads(text)


def retired_forms(name: str) -> list[tuple[str, str]]:
    """Return the (TOML pairs, Python call) of each form that replaces a former name."""
    forms = retired_table()[name].get("figure", [])
    out = []
    for form in [forms] if isinstance(forms, dict) else forms:
        lead = "variable" if "variable" in form else "preset"
        rest = [f"{k}={json.dumps(v)}" for k, v in form.items() if k != lead]
        toml = ", ".join(f"{k} = {json.dumps(v)}" for k, v in form.items())
        out.append((toml, f"run.figure({', '.join([json.dumps(form[lead]), *rest])})"))
    return out


def retired(name: str) -> str | None:
    """Return the sentence for a figure name of a pre-release, or None for any other name."""
    row = retired_table().get(name)
    if row is None:
        return None
    text = f"{name!r} was a figure of a pre-release."
    if "none" in row:
        return f"{text} {row['none']}"
    forms = retired_forms(name)
    write = " and ".join(f"[[display.figure]] {t}" for t, _ in forms)
    text += f" Write {write}, or {' and '.join(c for _, c in forms)}."
    return text + (f" Lost: {row['lost']}" if "lost" in row else "")


def unknown_variable(name: str, presets: Iterable[str] = ()) -> str:
    """Return the refusal for a variable no registry knows. With ``presets``, it is a figure name."""
    if (former := retired(name)) is not None:
        return former
    known = [*FIELD_REGISTRY, *REBUILT_FIELDS, *TIME_SERIES_REGISTRY, BUDGET, *presets]
    close = difflib.get_close_matches(name, known, n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    if presets:
        return f"Unknown figure {name!r}.{hint} A figure is a variable or a preset."
    return (
        f"Unknown variable {name!r}.{hint} A variable is a name of the field or series "
        "registry (results/field_registry.py), 'budget', or a 'table.column' in a table panel."
    )


def descriptor(name: str) -> FieldDescriptor | TimeSeriesDescriptor | ColumnDescriptor:
    """Return the descriptor of a field, a rebuilt field, a table column or a series, series first."""
    for registry in (TIME_SERIES_REGISTRY, FIELD_REGISTRY, REBUILT_FIELDS, COLUMN_REGISTRY):
        if name in registry:
            return registry[name]
    raise ValueError(unknown_variable(name))


def shape_of(name: str) -> str:
    """Return the registry shape of ``name``. A table column and an index kind are refused."""
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
    variable: Names | None = Field(
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
    overlays: Names | None = Field(
        default=None,
        description="Context layers drawn over a map or a section, in place of the default "
        "ones. A map keeps its relief and its scale bar.",
    )
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="Window drawn (xmin, ymin, xmax, ymax). On a map, in m in the mesh CRS. "
        "On a section, distances along the line then elevations, in m.",
    )
    line: list[tuple[float, float]] | None = Field(
        default=None, description="Trace of a section, points (x, y) in m in the mesh CRS."
    )
    limits: tuple[float, float] | None = Field(
        default=None,
        description="Colour limits of a map or a section (low, high), in the unit drawn. "
        "Unset, the range of the values.",
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

    @field_validator(
        "type", "by", "overlays", "holes", "special", "width", "engine", check_fields=False
    )
    @classmethod
    def _known_word(cls, value: Any, info: ValidationInfo) -> Any:
        known, what = VOCABULARIES[info.field_name]
        for word in listed(value) or ():
            if word not in known:
                raise ValueError(_closest(word, known, what))
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
        if (isinstance(value, str) and value not in words) or (
            isinstance(value, bool) or (isinstance(value, int) and value < 0)
        ):
            raise ValueError(f"layer = {value!r}: write a layer index or one of {words}.")
        return value

    @field_validator("station", mode="after")
    @classmethod
    def _known_zone(cls, value: str | list[str] | None) -> str | list[str] | None:
        for name in listed(value) or ():
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

    @field_validator("limits")
    @classmethod
    def _limits_order(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and not value[0] < value[1]:
            raise ValueError(f"limits = {list(value)}: write [low, high].")
        return value

    @field_validator("line")
    @classmethod
    def _line_points(cls, value: list | None) -> list | None:
        if value is not None and len(value) < 2:
            raise ValueError("line needs two points or more, [[x0, y0], [x1, y1]].")
        return value


PANEL_FIELDS = tuple(PanelFields.model_fields)
VOCABULARIES = {
    "type": (FRAMES, "frame"),
    "by": (GROUP_KEYS, "group key"),
    "overlays": (OVERLAY_FIELDS, "overlay"),
    "holes": (PANEL_FIELDS, "panel field"),
    "special": (SPECIALS, "special figure"),
    "width": (WIDTHS_MM, "width"),
    "engine": (ENGINES, "engine"),
}
"""The closed words each field accepts, and what one is called in a refusal."""


class PanelRequest(PanelFields):
    """One panel of a figure, with the ``holes`` it leaves to the user when it is in a preset."""

    holes: Names | None = Field(
        default=None,
        description="In a preset, the panel fields a user may give. The value written is "
        "the default.",
    )


class FigureRequest(PanelFields):
    """One figure: a variable, a preset, a list of panels or a Python function.

    ``draw`` and ``special`` stay out of the schema and of every dump, so no file names code.
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
        description="When the figure is drawn: 'end', 'session' or 'after:<step>'.",
    )
    engine: Names = Field(
        default_factory=lambda: [STATIC],
        description="Drawing engines to use for the figure, one file per engine.",
    )
    formats: Names = Field(
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
            if step not in FIGURE_STEPS:
                raise ValueError(f"when = {value!r}: " + _closest(step, FIGURE_STEPS, "step"))
        elif value not in WHEN[:-1]:
            raise ValueError(_closest(value, [*WHEN[:-1], AFTER + "<step>"], "when value"))
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
        allowed = [fmt for name in self.engine for fmt in ENGINES[name]]
        if "formats" not in self.model_fields_set:
            self.formats = [ENGINES[name][0] for name in self.engine]
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
    preset: str | None = None
    draw: Callable[..., Any] | None = None
    special: str | None = None
    draw_keywords: Mapping[str, Any] = field(default_factory=dict)


FIGURE_FIELDS = ("name", "title", "width", "facet", "when", "engine", "formats")


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
"""Old options of the figures that kept their name: the field that replaces each, or None."""


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


def keywords_of(base: FigureRequest | None) -> tuple[str, ...]:
    """Return the panel fields a figure accepts at the figure level, ``base`` being its preset."""
    if base is None:
        return PANEL_FIELDS
    if base.special is not None:
        return SPECIALS[base.special].keywords
    if base.draw is not None:
        declared = inspect.signature(base.draw).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in declared.values()):
            return DRAW_KEYWORDS
        return tuple(key for key in DRAW_KEYWORDS if key in declared)
    return tuple(dict.fromkeys(h for p in base.panels or () for h in p.holes or ()))


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
        raise ValueError(no_option(name, unknown, keywords_of(base))) from None


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
    for name in resolved.variable or ():
        if is_column(name):
            _check_column(resolved, name, where)
        elif frame == TABLE:
            raise ValueError(f"{where}: a table panel takes 'table.column' names, not {name!r}.")
        elif name != BUDGET:
            shape_of(name)
    overlays = _overlays(FRAMES[frame], resolved.overlays, resolved.variable or ())
    return resolved.model_copy(update={"overlays": overlays})


def _overlays(
    frame: Frame, listed: Sequence[str] | None, variables: Sequence[str] = ()
) -> list[str]:
    """Return the overlays a panel draws: its own list around the ones the frame keeps.

    A panel that lists none draws those of the frame, without the mapped reaches when
    its variable is one of :data:`NETWORK_CELL_FIELDS`.
    """
    if listed is None:
        covered = {"network"} if set(variables) & set(NETWORK_CELL_FIELDS) else set()
        return [name for name in frame.overlays if name not in covered]
    under = list(takewhile(lambda name: name in frame.kept, frame.overlays))
    over = [name for name in frame.kept if name not in under]
    return [*under, *(name for name in listed if name not in frame.kept), *over]


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
    """Return the figure a request asks for. The user fills the holes of a preset and wins."""
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
    keywords, panels = {}, []
    if base.special is not None or base.draw is not None:
        accepted = keywords_of(base)
        wrong = [key for key in given if key not in accepted]
        if wrong:
            raise ValueError(no_option(preset or base.special or "this figure", wrong, accepted))
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
        preset=preset,
        draw=base.draw,
        special=base.special,
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
    seen = Counter(file_stem(request) for request in requests)
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
    """Return the sorted variables the run planner keeps for a request, overlay fields included."""
    names: set[str] = set()
    figure = expand(request, presets)
    if figure.special is not None:
        asked = listed(figure.draw_keywords.get("variable")) or ()
        reads = (*SPECIALS[figure.special].variables, *asked)
        names.update(name for name in reads if is_registered(name))
    for panel in figure.panels:
        names.update(name for name in panel.variable or () if is_registered(name))
        if BUDGET in (panel.variable or ()):
            names.update(budget_terms() if terms else (BUDGET,))
        for overlay in panel.overlays or ():
            names.update(OVERLAY_FIELDS[overlay])
    return tuple(sorted(names))


def first_figure_step(request: FigureRequest, presets: Mapping[str, FigureRequest]) -> str:
    """Return the first step after which the run store holds what a request draws."""
    names = required_variables(request, presets, terms=False)
    figure = expand(request, presets)
    # What no registered variable describes (a special, a draw function, an overlay such as
    # pathlines or stations) is read from results written at extract. The overlays a frame
    # draws by itself are geographic and stand there from the start.
    framed = {name for frame in FRAMES.values() for name in frame.overlays}
    unlisted = (
        figure.special is not None
        or figure.draw is not None
        or any(
            not OVERLAY_FIELDS[overlay] and overlay not in framed
            for panel in figure.panels
            for overlay in panel.overlays or ()
        )
    )
    steps = ["extract"] if unlisted or not names else []
    steps += [
        FIELD_REGISTRY[name].stored_at if name in FIELD_REGISTRY else "extract" for name in names
    ]
    return max(steps, key=STEP_NAMES.index)


def check_when(request: FigureRequest, presets: Mapping[str, FigureRequest]) -> None:
    """Refuse a request drawn after a step whose run store does not hold its data yet."""
    if not request.when.startswith(AFTER):
        return
    first = first_figure_step(request, presets)
    if STEP_NAMES.index(request.when[len(AFTER) :]) < STEP_NAMES.index(first):
        raise ValueError(
            f"Figure {file_stem(request)!r} has when = {request.when!r}, but its data is "
            f"stored at {first}. Write when = '{AFTER}{first}' or a later step."
        )


def replay_request(figure: ResolvedFigure) -> FigureRequest:
    """Return the request that draws ``figure`` again, as the ledger records it."""
    common = {
        "name": figure.stem,
        "title": figure.title,
        "width": figure.width,
        "when": figure.when,
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
