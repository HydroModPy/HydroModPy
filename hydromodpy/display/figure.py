"""Figure protocol and base class shared by every HydroModPy figure.

A figure is a class with a ``spec`` (static metadata) and a ``render(sim, ax)``
method (the only thing subclasses must implement). The ABC provides ``plot()``
which builds the matplotlib Figure, applies styling and handles saving.

All figures consume ``Run`` (catalog interface). They never touch a
solver, a raw output file or a ``ProjectState``.
"""

from __future__ import annotations

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
    """

    name: str
    title: str
    kind: FigureKind = "spatial"
    required_fields: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    required_solvers: tuple[str, ...] = ()
    default_figsize: tuple[float, float] = (7.0, 5.0)


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
                time=opts.get("time") or opts.get("timestep"),
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
    """Pull the EPSG integer code from a ``Run`` instance when available.

    Tries the catalog-backed ``simulations.crs_epsg`` column first; falls
    back to ``None`` rather than raising, so PNG metadata stays optional.
    """
    try:
        catalog = getattr(sim, "_catalog", None)
        sim_id = getattr(sim, "_sim_id", None) or getattr(sim, "sim_id", None)
        if catalog is None or sim_id is None:
            return None
        backend = getattr(catalog, "backend", None)
        if backend is None:
            return None
        df = backend.query(
            "SELECT crs_epsg FROM simulations WHERE sim_id = ?",
            [sim_id],
        )
        if df.empty:
            return None
        value = df.iloc[0]["crs_epsg"]
        if value is None:
            return None
        return int(value)
    except Exception:
        return None
