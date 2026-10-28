"""The ``voronoi`` engine: polygons around generators, orthogonal to their neighbours.

``seeds = "generated"`` places the generators itself (``generated.py``): river
seeds, Berge mirror pairs on the face lines, boundary seeds, then free seeds
relaxed by a weighted Lloyd iteration, and tessellates them with GEOS. Every face
lies on the perpendicular bisector of its two generators. ``seeds =
"triangulation"`` takes the vertices of a triangulation read from a file as the
generators (``from_triangulation.py``). The engine takes the second path
exactly when the request carries a triangulation: ``[mesh.voronoi] seeds``
agrees with ``[mesh.triangle] path``, which the config checks.

The engine draws its free seeds from the request seed with an explicit generator
and reads no global state, so one request gives one mesh on one platform and one
GEOS version: it asks for no cache.
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar

import numpy as np

from hydromodpy.spatial.mesh.cache import library_versions
from hydromodpy.spatial.mesh.engines.voronoi.from_triangulation import dual_cell_mesh
from hydromodpy.spatial.mesh.engines.voronoi.generated import generate_cell_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.planar_cell_mesh import MeshIdentity, PlanarCellMesh
from hydromodpy.spatial.mesh.ops.side_offset import annotate_side_cells
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.request import MeshRequest, SizeField
from hydromodpy.spatial.mesh.resample import resample_families

__all__ = ["VoronoiMeshEngine"]

_SIDE_STATEMENT = (
    "a side head applies to the cells whose generator lies on the side, so the head sits on "
    "the boundary; when no generator lies there it applies to the cells that have a face on "
    "the side"
)


def _platform_note() -> str:
    """The library builds this mesh is reproducible with, since GEOS and scipy can move a vertex."""
    versions = {**library_versions(), "numpy": np.__version__}
    del versions["gmsh"]
    return "the voronoi mesh is reproducible with " + ", ".join(
        f"{name} {version}" for name, version in versions.items()
    )


def _prepared(request: MeshRequest) -> MeshRequest:
    """The request with a size field and its lines noded and resampled at the local size.

    A request without a size field gets its nominal size as a constant one. The
    generator needs the crossings of the lines as vertices of both lines and one
    vertex per local cell along them; the planner has done both, and a second pass
    moves a vertex by a few millimetres at most. A request built by hand gets here
    what the planner would have given it.
    """
    size_field = request.size_field
    if size_field is None:
        grid = request.grid
        size_field = SizeField(np.full((grid.nrow, grid.ncol), request.nominal_size_m), grid)
    lines = resample_families(request.lines, domain=request.domain, size_field=size_field).families
    return dataclasses.replace(request, size_field=size_field, lines=lines)


class VoronoiMeshEngine:
    """Voronoi cells around generated generators, or around the vertices of a read triangulation."""

    engine_id: ClassVar[str] = "voronoi"
    engine_version: ClassVar[str] = "2.4.0"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.POLYGON,),
        structured=False,
        graded=True,
        exact_faces=True,
        cell_families="exact",
        deterministic=True,
        needs_cache=False,
    )

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Generate the generators of the request, or read them, and tessellate."""
        declarations = self.capabilities.declarations()
        notes = (*request.notes, _platform_note())
        if request.input_triangulation is None:
            identity = MeshIdentity(
                self.engine_id, self.engine_version, request.canonical_hash(), request.seed
            )
            cell_mesh = generate_cell_mesh(
                _prepared(request),
                identity=identity,
                declarations=declarations,
                notes=notes,
            )
        else:
            identity = MeshIdentity(
                self.engine_id, self.engine_version, request.canonical_hash(), None
            )
            cell_mesh = dual_cell_mesh(
                request, identity=identity, declarations=declarations, notes=notes
            )
        return annotate_side_cells(cell_mesh, _SIDE_STATEMENT)
