"""Candidate-building phases for site-selection builds."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.candidates.candidate_builders import (
    CandidateAuditEvidence,
    build_dem_area_target_candidate_outlets,
    build_network_candidate_outlets,
    candidate_audit_evidence_with_candidate_attributes,
    ensure_raw_accumulation_cells,
)
from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    ReferenceNetworkBundle,
    load_reference_network_for_outlets,
    score_outlets_against_reference_network,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

RawAccumulationBuilder = Callable[..., str | Path]


@dataclass(frozen=True)
class CandidateBuildResult:
    """Candidate outlets and the optional context used to build them."""

    candidates: list[CandidateOutlet]
    evidence: list[CandidateAuditEvidence]
    search_geometry: object | None = None
    reference_network: object | None = None
    reference_bundle: ReferenceNetworkBundle | None = None
    raw_accumulation_path: Path | None = None


def build_station_candidate_outlets(
    records: Iterable[Any],
    *,
    config: SiteSelectionConfig,
    target_crs: str | None,
    preserve_all: bool = False,
) -> list[CandidateOutlet]:
    """Build candidate outlets from already-loaded station records."""

    candidates = candidate_outlets_from_point_records(
        list(records),
        candidate_prefix="station",
        source="station_outlets",
        target_crs=target_crs,
    )
    if preserve_all or config.outlets.min_distance_between_outlets_km is None:
        return candidates
    return thin_candidate_outlets(
        candidates,
        min_distance_km=config.outlets.min_distance_between_outlets_km,
    )


def build_dem_network_candidates(
    *,
    config: SiteSelectionConfig,
    flow_products: SiteSelectionFlowProducts,
    target_crs: str | None,
    root: Path,
    search_geometry: object | None,
) -> CandidateBuildResult:
    """Build DEM-network candidates and optionally score them against a reference network."""

    candidates, evidence = build_network_candidate_outlets(
        flow_products=flow_products,
        outlets=config.outlets,
        hydrology=config.hydrology,
        search_geometry=search_geometry,
    )
    reference_network, reference_bundle = load_reference_network_for_dem_network_candidates(
        config=config,
        candidates=candidates,
        target_crs=target_crs or first_candidate_crs(candidates),
        root=root,
    )
    if reference_network is not None and reference_bundle is not None:
        candidates = score_outlets_against_reference_network(
            candidates,
            reference_network,
            max_distance_m=config.outlets.reference_network_snap_max_distance_m,
            source=reference_bundle.source,
        )
        evidence = candidate_audit_evidence_with_candidate_attributes(
            evidence,
            candidates,
        )
    return CandidateBuildResult(
        candidates=candidates,
        evidence=evidence,
        search_geometry=search_geometry,
        reference_network=reference_network,
        reference_bundle=reference_bundle,
    )


def build_dem_area_target_candidates(
    *,
    config: SiteSelectionConfig,
    flow_products: SiteSelectionFlowProducts,
    target_crs: str | None,
    root: Path,
    search_geometry: object | None,
    backend: object | None = None,
    raw_accumulation_builder: RawAccumulationBuilder | None = None,
) -> CandidateBuildResult:
    """Build DEM outlet candidates around the configured target area."""

    if config.dem_area_target is None:
        raise ValueError("build_dem_area_target_candidates requires dem_area_target config.")

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
    candidates, evidence = build_dem_area_target_candidate_outlets(
        flow_products=flow_products,
        dem_area_target=config.dem_area_target,
        hydrology=config.hydrology,
        accumulation_cells_path=raw_accumulation_path,
        search_geometry=search_geometry,
        max_candidates_before_delineation=config.dem_area_target.max_candidates_before_delineation,
    )
    return CandidateBuildResult(
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
    )


def load_reference_network_for_dem_network_candidates(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    """Load a reference network for DEM-network candidates when snapping/scoring needs it."""

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
    )


def site_selection_search_geometry(
    config: SiteSelectionConfig,
    *,
    target_crs: str | None,
) -> object | None:
    """Return the optional territory geometry used to constrain candidate sampling."""

    territory = config.territory
    if not territory.clip_to_territory:
        return None
    mode = territory.mode
    if mode == "admin_departments" and (territory.country or "").upper() == "FR":
        from hydromodpy.data.common.administrative.france import geometry_for_departments

        return _make_search_geometry_valid(
            geometry_for_departments(territory.departments, target_crs=target_crs)
        )
    if mode == "admin_regions" and (territory.country or "").upper() == "FR":
        from hydromodpy.data.common.administrative.france import geometry_for_regions

        return _make_search_geometry_valid(
            geometry_for_regions(territory.regions, target_crs=target_crs)
        )
    if mode == "polygon_file" and territory.polygon_file is not None:
        try:
            import geopandas as gpd
        except ImportError as exc:  # pragma: no cover - optional geospatial dependency.
            raise ImportError(
                "geopandas is required for site_selection territory polygons."
            ) from exc

        frame = gpd.read_file(territory.polygon_file)
        if target_crs and frame.crs is not None and str(frame.crs) != str(target_crs):
            frame = frame.to_crs(target_crs)
        return _make_search_geometry_valid(_union_geometries(frame))
    if mode == "bbox" and territory.bbox is not None:
        from shapely.geometry import box

        return box(*territory.bbox)
    return None


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
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    if not target_crs:
        raise ValueError(f"{error_context} requires a projected outlet CRS.")
    network, bundle = load_reference_network_for_outlets(
        source=config.outlets.reference_network_source,
        path=config.outlets.reference_network_path,
        outlets=candidates,
        target_crs=target_crs,
        output_dir=root / "reference_network",
        fetch_margin_m=config.outlets.reference_network_fetch_margin_m,
        page_size=config.outlets.reference_network_page_size,
        force_refresh=config.outlets.reference_network_force_refresh,
    )
    return network, bundle


def _union_geometries(frame: object) -> object:
    geometry = frame.geometry[frame.geometry.notna() & (~frame.geometry.is_empty)]
    if hasattr(geometry, "union_all"):
        return geometry.union_all()
    return geometry.unary_union


def _make_search_geometry_valid(geometry: object | None) -> object | None:
    if geometry is None:
        return None
    if bool(getattr(geometry, "is_valid", True)):
        return geometry
    try:
        from shapely.validation import make_valid

        return make_valid(geometry)
    except Exception:
        return geometry.buffer(0)


__all__ = [
    "CandidateBuildResult",
    "build_dem_area_target_candidates",
    "build_dem_network_candidates",
    "build_station_candidate_outlets",
    "first_candidate_crs",
    "load_reference_network_for_dem_network_candidates",
    "load_reference_network_for_station_candidates",
    "site_selection_search_geometry",
]
