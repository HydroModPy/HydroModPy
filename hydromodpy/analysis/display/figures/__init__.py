"""Generic, reusable figure functions for HydroModPy display.

Every ``render_*`` function takes an existing Axes and renders in place.
Every ``plot_*`` convenience wrapper creates a figure, renders, and optionally
saves via :func:`~hydromodpy.analysis.display.common.finalize_figure`.

These functions accept only primitive/generic types (arrays, DataFrames, dicts)
so they can be called from any context (simulation, overview, standalone).
"""

from hydromodpy.analysis.display.figures.animation import (
    build_gif,
    build_mp4,
    build_plotly_slider,
)
from hydromodpy.analysis.display.figures.boussinesq import (
    plot_boussinesq_diagnostics,
    plot_boussinesq_edge_flux_map,
    plot_boussinesq_state,
    render_boussinesq_diagnostics,
    render_boussinesq_edge_flux_map,
    render_boussinesq_state,
)
from hydromodpy.analysis.display.figures.cross_section import (
    plot_cross_section,
    render_cross_section,
)
from hydromodpy.analysis.display.figures.flow_diagnostics import (
    plot_flow_mass_balance,
    plot_flow_probe_timeseries,
    render_flow_mass_balance,
    render_flow_probe_timeseries,
)
from hydromodpy.analysis.display.figures.flow_synthesis import (
    plot_flow_recharge_discharge_cumulative,
    plot_flow_spatial_field,
    plot_flow_state_triptych,
    render_flow_recharge_discharge_cumulative,
    render_flow_spatial_field,
    render_flow_state_triptych,
)
from hydromodpy.analysis.display.figures.maps import (
    plot_dem_map,
    plot_geology_map,
    plot_hydrography_map,
    plot_pathlines_map,
    render_dem_map,
    render_geology_map,
    render_hydrography_map,
    render_pathlines_map,
)
from hydromodpy.analysis.display.figures.spatial import (
    plot_concentration_map,
    plot_raster_field,
    render_concentration_map,
    render_raster_field,
)
from hydromodpy.analysis.display.figures.tables import (
    plot_stats_card,
    plot_station_inventory,
    render_stats_card,
    render_station_inventory,
)
from hydromodpy.analysis.display.figures.timeseries import (
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
    # generic flow diagnostics
    "render_flow_mass_balance",
    "render_flow_probe_timeseries",
    "plot_flow_mass_balance",
    "plot_flow_probe_timeseries",
    "render_flow_spatial_field",
    "render_flow_state_triptych",
    "render_flow_recharge_discharge_cumulative",
    "plot_flow_spatial_field",
    "plot_flow_state_triptych",
    "plot_flow_recharge_discharge_cumulative",
    # boussinesq
    "render_boussinesq_diagnostics",
    "render_boussinesq_edge_flux_map",
    "render_boussinesq_state",
    "plot_boussinesq_diagnostics",
    "plot_boussinesq_edge_flux_map",
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
    "build_mp4",
    "build_plotly_slider",
]
