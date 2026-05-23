"""Catchment delineation adapters for site-selection candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.flow_products_adapter import SiteSelectionFlowProducts

DelineationBuilder = Callable[..., CatchmentFromPointProducts]
AreaReader = Callable[[str | Path], float | None]


@dataclass(frozen=True)
class DelineatedCatchment:
    """Delineation result for one candidate outlet."""

    site_id: str
    outlet: CandidateOutlet
    outlet_shp: str | None = None
    outlet_snap_shp: str | None = None
    watershed_tif: str | None = None
    watershed_shp: str | None = None
    area_km2: float | None = None
    status: str = "delineated"
    failure_reason: str = ""

    def to_record(self) -> dict[str, Any]:
        """Return a CSV/parquet-friendly mapping."""

        return {
            "site_id": self.site_id,
            "candidate_id": self.outlet.candidate_id,
            "x_outlet": self.outlet.x,
            "y_outlet": self.outlet.y,
            "outlet_crs": self.outlet.crs,
            "outlet_shp": self.outlet_shp,
            "outlet_snap_shp": self.outlet_snap_shp,
            "watershed_tif": self.watershed_tif,
            "watershed_shp": self.watershed_shp,
            "area_km2": self.area_km2,
            "status": self.status,
            "failure_reason": self.failure_reason,
        }


def delineate_candidate_outlet(
    *,
    outlet: CandidateOutlet,
    flow_products: SiteSelectionFlowProducts | FlowProducts,
    output_root: str | Path,
    snap_dist_m: int,
    crs_project: str | None = None,
    site_id: str | None = None,
    backend: object | None = None,
    builder: DelineationBuilder = extract_catchment_from_point,
    area_reader: AreaReader | None = None,
) -> DelineatedCatchment:
    """Delineate one candidate by delegating to existing geographic code."""

    if snap_dist_m <= 0:
        raise ValueError("snap_dist_m must be > 0.")
    products = _flow_products(flow_products)
    target_site_id = site_id or outlet.candidate_id
    output_dir = Path(output_root) / _safe_path_name(target_site_id)
    result = builder(
        x_outlet=float(outlet.x),
        y_outlet=float(outlet.y),
        snap_dist=int(snap_dist_m),
        acc_path=products.acc,
        direc_path=products.direc,
        output_dir=output_dir,
        crs_project=crs_project or outlet.crs,
        acc_data=products.acc_data,
        direc_data=products.direc_data,
        backend=backend,
    )
    area_km2 = _read_area_km2(result.watershed_shp, area_reader=area_reader)
    return DelineatedCatchment(
        site_id=target_site_id,
        outlet=outlet,
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
    builder: DelineationBuilder = extract_catchment_from_point,
    area_reader: AreaReader | None = None,
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
            builder=builder,
            area_reader=area_reader,
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
    try:
        import geopandas as gpd
    except ImportError:
        return None

    gdf = gpd.read_file(str(path))
    if gdf.empty:
        return None
    return float(gdf.geometry.area.sum() / 1_000_000.0)


def _safe_path_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe.strip("_") or "site"


__all__ = [
    "DelineatedCatchment",
    "delineate_candidate_outlet",
    "try_delineate_candidate_outlet",
]
