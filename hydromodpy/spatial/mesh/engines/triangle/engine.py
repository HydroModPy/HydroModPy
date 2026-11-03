"""The ``triangle`` engine: gmsh constrained Delaunay triangles, or a read ``.msh``.

A generated triangulation embeds every family line as mesh edges, so face
families are exact. The ``rivers`` cell family is derived from its faces: the
triangles on the left bank of each line, in order. Centers are the vertex
means the solvers use. gmsh is not reproducible, so the engine asks for a cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from hydromodpy.spatial.mesh.cells.boundary import annotate_side_cells
from hydromodpy.spatial.mesh.engines.face_families import (
    EdgeLookup,
    box_side_edges,
    edge_lookup,
    face_table,
    request_zone_names,
)
from hydromodpy.spatial.mesh.engines.triangle.families import (
    TriangleFamilies,
    cell_zones,
    chains_of,
    families_from_line_edges,
    families_from_matching,
)
from hydromodpy.spatial.mesh.engines.triangle.gmsh_triangulation import triangulate
from hydromodpy.spatial.mesh.engines.triangle.msh_groups import families_from_labels
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.geometry import DerivedGeometry, derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest

if TYPE_CHECKING:
    from shapely.geometry import LineString

__all__ = ["TriangleMeshEngine", "TriangulatedRequest", "triangulate_request"]

_SIDE_STATEMENT = (
    "a side head applies to the triangles that have an edge on the side: their centre is "
    "the vertex mean, inside the domain"
)


@dataclass(frozen=True, eq=False)
class TriangulatedRequest:
    """A triangulation of a request with its families, before any cell mesh.

    ``lines`` are the families with the lines the triangulation follows: those
    gmsh embedded, or those of the request for a triangulation read. The
    ``voronoi`` engine starts from the same object: its generators are the
    vertices and its river chains follow the ``rivers`` edges.
    """

    request: MeshRequest
    lines: tuple[LineFamilySpec, ...]
    mesh: HydroMesh
    geometry: DerivedGeometry
    lookup: EdgeLookup
    families: TriangleFamilies
    read: bool
    notes: tuple[str, ...]

    def lines_for_qa(self) -> dict[str, tuple[LineString, ...]]:
        """The source lines of each requested family, for the QA."""
        return {family.name: family.lines for family in self.lines}


def _read_families(
    request: MeshRequest, mesh: HydroMesh, geometry: DerivedGeometry, lookup: EdgeLookup
) -> tuple[TriangleFamilies, tuple[str, ...]]:
    """Families of a read triangulation: physical line groups first, else the request lines."""
    triangulation = request.input_triangulation
    labelled, label_zones, notes = families_from_labels(triangulation.edge_labels, lookup, geometry)
    from_labels = frozenset(family.name for family in labelled)
    matched = families_from_matching(request, mesh.vertices, geometry, lookup, skip=from_labels)
    cell_families = {family.name for family in request.lines if family.intent == "cell"}
    if "rivers" in from_labels:
        cell_families.add("rivers")
    families = TriangleFamilies(
        families=labelled + matched,
        zone_names=label_zones if "geology" in from_labels else request_zone_names(request),
        cell_families=tuple(sorted(cell_families)),
    )
    note = "triangle read the input triangulation; family lines were not embedded"
    return families, (note, *notes)


def triangulate_request(request: MeshRequest) -> TriangulatedRequest:
    """Triangulate *request*, or take its input triangulation, and derive its families."""
    triangulation = request.input_triangulation
    if triangulation is not None:
        vertices = np.asarray(triangulation.vertices, dtype=np.float64)
        triangles = np.asarray(triangulation.triangles, dtype=np.int64)
        lines = request.lines
    else:
        generated = triangulate(request)
        vertices, triangles, lines = generated.vertices, generated.triangles, generated.lines
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=CellType.TRIANGLE, connectivity=triangles),),
    )
    geometry = derive_geometry(mesh)
    lookup = edge_lookup(vertices, triangles)
    if triangulation is None:
        families = families_from_line_edges(request, lookup, generated.line_edges)
        notes: tuple[str, ...] = ()
    else:
        families, notes = _read_families(request, mesh, geometry, lookup)
    return TriangulatedRequest(
        request=request,
        lines=lines,
        mesh=mesh,
        geometry=geometry,
        lookup=lookup,
        families=TriangleFamilies(
            families=families.families + box_side_edges(vertices, geometry, lookup),
            zone_names=families.zone_names,
            cell_families=families.cell_families,
        ),
        read=triangulation is not None,
        notes=notes,
    )


def _target_size(request: MeshRequest, centers: np.ndarray) -> np.ndarray:
    """The cell size [m] the request asks for at each center, for the QA."""
    if request.size_field is None:
        return np.full(len(centers), request.nominal_size_m)
    return request.size_field.sample(centers)


class TriangleMeshEngine:
    """Triangles of a gmsh constrained Delaunay triangulation (or of a read ``.msh``)."""

    engine_id: ClassVar[str] = "triangle"
    engine_version: ClassVar[str] = "1.2.0"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.TRIANGLE,),
        structured=False,
        graded=True,
        exact_faces=True,
        cell_families="derived_from_faces",
        deterministic=False,
        needs_cache=True,
    )

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Triangulate the request and assemble its planar cell mesh."""
        triangulated = triangulate_request(request)
        return self.assemble(triangulated)

    def assemble(self, triangulated: TriangulatedRequest) -> PlanarCellMesh:
        """The planar cell mesh of a triangulated request."""
        mesh = triangulated.mesh
        families = triangulated.families
        chains = tuple(
            chain
            for name in families.cell_families
            if (family := families.get(name)) is not None
            for chain in chains_of(family, triangulated.lookup)
        )
        request = triangulated.request
        centers = mesh.vertices[np.asarray(mesh.flat_connectivity)].mean(axis=1)
        cell_mesh = build_planar_cell_mesh(
            mesh,
            centers,
            geometry=triangulated.geometry,
            center_kind="vertex_mean",
            crs_wkt=request.crs_wkt,
            identity=MeshIdentity(
                self.engine_id,
                self.engine_version,
                request.canonical_hash(),
                None if triangulated.read else request.seed,
            ),
            declarations=self.capabilities.declarations(),
            cell_chains=chains,
            face_families=face_table(families.families),
            cell_zone=cell_zones(
                triangulated.geometry, families.get("geology"), len(families.zone_names)
            ),
            zone_names=families.zone_names,
            domain_area_m2=request.domain.area,
            lines=triangulated.lines_for_qa(),
            target_size=None if triangulated.read else _target_size(request, centers),
            notes=triangulated.notes,
        )
        return annotate_side_cells(cell_mesh, _SIDE_STATEMENT)
