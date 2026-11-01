"""GeoJSON exports for site-selection spatial review artifacts.

Every file follows RFC 7946: its coordinates are WGS 84 longitudes and
latitudes and it carries no ``crs`` member. ``hydromodpy_coordinate_crs`` says
so, and ``hydromodpy_project_crs`` names the CRS the features came from. The
project coordinates stay in the GeoPackage and GeoParquet layers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry import Point, mapping

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.crs import RFC7946_CRS
from hydromodpy.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
)
from hydromodpy.site_selection.domain.export_values import single_or_mixed
from hydromodpy.site_selection.domain.watershed import read_watershed
from hydromodpy.site_selection.outputs.features import (
    basin_properties,
    observation_properties,
    outlet_properties,
    placed_observations,
    repair_geometry_for_export,
)


def lon_lat_geometry(
    geometry: Any, crs: str, *, path: str | Path, feature_id: str
) -> dict[str, Any]:
    """Return *geometry*, written in *crs*, as a GeoJSON geometry in WGS 84 lon/lat.

    A feature without a CRS, or with one pyproj cannot read, is refused: its
    coordinates cannot be placed in WGS 84.
    """
    transformer = lon_lat_transformer(crs, path=path, feature_id=feature_id)
    return mapping(shapely.transform(geometry, lambda xy: _lon_lat(transformer, xy)))


def lon_lat_transformer(crs: str, *, path: str | Path, feature_id: str) -> Transformer:
    """Return the transform from *crs* to WGS 84 lon/lat, refusing a missing CRS by name."""
    if not crs or crs == "mixed":
        raise ExportError(
            f"{path}: feature {feature_id!r} has no CRS, so its coordinates cannot be written "
            "in the WGS 84 longitude and latitude that a GeoJSON holds (RFC 7946)."
        )
    try:
        return _to_lon_lat(crs)
    except (CRSError, ProjError) as exc:
        raise ExportError(
            f"{path}: feature {feature_id!r} names the CRS {crs!r}, which pyproj cannot read "
            "or cannot transform to WGS 84 (a local frame), so its coordinates cannot be "
            "written in the WGS 84 longitude and latitude a GeoJSON holds (RFC 7946)."
        ) from exc


@lru_cache(maxsize=32)
def _to_lon_lat(crs: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(crs), RFC7946_CRS, always_xy=True)


def _lon_lat(transformer: Transformer, xy: np.ndarray) -> np.ndarray:
    lon, lat = transformer.transform(xy[:, 0], xy[:, 1])
    return np.column_stack([lon, lat])


def feature_collection(
    path: str | Path, *, project_crs: str, features: list[dict[str, Any]], **members: Any
) -> dict[str, Any]:
    """Return the RFC 7946 collection named after *path* that holds *features*.

    *project_crs* is the CRS the features came from, a single label, ``"mixed"``
    or ``""``. *members* are the other ``hydromodpy_*`` members.
    """
    return {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_coordinate_crs": RFC7946_CRS,
        "hydromodpy_project_crs": project_crs,
        **members,
        "features": features,
    }


def write_geojson(path: str | Path, collection: Mapping[str, Any]) -> Path:
    """Write *collection* to *path* as indented JSON with sorted keys, in ASCII."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(dict(collection), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_outlets_geojson(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
    site_status: str,
) -> Path:
    """Write a lightweight point GeoJSON for selected or rejected outlets."""

    materialized = list(catchments)
    features = []
    for catchment in materialized:
        features.append(
            {
                "type": "Feature",
                "id": catchment.site_id,
                "geometry": lon_lat_geometry(
                    Point(outlet_display_xy(catchment)),
                    catchment.outlet.crs,
                    path=path,
                    feature_id=catchment.site_id,
                ),
                "properties": outlet_properties(
                    catchment,
                    selection_id=selection_id,
                    region_id=region_id,
                    site_status=site_status,
                    missing="",
                ),
            }
        )

    project_crs = single_or_mixed(catchment.outlet.crs for catchment in materialized)
    return write_geojson(path, feature_collection(path, project_crs=project_crs, features=features))


def write_basins_geojson(
    path: str | Path,
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str = "",
    site_status: str,
) -> Path:
    """Write basin contour geometries when delineated vector files exist."""

    materialized = list(catchments)
    features: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    crs_values: set[str] = set()
    for catchment in materialized:
        watershed_path = Path(catchment.watershed_shp or "")
        if not catchment.watershed_shp or not watershed_path.is_file():
            skipped.append(
                {
                    "site_id": catchment.site_id,
                    "reason": "missing_watershed_vector",
                    "watershed_shp": catchment.watershed_shp or "",
                }
            )
            continue
        try:
            frame = read_watershed(watershed_path)
        except Exception as exc:  # noqa: BLE001 - keep export robust and auditable.
            skipped.append(
                {
                    "site_id": catchment.site_id,
                    "reason": f"read_failed: {exc}",
                    "watershed_shp": str(watershed_path),
                }
            )
            continue
        # A basin file without a CRS is in the CRS of its outlet, as in the other layers.
        crs_label = _crs_label(frame.crs) or catchment.outlet.crs
        features.extend(
            _features_from_watershed_frame(
                frame,
                crs=crs_label,
                path=path,
                properties=basin_properties(
                    catchment,
                    watershed_path=watershed_path,
                    selection_id=selection_id,
                    region_id=region_id,
                    site_status=site_status,
                    missing="",
                ),
                site_id=catchment.site_id,
            )
        )
        crs_values.add(crs_label)

    collection = feature_collection(
        path,
        project_crs=single_or_mixed(crs_values),
        features=features,
        hydromodpy_geometry_role="basin_contours",
        hydromodpy_skipped_basins=skipped,
    )
    return write_geojson(path, collection)


def write_observation_points_geojson(
    path: str | Path,
    evidence: Iterable[object],
) -> Path:
    """Write observation locations from normalized observation evidence."""

    rows = [item.to_record() if hasattr(item, "to_record") else dict(item) for item in evidence]
    placed, skipped = placed_observations(rows)
    features: list[dict[str, Any]] = []
    for row, x, y, crs in placed:
        feature_id = f"{row.get('site_id', '')}:{row.get('feature_id', '')}"
        features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "geometry": lon_lat_geometry(Point(x, y), crs, path=path, feature_id=feature_id),
                "properties": observation_properties(row, crs=crs),
            }
        )

    collection = feature_collection(
        path,
        project_crs=single_or_mixed(crs for _row, _x, _y, crs in placed),
        features=features,
        hydromodpy_geometry_role="observation_points",
        hydromodpy_skipped_observations=skipped,
    )
    return write_geojson(path, collection)


def _features_from_watershed_frame(
    frame: Any,
    *,
    crs: str,
    path: str | Path,
    properties: dict[str, Any],
    site_id: str,
) -> list[dict[str, Any]]:
    features = []
    for index, geometry in enumerate(frame.geometry):
        geometry = repair_geometry_for_export(geometry)
        if geometry is None or geometry.is_empty:
            continue
        feature_id = f"{site_id}:{index}"
        features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "geometry": lon_lat_geometry(geometry, crs, path=path, feature_id=feature_id),
                "properties": properties,
            }
        )
    return features


def _crs_label(value: object) -> str:
    return "" if value is None else str(value)


__all__ = [
    "feature_collection",
    "lon_lat_geometry",
    "lon_lat_transformer",
    "write_basins_geojson",
    "write_geojson",
    "write_observation_points_geojson",
    "write_outlets_geojson",
]
