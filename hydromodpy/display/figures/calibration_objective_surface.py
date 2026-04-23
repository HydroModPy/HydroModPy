"""Objective surface over a 2D slice of the calibration parameter space.

Interpolates the objective function (stored in ``calibration_iterations``)
over a regular 2D grid using scipy's ``griddata`` and overlays the evaluated
points. This is a simplified port of the original 605-LOC helper which also
fitted a Gaussian-process surrogate; we only keep the RAM-side interpolation
(``cubic`` with ``linear`` fallback) which is enough for inspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


def _load_iterations(sim: Run, session_id: str | None) -> pd.DataFrame:
    iters = getattr(sim, "calibration_iterations", None)
    if iters is None:
        raise ValueError("calibration_objective_surface: simulation has no calibration_iterations")
    df = pd.DataFrame(iters)
    if session_id is not None and "session_id" in df.columns:
        df = df[df["session_id"] == session_id]
    if df.empty:
        raise ValueError("calibration_objective_surface: iteration set is empty")
    return df.reset_index(drop=True)


def _interp_cubic_then_linear(
    pts: np.ndarray,
    vals: np.ndarray,
    xi: np.ndarray,
    yi: np.ndarray,
) -> tuple[np.ndarray, str]:
    from scipy.interpolate import griddata

    grid = np.column_stack([xi.ravel(), yi.ravel()])
    try:
        zz = griddata(pts, vals, grid, method="cubic")
        if np.all(np.isnan(zz)):
            raise ValueError("all-nan cubic result")
        method = "cubic"
    except Exception:
        zz = griddata(pts, vals, grid, method="linear")
        method = "linear"
    return zz.reshape(xi.shape), method


@register
class CalibrationObjectiveSurfaceFigure(BaseFigure):
    """Heatmap/contour of the calibration objective over a 2D parameter plane."""

    spec = FigureSpec(
        name="calibration_objective_surface",
        title="Calibration objective surface",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(7.5, 6.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        parameters: tuple[str, ...] = ("K", "Sy"),
        objective: str = "objective_value",
        session_id: str | None = None,
        grid_size: int = 120,
        **_,
    ) -> Axes:
        if not isinstance(parameters, (list, tuple)) or len(parameters) != 2:
            raise ValueError(
                "calibration_objective_surface: `parameters=` must be a length-2 "
                "sequence (e.g. parameters=('K', 'Sy'))"
            )

        df = _load_iterations(sim, session_id)

        if objective not in df.columns and "objective" in df.columns:
            objective = "objective"
        missing = [p for p in parameters if p not in df.columns]
        if missing or objective not in df.columns:
            available = ", ".join(sorted(df.columns))
            raise ValueError(
                "calibration_objective_surface: missing columns "
                f"{missing + ([objective] if objective not in df.columns else [])}"
                f" (available: {available}). Use the `parameters=` kwarg to pick two."
            )

        px = df[parameters[0]].to_numpy(dtype=float)
        py = df[parameters[1]].to_numpy(dtype=float)
        pz = df[objective].to_numpy(dtype=float)
        finite = np.isfinite(px) & np.isfinite(py) & np.isfinite(pz)
        px, py, pz = px[finite], py[finite], pz[finite]
        if px.size < 4:
            raise ValueError(
                "calibration_objective_surface: need at least 4 finite evaluations "
                f"(have {px.size})"
            )

        n = max(25, int(grid_size))
        xi, yi = np.meshgrid(
            np.linspace(px.min(), px.max(), n),
            np.linspace(py.min(), py.max(), n),
        )
        zz, method = _interp_cubic_then_linear(np.column_stack([px, py]), pz, xi, yi)

        pcm = ax.pcolormesh(xi, yi, zz, cmap="viridis", shading="auto")
        cs = ax.contour(xi, yi, zz, colors="white", linewidths=0.5, alpha=0.6)
        ax.clabel(cs, inline=True, fontsize=7, fmt="%.3g")
        ax.scatter(px, py, c=pz, cmap="viridis", edgecolors="black", s=22, lw=0.4)

        best = int(np.argmin(pz))
        ax.scatter([px[best]], [py[best]], marker="*", s=180, c="red", edgecolors="black", lw=0.6)

        fig = ax.figure
        fig.colorbar(pcm, ax=ax, label=objective)
        ax.set_xlabel(parameters[0])
        ax.set_ylabel(parameters[1])
        ax.set_title(f"Objective surface ({method}) — {sim.name or sim.sim_id}")
        return ax

    def plot(
        self,
        sim: Run,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **opts,
    ) -> MplFigure:
        return super().plot(sim, figsize=figsize, dpi=dpi, save_path=save_path, **opts)
