"""Map of the stream network feeding the SFR package, with routed-flow context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figures.sfr_reach_timeseries import sfr_reach_stations
from hydromodpy.display.geo import GeoFigureMixin
from hydromodpy.display.map_axes import overlay_watershed_contour, style_relative_km_axes

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class SfrReachNetwork(GeoFigureMixin, BaseFigure):
    """The delineated stream network that the SFR reaches discretize.

    Draws the persisted ``generated`` hydrographic network (the exact linework
    the SFR delineation consumed; per-segment Strahler colouring applies when
    the persisted layer carries a ``strahler`` column) and annotates the routed
    state read from the store: reach count and the terminal reach's last
    ``downstream_flow``.
    """

    spec = FigureSpec(
        name="sfr_reach_network",
        title="SFR reach network",
        kind="spatial",
        required_tables=("timeseries",),
        default_figsize=(7.0, 6.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "downstream_flow",
        **_,
    ) -> Axes:
        triples = sfr_reach_stations(sim, variable)
        if not triples:
            raise KeyError(f"sfr_reach_network: no SFR '{variable}' series for sim {sim.sim_id}")
        network_id = triples[0][0]
        terminal_station = triples[-1][2]
        terminal_flow = float(sim.timeseries(variable, station=terminal_station).iloc[-1])

        gdf = sim.hydrographic_network("generated")
        if gdf is None or gdf.empty:
            raise KeyError(
                f"sfr_reach_network: no generated hydrographic network for sim {sim.sim_id}"
            )
        strahler_column = next(
            (column for column in gdf.columns if column.lower() == "strahler"), None
        )
        if strahler_column is not None:
            gdf.plot(ax=ax, column=strahler_column, cmap="Blues", linewidth=1.8, zorder=4)
        else:
            gdf.plot(ax=ax, color="steelblue", linewidth=1.5, alpha=0.95, zorder=4)
        overlay_watershed_contour(
            ax,
            sim,
            color="#404040",
            linewidth=0.9,
            alpha=0.7,
            target_crs=None if gdf.crs is None else str(gdf.crs),
        )
        style_relative_km_axes(ax)
        self.add_scale_bar(ax)
        self.add_north_arrow(ax)
        ax.set_title(f"SFR reach network - {sim.name or sim.sim_id}")
        ax.text(
            0.02,
            0.98,
            "\n".join(
                [
                    f"network: {network_id}",
                    f"reaches: {len(triples)}",
                    f"terminal {variable}: {terminal_flow:.4g} m³/s",
                ]
            ),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
        )
        return ax
