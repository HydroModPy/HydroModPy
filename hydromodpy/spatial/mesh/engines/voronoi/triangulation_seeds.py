"""The Voronoi dual of a triangulation read from a file: its vertices are the generators.

No constraint seed and no relaxation: the refinement and the lines the triangles
follow are in the vertex placement. The cells are tessellated as in the
generated mode (``tessellation.py``, in the local frame); the families are
carried over from the triangles (``dual_families.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import shapely

from hydromodpy.spatial.mesh.engines.triangle.engine import triangulate_request
from hydromodpy.spatial.mesh.engines.triangle.families import face_table
from hydromodpy.spatial.mesh.engines.voronoi.dual_families import (
    dual_chains,
    dual_face_families,
    river_faces,
    side_faces,
)
from hydromodpy.spatial.mesh.engines.voronoi.frame import local_frame
from hydromodpy.spatial.mesh.engines.voronoi.gates import check_gates, gated_geometry
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    cell_topology,
    tessellate,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = ["dual_cell_mesh"]

_FACES_NOTE = (
    "voronoi dual faces do not follow the face family lines: a face family is the "
    "staircase of dual faces between its two sides, rivers faces are the dual faces "
    "a river edge crosses"
)


def dual_cell_mesh(
    request: MeshRequest,
    *,
    identity: MeshIdentity,
    declarations: Mapping[str, bool],
    notes: Sequence[str],
) -> PlanarCellMesh:
    """Tessellate the vertices of the triangulation of *request*; the gates raise on any fault.

    *notes* open the notes of the mesh QA.
    """
    triangulated = triangulate_request(request)
    frame = local_frame(request.domain)
    domain = shapely.normalize(frame.to_local(request.domain))
    shapely.prepare(domain)
    generators = np.asarray(triangulated.mesh.vertices, dtype=float)[:, :2]
    seeds = frame.to_local(generators)
    tess = tessellate(seeds, len(seeds), domain, voronoi_envelope(domain, request.nominal_size_m))
    topology = cell_topology(tess.cells, frame)
    # The generators come first and unmoved; the boundary seeds the tessellation added follow.
    centers = np.vstack([generators, frame.to_world(tess.seeds[len(generators) :])])
    mesh = HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=topology.rings),),
        cell_data={"disv_cell_center": centers},
    )
    geometry = gated_geometry(mesh)
    chains = dual_chains(triangulated, geometry, centers)
    check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=geometry,
        domain_area=domain.area,
        frame=frame,
        chains=chains,
    )
    vertices = np.asarray(mesh.vertices, dtype=float)
    families = (
        river_faces(triangulated, geometry, vertices),
        *side_faces(geometry, vertices, centers),
        *dual_face_families(triangulated, geometry, vertices),
    )
    return build_planar_cell_mesh(
        mesh,
        centers,
        geometry=geometry,
        center_kind="generator",
        crs_wkt=request.crs_wkt,
        identity=identity,
        declarations=declarations,
        cell_chains=chains,
        face_families=face_table(tuple(family for family in families if family is not None)),
        zone_names=triangulated.families.zone_names,
        domain_area_m2=request.domain.area,
        lines=triangulated.lines_for_qa(),
        notes=(
            *notes,
            *triangulated.notes,
            "voronoi generators are the vertices of the input triangulation",
            _FACES_NOTE,
        ),
        extras={
            "boundary_seeds_added": float(tess.boundary_seeds_added),
            "origin_x": frame.origin[0],
            "origin_y": frame.origin[1],
        },
    )
