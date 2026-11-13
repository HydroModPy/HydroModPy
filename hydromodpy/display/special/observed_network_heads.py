"""The mapped network drawn from its heads, and how each head landed.

The heads rule keeps only where the map says a stream starts and lets the criterion
graph draw the rest. So the figure shows the trace, the cells a head walked down the
graph, with the mapped lines under it. A kept head is joined by a segment to the cell
it landed on, a free end that found no landing cell is a lost head, and the foot of a
dam is a forced head. The figure always redraws the run under the heads rule. A note gives the share of the
trace near the mapped network and the settings the tracing used.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.collections import PolyCollection

from hydromodpy.display import overlays, static
from hydromodpy.display.subject import FigureNotApplicable, read_mesh
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.stream_network.comparison import unavailable_reason_for_comparison
from hydromodpy.results.derive.stream_network.heads_view import network_heads_view_from_run

FULL_MARKS = (
    ("head_xy", "^", "well", "Head kept"),
    ("lost_xy", "x", "barrier", "Head lost"),
    ("forced_xy", "D", "storage", "Dam foot"),
)
PERMANENT_MARKS = (("head_xy", "v", "reference_network", "Permanent head kept"),)


def _trace(ax: Any, polygons: list, mask: np.ndarray, role: str, label: str, theme: Theme) -> None:
    cells = [polygons[i] for i in np.flatnonzero(mask)]
    colour = theme.roles[role]
    ax.add_collection(
        PolyCollection(
            cells, facecolors=colour, edgecolors=colour, linewidths=theme.line_width,
            label=f"{label} ({len(cells)} cells)", zorder=3,
        )
    )  # fmt: skip


def _heads(ax: Any, heads: Any, marks: tuple, theme: Theme, landing_label: str | None) -> None:
    for head, landing in zip(heads.head_xy, heads.landing_xy, strict=True):
        ax.plot(
            *zip(head, landing, strict=True),
            color=theme.roles["bounds"],
            linewidth=theme.line_width,
            zorder=4,
        )
    if heads.landing_xy.size:
        ax.scatter(*heads.landing_xy.T, s=3, color=theme.ink, zorder=5, label=landing_label)
    for name, marker, role, label in marks:
        points = getattr(heads, name)
        if points.size:
            ax.scatter(
                *points.T, s=22, marker=marker, color=theme.roles[role], zorder=7,
                label=f"{label} ({len(points)})",
            )  # fmt: skip


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the trace, the mapped lines and the kept, lost and forced heads on ``ax``."""
    reason = unavailable_reason_for_comparison(subject)
    if reason is not None:
        raise FigureNotApplicable(f"Run {subject.name!r}: {reason}.")
    try:
        view = network_heads_view_from_run(subject)
    except ValueError as error:
        raise FigureNotApplicable(f"Run {subject.name!r}: no head to draw ({error}).") from error
    mesh = read_mesh(subject)
    polygons = [mesh.vertices[ring[ring >= 0]] for ring in mesh.faces]
    _trace(ax, polygons, view.full.traced, "seepage", "Traced", theme)
    if view.permanent is not None:
        _trace(ax, polygons, view.permanent.traced, "reference_network", "Permanent trace", theme)
    for i, line in enumerate(view.mapped_lines_xy):
        ax.plot(
            line[:, 0], line[:, 1], color=theme.roles["outline"], linewidth=theme.line_width,
            zorder=2, label="Mapped network" if i == 0 else None,
        )  # fmt: skip
    _heads(ax, view.full, FULL_MARKS, theme, "Landing cell centre")
    if view.permanent is not None:
        _heads(ax, view.permanent, PERMANENT_MARKS, theme, None)
    overlays.outline(ax, subject, theme)
    box = np.concatenate([polygons[i] for i in np.flatnonzero(view.catchment)])
    pad = 0.04 * max(np.ptp(box[:, 0]), np.ptp(box[:, 1]))
    lost = int(view.full.indices["n_heads_lost"])
    ax.set_title(f"Heads: {int(view.full.indices['n_heads']) - lost} traced, {lost} lost")
    static.map_axes(ax, theme, extent=(*(box.min(axis=0) - pad), *(box.max(axis=0) + pad)))
    static.legend(ax, theme)
    static.scale_bar(ax, theme, loc="lower right")
    near = float(view.full.indices["heads_trace_near_map_share"])
    lines = [f"{near:.0%} of the trace near the mapped network" if np.isfinite(near) else ""]
    lines.append(view.settings_note)
    if view.redrawn_as_heads:
        lines.append("Redrawn under map.drawn_by = 'heads' with its default radius and area")
    static.note(ax, "\n".join(line for line in lines if line), theme, loc="upper left")
