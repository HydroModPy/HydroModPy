"""Plotting helpers for the 2D recharge mound case."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection


def plot_hantush_recharge_mound_comparison(
    comparison,
    *,
    output_png: str | Path,
    show_plot: bool = True,
    dpi: int = 160,
) -> Path:
    """Save one figure: centre rise over time, transect profiles and final error map."""
    reference_cfg = dict(comparison.metadata.get("reference", {}))
    initial_head = float(reference_cfg["initial_head_m"])
    fig, axes = plt.subplots(1, 3, figsize=(16.0, 4.8))

    days = np.asarray(comparison.elapsed_days, dtype=float)
    axes[0].plot(days, comparison.analytical_centre_rise, "k-", label="Hantush (1967)")
    axes[0].plot(days, comparison.numerical_centre_rise, "o", ms=3, label="simulated")
    axes[0].set_xlabel("time (d)")
    axes[0].set_ylabel("head rise at the centre (m)")
    axes[0].legend()

    for index in np.unique(np.linspace(0, days.size - 1, 4).round().astype(int)):
        line = axes[1].plot(
            comparison.x, comparison.analytical_profiles[index] - initial_head, "-"
        )[0]
        axes[1].plot(
            comparison.x,
            comparison.numerical_profiles[index] - initial_head,
            "o",
            ms=2.5,
            color=line.get_color(),
            label=f"t = {days[index]:.1f} d",
        )
    axes[1].set_xlabel("x from the centre (m)")
    axes[1].set_ylabel("head rise on the transect (m)")
    axes[1].legend()

    error = np.asarray(comparison.map_simulated) - np.asarray(comparison.map_reference)
    bound = float(np.nanmax(np.abs(error))) or 1.0
    collection = PolyCollection(
        [np.asarray(polygon) for polygon in comparison.map_cell_polygons],
        array=error,
        cmap="RdBu_r",
        clim=(-bound, bound),
        edgecolors="none",
    )
    axes[2].add_collection(collection)
    half = float(reference_cfg["transect_half_length_m"])
    axes[2].set_xlim(-half, half)
    axes[2].set_ylim(-half, half)
    axes[2].set_aspect("equal")
    axes[2].set_title(f"final head error (m), t = {days[-1]:.1f} d")
    fig.colorbar(collection, ax=axes[2], shrink=0.8)

    fig.suptitle(
        "Recharge mound 2D: "
        f"w={float(reference_cfg['recharge_mm_day']):.0f} mm/d on "
        f"{2 * float(reference_cfg['half_length_x_m']):.0f} x "
        f"{2 * float(reference_cfg['half_width_y_m']):.0f} m, "
        f"K={float(reference_cfg['hydraulic_conductivity_m_per_s']):.0e} m/s, "
        f"Sy={float(reference_cfg['specific_yield']):.2f}, hi={initial_head:.0f} m"
    )
    fig.tight_layout()
    output_path = Path(output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=int(dpi))
    if show_plot:
        plt.show()
    plt.close(fig)
    return output_path
