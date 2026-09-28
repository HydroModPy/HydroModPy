"""What the two snap figures share: the snap of a run, its palette, its note.

The snap is read through the comparison the other stream maps read, so the map
of the snap and the map of the agreement are drawn from one construction and
cannot disagree about which cells the criterion scored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_snap import (
    SNAP_MERGED,
    SNAP_MOVED,
    SNAP_REJECTED,
    SNAP_UNCHANGED,
    StreamSnap,
)
from hydromodpy.display.figures._stream_comparison import comparison_from_run
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET
from hydromodpy.results.derive.snapped_network import (
    snap_of_comparison,
    snap_settings_of_run,
)
from hydromodpy.results.derive.stream_network import unavailable_reason_for_comparison

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

STATUS_COLORS: dict[int, str] = {
    SNAP_UNCHANGED: "#7F7F7F",
    SNAP_MOVED: HIGH_CONTRAST_TRIPLET[0],
    SNAP_MERGED: HIGH_CONTRAST_TRIPLET[1],
    SNAP_REJECTED: HIGH_CONTRAST_TRIPLET[2],
}
"""One colour per status: grey where nothing moved, red where nothing could."""

STATUS_ORDER: tuple[int, ...] = (SNAP_UNCHANGED, SNAP_MOVED, SNAP_MERGED, SNAP_REJECTED)


def snap_unavailable_reason(sim: Run) -> str | None:
    """Return why this run holds no snap to draw, or None when it does."""
    reason = unavailable_reason_for_comparison(sim)
    if reason is not None:
        return reason
    if snap_settings_of_run(sim) is None:
        return "[geographic.snap_streams] mode is off for this run"
    return None


def snap_from_run(sim: Run) -> StreamSnap:
    """Return the snap the run's own setting produces, through the scored construction."""
    return snap_of_comparison(comparison_from_run(sim))


def snap_note(snap: StreamSnap) -> str:
    """Return the indices a snap figure prints beside what it draws."""
    return "\n".join(
        [
            f"mode {snap.mode}, radius {snap.radius_m:.4g} m, h_obs {snap.h_obs_m:.4g} m",
            f"displacement p50 {snap.displacement_p50_m:.4g} m, p90 "
            f"{snap.displacement_p90_m:.4g} m (bound {snap.displacement_bound_m:.4g} m)",
            f"rejected {snap.rejected_share:.1%} (bound {snap.rejected_share_max:.0%}), "
            f"length ratio {snap.length_ratio:.3f}, connected {snap.connected_share:.1%}",
            f"floor F = {snap.floor_m:.4g} m",
        ]
    )


def status_cells(snap: StreamSnap, code: int) -> np.ndarray:
    """Return the raw mapped cells of one status."""
    return np.flatnonzero(snap.raw & (snap.status == code))


__all__ = (
    "STATUS_COLORS",
    "STATUS_ORDER",
    "snap_from_run",
    "snap_note",
    "snap_unavailable_reason",
    "status_cells",
)
