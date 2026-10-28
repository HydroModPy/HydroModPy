"""Catchment delineation adapters for site-selection candidates.

Catchment-delineation phase for site-selection builds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.delineated_catchment import DelineatedCatchment
from hydromodpy.spatial.site_selection.domain.watershed import read_watershed, watershed_area_m2
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts
from hydromodpy.spatial.site_selection.hydrology.reference_network import (
    snap_outlet_to_reference_network,
)

DelineationBuilder = Callable[..., CatchmentFromPointProducts]
AreaReader = Callable[[str | Path], float | None]


def delineate_candidate_outlet(
    *,
    outlet: CandidateOutlet,
    flow_products: SiteSelectionFlowProducts | FlowProducts,
    output_root: str | Path,
    snap_dist_m: int,
    crs_project: str | None = None,
    site_id: str | None = None,
    backend: object | None = None,
    engine_id: str | None = None,
    builder: DelineationBuilder = extract_catchment_from_point,
    area_reader: AreaReader | None = None,
    reference_network: object | None = None,
    reference_network_source: str = "reference_network",
    reference_network_max_distance_m: float | None = None,
) -> DelineatedCatchment:
    """Delineate one candidate by delegating to existing geographic code."""

    if snap_dist_m <= 0:
        raise ValueError("snap_dist_m must be > 0.")
    products = _flow_products(flow_products)
    target_site_id = site_id or outlet.candidate_id
    working_outlet = outlet
    if reference_network is not None:
        working_outlet = snap_outlet_to_reference_network(
            outlet,
            reference_network,
            max_distance_m=float(reference_network_max_distance_m or snap_dist_m),
            source=reference_network_source,
        )
    output_dir = Path(output_root) / _safe_path_name(target_site_id)
    result = builder(
        x_outlet=float(working_outlet.x),
        y_outlet=float(working_outlet.y),
        snap_dist=int(snap_dist_m),
        accumulation=products.accumulation,
        output_dir=output_dir,
        crs_project=crs_project or working_outlet.crs,
        backend=backend,
        engine_id=engine_id,
    )
    area_km2 = _read_area_km2(result.watershed_shp, area_reader=area_reader)
    return DelineatedCatchment(
        site_id=target_site_id,
        outlet=working_outlet,
        outlet_shp=result.outlet_shp,
        outlet_snap_shp=result.outlet_snap_shp,
        watershed_tif=result.watershed_tif,
        watershed_shp=result.watershed_shp,
        area_km2=area_km2,
    )


def try_delineate_candidate_outlet(
    *,
    outlet: CandidateOutlet,
    flow_products: SiteSelectionFlowProducts | FlowProducts,
    output_root: str | Path,
    snap_dist_m: int,
    crs_project: str | None = None,
    site_id: str | None = None,
    backend: object | None = None,
    engine_id: str | None = None,
    builder: DelineationBuilder = extract_catchment_from_point,
    area_reader: AreaReader | None = None,
    reference_network: object | None = None,
    reference_network_source: str = "reference_network",
    reference_network_max_distance_m: float | None = None,
) -> DelineatedCatchment:
    """Delineate one candidate and return a rejected record on failure."""

    try:
        return delineate_candidate_outlet(
            outlet=outlet,
            flow_products=flow_products,
            output_root=output_root,
            snap_dist_m=snap_dist_m,
            crs_project=crs_project,
            site_id=site_id,
            backend=backend,
            engine_id=engine_id,
            builder=builder,
            area_reader=area_reader,
            reference_network=reference_network,
            reference_network_source=reference_network_source,
            reference_network_max_distance_m=reference_network_max_distance_m,
        )
    except Exception as exc:  # noqa: BLE001 - this is an audit record boundary.
        return DelineatedCatchment(
            site_id=site_id or outlet.candidate_id,
            outlet=outlet,
            status="rejected_delineation_failed",
            failure_reason=str(exc),
        )


def _flow_products(flow_products: SiteSelectionFlowProducts | FlowProducts) -> FlowProducts:
    if isinstance(flow_products, SiteSelectionFlowProducts):
        return flow_products.products
    return flow_products


def _read_area_km2(path: str | Path, *, area_reader: AreaReader | None) -> float | None:
    if area_reader is not None:
        return area_reader(path)
    frame = read_watershed(path)
    if frame.empty:
        return None
    return watershed_area_m2(frame) / 1_000_000.0


def _safe_path_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe.strip("_") or "site"


__all__ = [
    "delineate_candidate_outlet",
    "try_delineate_candidate_outlet",
    "delineate_site_selection_candidates",
]


def delineate_site_selection_candidates(
    candidates: Iterable[CandidateOutlet],
    *,
    flow_products: SiteSelectionFlowProducts,
    output_root: str | Path,
    snap_dist_m: int,
    crs_project: str | None,
    backend: object | None = None,
    engine_id: str | None = None,
    delineation_builder: DelineationBuilder | None = None,
    area_reader: AreaReader | None = None,
    reference_network: object | None = None,
    reference_network_source: str = "",
    reference_network_max_distance_m: float | None = None,
) -> list[DelineatedCatchment]:
    """Delineate all candidate outlets with the same DEM products and settings."""

    builder_kwargs = {}
    if delineation_builder is not None:
        builder_kwargs["builder"] = delineation_builder

    return [
        try_delineate_candidate_outlet(
            outlet=candidate,
            flow_products=flow_products,
            output_root=output_root,
            snap_dist_m=snap_dist_m,
            crs_project=crs_project or candidate.crs,
            site_id=candidate.candidate_id,
            backend=backend,
            engine_id=engine_id,
            area_reader=area_reader,
            reference_network=reference_network,
            reference_network_source=reference_network_source,
            reference_network_max_distance_m=reference_network_max_distance_m,
            **builder_kwargs,
        )
        for candidate in candidates
    ]
