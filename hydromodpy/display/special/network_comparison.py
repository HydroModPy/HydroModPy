"""The mapped and the generated networks matched at the tolerance of the run.

A line of one network is matched when it lies inside the tolerance buffer of the
other. The tolerance is the positional accuracy of the map the run was scored with,
else the default of the comparison. One map colours both networks on their lines,
mapped and generated lines that match, mapped lines the generated network misses and
generated lines that the map does not have, over the filled buffer of the mapped
network. The lengths, the missing and extra lengths, the ratios and the Hausdorff distance of the
comparison are written in a note.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.collections import LineCollection

from hydromodpy.display import static
from hydromodpy.display.subject import read_network
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.stream_network.criterion_settings import network_criterion_settings

CLASSES = (
    ("reference_matched_gdf", "matched_reference", "Mapped, matched", 1.0),
    ("candidate_matched_gdf", "valid", "Generated, matched", 0.6),
    ("reference_missing_gdf", "missing", "Mapped only", 1.4),
    ("candidate_extra_gdf", "extra", "Generated only", 1.4),
)


def _parts(frame: Any) -> list[np.ndarray]:
    return [
        np.asarray(part.coords)[:, :2]
        for geometry in frame.geometry
        for part in getattr(geometry, "geoms", [geometry])
    ]


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the buffer and the four classes of line on ``ax``, with the length note."""
    for role in ("reference", "generated"):
        read_network(subject, role)
    accuracy = network_criterion_settings(subject).observed_position_accuracy_m
    tolerance = {} if accuracy is None else {"tolerance_m": float(accuracy)}
    result = subject.hydrographic_network_comparison(**tolerance)
    buffer = result.reference_gdf.geometry.union_all().buffer(result.tolerance_m)
    for i, polygon in enumerate(getattr(buffer, "geoms", [buffer])):
        ax.fill(
            *polygon.exterior.xy, color=theme.roles["reference_network"], alpha=0.2, linewidth=0,
            zorder=1, label=f"Buffer, {result.tolerance_m:g} m" if i == 0 else None,
        )  # fmt: skip
    for name, role, label, scale in CLASSES:
        frame = getattr(result, name)
        ax.add_collection(
            LineCollection(
                _parts(frame),
                colors=theme.roles[role],
                linewidths=scale * theme.data_line_width,
                label=f"{label} ({len(frame)})",
                zorder=3,
                capstyle="round",
            )  # fmt: skip
        )
    bounds = np.array([result.reference_gdf.total_bounds, result.candidate_gdf.total_bounds])
    low, high = bounds[:, :2].min(axis=0), bounds[:, 2:].max(axis=0)
    pad = 0.04 * float(np.max(high - low))
    ax.set_title(f"Mapped and generated networks, tolerance {result.tolerance_m:g} m")
    static.map_axes(ax, theme, extent=(*(low - pad), *(high + pad)))
    static.legend(ax, theme)
    static.scale_bar(ax, theme, loc="upper right")
    km = 1000.0
    hausdorff = result.hausdorff_distance_m
    static.note(
        ax,
        f"Mapped length {result.reference_total_length_m / km:.1f} km, covered "
        f"{result.reference_coverage_ratio:.0%}\n"
        f"Generated length {result.candidate_total_length_m / km:.1f} km, matched "
        f"{result.candidate_match_ratio:.0%}\n"
        f"Missing {result.missing_reference_length_m:,.0f} m, extra "
        f"{result.extra_candidate_length_m:,.0f} m\n"
        f"Length F1 {result.length_f1_ratio:.2f}, Hausdorff "
        + ("unknown" if hausdorff is None else f"{hausdorff:,.0f} m"),
        theme,
    )
