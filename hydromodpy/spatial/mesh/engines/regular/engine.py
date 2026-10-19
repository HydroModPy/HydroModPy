"""The ``regular`` mesh engine: square cells on the DEM rectangle, row 0 north.

The mesh is a function of the grid and of one size only: the domain polygon, the
size field and the river sizes shape no cell. The solver masks the cells outside
the domain. Rivers are cell chains (thin-line rasterization), face families are
staircases, and the QA says so.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.regular.families import cell_chains, face_family_columns
from hydromodpy.spatial.mesh.engines.regular.grid import plan_layout, quad_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.ops.side_offset import annotate_side_cells
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = ["RegularMeshEngine"]

_SIDE_STATEMENT = (
    "a side head applies to the cells that have a face on the side: their centre is "
    "half a cell inside the domain"
)


class RegularMeshEngine:
    """Quadrilateral cells of one pitch, bit for bit the grid flopy builds."""

    engine_id: ClassVar[str] = "regular"
    engine_version: ClassVar[str] = "1.0.1"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.QUADRILATERAL,),
        structured=True,
        graded=False,
        exact_faces=False,
        cell_families="rasterized",
        deterministic=True,
        needs_cache=False,
    )

    def build(self, request: MeshRequest) -> PlanarCellMesh:
        """Build the grid of *request*; refuse an input triangulation or a size finer than the DEM."""
        if request.input_triangulation is not None:
            raise MeshRequestError("the regular engine cannot use an input triangulation")
        layout = plan_layout(request.grid, request.nominal_size_m, request.options)
        mesh = quad_mesh(layout)
        corners = mesh.vertices[np.asarray(mesh.flat_connectivity)]
        centers = corners.mean(axis=1)
        geometry = derive_geometry(mesh)

        chains = []
        for spec in request.lines:
            if spec.intent == "cell":
                chains += cell_chains(
                    spec, mesh, centers, layout, request.crs_wkt, first_chain_id=len(chains)
                )
        faces = face_family_columns(
            [spec for spec in request.lines if spec.intent == "face"],
            request.domain,
            geometry,
            centers,
            layout,
        )

        notes = []
        if request.size_field is not None:
            notes.append("regular ignores the size field")
        if not layout.native:
            notes.append(
                f"regular resamples the DEM to {layout.nrow} x {layout.ncol} cells "
                f"of {layout.dy:g} x {layout.dx:g} m"
            )
        cell_mesh = build_planar_cell_mesh(
            mesh,
            centers,
            geometry=geometry,
            center_kind="cell_center",
            crs_wkt=request.crs_wkt,
            identity=MeshIdentity(
                self.engine_id, self.engine_version, request.canonical_hash(), None
            ),
            declarations=self.capabilities.declarations(),
            cell_chains=chains,
            face_families=faces.table,
            cell_zone=faces.cell_zone,
            zone_names=faces.zone_names,
            structured_shape=(layout.nrow, layout.ncol),
            domain_area_m2=layout.nrow * layout.dy * layout.ncol * layout.dx,
            lines={spec.name: spec.lines for spec in request.lines},
            notes=notes,
            extras={"dx_m": layout.dx, "dy_m": layout.dy},
        )
        return annotate_side_cells(cell_mesh, _SIDE_STATEMENT)
