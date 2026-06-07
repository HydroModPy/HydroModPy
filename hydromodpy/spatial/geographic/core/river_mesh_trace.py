"""In-memory river-trace payload used by river-conformal meshing.

Purpose
-------
Expose one compact, immutable contract carrying only the river polylines
required by downstream mesh builders. The payload intentionally avoids
storing raster products or file paths.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import geopandas as gpd
from shapely.geometry import GeometryCollection, LineString, MultiLineString
from shapely.ops import unary_union

RiverMeshTraceSourceKind = Literal[
    "geographic_generated",
    "hydrography_loaded",
    "file",
]


def _iter_non_empty_lines(geometries: Iterable[LineString | MultiLineString]) -> list[LineString]:
    """Normalize a geometry iterable to non-empty ``LineString`` segments."""
    lines: list[LineString] = []
    for geometry in geometries:
        if isinstance(geometry, LineString):
            if not geometry.is_empty:
                lines.append(geometry)
            continue
        if isinstance(geometry, MultiLineString):
            for line in geometry.geoms:
                if not line.is_empty:
                    lines.append(line)
            continue
        raise TypeError("river geometries must contain only LineString or MultiLineString values.")
    return lines


def _extract_lines(geometry) -> list[LineString]:
    """Extract ``LineString`` primitives from one geometry recursively."""
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if not line.is_empty]
    if isinstance(geometry, GeometryCollection):
        lines: list[LineString] = []
        for child in geometry.geoms:
            lines.extend(_extract_lines(child))
        return lines
    return []


@dataclass(frozen=True, slots=True)
class RiverMeshTrace:
    """Minimal in-memory river geometry contract for meshing."""

    source_kind: RiverMeshTraceSourceKind
    crs_wkt: str
    lines: tuple[LineString, ...]
    segment_count: int = field(init=False)
    total_length_m: float = field(init=False)

    def __post_init__(self) -> None:
        valid_source_kinds = {"geographic_generated", "hydrography_loaded", "file"}
        if str(self.source_kind) not in valid_source_kinds:
            raise ValueError(
                "source_kind must be one of: geographic_generated, hydrography_loaded, file."
            )
        if str(self.crs_wkt).strip() == "":
            raise ValueError("crs_wkt cannot be empty")

        normalized_lines = _iter_non_empty_lines(self.lines)
        if not normalized_lines:
            raise ValueError("RiverMeshTrace.lines cannot be empty")

        total_length_m = float(sum(float(line.length) for line in normalized_lines))
        object.__setattr__(self, "lines", tuple(normalized_lines))
        object.__setattr__(self, "segment_count", int(len(normalized_lines)))
        object.__setattr__(self, "total_length_m", total_length_m)

    @classmethod
    def from_geometries(
        cls,
        *,
        source_kind: RiverMeshTraceSourceKind,
        crs_wkt: str,
        geometries: Iterable[LineString | MultiLineString],
    ) -> RiverMeshTrace:
        """Build one trace from raw line or multilinestring geometries."""
        return cls(
            source_kind=source_kind,
            crs_wkt=str(crs_wkt),
            lines=tuple(_iter_non_empty_lines(geometries)),
        )

    def as_multilinestring(self) -> MultiLineString:
        """Return the trace as one ``MultiLineString``."""
        return MultiLineString(list(self.lines))


def build_river_mesh_trace_from_vector(
    *,
    vector_path: str | Path,
    source_kind: RiverMeshTraceSourceKind,
    target_crs: str | None = None,
    clip_polygon_path: str | Path | None = None,
) -> RiverMeshTrace | None:
    """Build one in-memory river trace from a vector dataset.

    Returns ``None`` when no valid line segment remains after optional clipping.
    """
    src_path = Path(vector_path)
    if not src_path.exists():
        raise FileNotFoundError(f"River network vector not found: {src_path}")

    rivers = gpd.read_file(src_path)
    if rivers.empty:
        return None
    target_crs_token = None if target_crs is None else str(target_crs).strip()
    if target_crs_token == "":
        target_crs_token = None

    if rivers.crs is None:
        if target_crs_token is not None:
            rivers = rivers.set_crs(target_crs_token, allow_override=True)
        elif clip_polygon_path is not None:
            clip_path = Path(clip_polygon_path)
            if clip_path.exists():
                clip_polygons = gpd.read_file(clip_path)
                if clip_polygons.crs is not None:
                    rivers = rivers.set_crs(clip_polygons.crs, allow_override=True)
        if rivers.crs is None:
            raise ValueError(
                f"River network vector has no CRS and no target CRS provided: {src_path}"
            )

    geometries = [
        geometry for geometry in rivers.geometry if geometry is not None and not geometry.is_empty
    ]
    if not geometries:
        return None

    if clip_polygon_path is not None:
        clip_path = Path(clip_polygon_path)
        if not clip_path.exists():
            raise FileNotFoundError(f"Clip polygon not found: {clip_path}")
        clip_polygons = gpd.read_file(clip_path)
        if clip_polygons.empty:
            return None
        if clip_polygons.crs is None:
            raise ValueError(f"Clip polygon has no CRS: {clip_path}")
        clip_polygons = clip_polygons.to_crs(rivers.crs)
        clip_union = unary_union(
            [
                geometry
                for geometry in clip_polygons.geometry
                if geometry is not None and not geometry.is_empty
            ]
        )
        if clip_union is None or clip_union.is_empty:
            return None
        clipped: list[object] = []
        for geometry in geometries:
            intersection = geometry.intersection(clip_union)
            if intersection is None or intersection.is_empty:
                continue
            clipped.append(intersection)
        geometries = clipped
        if not geometries:
            return None

    if target_crs_token is not None:
        if target_crs_token:
            rivers = gpd.GeoDataFrame(geometry=geometries, crs=rivers.crs).to_crs(target_crs_token)
            crs_wkt = rivers.crs.to_wkt() if rivers.crs is not None else target_crs_token
            geometries = list(rivers.geometry)
        else:
            crs_wkt = rivers.crs.to_wkt()
    else:
        crs_wkt = rivers.crs.to_wkt()

    lines: list[LineString] = []
    for geometry in geometries:
        lines.extend(_extract_lines(geometry))
    if not lines:
        return None

    return RiverMeshTrace.from_geometries(
        source_kind=source_kind,
        crs_wkt=crs_wkt,
        geometries=lines,
    )
