"""The files that describe the generated candidates and the network they came from.

Both GeoJSON files hold WGS 84 lon/lat (RFC 7946), as every GeoJSON of a
selection does.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import Point

from hydromodpy.spatial.site_selection.candidates.generation import (
    AccumulationRaster,
    CandidateGenerationEvidence,
    read_accumulation_raster,
    resolve_accumulation_threshold,
    search_geometry_mask,
)
from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.export_values import clean_properties, single_or_mixed
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts
from hydromodpy.spatial.site_selection.outputs.geojson import (
    feature_collection,
    lon_lat_geometry,
    lon_lat_transformer,
    write_geojson,
)

__all__ = [
    "write_candidate_generation_jsonl",
    "write_candidate_outlets_geojson",
    "write_generated_network_geojson",
]


def write_candidate_generation_jsonl(
    path: str | Path,
    evidence: Iterable[CandidateGenerationEvidence],
) -> Path:
    """Write generated-candidate evidence as JSONL."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in evidence:
            handle.write(json.dumps(row.to_record(), ensure_ascii=True, sort_keys=True) + "\n")
    return destination


def write_generated_network_geojson(
    path: str | Path,
    *,
    flow_products: SiteSelectionFlowProducts,
    hydrology: HydrologyConfig,
    max_cells: int | None = 50000,
    search_geometry: object | None = None,
) -> Path:
    """Write the DEM-derived stream network as a lightweight vector layer."""

    raster = read_accumulation_raster(flow_products.products.acc)
    search_mask = search_geometry_mask(raster, search_geometry)
    valid_search_mask = (
        raster.valid_mask if search_mask is None else raster.valid_mask & search_mask
    )
    threshold = resolve_accumulation_threshold(
        raster,
        network_threshold_area_km2=hydrology.network_threshold_area_km2,
    )
    cells, source_cell_count = _network_cells_for_export(
        raster,
        valid_mask=valid_search_mask,
        threshold=threshold,
        max_cells=max_cells,
    )
    lon_lat = _cell_lon_lat(cells, raster, path=path)
    features = _network_line_features(cells, lon_lat)
    isolated = _isolated_network_point_features(cells, lon_lat, start_index=len(features) + 1)
    features.extend(isolated)
    collection = feature_collection(
        path,
        project_crs=raster.crs,
        features=features,
        hydromodpy_geometry_role="generated_dem_network",
        hydromodpy_network_threshold_area_km2=hydrology.network_threshold_area_km2,
        hydromodpy_threshold_value_used=threshold,
        hydromodpy_source_accumulation=str(flow_products.products.acc),
        hydromodpy_network_cell_count=len(cells),
        hydromodpy_network_source_cell_count=source_cell_count,
        hydromodpy_network_cell_export_cap=max_cells,
        hydromodpy_network_export_truncated=(
            False if max_cells is None else source_cell_count > int(max_cells)
        ),
    )
    return write_geojson(path, collection)


def write_candidate_outlets_geojson(
    path: str | Path,
    candidates: Iterable[CandidateOutlet],
) -> Path:
    """Write generated candidate outlets as a lightweight GeoJSON."""

    materialized = list(candidates)
    features = [
        {
            "type": "Feature",
            "id": candidate.candidate_id,
            "geometry": lon_lat_geometry(
                Point(float(candidate.x), float(candidate.y)),
                candidate.crs,
                path=path,
                feature_id=candidate.candidate_id,
            ),
            "properties": {
                "candidate_id": candidate.candidate_id,
                "source": candidate.source,
                "source_feature_id": candidate.source_feature_id,
                "source_label": candidate.source_label,
                "priority": candidate.priority,
                **clean_properties(candidate.attributes),
            },
        }
        for candidate in materialized
    ]
    collection = feature_collection(
        path,
        project_crs=single_or_mixed(candidate.crs for candidate in materialized),
        features=features,
        hydromodpy_geometry_role="candidate_outlets",
    )
    return write_geojson(path, collection)


def _network_cells_for_export(
    raster: AccumulationRaster,
    *,
    valid_mask: np.ndarray | None = None,
    threshold: float,
    max_cells: int | None,
) -> tuple[dict[tuple[int, int], float], int]:
    base_mask = raster.valid_mask if valid_mask is None else valid_mask
    rows, cols = np.where(base_mask & (raster.array >= threshold))
    if rows.size == 0:
        rows, cols = np.where(base_mask)
    scored = sorted(
        (
            (float(raster.array[int(row), int(col)]), int(row), int(col))
            for row, col in zip(rows, cols, strict=True)
        ),
        reverse=True,
    )
    source_cell_count = len(scored)
    if max_cells is not None:
        scored = scored[: int(max_cells)]
    return {(row, col): value for value, row, col in scored}, source_cell_count


def _cell_lon_lat(
    cells: dict[tuple[int, int], float], raster: AccumulationRaster, *, path: str | Path
) -> dict[tuple[int, int], list[float]]:
    """Return the WGS 84 lon/lat of the centre of each network cell, in one transform."""
    transformer = lon_lat_transformer(raster.crs, path=path, feature_id="generated_network")
    keys = sorted(cells)
    points = np.array([raster.xy(row, col) for row, col in keys], dtype=float).reshape(-1, 2)
    lon, lat = transformer.transform(points[:, 0], points[:, 1])
    return {key: [float(x), float(y)] for key, x, y in zip(keys, lon, lat, strict=True)}


def _network_line_features(
    cells: dict[tuple[int, int], float],
    lon_lat: dict[tuple[int, int], list[float]],
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    cell_keys = set(cells)
    for row, col in sorted(cell_keys):
        for neighbor_row, neighbor_col in (
            (row + 1, col),
            (row, col + 1),
            (row + 1, col + 1),
            (row + 1, col - 1),
        ):
            neighbor = (neighbor_row, neighbor_col)
            if neighbor not in cell_keys:
                continue
            start_value = float(cells[(row, col)])
            end_value = float(cells[neighbor])
            features.append(
                {
                    "type": "Feature",
                    "id": f"generated_network_{len(features) + 1:07d}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [lon_lat[(row, col)], lon_lat[neighbor]],
                    },
                    "properties": {
                        "feature_kind": "network_segment",
                        "from_row": row,
                        "from_col": col,
                        "to_row": neighbor_row,
                        "to_col": neighbor_col,
                        "accumulation_min": min(start_value, end_value),
                        "accumulation_max": max(start_value, end_value),
                    },
                }
            )
    return features


def _isolated_network_point_features(
    cells: dict[tuple[int, int], float],
    lon_lat: dict[tuple[int, int], list[float]],
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    connected: set[tuple[int, int]] = set()
    cell_keys = set(cells)
    for row, col in cell_keys:
        for drow in (-1, 0, 1):
            for dcol in (-1, 0, 1):
                if drow == 0 and dcol == 0:
                    continue
                neighbor = (row + drow, col + dcol)
                if neighbor in cell_keys:
                    connected.add((row, col))
                    connected.add(neighbor)
    features: list[dict[str, Any]] = []
    for row, col in sorted(cell_keys - connected):
        features.append(
            {
                "type": "Feature",
                "id": f"generated_network_{start_index + len(features):07d}",
                "geometry": {"type": "Point", "coordinates": lon_lat[(row, col)]},
                "properties": {
                    "feature_kind": "isolated_network_cell",
                    "raster_row": row,
                    "raster_col": col,
                    "accumulation_value": float(cells[(row, col)]),
                },
            }
        )
    return features
