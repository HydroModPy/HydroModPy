"""Where each cell sends its water on the descent, drawn as binned arrows over the relief.

The receiver of a cell comes from the descent of the run, which follows the channel
tree where there is one, so it is not always a neighbour. A map of every cell is a
black block, so the cells are binned on a square grid and each bin gets one arrow,
the mean unit direction of its cells drawn at its full length. A bin whose cells
disagree gets a short arrow, so the length reads as agreement. The cells the descent
raised on its copy of the top are ringed. The legend counts the cells with no receiver.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.collections import PolyCollection

from hydromodpy.display import static, variables
from hydromodpy.display.subject import FigureNotApplicable, read_field, read_mesh
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.stream_network.routing_surface import unavailable_reason_for_routing

TOPOGRAPHY = "topography"
BINS = 18
"""Arrows across the widest side of the domain."""


def _binned_arrows(points: np.ndarray, unit: np.ndarray, bins: int) -> np.ndarray:
    """Return one row ``(x, y, ux, uy, step)`` per occupied bin, with the mean position and direction."""
    origin = points.min(axis=0)
    step = float(np.ptp(points, axis=0).max()) / bins
    cell = np.minimum((points - origin) / step, bins - 1).astype(int)
    key = cell[:, 1] * bins + cell[:, 0]
    count = np.bincount(key, minlength=bins * bins)
    held = count > 0
    columns = (points[:, 0], points[:, 1], unit[:, 0], unit[:, 1])
    mean = [np.bincount(key, weights=c, minlength=bins * bins)[held] / count[held] for c in columns]
    return np.column_stack([*mean, np.full(held.sum(), step)])


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the relief, one arrow per bin and the raised cells on ``ax``."""
    reason = unavailable_reason_for_routing(subject)
    if reason is not None:
        raise FigureNotApplicable(f"Run {subject.name!r}: {reason}.")
    mesh = read_mesh(subject)
    receiver = np.asarray(subject.descent.receiver, dtype=int)
    raised = np.asarray(subject.descent.raised, dtype=bool)
    top = variables.to_display(TOPOGRAPHY, read_field(subject, TOPOGRAPHY))
    drawn = mesh.zones["domain"] & np.isfinite(top)
    polygons = [mesh.vertices[ring[ring >= 0]] for ring in mesh.faces[drawn]]
    relief = PolyCollection(
        polygons, array=top[drawn], cmap=variables.ramp(TOPOGRAPHY, theme), edgecolors="none",
        linewidths=0.0, antialiased=False, alpha=0.6, zorder=1,
    )  # fmt: skip
    relief.set_rasterized(True)
    ax.add_collection(relief)
    centres = mesh.centres
    delta = centres[np.where(receiver >= 0, receiver, 0)] - centres
    length = np.hypot(delta[:, 0], delta[:, 1])
    moving = drawn & (receiver >= 0) & (length > 0)
    if not moving.any():
        raise FigureNotApplicable(f"Run {subject.name!r}: no cell of the descent has a receiver.")
    arrows = _binned_arrows(centres[moving], delta[moving] / length[moving, None], BINS)
    scale = 1.0 / (0.85 * arrows[0, 4])
    ax.quiver(
        *arrows[:, :4].T, angles="xy", scale_units="xy", scale=scale, width=0.003, pivot="mid",
        color=theme.ink, zorder=5,
    )  # fmt: skip
    ax.plot([], [], color=theme.ink, marker=">", markersize=3, linewidth=theme.line_width,
            label=f"Receiver, mean of a bin ({len(arrows)} arrows)")  # fmt: skip
    ax.plot([], [], " ", label=f"{int((drawn & (receiver < 0)).sum())} cells have no receiver")
    if (raised & drawn).any():
        ax.scatter(
            *centres[raised & drawn].T, s=6, facecolors="none", edgecolors=theme.roles["barrier"],
            linewidths=theme.line_width, zorder=6, label=f"Raised by the descent ({(raised & drawn).sum()})",
        )  # fmt: skip
    box = np.concatenate(polygons)
    ax.set_title("Flow directions on the descent")
    static.map_axes(ax, theme, extent=(*box.min(axis=0), *box.max(axis=0)))
    static.colorbar(ax.figure, relief, ax, theme, label=variables.label(TOPOGRAPHY))
    static.legend(ax, theme)
    static.scale_bar(ax, theme, loc="lower right")
