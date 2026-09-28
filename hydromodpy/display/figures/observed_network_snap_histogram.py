"""How far the snap moved each mapped cell, as a histogram.

The p90 of this distribution is what Eq. 4 bounds when the snap is applied,
so the bound and the radius are drawn on it: a distribution piled against the
radius says the snap reached as far as it was allowed to, and the rejected
cells, which have no displacement, are counted in the key rather than left
out silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_snap import SNAP_REJECTED, SNAP_STATUS_LABELS
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._observed_network_snap import (
    STATUS_COLORS,
    STATUS_ORDER,
    snap_from_run,
    snap_note,
    snap_unavailable_reason,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class ObservedNetworkSnapHistogram(BaseFigure):
    """Displacement of the mapped cells under ``[geographic.snap_streams]``."""

    spec = FigureSpec(
        name="observed_network_snap_histogram",
        title="Displacement of the mapped cells",
        kind="comparison",
        required_fields=("release_flux",),
        default_figsize=(7.0, 4.8),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run holds no snap, or None when it does."""
        return snap_unavailable_reason(sim) or super().unavailable_reason(sim)

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
        snap = snap_from_run(sim)
        placed = [code for code in STATUS_ORDER if code != SNAP_REJECTED]
        series = [snap.displacement_m[snap.raw & (snap.status == code)] for code in placed]
        largest = max(
            [float(np.nanmax(values)) for values in series if values.size] + [snap.radius_m]
        )
        step = snap.h_obs_m / 4.0 if snap.h_obs_m > 0.0 else largest / 20.0
        edges = np.arange(0.0, largest + 2.0 * step, step) - step / 2.0
        edges[0] = 0.0
        ax.hist(
            series,
            bins=edges,
            stacked=True,
            color=[STATUS_COLORS[code] for code in placed],
            label=[
                f"{SNAP_STATUS_LABELS[code]} ({values.size})"
                for code, values in zip(placed, series, strict=True)
            ],
        )
        n_rejected = int(np.count_nonzero(snap.raw & (snap.status == SNAP_REJECTED)))
        ax.axvline(
            snap.displacement_bound_m,
            color="#222222",
            linestyle="--",
            label=f"p90 bound {snap.displacement_bound_m:.4g} m",
        )
        ax.axvline(
            snap.radius_m, color="#222222", linestyle=":", label=f"radius {snap.radius_m:.4g} m"
        )
        if np.isfinite(snap.displacement_p90_m):
            ax.axvline(
                snap.displacement_p90_m,
                color=STATUS_COLORS[SNAP_REJECTED],
                linewidth=1.5,
                label=f"p90 {snap.displacement_p90_m:.4g} m",
            )
        ax.plot([], [], " ", label=f"rejected, no displacement ({n_rejected})")
        ax.set_xlabel("displacement (m)")
        ax.set_ylabel("mapped cells")
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        ax.legend(title=snap_note(snap), fontsize=8, title_fontsize=8, loc="upper right")
        return ax


__all__ = ["ObservedNetworkSnapHistogram"]
