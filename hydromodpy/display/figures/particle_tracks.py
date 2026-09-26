"""Particle pathlines drawn over the catchment footprint.

The pathlines come from :mod:`hydromodpy.results.run.particles`, which reads
the arrays the MODFLOW 6 PRT and the MODPATH extractors write alike, so the
same figure serves both backends and both tracking directions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.legend_placement import place_legend
from hydromodpy.display.map_axes import (
    RELATIVE_MAP_COLORBAR_LABEL_SIZE,
    RELATIVE_MAP_COLORBAR_TICK_SIZE,
    style_relative_km_axes,
)
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.results.run.particles import (
    has_particle_tracks,
    particle_time_to_days,
    read_particle_tracks,
    travel_time,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_DAYS_PER_YEAR = 365.25


@register
class ParticleTracks(BaseFigure):
    """Plan view of particle pathlines, coloured by travel time."""

    spec = FigureSpec(
        name="particle_tracks",
        title="Particle pathlines",
        kind="particles",
        required_fields=("particles",),
        default_figsize=(7.0, 5.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require a particle that moved, not only the ``particles`` group."""
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if not has_particle_tracks(sim):
            return "run holds no particle pathline: no particle moved from its release point"
        return None

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        cmap: str = "magma_r",
        lw: float = 0.7,
        max_tracks: int = 500,
        color_by: str = "travel_time",
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.collections import LineCollection

        tracks = read_particle_tracks(sim)
        if not tracks:
            raise ValueError(f"no particle pathlines stored for sim {sim.sim_id}")

        step = max(1, len(tracks) // max_tracks)
        selected = tracks[::step]
        segments = [track[:, :2] for track in selected]

        to_days = particle_time_to_days(sim)
        travel_years = np.array(
            [travel_time(track) * to_days / _DAYS_PER_YEAR for track in selected],
            dtype="float64",
        )
        has_time = bool(np.isfinite(travel_years).any()) and color_by == "travel_time"

        collection = LineCollection(segments, linewidths=lw, cmap=cmap)
        if has_time:
            collection.set_array(travel_years)
        else:
            collection.set_color("0.2")
        ax.add_collection(collection)
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()

        if has_time:
            cbar = ax.figure.colorbar(collection, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_label("Travel time (years)", fontsize=RELATIVE_MAP_COLORBAR_LABEL_SIZE)
            cbar.ax.tick_params(labelsize=RELATIVE_MAP_COLORBAR_TICK_SIZE)

        apply_overlays(ax, sim, ("watershed", "seepage") if overlays is None else overlays)
        style_relative_km_axes(ax)
        shown = f"{len(selected)} of {len(tracks)}" if step > 1 else f"{len(tracks)}"
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\n{shown} pathlines")
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
