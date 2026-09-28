"""Figure protocol and base class shared by every HydroModPy figure.

A figure is a class with a ``spec`` (static metadata) and a ``render(sim, ax)``
method (the only thing subclasses must implement). The ABC provides ``plot()``
which builds the matplotlib Figure, applies styling and handles saving.

All figures consume ``Run`` (catalog interface). They never touch a
solver, a raw output file or a ``ProjectState``.
"""

from __future__ import annotations

import functools
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import FieldDescriptor

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


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


class FigureNotApplicable(ValueError):
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
    ``required_solvers`` restricts the figure to specific solver backends
    (empty means any). Together they define whether one figure applies to a
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
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    required_solvers: tuple[str, ...] = ()
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


@runtime_checkable
class Figure(Protocol):
    """The unique figure contract."""

    spec: FigureSpec

    def render(self, sim: Run, ax: Axes, **opts) -> Axes: ...

    def plot(self, sim: Run, **opts) -> MplFigure: ...

    def unavailable_reason(self, sim: Run) -> str | None: ...


class BaseFigure(ABC):
    """ABC providing the universal ``plot()`` boilerplate."""

    spec: FigureSpec

    @abstractmethod
    def render(self, sim: Run, ax: Axes, **opts) -> Axes:
        raise NotImplementedError(
            "render must be implemented by subclasses (defines how the figure draws itself onto the given axes)."
        )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this figure cannot render ``sim``, or None when it can.

        Checks the declared ``spec`` requirements against what the run
        actually persisted. This is what lets a project list every figure it
        may want and get only the ones its solver and processes produced: a
        run without particle tracking reports ``particle_tracks`` as
        unavailable rather than drawing an empty axes.
        """
        solvers = self.spec.required_solvers
        if solvers:
            solver = str(getattr(sim, "solver", "") or "")
            if solver and solver not in solvers:
                return f"requires solver {' or '.join(solvers)}, run used '{solver}'"
        missing_fields = [name for name in self.spec.required_fields if not sim.has_field(name)]
        if missing_fields:
            return f"missing result field(s): {', '.join(missing_fields)}"
        missing_tables = [name for name in self.spec.required_tables if not sim.has_table(name)]
        if missing_tables:
            return f"missing catalog table(s): {', '.join(missing_tables)}"
        return None

    def plot(
        self,
        sim: Run,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        **opts,
    ) -> MplFigure:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        self.render(sim, ax, **opts)
        if save_path is not None:
            self._save(
                fig,
                Path(save_path),
                dpi=dpi,
                sim=sim,
                field=opts.get("variable") or opts.get("field"),
                time=_period_drawn(sim, opts.get("timestep")),
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


def _extract_crs_epsg(sim: Run) -> int | None:
    """Return the EPSG code the catalog recorded for ``sim``, or ``None``.

    PNG provenance is optional. A run-shaped object with no catalog behind it
    (the calibration report builds one from a session journal) still gets its
    PNG, without an EPSG.
    """
    from hydromodpy.results.run.geographic import crs_epsg

    try:
        return crs_epsg(sim)
    except Exception:  # provenance is optional; it never costs the PNG
        return None


# Arguments a caller of ``plot`` fills itself, never an option a user writes.
_NOT_OPTIONS = frozenset({"self", "sim", "ax", "dpi", "save_path", "timestep"})


def _walk_keywords(cls: type, method: str) -> tuple[set[str], bool]:
    """Collect the keyword names ``method`` accepts along the MRO of ``cls``.

    A ``**`` parameter named other than ``_`` forwards to the next definition
    up the MRO, so the walk goes on. A ``**_`` swallows what is left, so the
    walk stops there. Returns the names and whether the walk reached
    :meth:`BaseFigure.plot`, which forwards its ``**opts`` to ``render``.
    """
    found: set[str] = set()
    for klass in cls.__mro__:
        func = klass.__dict__.get(method)
        if func is None:
            continue
        rest: str | None = None
        for param in inspect.signature(func).parameters.values():
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
    :meth:`BaseFigure.plot`. A figure that draws one instant takes ``time``,
    which the display layer resolves to the step it draws; the internal
    ``timestep`` is never a user option. ``dpi`` belongs to ``[display]``.
    """
    found, forwards = _walk_keywords(cls, "plot")
    if forwards:
        render_names, _ = _walk_keywords(cls, "render")
        found |= render_names
    draws_one_instant = "timestep" in found
    found -= _NOT_OPTIONS
    if draws_one_instant:
        found.add("time")
    return frozenset(found)
