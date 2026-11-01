"""Production vector exports for site-selection spatial artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry import Point

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.crs import same_crs
from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.core.logging import get_logger
from hydromodpy.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
)
from hydromodpy.site_selection.domain.export_values import clean_properties, single_crs
from hydromodpy.site_selection.domain.watershed import read_watershed
from hydromodpy.site_selection.outputs.features import (
    basin_properties,
    observation_properties,
    outlet_properties,
    placed_observations,
    repair_geometry_for_export,
)

logger = get_logger(__name__)

GPKG_NAME = "site_selection.gpkg"

VectorFormat = Literal["gpkg", "geoparquet"]


def write_vector_layer(
    frame: gpd.GeoDataFrame,
    path: str | Path,
    *,
    fmt: VectorFormat,
    layer: str | None = None,
) -> Path | None:
    """Write *frame* as the GeoPackage layer *layer* or as a GeoParquet file.

    An empty frame writes nothing and gives ``None``.
    """
    if frame.empty:
        return None
    destination = Path(path)
    if fmt == "geoparquet":
        return write_geoparquet_atomic(frame, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(str(destination), layer=layer, driver="GPKG")
    return destination


def write_selection_geopackage(
    path: str | Path,
    *,
    selected: Iterable[DelineatedCatchment],
    rejected: Iterable[DelineatedCatchment],
    selection_id: str,
    region_id: str = "",
) -> Path | None:
    """Write selected/rejected outlets and basins to one GeoPackage."""

    destination = Path(path)
    if destination.exists():
        destination.unlink()
    written = False
    for layer, frame in _selection_layers(
        selected, rejected, selection_id=selection_id, region_id=region_id
    ):
        if write_vector_layer(frame, destination, fmt="gpkg", layer=layer) is not None:
            written = True
    return destination if written else None


def write_selection_geoparquet_layers(
    output_root: str | Path,
    *,
    selected: Iterable[DelineatedCatchment],
    rejected: Iterable[DelineatedCatchment],
    selection_id: str,
    region_id: str = "",
) -> dict[str, Path]:
    """Write selected/rejected outlets and basins as separate GeoParquet files."""

    root = Path(output_root)
    paths: dict[str, Path] = {}
    for layer, frame in _selection_layers(
        selected, rejected, selection_id=selection_id, region_id=region_id
    ):
        written = write_vector_layer(frame, root / f"{layer}.parquet", fmt="geoparquet")
        if written is not None:
            paths[f"{layer}_geoparquet"] = written
    return paths


def observation_points_gdf(evidence: Iterable[object]) -> gpd.GeoDataFrame:
    """Return normalized observation evidence as a point GeoDataFrame.

    The frame is in the first CRS of the batch, and a point given in another
    CRS is moved into it. A point without a readable location or CRS cannot be
    placed, so it is skipped as in the GeoJSON layer, logged, and recorded in
    ``attrs["hydromodpy_skipped_observations"]``. ``observation_crs`` keeps
    the CRS each provider gave.
    """

    rows = [item.to_record() if hasattr(item, "to_record") else dict(item) for item in evidence]
    placed, skipped = placed_observations(rows)
    target = single_crs(crs for _row, _x, _y, crs in placed)
    records: list[dict[str, Any]] = []
    geometries = []
    for row, x, y, crs in placed:
        if target is not None and not same_crs(crs, target):
            x, y = _to_batch_crs(row, crs, target).transform(x, y)
        records.append(clean_properties(observation_properties(row, crs=crs)))
        geometries.append(Point(x, y))
    if skipped:
        logger.warning(
            "Observation points left out of the vector layers, since they cannot be placed: %s",
            ", ".join(
                f"{item['site_id']}:{item['feature_id']} ({item['reason']})" for item in skipped
            ),
        )
    frame = gpd.GeoDataFrame(records, geometry=geometries, crs=target)
    frame.attrs["hydromodpy_skipped_observations"] = skipped
    return frame


def _to_batch_crs(row: Mapping[str, Any], crs: str, target: str) -> Transformer:
    """Return the transform of one observation point from *crs* into *target*."""
    try:
        return Transformer.from_crs(crs, target, always_xy=True)
    except (CRSError, ProjError) as exc:
        raise ExportError(
            f"observation point {row.get('feature_id', '')!r} of site {row.get('site_id', '')!r} "
            f"names the CRS {crs!r}, which pyproj cannot transform into {target!r}, the CRS "
            "of the batch (a local frame)."
        ) from exc


def _selection_layers(
    selected: Iterable[DelineatedCatchment],
    rejected: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str,
) -> list[tuple[str, gpd.GeoDataFrame]]:
    selected_list = list(selected)
    rejected_list = list(rejected)
    names = dict(selection_id=selection_id, region_id=region_id)
    return [
        ("selected_outlets", _outlets_gdf(selected_list, site_status="selected", **names)),
        ("rejected_outlets", _outlets_gdf(rejected_list, site_status="rejected", **names)),
        ("selected_basins", _basins_gdf(selected_list, site_status="selected", **names)),
        ("rejected_basins", _basins_gdf(rejected_list, site_status="rejected", **names)),
    ]


def _outlets_gdf(
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
) -> gpd.GeoDataFrame:
    records: list[dict[str, Any]] = []
    geometries = []
    crs_values: list[str] = []
    for catchment in catchments:
        display_x, display_y = outlet_display_xy(catchment)
        if catchment.outlet.crs:
            crs_values.append(catchment.outlet.crs)
        properties = outlet_properties(
            catchment,
            selection_id=selection_id,
            region_id=region_id,
            site_status=site_status,
            missing=None,
        )
        records.append(clean_properties(properties))
        geometries.append(Point(display_x, display_y))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=single_crs(crs_values))


def _basins_gdf(
    catchments: Iterable[DelineatedCatchment],
    *,
    selection_id: str,
    region_id: str,
    site_status: str,
) -> gpd.GeoDataFrame:
    frames = []
    target_crs = ""
    for catchment in catchments:
        watershed_path = Path(catchment.watershed_shp or "")
        if not catchment.watershed_shp or not watershed_path.is_file():
            continue
        try:
            frame = read_watershed(watershed_path)
        except Exception:  # noqa: BLE001 - an unreadable basin file leaves the layer.
            continue
        if frame.empty:
            continue
        frame = _repair_frame_geometries(frame)
        if frame.empty:
            continue
        if frame.crs is None and catchment.outlet.crs:
            frame = frame.set_crs(catchment.outlet.crs, allow_override=True)
        if not target_crs:
            target_crs = "" if frame.crs is None else str(frame.crs)
        elif frame.crs is not None and str(frame.crs) != target_crs:
            frame = frame.to_crs(target_crs)
        properties = clean_properties(
            basin_properties(
                catchment,
                watershed_path=watershed_path,
                selection_id=selection_id,
                region_id=region_id,
                site_status=site_status,
                missing=None,
            )
        )
        export_frame = gpd.GeoDataFrame(
            [properties for _geometry in frame.geometry],
            geometry=list(frame.geometry),
            crs=frame.crs,
        )
        frames.append(export_frame)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=None)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=frames[0].crs,
    )


def _repair_frame_geometries(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = frame.copy()
    frame.geometry = [repair_geometry_for_export(geometry) for geometry in frame.geometry]
    frame = frame[frame.geometry.notna()]
    if frame.empty:
        return frame
    return frame[~frame.geometry.is_empty]


__all__ = [
    "GPKG_NAME",
    "VectorFormat",
    "observation_points_gdf",
    "write_selection_geopackage",
    "write_selection_geoparquet_layers",
    "write_vector_layer",
]
