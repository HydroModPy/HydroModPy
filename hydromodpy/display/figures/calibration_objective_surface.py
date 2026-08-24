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

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


def _pair(table: TrialTable, parameters: tuple[str, ...] | list[str] | None) -> tuple[str, str]:
    """Name the two parameters the surface spans, and refuse to guess."""
    if parameters is None:
        sampled = table.parameters
        if len(sampled) != 2:
            raise ValueError(
                "calibration_objective_surface: a surface spans exactly two parameters, "
                f"and the session sampled {', '.join(sampled) or '<none>'}. Use the "
                "`parameters=` kwarg to pick two."
            )
        return sampled[0], sampled[1]
    if not isinstance(parameters, (list, tuple)) or len(parameters) != 2:
        raise ValueError(
            "calibration_objective_surface: `parameters=` must be a length-2 "
            "sequence (e.g. parameters=('K', 'Sy'))"
        )
    return str(parameters[0]), str(parameters[1])


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
        parameters: tuple[str, ...] | list[str] | None = None,
        objective: str | None = None,
        session_id: str | None = None,
        grid_size: int = 120,
        **_,
    ) -> Axes:
        table = trial_table(sim, session_id=session_id)
        first, second = _pair(table, parameters)
        _, px = table.parameter_values(first)
        _, py = table.parameter_values(second)
        objective_name, pz = table.objective_values(objective)
        finite = np.isfinite(px) & np.isfinite(py) & np.isfinite(pz)
        px, py, pz = px[finite], py[finite], pz[finite]
        if px.size < 4:
            raise ValueError(
                "calibration_objective_surface: need at least 4 finite evaluations "
                f"(have {px.size})"
            )
        # A surface needs a plane to be drawn on. A one-dimensional search, or
        # two parameters a phase moved together, gives collinear points: the
        # triangulation is then degenerate and the interpolation returns an
        # all-NaN grid that draws as an empty panel with a colour bar.
        spread = np.column_stack([px - px.mean(), py - py.mean()])
        if np.linalg.matrix_rank(spread) < 2:
            raise ValueError(
                f"calibration_objective_surface: the trials of {first!r} and {second!r} are "
                "collinear, so they span no surface to interpolate. A one-dimensional search "
                "is read on calibration_trace or parameter_cost_profile."
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
        fig.colorbar(pcm, ax=ax, label=objective_name)
        ax.set_xlabel(first)
        ax.set_ylabel(second)
        ax.set_title(f"Objective surface ({method}) - {sim.name or sim.sim_id}")
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
