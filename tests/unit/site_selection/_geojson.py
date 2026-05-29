from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_feature_collection_geojson(
    path: Path,
    *,
    geometry: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": properties or {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_point_geojson(
    path: Path,
    *,
    coordinates: list[float],
    properties: dict[str, Any] | None = None,
) -> Path:
    return write_feature_collection_geojson(
        path,
        geometry={"type": "Point", "coordinates": coordinates},
        properties=properties,
    )


def write_polygon_geojson(
    path: Path,
    *,
    coordinates: list[list[float]],
    properties: dict[str, Any] | None = None,
) -> Path:
    return write_feature_collection_geojson(
        path,
        geometry={"type": "Polygon", "coordinates": [coordinates]},
        properties=properties,
    )


def write_square_geojson(
    path: Path,
    *,
    size: float = 10.0,
    x0: float = 0.0,
    y0: float = 0.0,
    properties: dict[str, Any] | None = None,
) -> Path:
    return write_polygon_geojson(
        path,
        coordinates=[
            [x0, y0],
            [x0 + size, y0],
            [x0 + size, y0 + size],
            [x0, y0 + size],
            [x0, y0],
        ],
        properties=properties,
    )
