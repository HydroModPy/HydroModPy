"""Semantic artifact IDs shared by report producers."""

from __future__ import annotations

from collections.abc import Mapping

SEMANTIC_ARTIFACT_ID_BY_FIGURE_ID: Mapping[str, str] = {
    "identity_stats": "catchment.identity.stats",
    "station_inventory": "observation.station.inventory",
    "regional_context": "catchment.context.regional_map",
    "dem_context": "catchment.context.dem_extent",
    "dem_map": "catchment.context.dem_map",
    "geology_map": "catchment.context.geology_map",
    "hydrography_map": "network.hydrography.reference_map",
    "climate_summary": "forcing.climate.summary",
    "observed_discharge_overview": "observation.discharge.overview",
    "observed_discharge_full": "observation.discharge.full_timeseries",
    "forcing_window": "forcing.simulation_window",
    "baseline_discharge_comparison": "simulation.discharge.observed_comparison",
    "network_comparison": "network.hydrography.reference_generated_comparison",
    "network_reference": "network.hydrography.reference",
    "network_generated": "network.hydrography.generated",
    "network_missing": "network.hydrography.reference_missing_from_generated",
    "network_extra": "network.hydrography.generated_extra",
    "active_network_overlay": "simulation.network.active_reference_overlay",
    "piezometric_map": "simulation.head.piezometric_map",
    "seepage_map": "simulation.seepage.map",
    "simulated_hydrograph": "simulation.discharge.timeseries",
    "water_budget": "simulation.water_budget.figure",
}


def semantic_artifact_id(figure_id: str) -> str:
    return SEMANTIC_ARTIFACT_ID_BY_FIGURE_ID.get(
        figure_id,
        f"catchment.figure.{figure_id}",
    )


__all__ = [
    "SEMANTIC_ARTIFACT_ID_BY_FIGURE_ID",
    "semantic_artifact_id",
]
