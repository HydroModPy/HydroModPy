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
    These hints let the catalog and the CLI validate compatibility before
    calling ``render``.
    """

    name: str
    title: str
    kind: FigureKind = "spatial"
    required_fields: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    default_figsize: tuple[float, float] = (7.0, 5.0)


@runtime_checkable
class Figure(Protocol):
    """The unique figure contract."""

    spec: FigureSpec

    def render(self, sim: "Run", ax: "Axes", **opts) -> "Axes": ...

    def plot(self, sim: "Run", **opts) -> "MplFigure": ...


class BaseFigure(ABC):
    """ABC providing the universal ``plot()`` boilerplate."""

    spec: FigureSpec

    @abstractmethod
    def render(self, sim: "Run", ax: "Axes", **opts) -> "Axes":
        raise NotImplementedError

    def plot(
        self,
        sim: "Run",
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        **opts,
    ) -> "MplFigure":
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        self.render(sim, ax, **opts)
        if save_path is not None:
            self._save(fig, Path(save_path), dpi=dpi)
        return fig

    @staticmethod
    def _save(fig: "MplFigure", path: Path, *, dpi: int) -> None:
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == "":
            path = path.with_suffix(".png")
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
