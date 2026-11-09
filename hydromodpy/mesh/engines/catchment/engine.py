"""The ``catchment`` mesh engine: the catchment the outlet closes, as one polygon cell.

A global model, such as a linear reservoir, computes on the catchment as a whole.
This engine gives it one cell whose vertices are the exterior ring of
``MeshRequest.catchment``, turned counterclockwise, with no face. The planner
fills that member for this engine only: the delineated polygon, or the domain on
a synthetic support. A delineated outline in several parts keeps its largest
part, as the planner does for every engine.

A hole of the outline is filled, and a note of the mesh says how many and how
large: water that falls in a hole of a delineated catchment still reaches its
outlet. The center is the point shapely's ``point_on_surface`` gives, so it lies
in the cell even when the vertex mean of a concave catchment falls outside it.

The engine refuses lines, a size field and an input triangulation. One cell holds
no chain, no face and no grading, so it would only drop them in silence.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.mesh.port import MeshEngineCapabilities
from hydromodpy.mesh.request import FAMILY_NAMES, MeshRequest

__all__ = ["CatchmentMeshEngine"]


class CatchmentMeshEngine:
    """One polygon cell on the exterior ring of the catchment, no face."""

    engine_id: ClassVar[str] = "catchment"
    engine_version: ClassVar[str] = "1"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.POLYGON,),
        structured=False,
        graded=False,
        exact_faces=False,
        cell_families="derived_from_faces",
        deterministic=True,
        needs_cache=False,
        lumped=True,
        ignored_families=FAMILY_NAMES,
    )

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Build the one cell of ``request.catchment``; refuse what one cell cannot hold."""
        catchment = _catchment_of(request)
        shell = orient(shapely.remove_repeated_points(Polygon(catchment.exterior)), sign=1.0)
        ring = np.asarray(shell.exterior.coords, dtype=np.float64)[:-1, :2]
        mesh = HydroMesh(
            vertices=ring,
            cell_blocks=(CellBlock(CellType.POLYGON, np.arange(len(ring))[None, :]),),
        )
        center = np.asarray(shapely.point_on_surface(shell).coords, dtype=np.float64)
        return build_planar_cell_mesh(
            mesh,
            center.reshape(1, 2),
            center_kind="interior_point",
            crs_wkt=request.crs_wkt,
            identity=MeshIdentity(
                self.engine_id, self.engine_version, request.canonical_hash(), None
            ),
            declarations=self.capabilities.declarations(),
            domain_area_m2=float(shell.area),
            notes=_hole_notes(catchment, shell),
        )


def _catchment_of(request: MeshRequest) -> Polygon:
    """The catchment of *request*, or the refusal that names the member at fault."""
    if request.catchment is None:
        raise MeshRequestError(
            "the catchment engine meshes MeshRequest.catchment as one cell, and the request "
            "carries no catchment"
        )
    refused = [
        name
        for name, given in (
            ("lines", bool(request.lines)),
            ("size_field", request.size_field is not None),
            ("input_triangulation", request.input_triangulation is not None),
        )
        if given
    ]
    if refused:
        raise MeshRequestError(
            "the catchment engine meshes the catchment as one cell and refuses "
            + ", ".join(f"MeshRequest.{name}" for name in refused)
        )
    return request.catchment


def _hole_notes(catchment: Polygon, shell: Polygon) -> tuple[str, ...]:
    """One note on the holes the cell fills, none when the outline has no hole."""
    holes = len(catchment.interiors)
    if holes == 0:
        return ()
    filled_m2 = shell.area - catchment.area
    return (
        f"catchment fills {holes} hole{'s' if holes > 1 else ''} of the catchment outline, "
        f"{filled_m2:.6g} m2 in all: water that falls in a hole still reaches the outlet",
    )
