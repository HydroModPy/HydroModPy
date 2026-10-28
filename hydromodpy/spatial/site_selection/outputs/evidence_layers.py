"""Vector layers of the geology and influence evidence of a selection.

A geology item carries the basin it describes, an influence item the dam or
withdrawal it found. Both are written the same way, as a GeoJSON file, a
GeoPackage layer or a GeoParquet file named after their role.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd

from hydromodpy.core.io.crs import geojson_crs_member
from hydromodpy.spatial.site_selection.domain.export_values import (
    clean_value,
    single_crs,
    single_or_mixed,
)
from hydromodpy.spatial.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.outputs.geojson import write_geojson
from hydromodpy.spatial.site_selection.outputs.geospatial import write_vector_layer

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
    crs_label = single_or_mixed({item.crs for item in located if item.crs})
    collection = {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "hydromodpy_geometry_role": role,
        "hydromodpy_coordinate_crs": crs_label,
        **geojson_crs_member(crs_label),
        "features": [
            {
                "type": "Feature",
                "id": _feature_id(item),
                "geometry": item.geometry.__geo_interface__,
                "properties": properties_without_geometry(item),
            }
            for item in located
        ],
    }
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
