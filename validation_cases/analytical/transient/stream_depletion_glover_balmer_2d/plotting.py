"""Figure of the stream depletion 2D case: depletion, drawdowns and the error map."""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Categorical slots, the diverging poles and the text inks of the figure.
_SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")
_DIVERGING = ("#2a78d6", "#f0efec", "#e34948")
_INK = "#52514e"


def plot_stream_depletion_comparison(
    comparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save the depletion fraction, the monitor drawdowns and the final error map."""
    import matplotlib

    if not show_plot:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

    days = comparison.elapsed_days
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.8), constrained_layout=True)

    ax = axes[0]
    ax.plot(days, comparison.analytical_depletion_fraction, color=_INK, lw=2, ls="--")
    ax.plot(days, comparison.numerical_depletion_fraction, color=_SERIES[0], lw=2)
    ax.set_xlabel("time (d)")
    ax.set_ylabel("stream depletion Qs / Q (-)")
    ax.set_title(f"Stream depletion, max error {comparison.depletion_max_error:.4f}", fontsize=10)
    ax.legend(["erfc (Glover and Balmer)", comparison.solver_name], frameon=False)

    ax = axes[1]
    for index, (x_m, y_m) in enumerate(comparison.monitor_cell_xy_m):
        color = _SERIES[index % len(_SERIES)]
        ax.plot(days, comparison.analytical_drawdown[:, index], color=color, lw=1.5, ls="--")
        ax.plot(days, comparison.numerical_drawdown_mean[:, index], color=color, lw=2)
        ax.annotate(
            f"({x_m:.0f}, {y_m - comparison.well_xy_m[1]:+.0f}) m",
            (days[-1], comparison.numerical_drawdown_mean[-1, index]),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=7,
            color=_INK,
            va="center",
        )
    ax.set_xlabel("time (d)")
    ax.set_ylabel("drawdown (m)")
    ax.set_title(
        f"Monitor drawdowns (dashed: image wells), RMSE {comparison.space_time_rmse:.4f} m",
        fontsize=10,
    )

    ax = axes[2]
    error = np.asarray(comparison.map_simulated) - np.asarray(comparison.map_reference)
    finite = np.isfinite(error)
    bound = float(np.max(np.abs(error[finite]))) if np.any(finite) else 1.0
    cells = PolyCollection(
        [
            np.asarray(polygon)
            for polygon, keep in zip(comparison.map_cell_polygons, finite)
            if keep
        ],
        array=error[finite],
        cmap=LinearSegmentedColormap.from_list("diverging", _DIVERGING),
        norm=TwoSlopeNorm(vcenter=0.0, vmin=-bound, vmax=bound),
        edgecolors="none",
    )
    ax.add_collection(cells)
    ax.autoscale_view()
    ax.set_aspect("equal")
    well_x, well_y = comparison.map_overlay["well"]
    ax.plot([well_x], [well_y], marker="o", ms=8, mfc="none", mec=_INK, mew=1.5)
    ax.set_xlabel("distance from the stream face (m)")
    ax.set_ylabel("distance along the stream from the well (m)")
    ax.set_title("Final head error, simulated minus closed form", fontsize=10)
    fig.colorbar(cells, ax=ax, label="head error (m)")

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=dpi)
    if show_plot:
        plt.show()
    plt.close(fig)
    return output_png
