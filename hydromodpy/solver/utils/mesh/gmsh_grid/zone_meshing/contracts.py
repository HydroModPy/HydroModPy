"""Public data contracts for zone-conformal meshing.

These dataclasses are the stable payload exchanged between planning code and
the low-level Gmsh orchestration layer. Keeping them here makes the public API
clearer and lets ``conformal.py`` focus on workflow orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_utils import (
    iter_line_parts,
)


@dataclass(frozen=True)
class ZonePartitionFace:
    """One partition face carrying one stable zone key."""

    face_id: int
    zone_key: str
    polygon: Polygon

    @property
    def area(self) -> float:
        return float(self.polygon.area)


@dataclass(frozen=True)
class ZoneConformalPartition:
    """One clean planar partition of polygonal zones."""

    faces: tuple[ZonePartitionFace, ...]
    zone_keys: tuple[str, ...]
    domain_geometry: Polygon | MultiPolygon
    covered_area: float
    cleaning_diagnostics: Mapping[str, Any] | None = None

    @property
    def n_faces(self) -> int:
        return int(len(self.faces))

    @property
    def domain_area(self) -> float:
        return float(self.domain_geometry.area)

    @property
    def face_counts_by_zone(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for face in self.faces:
            counts[face.zone_key] = counts.get(face.zone_key, 0) + 1
        return counts

    @property
    def face_areas_by_zone(self) -> dict[str, float]:
        areas: dict[str, float] = {}
        for face in self.faces:
            areas[face.zone_key] = areas.get(face.zone_key, 0.0) + float(face.area)
        return areas


@dataclass(frozen=True)
class ZoneConformalPhysicalGroup:
    """Structured description of one physical group created during meshing."""

    dimension: int
    tag: int
    name: str
    group_kind: str
    entity_tags: tuple[int, ...]
    zone_keys: tuple[str, ...] = ()

    @property
    def entity_count(self) -> int:
        return int(len(self.entity_tags))

    def to_summary(self) -> dict[str, Any]:
        return {
            "dimension": int(self.dimension),
            "tag": int(self.tag),
            "name": str(self.name),
            "group_kind": str(self.group_kind),
            "entity_count": int(self.entity_count),
            "zone_keys": [str(zone_key) for zone_key in self.zone_keys],
        }


@dataclass(frozen=True)
class ZoneConformalMeshResult:
    """Result bundle for one generated conformal planar mesh."""

    mesh: GmshPlanarMesh2D
    partition: ZoneConformalPartition
    output_path: Path
    physical_groups: tuple[ZoneConformalPhysicalGroup, ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class ZoneLinearConstraint:
    """One named internal line constraint that must appear in the generated mesh."""

    name: str
    kind: str
    lines: tuple[LineString, ...]
    participates_in_refinement: bool = True

    @property
    def line_count(self) -> int:
        return int(len(self.lines))

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> ZoneLinearConstraint:
        """Build one constraint from the public mapping form."""
        name_text = str(payload.get("name", "")).strip()
        kind_text = str(payload.get("kind", "")).strip()
        if name_text == "":
            raise ValueError("linear constraints require one non-empty name.")
        if kind_text == "":
            raise ValueError(f"linear constraint '{name_text}' requires one non-empty kind.")
        lines_attr = payload.get("lines")
        if lines_attr is None:
            raise TypeError(f"linear constraint '{name_text}' must expose one 'lines' collection.")

        lines: list[LineString] = []
        for geometry in lines_attr:
            if geometry is None:
                continue
            for line in iter_line_parts(geometry):
                if float(line.length) > 0.0:
                    lines.append(line)

        if not lines:
            raise ValueError(f"linear constraint '{name_text}' produced no usable line segment.")
        return cls(
            name=name_text,
            kind=kind_text,
            lines=tuple(lines),
            participates_in_refinement=bool(payload.get("participates_in_refinement", True)),
        )


@dataclass(frozen=True)
class ZoneRegionalSizeField:
    """One regional inside/outside background-size field."""

    name: str
    region_geometry: BaseGeometry
    inside_size: float
    outside_size: float
    transition_distance: float | None
    grid_resolution: float
