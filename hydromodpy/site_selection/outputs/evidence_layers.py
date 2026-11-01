"""Vector layers of the geology and influence evidence of a selection.

A geology item carries the basin it describes, an influence item the dam or
withdrawal it found. Both are written the same way, as a GeoJSON file in WGS 84
lon/lat (RFC 7946), or as a GeoPackage layer or a GeoParquet file named after
their role, in the CRS of the items.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd

from hydromodpy.site_selection.domain.export_values import (
    clean_value,
    single_crs,
    single_or_mixed,
)
from hydromodpy.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.site_selection.outputs.geojson import (
    feature_collection,
    lon_lat_geometry,
    write_geojson,
)
from hydromodpy.site_selection.outputs.geospatial import write_vector_layer

EvidenceItem = GeologyEvidence | InfluenceEvidence


def write_evidence_layer(
    path: str | Path,
    evidence: Iterable[EvidenceItem],
    *,
    role: str,
    fmt: Literal["geojson", "gpkg", "geoparquet"],
) -> Path | None:
    """Write the evidence items that carry a geometry as one layer named *role*.

    *role* is the ``hydromodpy_geometry_role`` of a GeoJSON file and the layer
    name in a GeoPackage. Without a located item nothing is written and the
    result is ``None``.
    """
    located = [item for item in evidence if item.geometry is not None]
    if not located:
        return None
    if fmt != "geojson":
        return write_vector_layer(_evidence_frame(located), path, fmt=fmt, layer=role)
    features = []
    for item in located:
        feature_id = _feature_id(item)
        features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "geometry": lon_lat_geometry(
                    item.geometry, item.crs, path=path, feature_id=feature_id
                ),
                "properties": properties_without_geometry(item),
            }
        )
    collection = feature_collection(
        path,
        project_crs=single_or_mixed(item.crs for item in located),
        features=features,
        hydromodpy_geometry_role=role,
    )
    return write_geojson(path, collection)


def _evidence_frame(located: list[EvidenceItem]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [properties_without_geometry(item) for item in located],
        geometry=[item.geometry for item in located],
        crs=single_crs(item.crs for item in located),
    )


def _feature_id(item: EvidenceItem) -> str:
    if isinstance(item, GeologyEvidence):
        return f"{item.site_id}:{item.source_layer}:{item.geology_class}"
    return f"{item.site_id}:{item.influence_type}:{item.feature_id or item.feature_index}"


def properties_without_geometry(item: EvidenceItem) -> dict[str, Any]:
    record = item.to_record()
    return {key: clean_value(value) for key, value in record.items() if key != "evidence_json"} | {
        "evidence_json": json.dumps(item.evidence_json, ensure_ascii=True, sort_keys=True)
    }


__all__ = ["write_evidence_layer"]
