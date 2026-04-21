"""Schoeller diagram (semi-log ion concentration profile)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


_IONS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


def _to_dataframe(source: Any):
    import pandas as pd

    if isinstance(source, pd.DataFrame):
        return source
    if hasattr(source, "timeseries"):
        try:
            return source.timeseries("hydrochemistry")
        except Exception as exc:
            raise ValueError(
                "schoeller_diagram: no hydrochemistry data available"
            ) from exc
    raise TypeError(f"schoeller_diagram: cannot read data from {type(source)!r}")


@register
class SchoellerDiagramFigure(BaseFigure):
    """Schoeller profile: ion concentration vs ion on a log axis."""

    spec = FigureSpec(
        name="schoeller_diagram",
        title="Schoeller diagram",
        kind="table",
        default_figsize=(7.0, 4.5),
    )

    def render(
        self,
        sim: "Run | Any",
        ax: "Axes",
        **_,
    ) -> "Axes":
        df = _to_dataframe(sim)
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
