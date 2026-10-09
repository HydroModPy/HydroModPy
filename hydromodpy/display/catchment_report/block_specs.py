"""Declarative block specifications for generic catchment reports."""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.display.report_blocks import DetailLevel


@dataclass(frozen=True)
class BlockFigureSpec:
    """Where one PNG goes in a report block, and from which detail level.

    Not the ``FigureSpec`` of a registered figure (``hydromodpy.display.figure``).
    """

    minimum_level: DetailLevel
    figure_id: str
    title: str
    required: bool = True


@dataclass(frozen=True)
class ReportBlockSpec:
    block_id: str
    title: str
    lead: str
    content_key: str
    minimum_level: DetailLevel = "compact"
    figures: tuple[BlockFigureSpec, ...] = field(default_factory=tuple)


DEFAULT_BLOCK_SPECS: tuple[ReportBlockSpec, ...] = (
    ReportBlockSpec(
        block_id="site_context",
        title="Site",
        content_key="site_context",
        lead="Identification of the catchment and of the data available for it.",
        figures=(
            BlockFigureSpec("compact", "identity_stats", "Identity card"),
            BlockFigureSpec("standard", "station_inventory", "Station inventory"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydraulic_properties",
        title="Hydraulic properties",
        content_key="hydraulic_properties",
        lead="Hydraulic parameters used by the reference simulation.",
    ),
    ReportBlockSpec(
        block_id="spatial_context",
        title="Spatial context: DEM and geology",
        content_key="spatial_context",
        lead="Physical support of the catchment: regional setting, relief and geology.",
        figures=(
            BlockFigureSpec("compact", "regional_context", "Regional context"),
            BlockFigureSpec("compact", "dem_context", "DEM, catchment and outlet"),
            BlockFigureSpec("standard", "geology_map", "Catchment geology"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydrographic_network",
        title="Observed and generated hydrographic network",
        content_key="hydrographic_network",
        lead=(
            "Reference hydrography, network derived from the DEM and local differences. "
            "The contributing-area threshold is the one of the source simulation."
        ),
        figures=(
            BlockFigureSpec("compact", "hydrography_map", "Reference hydrographic network"),
            BlockFigureSpec(
                "standard", "network_generated", "DEM-generated network", required=False
            ),
            BlockFigureSpec("audit", "network_comparison", "Reference / DEM network comparison"),
            BlockFigureSpec(
                "audit",
                "network_missing",
                "Reference segments missing from the generated network",
                required=False,
            ),
            BlockFigureSpec(
                "audit", "network_extra", "Generated segments outside the reference", required=False
            ),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_network_outputs",
        title="Simulated active network and seepage",
        content_key="simulation_network_outputs",
        lead=(
            "Spatial simulation results: active network, comparison with the reference "
            "network and seepage zones when the figure is available."
        ),
        figures=(
            BlockFigureSpec(
                "standard", "active_network_overlay", "Simulated active network vs reference"
            ),
            BlockFigureSpec("compact", "seepage_map", "Simulated seepage map", required=False),
        ),
    ),
    ReportBlockSpec(
        block_id="forcing_flux_context",
        title="Fluxes, observed discharge and forcings",
        content_key="forcing_flux_context",
        lead=(
            "Observed discharge, reference simulated discharge and the climate context "
            "of the simulation window."
        ),
        figures=(
            BlockFigureSpec(
                "compact", "forcing_window", "Simulation window: observed and simulated discharge"
            ),
            BlockFigureSpec("audit", "observed_discharge_full", "Full observed discharge"),
            BlockFigureSpec("audit", "climate_summary", "Monthly climatology"),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_outputs",
        title="Simulated fluxes",
        content_key="simulation_outputs",
        lead="Hydrograph, head map and water budget of the reference simulation.",
        figures=(
            BlockFigureSpec(
                "compact", "baseline_discharge_comparison", "Observed vs simulated discharge"
            ),
            BlockFigureSpec("standard", "simulated_hydrograph", "Simulated hydrograph"),
            BlockFigureSpec("audit", "piezometric_map", "Head map"),
            BlockFigureSpec("audit", "water_budget", "Catchment water budget"),
        ),
    ),
    ReportBlockSpec(
        block_id="artifacts",
        title="Artifacts and limits",
        content_key="artifacts",
        minimum_level="audit",
        lead=(
            "Source paths, manifest and limits of the report. This page gathers "
            "the artifacts produced by the overview, context and simulation steps."
        ),
    ),
)


__all__ = [
    "BlockFigureSpec",
    "DEFAULT_BLOCK_SPECS",
    "ReportBlockSpec",
]
