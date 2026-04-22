"""Piper diagram of major-ion hydrochemistry.

The figure accepts either a :class:`Run` (in which case it
reads ``hydrochemistry`` observation-point data) or a pandas
``DataFrame`` with columns ``Ca, Mg, Na, K, Cl, SO4, HCO3`` (meq/L).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


_MAJORS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


def _to_dataframe(source: Any):
    """Return a pandas DataFrame of hydrochem samples from any supported input."""
    import pandas as pd

    if isinstance(source, pd.DataFrame):
        return source
    # Run: try a timeseries hook; fall back to None.
    if hasattr(source, "timeseries"):
        try:
            return source.timeseries("hydrochemistry")
        except Exception as exc:
            raise ValueError(
                "piper_diagram: no hydrochemistry data available on this simulation"
            ) from exc
    raise TypeError(f"piper_diagram: cannot read hydrochem data from {type(source)!r}")


@register
class PiperDiagramFigure(BaseFigure):
    """Classical Piper trilinear + diamond diagram."""

    spec = FigureSpec(
        name="piper_diagram",
        title="Piper diagram",
        kind="table",
        default_figsize=(7.5, 6.5),
    )

    def render(
        self,
        sim: "Run | Any",
        ax: "Axes",
        **_,
    ) -> "Axes":
        df = _to_dataframe(sim)
        missing = [c for c in _MAJORS if c not in df.columns]
        if missing:
            raise KeyError(f"piper_diagram: missing columns {missing}")
        cations = df[["Ca", "Mg", "Na", "K"]].to_numpy(dtype=float)
        anions = df[["Cl", "SO4", "HCO3"]].to_numpy(dtype=float)
        cat_sum = cations.sum(axis=1, keepdims=True)
        an_sum = anions.sum(axis=1, keepdims=True)
        cat_sum = np.where(cat_sum == 0, 1, cat_sum)
        an_sum = np.where(an_sum == 0, 1, an_sum)
        cations /= cat_sum
        anions /= an_sum

        # Left triangle (cations): Ca, Mg, Na+K
        ca, mg = cations[:, 0], cations[:, 1]
        nak = cations[:, 2] + cations[:, 3]
        xL = 0.5 * (2 * nak + mg)
        yL = (np.sqrt(3) / 2) * mg

        # Right triangle (anions): Cl, SO4, HCO3 — shifted by +2
        cl, so4, hco3 = anions[:, 0], anions[:, 1], anions[:, 2]
        xR = 2 + 0.5 * (2 * cl + so4)
        yR = (np.sqrt(3) / 2) * so4

        # Diamond
        xD = 0.5 * (xL + xR + 1)
        yD = (np.sqrt(3) / 2) + 0.5 * ((yL + yR) - 0.5 * (cl - nak))

        # Draw frames.
        tri_left = np.array([[0, 0], [1, 0], [0.5, np.sqrt(3) / 2], [0, 0]])
        tri_right = np.array([[2, 0], [3, 0], [2.5, np.sqrt(3) / 2], [2, 0]])
        diam = np.array(
            [
                [1.0, np.sqrt(3) / 2],
                [1.5, np.sqrt(3)],
                [2.0, np.sqrt(3) / 2],
                [1.5, 0.0],
                [1.0, np.sqrt(3) / 2],
            ]
        )
        for shape in (tri_left, tri_right, diam):
            ax.plot(shape[:, 0], shape[:, 1], "k-", lw=0.8)

        ax.scatter(xL, yL, c="tab:blue", s=20, alpha=0.8, label="cations")
        ax.scatter(xR, yR, c="tab:green", s=20, alpha=0.8, label="anions")
        ax.scatter(xD, yD, c="tab:red", s=20, alpha=0.8, label="facies")
        ax.set_xlim(-0.1, 3.1)
        ax.set_ylim(-0.1, np.sqrt(3) + 0.1)
        ax.set_aspect("equal")
        ax.set_axis_off()
        ax.legend(loc="lower center", ncol=3, frameon=False)
        ax.set_title("Piper diagram")
        return ax
