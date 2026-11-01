"""Candidate-building phases for site-selection builds."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS, Transformer
from shapely.geometry import box

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.io.crs import same_crs
from hydromodpy.site_selection.candidates.generation import (
    CandidateGenerationEvidence,
    candidate_generation_evidence_with_candidate_attributes,
    ensure_raw_accumulation_cells,
    generate_dem_area_light_candidate_outlets,
    generate_network_candidate_outlets,
)
from hydromodpy.site_selection.candidates.outlets import (
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from hydromodpy.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.site_selection.config.strategy_config import TerritoryConfig
from hydromodpy.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.site_selection.hydrology.reference_network import (
    ReferenceNetworkBundle,
    ReferenceNetworkFetcher,
    load_reference_network_for_outlets,
    score_outlets_against_reference_network,
)
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts

RawAccumulationBuilder = Callable[..., str | Path]

LAMBERT_93 = "EPSG:2154"
"""The default CRS of a French territory, and the CRS of the French data requests."""


@dataclass(frozen=True)
class GeneratedCandidateResult:
    """Generated candidates and the optional context used to build them."""

    candidates: list[CandidateOutlet]
    evidence: list[CandidateGenerationEvidence]
    search_geometry: object | None = None
    reference_network: object | None = None
    reference_bundle: ReferenceNetworkBundle | None = None
    raw_accumulation_path: Path | None = None


def build_station_candidate_outlets(
    records: Iterable[Any],
    *,
    config: SiteSelectionConfig,
    target_crs: str | None,
) -> list[CandidateOutlet]:
    """Build candidate outlets from already-loaded station records."""

    candidates = candidate_outlets_from_point_records(
        list(records),
        candidate_prefix="station",
        source="station_outlets",
        target_crs=target_crs,
    )
    if config.outlets.min_distance_between_outlets_km is None:
        return candidates
    return thin_candidate_outlets(
        candidates,
        min_distance_km=config.outlets.min_distance_between_outlets_km,
    )


def build_generated_network_candidates(
    *,
    config: SiteSelectionConfig,
    flow_products: FlowProducts,
    target_crs: str | None,
    root: Path,
    search_geometry: object | None,
    reference_network_fetcher: ReferenceNetworkFetcher,
) -> GeneratedCandidateResult:
    """Build DEM-network candidates and optionally score them against a reference network.

    *reference_network_fetcher* downloads BD Topage when the configuration asks for it.
    """

    candidates, evidence = generate_network_candidate_outlets(
        flow_products=flow_products,
        outlets=config.outlets,
        hydrology=config.hydrology,
        search_geometry=search_geometry,
    )
    reference_network, reference_bundle = load_reference_network_for_generated_candidates(
        config=config,
        candidates=candidates,
        target_crs=target_crs or first_candidate_crs(candidates),
        root=root,
        fetcher=reference_network_fetcher,
    )
    if reference_network is not None and reference_bundle is not None:
        candidates = score_outlets_against_reference_network(
            candidates,
            reference_network,
            max_distance_m=config.outlets.reference_network_max_distance_m,
            source=reference_bundle.source,
        )
        evidence = candidate_generation_evidence_with_candidate_attributes(
            evidence,
            candidates,
        )
    return GeneratedCandidateResult(
        candidates=candidates,
        evidence=evidence,
        search_geometry=search_geometry,
        reference_network=reference_network,
        reference_bundle=reference_bundle,
    )


def build_dem_area_light_candidates(
    *,
    config: SiteSelectionConfig,
    flow_products: FlowProducts,
    target_crs: str | None,
    root: Path,
    search_geometry: object | None,
    backend: object | None = None,
    raw_accumulation_builder: RawAccumulationBuilder | None = None,
) -> GeneratedCandidateResult:
    """Build lightweight DEM-area candidates around the configured target area."""

    if config.dem_area_light is None:
        raise ValueError("build_dem_area_light_candidates requires dem_area_light config.")

    raw_accumulation_path = (
        Path(
            raw_accumulation_builder(
                flow_products=flow_products,
                output_dir=root / "flow_products",
                backend=backend,
                crs_project=target_crs,
            )
        )
        if raw_accumulation_builder is not None
        else ensure_raw_accumulation_cells(
            flow_products=flow_products,
            output_dir=root / "flow_products",
            backend=backend,
            crs_project=target_crs,
        )
    )
    candidates, evidence = generate_dem_area_light_candidate_outlets(
        flow_products=flow_products,
        dem_area_light=config.dem_area_light,
        hydrology=config.hydrology,
        accumulation_cells_path=raw_accumulation_path,
        search_geometry=search_geometry,
        max_candidates_before_delineation=config.dem_area_light.max_candidates_before_delineation,
    )
    return GeneratedCandidateResult(
        candidates=candidates,
        evidence=evidence,
        search_geometry=search_geometry,
        raw_accumulation_path=raw_accumulation_path,
    )


def load_reference_network_for_station_candidates(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
    fetcher: ReferenceNetworkFetcher,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    """Load the reference network used to snap station-led outlets, when enabled."""

    if config.outlets.snap_strategy != "bdtopage_then_dem":
        return None, None
    return _load_reference_network_for_candidates(
        config=config,
        candidates=candidates,
        target_crs=target_crs,
        root=root,
        error_context="bdtopage_then_dem",
        fetcher=fetcher,
    )


def load_reference_network_for_generated_candidates(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
    fetcher: ReferenceNetworkFetcher,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    """Load a reference network for generated candidates when snapping or scoring needs it."""

    should_load_for_snap = config.outlets.snap_strategy == "bdtopage_then_dem"
    should_load_for_score_only = (
        config.outlets.snap_strategy == "dem_accumulation"
        and config.outlets.reference_network_path is not None
    )
    if not should_load_for_snap and not should_load_for_score_only:
        return None, None
    return _load_reference_network_for_candidates(
        config=config,
        candidates=candidates,
        target_crs=target_crs,
        root=root,
        error_context="Reference-network scoring",
        fetcher=fetcher,
    )


def site_selection_search_geometry(
    config: SiteSelectionConfig,
    *,
    target_crs: str | None,
) -> object | None:
    """Return the optional territory geometry used to constrain candidate sampling."""

    if not config.territory.clip_to_territory:
        return None
    return territory_geometry(config.territory, target_crs=target_crs)


def territory_geometry(
    territory: TerritoryConfig,
    *,
    target_crs: str | None,
) -> object:
    """Return the territory as one geometry in *target_crs*.

    The configuration keeps the administrative modes to France, so they read
    the French departments. A polygon file is united and made valid. A box is
    taken as written, in *target_crs*.
    """

    mode = territory.mode
    if mode == "admin_departments":
        from hydromodpy.spatial.administrative.france import geometry_for_departments

        return _make_search_geometry_valid(
            geometry_for_departments(territory.departments, target_crs=target_crs)
        )
    if mode == "admin_regions":
        from hydromodpy.spatial.administrative.france import geometry_for_regions

        return _make_search_geometry_valid(
            geometry_for_regions(territory.regions, target_crs=target_crs)
        )
    if mode == "polygon_file":
        frame = gpd.read_file(territory.polygon_file)
        if target_crs and frame.crs is not None and not same_crs(frame.crs.to_string(), target_crs):
            frame = frame.to_crs(target_crs)
        return _make_search_geometry_valid(_union_geometries(frame))
    return box(*territory.bbox)


def default_project_crs(territory: TerritoryConfig) -> str | None:
    """Return the CRS a territory falls back to: Lambert-93 in France, else ``None``."""

    return LAMBERT_93 if (territory.country or "").upper() == "FR" else None


def require_lambert93_extent(
    bounds: tuple[float, float, float, float],
    *,
    what: str,
    fix: str,
) -> None:
    """Refuse a box read in EPSG:2154 that falls outside the EPSG:2154 area of use.

    The area of use pyproj gives in degrees is projected into EPSG:2154 with
    densified edges, and the box is compared with it in metres, corners in any
    order. Comparing the corners in degrees would refuse a box of the whole
    country, because the north-east corner of a projected box lies east of the
    area in longitude. A box that is not finite is outside. *what* names the
    box and *fix* says what to write instead.
    """

    xmin, ymin, xmax, ymax = (float(value) for value in bounds)
    west, south, east, north = _lambert93_area_of_use()
    inside = (
        west <= min(xmin, xmax) <= max(xmin, xmax) <= east
        and south <= min(ymin, ymax) <= max(ymin, ymax) <= north
    )
    if not inside:
        raise ConfigValidationError(
            f"{what} {tuple(bounds)} is read in {LAMBERT_93} (Lambert-93) but lies "
            f"outside its area of use, metropolitan France and Corsica (x {west:.0f} "
            f"to {east:.0f} m, y {south:.0f} to {north:.0f} m). An overseas territory "
            f"needs its own CRS. {fix}"
        )


@cache
def _lambert93_area_of_use() -> tuple[float, float, float, float]:
    area = CRS.from_user_input(LAMBERT_93).area_of_use
    to_lambert = Transformer.from_crs("EPSG:4326", LAMBERT_93, always_xy=True)
    return to_lambert.transform_bounds(area.west, area.south, area.east, area.north, densify_pts=21)


def first_candidate_crs(candidates: list[CandidateOutlet]) -> str | None:
    """Return the first non-empty CRS found in candidate outlets."""

    for candidate in candidates:
        if candidate.crs:
            return candidate.crs
    return None


def _load_reference_network_for_candidates(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
    error_context: str,
    fetcher: ReferenceNetworkFetcher,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    if not target_crs:
        raise ValueError(f"{error_context} requires a projected outlet CRS.")
    network, bundle = load_reference_network_for_outlets(
        source=config.outlets.reference_network_source,
        path=config.outlets.reference_network_path,
        outlets=candidates,
        target_crs=target_crs,
        output_dir=root / "reference_network",
        fetcher=fetcher,
        fetch_margin_m=config.outlets.reference_network_fetch_margin_m,
        page_size=config.outlets.reference_network_page_size,
        force_refresh=config.outlets.reference_network_force_refresh,
    )
    return network, bundle


def _union_geometries(frame: object) -> object:
    geometry = frame.geometry[frame.geometry.notna() & (~frame.geometry.is_empty)]
    return geometry.union_all()


def _make_search_geometry_valid(geometry: object) -> object:
    if bool(getattr(geometry, "is_valid", True)):
        return geometry
    try:
        from shapely.validation import make_valid

        return make_valid(geometry)
    except Exception:
        return geometry.buffer(0)


__all__ = [
    "LAMBERT_93",
    "GeneratedCandidateResult",
    "build_dem_area_light_candidates",
    "build_generated_network_candidates",
    "build_station_candidate_outlets",
    "default_project_crs",
    "first_candidate_crs",
    "load_reference_network_for_generated_candidates",
    "load_reference_network_for_station_candidates",
    "require_lambert93_extent",
    "site_selection_search_geometry",
    "territory_geometry",
]
