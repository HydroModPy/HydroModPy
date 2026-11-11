"""The report presets and the text the caller gives to the engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hydromodpy.display.report.engine import Level

SHEET_FIGURES: tuple[str, ...] = ("watershed_id_card", "hydrograph_sim_obs", "seepage_map")


@dataclass(frozen=True, slots=True)
class ReportTexts:
    """Text the engine shows, written by the caller from the phrase table."""

    method: str
    label: str
    titles: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Preset:
    """A preset: its page shape, the run figures it names by level, the overview panels."""

    name: str
    levels: bool
    figures: Mapping[Level, tuple[str, ...]]
    panels: tuple[str, ...]


PRESETS: dict[str, Preset] = {
    "research": Preset(
        name="research",
        levels=True,
        figures={
            "compact": ("watershed_id_card", "seepage_map", "hydrograph_sim_obs"),
            "standard": (
                "network_extent_bounds_map",
                "hydrographic_network_generated",
                "flow_persistence_map",
                "flow_intermittence_map",
                "seepage_network_confusion_map",
                "flux_timeseries",
                "hydrograph_log_nse",
                "piezometric_map",
                "water_budget",
            ),
            "audit": (
                "hydrographic_network_permanence",
                "downslope_distance_map",
                "watertable_depth_map",
                "cross_section",
                "simulated_active_network_reference_overlay",
                "hydrographic_network_comparison",
                "hydrographic_network_reference_missing_only",
                "hydrographic_network_generated_extra_only",
            ),
        },
        panels=(
            "stats_card",
            "station_inventory",
            "map_regional_context",
            "map_dem",
            "map_geology",
            "map_hydrography",
            "climatic_summary",
            "timeseries_discharge",
        ),
    ),
    "management": Preset(
        name="management",
        levels=False,
        figures={"compact": SHEET_FIGURES, "standard": (), "audit": ()},
        panels=(),
    ),
}


def preset_figures(preset: Preset) -> tuple[str, ...]:
    """Return every run figure a preset names, once, in level order."""
    return tuple(dict.fromkeys(name for names in preset.figures.values() for name in names))
