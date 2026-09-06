"""Vertical cross-section of the aquifer along a line across the mesh.

Draws the classic hydrogeological section: land surface, water table, the
saturated body between them, the model layers below, and the seepage
segments where the water table outcrops. The section is defined in map
coordinates, so it is valid whatever the grid type.

Where the line crosses a stream reach it also marks the streambed and the
elevation at which MODFLOW disconnects the reach from the aquifer. Without
them a reader compares the water table to the land surface, while the solver
compares it to a threshold set metres lower, so a connected reach reads as a
detached water table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.legend_placement import place_legend
from hydromodpy.display.transect import build_transect, layer_interfaces

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class CrossSection(BaseFigure):
    """Topography, water table and layering along one transect.

    Options
    -------
    ``line``
        ``[x0, y0, x1, y1]`` in the project CRS. Overrides ``orientation``.
    ``orientation``
        ``"we"`` (west to east, default) or ``"sn"`` (south to north).
    ``through``
        ``[x, y]`` the section must pass through. Defaults to the outlet.
    ``timestep``
        Index of the stress period to draw; defaults to the last one.
    """

    spec = FigureSpec(
        name="cross_section",
        title="Cross-section",
        kind="section",
        required_fields=("watertable_elevation", "topography"),
        optional_fields=("streambed_top", "streambed_connection"),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        line: tuple[float, float, float, float] | list[float] | None = None,
        orientation: str = "we",
        through: tuple[float, float] | list[float] | None = None,
        n_samples: int | None = None,
        **_,
    ) -> Axes:
        from hydromodpy.display.ugrid import last_timestep

        step = last_timestep(sim) if timestep is None else timestep
        transect = build_transect(
            sim,
            line=tuple(line) if line is not None else None,
            orientation="sn" if str(orientation).lower() == "sn" else "we",
            through=tuple(through) if through is not None else None,
            n_samples=n_samples,
        )
        if not transect.inside.any():
            raise ValueError("cross-section line does not intersect the mesh")

        distance = transect.distance
        topography = transect.sample(np.asarray(sim.field("topography")))
        watertable = transect.sample(np.asarray(sim.field("watertable_elevation", timestep=step)))
        # The water table cannot be drawn above ground; the derived field already
        # clips it, this only guards a solver that reports a perched head.
        watertable = np.minimum(watertable, topography)

        interfaces = layer_interfaces(sim)
        bottom = (
            transect.sample(interfaces[-1])
            if interfaces is not None
            else np.full_like(topography, np.nan)
        )

        ax.fill_between(
            distance,
            watertable,
            topography,
            color="saddlebrown",
            alpha=0.35,
            lw=0,
            label="Unsaturated zone",
        )
        if np.isfinite(bottom).any():
            ax.fill_between(
                distance,
                bottom,
                watertable,
                color="dodgerblue",
                alpha=0.35,
                lw=0,
                label="Saturated zone",
            )
            ax.plot(distance, bottom, color="dimgray", lw=1.6, label="Aquifer base")
            if interfaces is not None and interfaces.shape[0] > 2:
                for index in range(1, interfaces.shape[0] - 1):
                    ax.plot(
                        distance,
                        transect.sample(interfaces[index]),
                        color="dimgray",
                        lw=0.7,
                        ls=":",
                    )
        ax.plot(distance, topography, color="saddlebrown", lw=1.8, label="Topography")
        ax.plot(distance, watertable, color="navy", lw=1.8, label="Water table")

        self._mark_streambed(ax, sim, transect)
        self._mark_seepage(ax, sim, transect, topography, step)

        ax.set_xlabel("Distance along section (m)")
        ax.set_ylabel("Elevation (m)")
        ax.set_xlim(float(distance[transect.inside].min()), float(distance[transect.inside].max()))
        ax.grid(True, ls=":", lw=0.4, alpha=0.6)
        place_legend(ax, fontsize=8, framealpha=0.9)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\n{_line_label(transect)}")
        return ax

    @staticmethod
    def _mark_streambed(ax: Axes, sim: Run, transect) -> None:
        """Mark the streambed and the connection threshold where the line crosses one.

        Reaches occupy isolated cells along the line, so this draws markers and
        not a continuous profile: joining them would invent a channel between
        two crossings that the section never meets.
        """
        if not sim.has_field("streambed_top"):
            return
        bed = transect.sample(np.asarray(sim.field("streambed_top")))
        on_reach = np.isfinite(bed)
        if not on_reach.any():
            return
        distance = transect.distance
        ax.scatter(
            distance[on_reach],
            bed[on_reach],
            s=26,
            marker="_",
            linewidths=2.0,
            color="teal",
            zorder=6,
            label="Streambed",
        )
        if not sim.has_field("streambed_connection"):
            return
        threshold = transect.sample(np.asarray(sim.field("streambed_connection")))
        visible = np.isfinite(threshold)
        if not visible.any():
            return
        ax.scatter(
            distance[visible],
            threshold[visible],
            s=26,
            marker="_",
            linewidths=1.4,
            color="firebrick",
            zorder=6,
            label="Disconnection threshold",
        )
        ax.vlines(
            distance[visible],
            threshold[visible],
            bed[visible],
            color="firebrick",
            lw=0.8,
            alpha=0.55,
            zorder=5,
        )

    @staticmethod
    def _mark_seepage(
        ax: Axes,
        sim: Run,
        transect,
        topography: np.ndarray,
        timestep: int,
    ) -> None:
        """Highlight the outcropping segments of the section, if stored."""
        if not sim.has_field("seepage_mask"):
            return
        mask = transect.sample(np.asarray(sim.field("seepage_mask", timestep=timestep))) > 0
        if not mask.any():
            return
        ax.scatter(
            transect.distance[mask],
            topography[mask],
            s=14,
            marker="o",
            color="black",
            zorder=5,
            label="Seepage",
        )


def _line_label(transect) -> str:
    """Return a short human description of the sampled line."""
    x0, y0 = transect.x[0], transect.y[0]
    x1, y1 = transect.x[-1], transect.y[-1]
    length = transect.distance[-1]
    return f"({x0:,.0f}, {y0:,.0f}) -> ({x1:,.0f}, {y1:,.0f}), {length:,.0f} m"
