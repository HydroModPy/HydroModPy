"""Generic, reusable figure functions for HydroModPy display.

Every ``render_*`` function takes an existing Axes and renders in place.
Every ``plot_*`` convenience wrapper creates a figure, renders, and optionally
saves via :func:`~hydromodpy.display.common.finalize_figure`.

These functions accept only primitive/generic types (arrays, DataFrames, dicts)
so they can be called from any context (simulation, overview, standalone).
"""

from hydromodpy.display.figures.animation import build_gif, build_plotly_slider
from hydromodpy.display.figures.boussinesq import (
    plot_boussinesq_state,
    render_boussinesq_state,
)
from hydromodpy.display.figures.cross_section import (
    plot_cross_section,
    render_cross_section,
)
from hydromodpy.display.figures.maps import (
    plot_dem_map,
    plot_geology_map,
    plot_hydrography_map,
    plot_pathlines_map,
    render_dem_map,
    render_geology_map,
    render_hydrography_map,
    render_pathlines_map,
)
from hydromodpy.display.figures.spatial import (
    plot_concentration_map,
    plot_raster_field,
    render_concentration_map,
    render_raster_field,
)
from hydromodpy.display.figures.tables import (
    plot_stats_card,
    plot_station_inventory,
    render_stats_card,
    render_station_inventory,
)
from hydromodpy.display.figures.timeseries import (
    plot_climatic_summary,
    plot_concentration_panel,
    plot_discharge,
    plot_intermittency,
    plot_piezometry,
    plot_water_quality,
    render_climatic_summary,
    render_concentration_panel,
    render_discharge,
    render_intermittency,
    render_piezometry,
    render_water_quality,
)

__all__ = [
    # maps
    "render_dem_map",
    "render_geology_map",
    "render_hydrography_map",
    "render_pathlines_map",
    "plot_dem_map",
    "plot_geology_map",
    "plot_hydrography_map",
    "plot_pathlines_map",
    # timeseries
    "render_discharge",
    "render_piezometry",
    "render_climatic_summary",
    "render_intermittency",
    "render_water_quality",
    "render_concentration_panel",
    "plot_discharge",
    "plot_piezometry",
    "plot_climatic_summary",
    "plot_intermittency",
    "plot_water_quality",
    "plot_concentration_panel",
    # spatial
    "render_raster_field",
    "render_concentration_map",
    "plot_raster_field",
    "plot_concentration_map",
    # boussinesq
    "render_boussinesq_state",
    "plot_boussinesq_state",
    # cross section
    "render_cross_section",
    "plot_cross_section",
    # tables
    "render_stats_card",
    "render_station_inventory",
    "plot_stats_card",
    "plot_station_inventory",
    # animation
    "build_gif",
    "build_plotly_slider",
]
