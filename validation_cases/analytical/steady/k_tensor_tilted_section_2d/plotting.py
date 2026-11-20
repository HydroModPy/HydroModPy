"""Figure of the vertical section with a tilted K tensor."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .comparison import TiltedSectionComparison


def plot_tilted_section_comparison(
    comparison: TiltedSectionComparison,
    *,
    output_png: str | Path,
    show_plot: bool = False,
    dpi: int = 160,
) -> Path:
    """Save the heads of the section with its window and the head against elevation."""
    output_path = Path(output_png).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stored, fit = comparison.stored, comparison.fit
    window_x = stored.x[comparison.window[0]]
    x = np.broadcast_to(stored.x, stored.heads.shape)

    fig, (ax_sec, ax_cut) = plt.subplots(2, 1, figsize=(9.0, 7.0), dpi=dpi)
    sc = ax_sec.scatter(x, stored.z, c=stored.heads, s=10, marker="s", cmap="viridis")
    ax_sec.axvspan(window_x.min(), window_x.max(), color="k", alpha=0.12, label="window")
    ax_sec.set_xlabel("x (m)")
    ax_sec.set_ylabel("elevation (m)")
    ax_sec.set_title(f"Head, ANGLE2 = {comparison.angle2_deg:+.0f} deg")
    ax_sec.legend(loc="upper right")
    fig.colorbar(sc, ax=ax_sec, label="head (m)")

    centre = float(np.mean(comparison.profile_reference))
    ax_cut.plot(comparison.profile_reference - centre, comparison.profile_z_m, "-", label="exact")
    ax_cut.plot(comparison.profile_numerical - centre, comparison.profile_z_m, "o", label="run")
    ax_cut.set_xlabel("head minus its mean (m)")
    ax_cut.set_ylabel("elevation (m)")
    ax_cut.set_title(
        f"At the middle: direction error {fit.gradient_ratio_error:.1e}, "
        f"head error {fit.head_max_error:.1e} m, end flow error {fit.flow_error:.1e}"
    )
    ax_cut.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    if show_plot:
        plt.show()
    plt.close(fig)
    return output_path


__all__ = ["plot_tilted_section_comparison"]
