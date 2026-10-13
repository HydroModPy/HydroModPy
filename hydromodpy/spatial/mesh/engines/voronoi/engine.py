"""The ``voronoi`` engine: the Voronoi dual of the ``triangle`` triangulation.

Until the generator of its own arrives, the engine wraps the current production
dual: the triangulation vertices are the generators, the dual is clipped to the
outline of the triangulation, and the support of the triangles is rebuilt on
the dual cells. A river line runs through triangulation vertices, so its chain
is the dual cells of those vertices in line order: exact, centred on the line.
Dual faces do not follow the face family lines: a contact becomes the staircase
of dual faces between its two sides, with its distance to the line in the QA.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.adapters.cell_mesh import cell_mesh_from_voronoi_dual
from hydromodpy.spatial.mesh.engines.triangle.engine import (
    TriangleMeshEngine,
    triangulate_request,
)
from hydromodpy.spatial.mesh.engines.voronoi.families import (
    dual_cell_zones,
    dual_chains,
    dual_face_families,
    merge_face_tables,
)
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    support_from_cell_mesh,
    support_on_planar_mesh,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.ops.side_offset import annotate_side_cells
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_dual_of_mesh
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = ["VoronoiMeshEngine", "generator_cells"]

_SIDE_STATEMENT = (
    "a side head applies to the cells whose generator lies on the side, so the head sits on "
    "the boundary; when no generator lies there it applies to the cells that have a face on "
    "the side"
)
_SOURCE_OF_SEEDS = {"generated": "generated", "triangulation": "input"}
_SEEDS = tuple(_SOURCE_OF_SEEDS)


def _seeds(request: MeshRequest) -> str:
    """The generator source the request names, checked against its input triangulation."""
    given = request.input_triangulation is not None
    seeds = str(request.options.get("seeds", "triangulation" if given else "generated"))
    if seeds not in _SEEDS:
        raise MeshRequestError(f"unknown voronoi seeds {seeds!r}; expected one of {_SEEDS}")
    if seeds == "triangulation" and not given:
        raise MeshRequestError('voronoi seeds = "triangulation" needs an input triangulation')
    if seeds == "generated" and given:
        raise MeshRequestError(
            'voronoi seeds = "generated" generates its triangulation; '
            "the request also carries one to read"
        )
    return seeds


def generator_cells(generators: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Dual cell of each generator, ``-1`` for a generator without its own cell.

    The dual keeps the generator order and drops a generator whose cell lies
    outside the domain. A kept cell is centred on its generator unless the clip
    split it; such a cell takes the generator left between its matched
    neighbours when exactly one is left there.
    """
    n_generators = len(generators)
    if len(centers) == n_generators:
        return np.arange(n_generators, dtype=np.int64)
    index = {xy: i for i, xy in enumerate(map(tuple, generators.tolist()))}
    generator_of = np.asarray([index.get(xy, -1) for xy in map(tuple, centers.tolist())])
    cell_of = np.full(n_generators, -1, dtype=np.int64)
    matched = np.flatnonzero(generator_of >= 0)
    cell_of[generator_of[matched]] = matched
    unmatched = generator_of < 0
    n_cells = len(centers)
    for cell in np.flatnonzero(unmatched).tolist():
        if (cell > 0 and unmatched[cell - 1]) or (cell + 1 < n_cells and unmatched[cell + 1]):
            continue
        low = int(generator_of[cell - 1]) + 1 if cell > 0 else 0
        high = int(generator_of[cell + 1]) if cell + 1 < n_cells else n_generators
        if high - low == 1:
            cell_of[low] = cell
    return cell_of


class VoronoiMeshEngine:
    """Voronoi cells around the vertices of a triangulation, clipped to its outline."""

    engine_id: ClassVar[str] = "voronoi"
    engine_version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.POLYGON,),
        structured=False,
        graded=True,
        exact_faces=False,
        cell_families="exact",
        deterministic=False,
        needs_cache=True,
    )

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Triangulate the request, take the dual and carry its families over."""
        seeds = _seeds(request)
        triangulated = triangulate_request(request)
        triangles = TriangleMeshEngine().assemble(triangulated)
        triangulation = triangles.mesh
        dual = voronoi_dual_of_mesh(triangulation, domain_polygon_from_mesh(triangulation))
        adapted = cell_mesh_from_voronoi_dual(
            dual,
            support_on_planar_mesh(support_from_cell_mesh(triangles), dual),
            crs_wkt=request.crs_wkt,
        )
        cell_of_vertex = generator_cells(
            np.asarray(triangulation.vertices, dtype=float), adapted.centers
        )
        geometry = adapted.geometry
        dual_vertices = np.asarray(dual.vertices, dtype=float)
        face_families = merge_face_tables(
            adapted.face_families,
            dual_face_families(triangulated, cell_of_vertex, geometry, dual_vertices),
        )
        notes = (
            *triangulated.notes,
            f"voronoi generators are the vertices of the {_SOURCE_OF_SEEDS[seeds]} triangulation",
            "voronoi dual faces do not follow the face family lines: a face family is the "
            "staircase of dual faces between its two sides, rivers faces are the dual faces "
            "a river edge crosses",
        )
        cell_mesh = build_planar_cell_mesh(
            dual,
            adapted.centers,
            geometry=geometry,
            center_kind="generator",
            crs_wkt=request.crs_wkt,
            identity=MeshIdentity(
                self.engine_id,
                self.engine_version,
                request.canonical_hash(),
                None if triangulated.read else request.seed,
            ),
            declarations=self.capabilities.declarations(),
            cell_chains=dual_chains(triangulated, cell_of_vertex, geometry, adapted.centers),
            face_families=face_families,
            cell_zone=dual_cell_zones(
                triangulated, triangles.cell_zone, cell_of_vertex, dual.n_cells
            ),
            zone_names=triangles.zone_names,
            domain_area_m2=request.domain.area,
            lines=triangulated.lines_for_qa(),
            notes=notes,
        )
        return annotate_side_cells(cell_mesh, _SIDE_STATEMENT)
