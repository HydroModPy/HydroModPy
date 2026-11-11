"""Base class shared by every HydroModPy figure.

A figure is a class with a ``spec`` (static metadata) and a
``render(subject, ax)`` method (the only thing subclasses must implement). The
base class provides ``plot()`` which builds the matplotlib Figure, applies styling and
handles saving.

A figure draws one subject, named by ``FigureSpec.subject``: a ``Run``, the
``Session`` of a calibration, or a ``RunSet``. ``render``, ``plot`` and
``unavailable_reason`` receive that object. The display layer resolves the
subject once (``_subject_for`` in :mod:`hydromodpy.display.runs`): a session figure
asked for on a run receives the session that promoted the run, and the run
itself as the option ``promoted``. Figures never touch a solver, a raw output
file or a ``ProjectState``.
"""

from __future__ import annotations

import functools
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display.figure_options import (
    COMMON_OPTIONS,
    Figsize,
    FigureOption,
    ShowRunName,
    Title,
    _declarations,
    _evaluate,
    describe_options,
)
from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import FieldDescriptor

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run.view import Run


FigureSubject = Literal["run", "session", "runset"]
"""What a figure draws: one run, one calibration session, or a set of runs."""

SUBJECTS: tuple[FigureSubject, ...] = ("run", "session", "runset")
"""Every subject a figure may declare."""

PROMOTED_OPTION = "promoted"
"""The option that hands a session figure the run the session promoted.

The display layer fills it, never a user: a session figure asked for on a run
receives the session as its subject and the run under this name.
"""

NOT_PROMOTED_REASON = (
    "draws the calibration session that promoted a run; this run was not promoted by a session"
)
"""Why a session figure skips a run no session promoted."""

NOT_A_RUNSET_REASON = "draws the envelope of several runs; pass a RunSet"
"""Why a runset figure refuses anything but a ``RunSet``."""

NOT_A_SESSION_REASON = "draws one calibration session; pass a Session or the run it promoted"
"""Why a session figure refuses anything but a ``Session``."""

NOT_A_RUN_REASON = "draws one run; pass a Run, such as the best run of a session"
"""Why a run figure refuses a ``Session`` or a ``RunSet``."""


def subject_refusal(subject: FigureSubject, obj: Any) -> str | None:
    """Return why a figure that draws ``subject`` cannot take ``obj``, else None.

    A session figure takes a ``Session`` and a runset figure a ``RunSet``,
    nothing else. A run figure takes anything but those two, so a test double
    of a run is a run. The display layer turns a promoted run into its
    session before it asks, so a run reaches a session figure only from a
    caller that skipped that step.
    """
    from hydromodpy.results.run.group import RunSet
    from hydromodpy.results.session.view import Session

    if subject == "session":
        return None if isinstance(obj, Session) else NOT_A_SESSION_REASON
    if subject == "runset":
        return None if isinstance(obj, RunSet) else NOT_A_RUNSET_REASON
    return NOT_A_RUN_REASON if isinstance(obj, (Session, RunSet)) else None


def _checks_subject(reason: Callable[..., str | None]) -> Callable[..., str | None]:
    """Make a figure's own ``unavailable_reason`` refuse the wrong subject first."""

    @functools.wraps(reason)
    def wrapper(self: BaseFigure, subject: Any) -> str | None:
        refusal = subject_refusal(self.spec.subject, subject)
        if refusal is not None:
            return refusal
        return reason(self, subject)

    return wrapper


FigureKind = Literal[
    "spatial",
    "section",
    "timeseries",
    "balance",
    "particles",
    "table",
    "comparison",
    "animation",
]


class FigureNotApplicable(DisplayError, ValueError):
    """Raised by a figure that finds, while reading the run, that it does not apply.

    :meth:`BaseFigure.unavailable_reason` refuses a run before drawing, from
    the run alone. Some refusals depend on the options too: a figure that
    reads one calibrated parameter applies to a session that sampled two once
    ``parameter`` names one. Such a figure raises this instead, and the batch
    renderer skips it with the message as its reason, as it skips an
    unavailable figure, whatever ``on_error`` says.
    """


@dataclass(frozen=True, slots=True)
class FigureSpec:
    """Static metadata describing one figure type.

    ``required_fields`` lists Zarr fields the figure reads (e.g. ``"head"``).
    ``required_tables`` lists DuckDB tables (e.g. ``"timeseries"``).
    Together they define whether one figure applies to a
    given run: :meth:`BaseFigure.unavailable_reason` turns them into a
    human-readable reason, so a figure that does not fit the configured
    processes is skipped explicitly instead of failing at render time.

    ``optional_fields`` lists fields the figure reads when they are there and
    does without otherwise. Required means "cannot render without"; optional
    means "compute it when this figure is asked for, but refuse with a
    sentence rather than be reported unavailable". A categorical map over a
    family of packages needs the family computed, not every member of it, so
    it declares the family here and its own ``unavailable_reason`` decides
    what a run missing all of them is told.

    ``subject`` names what the figure draws: ``"run"`` (the default), a
    calibration ``"session"`` or a ``"runset"``. ``render``, ``plot`` and
    ``unavailable_reason`` receive that object. A figure that compares a run
    with its reference stays a ``"run"`` figure and takes ``reference=``: a
    pair has an order and a ``RunSet`` has none.
    """

    name: str
    title: str
    former_names: tuple[str, ...] = ()
    """What this figure used to be called.

    A figure name is written in ``[display].figures`` and checked against the
    registry, so a rename refuses every project file that already lists it.
    Declaring the old spelling here keeps those files loading and warns with
    both names, which is the only way a reader learns what to write.
    """

    kind: FigureKind = "spatial"
    subject: FigureSubject = "run"
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    default_figsize: tuple[float, float] = (7.0, 5.0)


def _period_drawn(sim: Run, timestep: object) -> str | None:
    """Return the stress period a figure drew, for the PNG metadata.

    An ISO 8601 interval, ``"2002-10-01/2002-11-01"``, its end exclusive,
    when the run has dates, else ``"period <i>"``. ``None`` when the figure
    was given no instant.
    """
    if timestep is None or isinstance(timestep, bool):
        return None
    try:
        index = int(timestep)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return str(timestep)
    try:
        edges = sim.periods.edges
    except (AttributeError, RuntimeError, ValueError):
        # A stand-in run or a run without a stored grid: the index is all there is.
        edges = None
    if edges is None or len(edges) < 2:
        return f"period {index}"
    n = len(edges) - 1
    position = index + n if index < 0 else index
    if not 0 <= position < n:
        return f"period {index}"
    start, end = edges[position], edges[position + 1]
    return f"{_iso(start)}/{_iso(end)}"


def _iso(stamp) -> str:
    """Return a timestamp as a date at midnight, else to the second."""
    if stamp == stamp.normalize():
        return stamp.strftime("%Y-%m-%d")
    return stamp.strftime("%Y-%m-%dT%H:%M:%S")


_SHOW_RUN_NAME: ContextVar[bool] = ContextVar("hmp_show_run_name", default=True)


def run_label(sim: object) -> str:
    """Return the name a reader knows ``sim`` by, or "" when titles hide it.

    The run name, else its ``sim_id``. A figure drawn with
    ``show_run_name = false`` gets "" and writes no run in its titles.
    """
    if not _SHOW_RUN_NAME.get():
        return ""
    return str(getattr(sim, "name", None) or getattr(sim, "sim_id", None) or "")


def run_suffix(sim: object, fmt: str = " - {}") -> str:
    """Return the run label put in ``fmt``, or "" when titles hide it.

    Every figure writes the run into its titles through this, so
    ``show_run_name`` reaches every title in one place:
    ``f"Hydrograph{run_suffix(sim)} @ outlet"``.
    """
    label = run_label(sim)
    return fmt.format(label) if label else ""


def _apply_title(fig: MplFigure, title: str) -> None:
    """Replace the main title of ``fig``: its suptitle, else the first axes title."""
    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None and suptitle.get_text():
        suptitle.set_text(title)
        return
    if fig.axes:
        fig.axes[0].set_title(title)


_UNSET: Any = object()


def _titled(plot: Callable[..., MplFigure]) -> Callable[..., MplFigure]:
    """Give a figure's own ``plot`` the ``title`` and ``show_run_name`` options.

    The figure draws with the run name shown or hidden, then the title is
    replaced and the file written, so the saved image carries the title.
    """

    @functools.wraps(plot)
    def wrapper(
        self: BaseFigure,
        subject: Any,
        *args: Any,
        title: str | None = _UNSET,
        show_run_name: bool = _UNSET,
        **kwargs: Any,
    ) -> MplFigure:
        if title is _UNSET and show_run_name is _UNSET:
            return plot(self, subject, *args, **kwargs)
        save_path = kwargs.pop("save_path", None)
        token = _SHOW_RUN_NAME.set(bool(show_run_name)) if show_run_name is not _UNSET else None
        try:
            fig = plot(self, subject, *args, **kwargs)
        finally:
            if token is not None:
                _SHOW_RUN_NAME.reset(token)
        if title is not _UNSET and title is not None:
            _apply_title(fig, title)
        if save_path is not None:
            self._save(
                fig,
                Path(save_path),
                dpi=int(kwargs.get("dpi", 150)),
                sim=_provenance_run(subject, kwargs),
            )
        return fig

    return wrapper


_SUBPLOTS_KEYWORDS = frozenset(
    {
        "sharex",
        "sharey",
        "squeeze",
        "width_ratios",
        "height_ratios",
        "subplot_kw",
        "gridspec_kw",
    }
)


def new_figure(**figure_kw: Any) -> MplFigure:
    """Return an empty figure on its own Agg canvas, which the ``pyplot`` registry never holds.

    No backend is chosen or switched, so a render in one thread leaves every
    other thread alone. The canvas lets the figure be drawn, measured and
    saved. A figure nobody keeps is freed with its last reference, so a skipped
    render needs no ``close``.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure as MplFigure

    fig = MplFigure(**figure_kw)
    FigureCanvasAgg(fig)
    return fig


def new_subplots(nrows: int = 1, ncols: int = 1, **kwargs: Any) -> tuple[MplFigure, Any]:
    """Return a figure and its axes, as ``pyplot.subplots`` does, without ``pyplot``.

    The keywords ``pyplot.subplots`` hands to its grid (``sharex``, ``squeeze``,
    ``gridspec_kw``, ...) go to the grid and every other one to the figure
    (``figsize``, ``dpi``, ``constrained_layout``).
    """
    grid_kw = {key: kwargs.pop(key) for key in tuple(kwargs) if key in _SUBPLOTS_KEYWORDS}
    fig = new_figure(**kwargs)
    return fig, fig.subplots(nrows, ncols, **grid_kw)


class BaseFigure(ABC):
    """ABC providing the universal ``plot()`` boilerplate."""

    name: ClassVar[str] = ""
    spec: FigureSpec

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        spec = cls.__dict__.get("spec")
        if spec is not None and hasattr(spec, "name"):
            cls.name = spec.name
        own_plot = cls.__dict__.get("plot")
        if own_plot is not None:
            # A figure that lays out its own figure still takes the common options.
            cls.plot = _titled(own_plot)  # type: ignore[method-assign]
        own_reason = cls.__dict__.get("unavailable_reason")
        if own_reason is not None:
            # A figure that checks its own subject still refuses the wrong kind first.
            cls.unavailable_reason = _checks_subject(own_reason)  # type: ignore[method-assign]

    @abstractmethod
    def render(self, subject: Any, ax: Axes, **opts) -> Axes:
        raise NotImplementedError(
            "render must be implemented by subclasses (defines how the figure draws itself onto the given axes)."
        )

    def unavailable_reason(self, subject: Any) -> str | None:
        """Return why this figure cannot render ``subject``, or None when it can.

        For a run figure, checks the declared ``spec`` requirements against
        what the run actually persisted. This is what lets a project list
        every figure it may want and get only the ones its solver and
        processes produced: a run without particle tracking reports
        ``particle_tracks`` as unavailable rather than drawing an empty axes.
        Any figure first refuses an object of the wrong kind
        (:func:`subject_refusal`). A session or a runset figure declares no
        field or table of a run, so it checks what it reads in its own override.
        """
        refusal = subject_refusal(self.spec.subject, subject)
        if refusal is not None or self.spec.subject != "run":
            return refusal
        sim = subject
        missing_fields = [name for name in self.spec.required_fields if not sim.has_field(name)]
        if missing_fields:
            return f"missing result field(s): {', '.join(missing_fields)}"
        from hydromodpy.results.calibration_trials import run_feeds_table

        missing_tables = [
            name for name in self.spec.required_tables if not run_feeds_table(sim, name)
        ]
        if missing_tables:
            return f"missing catalog table(s): {', '.join(missing_tables)}"
        return None

    def plot(
        self,
        subject: Any,
        *,
        figsize: Figsize = None,
        title: Title = None,
        show_run_name: ShowRunName = True,
        dpi: int = 150,
        save_path: str | Path | None = None,
        **opts,
    ) -> MplFigure:
        fig, ax = new_subplots(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        # A figure's own plot that calls this one has already set the switch.
        token = _SHOW_RUN_NAME.set(bool(show_run_name) and _SHOW_RUN_NAME.get())
        try:
            self.render(subject, ax, **opts)
        finally:
            _SHOW_RUN_NAME.reset(token)
        if title is not None:
            _apply_title(fig, title)
        if save_path is not None:
            run = _provenance_run(subject, opts)
            self._save(
                fig,
                Path(save_path),
                dpi=dpi,
                sim=run,
                field=opts.get("variable") or opts.get("field"),
                time=_period_drawn(run, opts.get("timestep")),
            )
        return fig

    @staticmethod
    def _save(
        fig: MplFigure,
        path: Path,
        *,
        dpi: int,
        sim: Run | None = None,
        field: object = None,
        time: object = None,
    ) -> None:
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == "":
            path = path.with_suffix(".png")
        if path.suffix.lower() == ".png":
            from hydromodpy.display.png_metadata import write_png_with_metadata

            sim_id = getattr(sim, "sim_id", None) if sim is not None else None
            crs_epsg = _extract_crs_epsg(sim) if sim is not None else None
            write_png_with_metadata(
                fig,
                path,
                sim_id=sim_id,
                field=str(field) if field is not None else None,
                time=str(time) if time is not None else None,
                crs_epsg=crs_epsg,
                dpi=dpi,
            )
            return
        fig.savefig(path, dpi=dpi, bbox_inches="tight")

    @staticmethod
    def field_descriptor_for(variable: str) -> FieldDescriptor:
        """Return the canonical descriptor for ``variable``.

        Helper for figures that need ``long_name`` / ``units`` to label axes
        or colorbars without hard-coding strings. Raises
        :class:`~hydromodpy.core.exceptions.UnknownFieldError` if ``variable``
        is not registered.
        """
        return field_registry.get(variable)

    @staticmethod
    def axis_label_for(variable: str) -> str:
        """Return ``"<long_name> (<units>)"`` for ``variable`` from the registry."""
        desc = field_registry.get(variable)
        return f"{desc.long_name} ({desc.units})"


def _provenance_run(subject: Any, opts: Mapping[str, Any]) -> Any:
    """Return the run whose provenance a saved PNG carries.

    A session figure drawn for a promoted run carries that run's id and CRS.
    Any other figure carries its own subject: a run, or a session or a set of
    runs, which have no sim id and get a PNG without one.
    """
    promoted = opts.get(PROMOTED_OPTION)
    return promoted if promoted is not None else subject


def _extract_crs_epsg(sim: Run) -> int | None:
    """Return the EPSG code the catalog recorded for ``sim``, or ``None``.

    PNG provenance is optional. A subject with no catalog behind it (a
    session, a set of runs) still gets its PNG, without an EPSG.
    """
    from hydromodpy.results.run.geographic import crs_epsg

    try:
        return crs_epsg(sim)
    except Exception:  # provenance is optional; it never costs the PNG
        return None


# Arguments a caller of ``plot`` fills itself, never an option a user writes.
_NOT_OPTIONS = frozenset(
    {"self", "sim", "subject", "ax", "dpi", "save_path", "timestep", PROMOTED_OPTION}
)


def _walk_keywords(cls: type, method: str) -> tuple[set[str], bool]:
    """Collect the keyword names ``method`` accepts along the MRO of ``cls``.

    A ``**`` parameter named other than ``_`` forwards to the next definition
    up the MRO, so the walk goes on. The subject a figure draws, named ``sim``,
    ``session`` or ``runset``, is never an option. A ``**_`` swallows what is left, so the
    walk stops there. Returns the names and whether the walk reached
    :meth:`BaseFigure.plot`, which forwards its ``**opts`` to ``render``.
    """
    found: set[str] = set()
    for klass in cls.__mro__:
        func = klass.__dict__.get(method)
        if func is None:
            continue
        rest: str | None = None
        # The first two parameters are ``self`` and the subject, whatever its name.
        for param in list(inspect.signature(func).parameters.values())[2:]:
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                rest = param.name
            elif param.kind in (
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                found.add(param.name)
        if klass is BaseFigure:
            return found, True
        if rest is None or rest == "_":
            return found, False
    return found, False


@functools.cache
def option_names_of(cls: type) -> frozenset[str]:
    """Return the options a user may write for the figure class ``cls``.

    They are the named parameters of its ``plot`` and ``render``, read along
    the MRO while a ``**`` parameter forwards them. ``figsize`` comes from
    :meth:`BaseFigure.plot`, as ``title`` and ``show_run_name``, which every
    figure takes. A figure that draws one instant takes ``time``, which the
    display layer resolves to the step it draws; the internal ``timestep`` is
    never a user option. ``dpi`` belongs to ``[display]``.
    """
    found, forwards = _walk_keywords(cls, "plot")
    if forwards:
        render_names, _ = _walk_keywords(cls, "render")
        found |= render_names
    draws_one_instant = "timestep" in found
    found -= _NOT_OPTIONS
    if draws_one_instant:
        found.add("time")
    # ``title`` and ``show_run_name`` reach every figure, through BaseFigure.plot
    # or through the wrapper a figure's own plot gets.
    found |= set(COMMON_OPTIONS)
    return frozenset(found)


def option_types_of(cls: type) -> dict[str, Any]:
    """Return the declared type of every option of the figure class ``cls``.

    The type is the one its parameter declares, without the ``Annotated``
    metadata, ready for a ``pydantic.TypeAdapter``. ``time`` is text: a date,
    ``"first"`` or ``"last"``. An option whose type cannot be resolved, such as
    a class imported only for typing, maps to ``None``.
    """
    import typing

    from pydantic import TypeAdapter

    own = _declarations(cls)
    shared = _declarations(BaseFigure)
    types: dict[str, Any] = {}
    for option in option_names_of(cls):
        if option == "time":
            types[option] = str
            continue
        found = shared.get(option) if option in COMMON_OPTIONS else None
        found = found or own.get(option)
        if found is None:
            types[option] = None
            continue
        param, module_globals = found
        annotation = _evaluate(param.annotation, module_globals)
        if typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        if isinstance(annotation, str) or annotation is param.empty:
            types[option] = None
            continue
        try:
            TypeAdapter(annotation)
        except Exception:
            # A class pydantic cannot validate (a run, a name imported only for
            # typing): the caller keeps the value as it was written.
            types[option] = None
            continue
        types[option] = annotation
    return types


def options_of(cls: type) -> tuple[FigureOption, ...]:
    """Return every option of the figure class ``cls``: type, default, unit, meaning.

    Read from the parameters that take them (:mod:`hydromodpy.display.figure_options`),
    so the catalog of figures shows what the code declares and nothing else.
    """
    return describe_options(cls, option_names_of(cls), BaseFigure)
