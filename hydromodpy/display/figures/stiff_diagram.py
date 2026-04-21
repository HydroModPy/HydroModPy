"""Stiff diagram of hydrochemical composition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.simulation import SimulationView


def _to_dataframe(source: Any):
    import pandas as pd

    if isinstance(source, pd.DataFrame):
        return source
    if hasattr(source, "timeseries"):
        try:
            return source.timeseries("hydrochemistry")
        except Exception as exc:
            raise ValueError(
                "stiff_diagram: no hydrochemistry data available"
            ) from exc
    raise TypeError(f"stiff_diagram: cannot read data from {type(source)!r}")


@register
class StiffDiagramFigure(BaseFigure):
    """Horizontal Stiff polygon (cations left, anions right)."""

    spec = FigureSpec(
        name="stiff_diagram",
        title="Stiff diagram",
        kind="table",
        default_figsize=(5.5, 4.5),
    )

    def render(
        self,
        sim: "SimulationView | Any",
        ax: "Axes",
        *,
        sample: int = 0,
        **_,
    ) -> "Axes":
        df = _to_dataframe(sim)
        row = df.iloc[sample]
        # Cations on the left (negative x), anions on the right (positive x).
        # Rows from top to bottom: Na+K / Ca / Mg (cations), Cl / HCO3 / SO4 (anions).
        na_k = float(row.get("Na", 0.0) + row.get("K", 0.0))
        ca = float(row.get("Ca", 0.0))
        mg = float(row.get("Mg", 0.0))
        cl = float(row.get("Cl", 0.0))
        hco3 = float(row.get("HCO3", 0.0))
        so4 = float(row.get("SO4", 0.0))

        xs = np.array([-na_k, -ca, -mg, so4, hco3, cl, -na_k])
        ys = np.array([3, 2, 1, 1, 2, 3, 3])
        ax.fill(xs, ys, color="tab:blue", alpha=0.5, edgecolor="black", lw=1.0)
        ax.axvline(0.0, color="black", lw=0.8)
        ax.set_yticks([1, 2, 3])
        ax.set_yticklabels(["Mg | SO4", "Ca | HCO3", "Na+K | Cl"])
        ax.set_xlabel("meq/L")
        max_side = max(abs(xs.min()), xs.max(), 1.0)
        ax.set_xlim(-max_side * 1.1, max_side * 1.1)
        ax.set_ylim(0.5, 3.5)
        ax.set_title(f"Stiff diagram — sample {sample}")
        return ax
