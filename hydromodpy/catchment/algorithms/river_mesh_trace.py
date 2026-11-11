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
from typing import TYPE_CHECKING, Literal

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseMultipartGeometry

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

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


def linear_parts(
    geometries: Iterable[BaseGeometry | None], *, refusal: str | None = None
) -> list[LineString]:
    """Split geometries into their non-empty lines, a ``LinearRing`` included.

    Multi-part geometries and collections are opened at any depth, and a
    ``None`` geometry is skipped. A part that is not a line is skipped too,
    unless *refusal* is given: it then raises ``ValueError`` with that reason.
    """
    lines: list[LineString] = []
    for geometry in geometries:
        if geometry is None:
            continue
        if isinstance(geometry, LineString):
            if not geometry.is_empty:
                lines.append(geometry)
        elif isinstance(geometry, BaseMultipartGeometry):
            lines.extend(linear_parts(geometry.geoms, refusal=refusal))
        elif refusal is not None:
            raise ValueError(f"{refusal}; got a {geometry.geom_type}.")
    return lines


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


def build_river_mesh_trace_from_network_gdf(
    *,
    network_gdf: gpd.GeoDataFrame,
    network_crs: str | None,
) -> RiverMeshTrace | None:
    if network_gdf.empty:
        return None

    crs = network_gdf.crs
    network_crs_token = None if network_crs is None else str(network_crs).strip()
    if crs is None and network_crs_token:
        network_gdf = network_gdf.set_crs(network_crs_token, allow_override=True)
        crs = network_gdf.crs
    if crs is None:
        return None

    line_geometries = linear_parts(network_gdf.geometry.tolist())
    if not line_geometries:
        return None

    return RiverMeshTrace.from_geometries(
        source_kind="geographic_generated",
        crs_wkt=crs.to_wkt(),
        geometries=line_geometries,
    )
