"""What each figure option means, declared on the parameter that takes it.

An option of a figure is a keyword parameter of its ``render`` or ``plot``.
Its type and its default are the parameter's own. Its description and its unit
sit on the same parameter, in an ``Annotated`` marker::

    tolerance_m: Annotated[
        float, Opt("Distance under which two lines match.", unit="m")
    ] = 50.0

So the catalog of figures, ``[display.overrides]`` and ``hmp.figure`` read one
declaration and nothing is written twice. Options many figures share have an
alias here (:data:`Cmap`, :data:`Overlays`, :data:`Station`, ...).
:func:`hydromodpy.display.figure.options_of` reads them back, and a test checks
that every option of every registered figure carries a description.
"""

from __future__ import annotations

import builtins
import inspect
import re
import typing
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = [
    "COMMON_OPTIONS",
    "Cmap",
    "Cycle",
    "FlowTauSpecificRatio",
    "NetworkTimestep",
    "CmapOrOwn",
    "DiagonalNeighbors",
    "Extent",
    "FieldName",
    "FigureOption",
    "Figsize",
    "Layer",
    "LogY",
    "ObjectiveName",
    "ObservedStation",
    "OneParameter",
    "Opt",
    "OutputName",
    "Overlays",
    "ParameterNames",
    "ParameterUnits",
    "ReferenceRun",
    "SectionLine",
    "SectionOrientation",
    "SectionSamples",
    "SectionThrough",
    "SessionId",
    "ShowRunName",
    "Station",
    "TauSpecificRatio",
    "Timestep",
    "Title",
    "TrialsSessionId",
    "Variable",
    "VisibleFlow",
    "Vmax",
    "Vmin",
    "describe_options",
]


@dataclass(frozen=True, slots=True)
class Opt:
    """The meaning of one figure option.

    ``description`` says what the option changes, in a sentence a reader of
    the catalog understands. ``unit`` is the unit of a number, ``None`` for a
    name, a switch or a count. ``python_only`` marks an option that takes a
    Python object (another run, a series), which a TOML file cannot write.
    """

    description: str
    unit: str | None = None
    python_only: bool = False


@dataclass(frozen=True, slots=True)
class FigureOption:
    """One option of one figure, as the catalog shows it."""

    name: str
    type: str
    default: str | None
    description: str
    unit: str | None = None
    python_only: bool = False


# --------------------------------------------------------------- shared options

Figsize = Annotated[
    tuple[float, float] | None,
    Opt(
        "Width and height of the figure. Left out, the figure's own size.",
        unit="in",
    ),
]
Title = Annotated[
    str | None,
    Opt(
        "Text that replaces the main title of the figure. An empty string removes "
        "the title. Left out, the figure writes its own title."
    ),
]
ShowRunName = Annotated[
    bool,
    Opt(
        "Write the run name in the titles and in the card rows that name the run. "
        "Turn it off for a figure shown outside the project, where the run name "
        "means nothing to the reader."
    ),
]
Timestep = Annotated[
    int | None,
    Opt(
        'The instant drawn: a date ("2002-10-15"), "first" or "last". The figure '
        "draws the stress period that holds the date. Left out, the last period."
    ),
]
Cmap = Annotated[
    str,
    Opt("Matplotlib colormap of the field, by name."),
]
CmapOrOwn = Annotated[
    str | None,
    Opt(
        "Matplotlib colormap of the field, by name. Left out, the colormap the "
        "figure picks for what it shows."
    ),
]
Vmin = Annotated[
    float | None,
    Opt(
        "Lower end of the colour scale, in the unit of the field. Left out, the "
        "smallest value drawn."
    ),
]
Vmax = Annotated[
    float | None,
    Opt(
        "Upper end of the colour scale, in the unit of the field. Left out, the "
        "largest value drawn."
    ),
]
Layer = Annotated[
    int | None,
    Opt("Model layer to draw, 0 for the top one. Left out, the top layer."),
]
Overlays = Annotated[
    tuple[str, ...] | list[str] | None,
    Opt(
        'Named layers drawn over the map: "watershed", "outlet", "network" (the '
        'mapped streams), "seepage", "particles", "wells". Left out, the map\'s own '
        "choice; an empty list draws none. An overlay the run cannot feed is "
        "skipped with a log line."
    ),
]
Extent = Annotated[
    Literal["catchment", "mesh"],
    Opt(
        '"catchment" crops to the delineated watershed and counts the cells inside '
        'it; "mesh" keeps the whole modelled domain.'
    ),
]
Station = Annotated[
    str,
    Opt(
        'Station whose series is drawn: a gauge id, or "_catchment" for the '
        "series at the catchment outlet."
    ),
]
ObservedStation = Annotated[
    str | None,
    Opt(
        "Gauge whose observed series is compared. Left out, the one gauge that "
        "observes the series; when several do, the figure is refused with their ids."
    ),
]
Variable = Annotated[
    str,
    Opt('Stored series to draw, by name, for example "discharge".'),
]
LogY = Annotated[
    bool,
    Opt("Draw the vertical axis on a logarithmic scale."),
]
SessionId = Annotated[
    str | None,
    Opt("Calibration session to read, by id. Left out, the latest session the run belongs to."),
]
TrialsSessionId = Annotated[
    str | None,
    Opt(
        "Calibration session to read, by id. Left out, every trial the catalog "
        "holds for this run, all sessions together."
    ),
]
OutputName = Annotated[
    str | None,
    Opt(
        "Calibration output to read, by its name in [calibration.outputs]. Left "
        "out, the one output that publishes what the figure reads; when several "
        "do, the figure asks for this option."
    ),
]
OneParameter = Annotated[
    str | None,
    Opt(
        "Calibrated parameter to read, by name. Left out, the one the session "
        "sampled; a session that sampled several is skipped with the reason."
    ),
]
ParameterUnits = Annotated[
    str | None,
    Opt(
        "Unit written on the parameter axis. Left out, the unit the session "
        'declared for the parameter, else "-".'
    ),
]
ObjectiveName = Annotated[
    str | None,
    Opt(
        'Column of the trial table read as the cost. Left out, "objective_value", else "objective".'
    ),
]
ParameterNames = Annotated[
    list[str] | None,
    Opt("Calibrated parameters to draw, by name. Left out, every one the session sampled."),
]
DiagonalNeighbors = Annotated[
    bool | None,
    Opt(
        "Count the diagonal neighbours of a cell when the stream-network criterion "
        "groups cells. Left out, the setting the run's network output scored with."
    ),
]
TauSpecificRatio = Annotated[
    float | None,
    Opt(
        "Seepage threshold as a fraction of the recharge a cell receives. Left "
        "out, the setting the run's network output scored with, else the "
        "criterion's default.",
        unit="-",
    ),
]
VisibleFlow = Annotated[
    str | None,
    Opt(
        "Routed discharge a cell of the seepage closure must carry to flow: a "
        'discharge with its unit ("1 L/s"), a share of the outlet discharge '
        '("1%"), or "0 L/s" for the closure alone. Left out, "1 L/s".'
    ),
]
NetworkTimestep = Annotated[
    int | None,
    Opt(
        'The instant drawn: a date ("2002-10-15"), "first" or "last". The figure '
        "draws the stress period that holds the date. Left out, the state the "
        "run's network output scored, else the last period."
    ),
]
Cycle = Annotated[
    str | None,
    Opt(
        "Label of one hydrological cycle, usually a calendar year. Left out, the last complete one."
    ),
]
FlowTauSpecificRatio = Annotated[
    float | None,
    Opt(
        "Seepage threshold as a fraction of the recharge a cell receives. Left "
        "out, the criterion's default, 1e-4.",
        unit="-",
    ),
]

SectionLine = Annotated[
    tuple[float, float, float, float] | list[float] | None,
    Opt(
        "The section as [x0, y0, x1, y1] in the project CRS. Overrides orientation and through.",
        unit="m",
    ),
]
SectionOrientation = Annotated[
    Literal["we", "sn"],
    Opt('"we" for a section from west to east, "sn" from south to north.'),
]
SectionThrough = Annotated[
    tuple[float, float] | list[float] | None,
    Opt(
        "A point [x, y] the section passes through, in the project CRS. Left out, "
        "the catchment outlet, else a cell near the centre of the mesh.",
        unit="m",
    ),
]
SectionSamples = Annotated[
    int | None,
    Opt(
        "Number of points sampled along the section. Left out, about two per cell "
        "crossed, between 32 and 4,000."
    ),
]

ReferenceRun = Annotated[
    "Run | None",
    Opt(
        "The other run, on the same mesh, compared with this one. Required: "
        "without it the figure is skipped with the reason.",
        python_only=True,
    ),
]
FieldName = Annotated[
    str,
    Opt('Stored field compared, by name, for example "head" or "watertable_depth".'),
]

# Options every figure takes, declared once on ``BaseFigure.plot``.
COMMON_OPTIONS = ("figsize", "title", "show_run_name")


# ------------------------------------------------------------------- reading


class _Unresolved:
    """Stand-in for a name an annotation uses but the module imports only for typing."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # typing accepts callables
        raise TypeError(self.text)

    def __or__(self, other: Any) -> _Unresolved:
        return _Unresolved(f"{self.text} | {_type_text(other)}")

    def __ror__(self, other: Any) -> _Unresolved:
        return _Unresolved(f"{_type_text(other)} | {self.text}")

    def __getitem__(self, item: Any) -> _Unresolved:
        items = item if isinstance(item, tuple) else (item,)
        return _Unresolved(f"{self.text}[{', '.join(_type_text(i) for i in items)}]")

    def __getattr__(self, name: str) -> _Unresolved:
        if name.startswith("__"):
            raise AttributeError(name)
        return _Unresolved(f"{self.text}.{name}")

    def __repr__(self) -> str:
        return self.text


class _Names(dict):
    """Locals of an annotation: the module's names, then a stand-in for the rest."""

    def __init__(self, module_globals: dict[str, Any]) -> None:
        super().__init__()
        self._globals = module_globals

    def __missing__(self, name: str) -> Any:
        if name in self._globals:
            return self._globals[name]
        if hasattr(builtins, name):
            return getattr(builtins, name)
        return _Unresolved(name)


def _evaluate(annotation: Any, module_globals: dict[str, Any]) -> Any:
    """The annotation as an object, whatever the module imports only for typing."""
    if not isinstance(annotation, str):
        return annotation
    try:
        return eval(annotation, dict(module_globals), _Names(module_globals))  # noqa: S307
    except Exception:
        return annotation


def _type_text(tp: Any) -> str:
    """A type as a reader writes it."""
    if tp is None or tp is type(None):
        return "None"
    if isinstance(tp, str):
        return tp
    if isinstance(tp, _Unresolved):
        return tp.text
    if isinstance(tp, type) and not typing.get_args(tp):
        return tp.__name__
    if typing.get_origin(tp) is typing.Union:
        return " | ".join(_type_text(arg) for arg in typing.get_args(tp))
    text = inspect.formatannotation(tp)
    # A reader writes ``Sequence[float]``, not the module path of each name.
    return re.sub(r"\b(?:[a-z_][\w]*\.)+(?=[A-Za-z_])", "", text)


def _split(annotation: Any, module_globals: dict[str, Any]) -> tuple[str, Opt | None]:
    """Return the type text and the :class:`Opt` of one parameter annotation."""
    tp = _evaluate(annotation, module_globals)
    meta: Opt | None = None
    if typing.get_origin(tp) is Annotated:
        args = typing.get_args(tp)
        tp = args[0]
        meta = next((m for m in args[1:] if isinstance(m, Opt)), None)
        if isinstance(tp, typing.ForwardRef):
            tp = tp.__forward_arg__
    elif tp is inspect.Parameter.empty:
        return "", None
    return _type_text(tp), meta


def _declarations(cls: type) -> dict[str, tuple[inspect.Parameter, dict[str, Any]]]:
    """Every keyword parameter of ``plot`` then ``render``, first definition along the MRO."""
    found: dict[str, tuple[inspect.Parameter, dict[str, Any]]] = {}
    for method in ("plot", "render"):
        for klass in cls.__mro__:
            func = klass.__dict__.get(method)
            if func is None:
                continue
            func = inspect.unwrap(func)
            try:
                params = inspect.signature(func).parameters
            except (TypeError, ValueError):
                continue
            for param in params.values():
                if param.kind in (
                    inspect.Parameter.VAR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                ):
                    continue
                found.setdefault(param.name, (param, getattr(func, "__globals__", {})))
    return found


def describe_options(cls: type, names: Iterable[str], base: type) -> tuple[FigureOption, ...]:
    """Every option in ``names`` of the figure class ``cls``, with its meaning.

    ``base`` is the class whose ``plot`` declares the options every figure
    takes. ``time`` is declared on the ``timestep`` parameter the display
    layer fills from it. Sorted by name. The figure layer calls it as
    :func:`hydromodpy.display.figure.options_of`.
    """
    declared = _declarations(cls)
    base_declared = _declarations(base)
    rows: list[FigureOption] = []
    for name in sorted(names):
        source = "timestep" if name == "time" else name
        # ``title`` and ``show_run_name`` are BaseFigure's, whatever plot a figure has.
        own = (
            base_declared.get(source)
            if name in ("title", "show_run_name")
            else declared.get(source)
        )
        if own is None:
            rows.append(FigureOption(name=name, type="", default=None, description=""))
            continue
        param, module_globals = own
        type_text, meta = _split(param.annotation, module_globals)
        if meta is None and name == "figsize":
            # A figure with its own plot keeps its default size and the shared meaning.
            figsize_param, figsize_globals = base_declared["figsize"]
            meta = _split(figsize_param.annotation, figsize_globals)[1]
        default = None if param.default is inspect.Parameter.empty else repr(param.default)
        if name == "time":
            # The instant is named by a date; the figure's own choice is in the text.
            type_text = 'date, "first" or "last"'
            default = None
        rows.append(
            FigureOption(
                name=name,
                type=type_text,
                default=default,
                description=meta.description if meta else "",
                unit=meta.unit if meta else None,
                python_only=meta.python_only if meta else False,
            )
        )
    return tuple(rows)
