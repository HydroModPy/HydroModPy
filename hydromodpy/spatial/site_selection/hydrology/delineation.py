"""Catchment delineation adapters for site-selection candidates."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    snap_outlet_to_reference_network,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

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


def snapped_outlet_xy(catchment: DelineatedCatchment) -> tuple[float, float] | None:
    """Return the snapped outlet coordinates when the delineation wrote them."""

    if not catchment.outlet_snap_shp:
        return None
    return _read_first_point_xy(Path(catchment.outlet_snap_shp))


def outlet_display_xy(catchment: DelineatedCatchment) -> tuple[float, float]:
    """Return the outlet coordinate to display on maps and spatial exports."""

    return snapped_outlet_xy(catchment) or (float(catchment.outlet.x), float(catchment.outlet.y))


def outlet_snap_distance_m(catchment: DelineatedCatchment) -> float | None:
    """Distance between original candidate outlet and snapped outlet in projected metres."""

    snapped = snapped_outlet_xy(catchment)
    if snapped is None:
        return None
    return math.hypot(
        snapped[0] - float(catchment.outlet.x), snapped[1] - float(catchment.outlet.y)
    )


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
    reference_network: object | None = None,
    reference_network_source: str = "reference_network",
    reference_network_snap_tolerance_m: float | None = None,
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
            max_distance_m=float(reference_network_snap_tolerance_m or snap_dist_m),
            source=reference_network_source,
        )
    output_dir = Path(output_root) / _safe_path_name(target_site_id)
    result = builder(
        x_outlet=float(working_outlet.x),
        y_outlet=float(working_outlet.y),
        snap_dist=int(snap_dist_m),
        acc_path=products.acc,
        direc_path=products.direc,
        output_dir=output_dir,
        crs_project=crs_project or working_outlet.crs,
        acc_data=products.acc_data,
        direc_data=products.direc_data,
        backend=backend,
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
    builder: DelineationBuilder = extract_catchment_from_point,
    area_reader: AreaReader | None = None,
    reference_network: object | None = None,
    reference_network_source: str = "reference_network",
    reference_network_snap_tolerance_m: float | None = None,
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
            reference_network=reference_network,
            reference_network_source=reference_network_source,
            reference_network_snap_tolerance_m=reference_network_snap_tolerance_m,
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


def _read_first_point_xy(path: Path) -> tuple[float, float] | None:
    if not path.is_file():
        return None
    if path.suffix.lower() in {".geojson", ".json"}:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return _first_point_xy_from_geojson(payload)
    try:
        import geopandas as gpd
    except ImportError:
        return None
    try:
        frame = gpd.read_file(str(path))
    except Exception:
        return None
    for geometry in frame.geometry:
        if geometry is None or geometry.is_empty:
            continue
        if geometry.geom_type == "Point":
            return float(geometry.x), float(geometry.y)
        if geometry.geom_type == "MultiPoint":
            point = next(iter(geometry.geoms), None)
            if point is not None:
                return float(point.x), float(point.y)
    return None


def _first_point_xy_from_geojson(payload: object) -> tuple[float, float] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list):
            return None
        for feature in features:
            if not isinstance(feature, dict):
                continue
            point = _point_xy_from_geometry(feature.get("geometry"))
            if point is not None:
                return point
        return None
    if payload.get("type") == "Feature":
        return _point_xy_from_geometry(payload.get("geometry"))
    return _point_xy_from_geometry(payload)


def _point_xy_from_geometry(geometry: object) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point" and isinstance(coordinates, list | tuple) and len(coordinates) >= 2:
        try:
            return float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError):
            return None
    if geometry_type == "MultiPoint" and isinstance(coordinates, list) and coordinates:
        first = coordinates[0]
        if isinstance(first, list | tuple) and len(first) >= 2:
            try:
                return float(first[0]), float(first[1])
            except (TypeError, ValueError):
                return None
    return None


def _safe_path_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe.strip("_") or "site"


__all__ = [
    "DelineatedCatchment",
    "delineate_candidate_outlet",
    "outlet_display_xy",
    "outlet_snap_distance_m",
    "snapped_outlet_xy",
    "try_delineate_candidate_outlet",
]
