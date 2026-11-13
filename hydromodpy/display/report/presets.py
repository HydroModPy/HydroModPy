"""The report presets and the text the caller gives to the engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hydromodpy.display.report.engine import Level
from hydromodpy.display.request import FigureRequest

SHEET_FIGURES: tuple[str, ...] = ("watershed_id_card", "hydrograph", "seepage_mask")

GAUGE = "gauge"
"""Station of a report request that the caller fills with the gauge of the site."""

LAKE = "lake"
"""Station of a report request that the caller fills with the lake of the run."""

_MAP_OVERLAYS = ["relief", "outline"]


def _request(name: str, **fields: object) -> FigureRequest:
    return FigureRequest.model_validate({"name": name, **fields})


REPORT_FIGURES: dict[str, FigureRequest] = {
    request.name: request
    for request in (
        _request("watershed_id_card", preset="watershed_id_card"),
        _request("seepage_mask", variable="seepage_mask", time="last"),
        _request("hydrograph", preset="hydrograph", station=GAUGE),
        _request(
            "network_agreement",
            variable="network_agreement",
            time="last",
            overlays=_MAP_OVERLAYS,
        ),
        _request(
            "generated_network",
            variable="topography",
            overlays=[*_MAP_OVERLAYS, "generated_network"],
        ),
        _request(
            "flowing_frequency",
            variable="simulated_active_network",
            reduce="frequency",
            overlays=["outline", "network"],
        ),
        _request("water_budget", preset="water_budget"),
        _request("hydrograph_log", preset="hydrograph", scale="log", station=GAUGE),
        _request(
            "watertable_elevation",
            variable="watertable_elevation",
            overlays=[*_MAP_OVERLAYS, "stations"],
        ),
        _request("reference_network", variable="topography", overlays=[*_MAP_OVERLAYS, "network"]),
        _request("downslope_distance", variable="downslope_distance", scale="log"),
        _request("watertable_depth", variable="watertable_depth", time="last"),
        _request("cross_section", variable="watertable_elevation", type="section"),
        _request(
            "flowing_cells",
            variable="simulated_active_network",
            time="last",
            overlays=[*_MAP_OVERLAYS, "network"],
        ),
        _request("network_comparison", preset="network_comparison"),
        _request("calibration_progress", preset="calibration_progress"),
        _request("parameter_trace", variable="trials.parameter", type="series", facet="parameter"),
        _request(
            "parameter_distribution",
            variable="trials.parameter",
            type="distribution",
            facet="parameter",
        ),
        _request("calibration_landscape", preset="calibration_landscape"),
        _request(
            "scatter_one_to_one",
            variable="discharge",
            type="xy",
            observed=True,
            reference=["one_to_one"],
            scores=True,
            station=GAUGE,
        ),
        _request("lake_stage", variable="stage", observed=True, station=LAKE),
    )
}
"""One request per report figure, keyed by the file stem the report reads."""


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
            "compact": ("watershed_id_card", "seepage_mask", "hydrograph"),
            "standard": (
                "network_agreement",
                "generated_network",
                "flowing_frequency",
                "water_budget",
                "hydrograph_log",
                "watertable_elevation",
            ),
            "audit": (
                "reference_network",
                "downslope_distance",
                "watertable_depth",
                "cross_section",
                "flowing_cells",
                "network_comparison",
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
