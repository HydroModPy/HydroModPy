"""Schoeller diagram (semi-log ion concentration profile)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figures._hydrochem import hydrochem_frame, missing_samples_reason

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.view import Run


_IONS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


class SchoellerDiagramFigure(BaseFigure):
    """Schoeller profile: ion concentration vs ion on a log axis."""

    spec = FigureSpec(
        name="schoeller_diagram",
        title="Schoeller diagram",
        kind="table",
        default_figsize=(7.0, 4.5),
    )

    def unavailable_reason(self, sim: Run | Any) -> str | None:
        """Require hydrochemistry samples, which ``spec`` cannot declare.

        A DataFrame given directly is its own samples. A run is asked for its
        ``hydrochemistry`` series, read here and not drawn.
        """
        return super().unavailable_reason(sim) or missing_samples_reason(sim, "schoeller_diagram")

    def render(
        self,
        sim: Run | Any,
        ax: Axes,
        **_,
    ) -> Axes:
        df = hydrochem_frame(sim, "schoeller_diagram")
        missing = [c for c in _IONS if c not in df.columns]
        if missing:
            raise KeyError(f"schoeller_diagram: missing columns {missing}")
        x = np.arange(len(_IONS))
        for _, row in df.iterrows():
            y = np.array([float(row[c]) for c in _IONS], dtype=float)
            y = np.where(y <= 0, np.nan, y)
            ax.plot(x, y, marker="o", lw=0.8, alpha=0.7)
        ax.set_yscale("log")
        ax.set_xticks(x)
        ax.set_xticklabels(_IONS)
        ax.set_ylabel("Concentration (meq/L)")
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title("Schoeller diagram")
        return ax
