"""Figure of the plan-view strip with a rotated K tensor."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .comparison import RotatedPlanComparison


def plot_rotated_plan_comparison(
    comparison: RotatedPlanComparison,
    *,
    output_png: str | Path,
    show_plot: bool = False,
    dpi: int = 160,
) -> Path:
    """Save the head map with its window and the head across the strip."""
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stored, fit = comparison.stored, comparison.fit
    window_x = stored.x[comparison.window[0]]

    fig, (ax_map, ax_cut) = plt.subplots(2, 1, figsize=(9.0, 7.0), dpi=dpi)
    sc = ax_map.scatter(stored.x, stored.y, c=stored.heads[0], s=6, marker="s", cmap="viridis")
    ax_map.axvspan(window_x.min(), window_x.max(), color="k", alpha=0.12, label="window")
    ax_map.set_xlabel("x (m)")
    ax_map.set_ylabel("y (m)")
    ax_map.set_title(f"Head, ANGLE1 = {comparison.angle1_deg:+.0f} deg")
    ax_map.legend(loc="upper right")
    fig.colorbar(sc, ax=ax_map, label="head (m)")

    centre = float(np.mean(comparison.profile_reference))
    ax_cut.plot(comparison.profile_y_m, comparison.profile_reference - centre, "-", label="exact")
    ax_cut.plot(comparison.profile_y_m, comparison.profile_numerical - centre, "o", label="run")
    ax_cut.set_xlabel("y (m)")
    ax_cut.set_ylabel("head minus its mean (m)")
    ax_cut.set_title(
        f"Across the middle: direction error {fit.gradient_ratio_error:.1e}, "
        f"head error {fit.head_max_error:.1e} m, end flow error {fit.flow_error:.1e}"
    )
    ax_cut.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    if show_plot:
        plt.show()
    plt.close(fig)
    return output_path


__all__ = ["plot_rotated_plan_comparison"]
