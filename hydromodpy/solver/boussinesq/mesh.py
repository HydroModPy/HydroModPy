"""Solver-owned mesh view for the gmsh catchment bundle contract.

The gmsh bundle reader exposes a rich, generic description of the catchment
mesh. The Boussinesq solver only needs a compact subset of that information:

- cell geometry and material properties,
- edge connectivity and metric terms,
- a few helper methods to locate wells and identify boundary supports.

This module performs that narrowing once, up front, so the assembly and runtime
code can work with contiguous NumPy arrays only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.boussinesq._mesh_builders import (
    assemble_mesh_arrays_from_bundle,
    build_planar_mesh_kwargs,
    build_runtime_bundle_from_cell_mesh,
    family_edge_indices,
)
from hydromodpy.solver.boussinesq._mesh_geometry import point_in_triangle
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
)
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells
from hydromodpy.spatial.mesh.ops.family_cells import SIDE_IDS, label_cells, side_cells

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


@dataclass(frozen=True)
class BoussinesqMesh:
    """Compact in-memory mesh view used by the Boussinesq backend.

    Every array is solver-oriented: ids are normalized to positional indices
    whenever useful, distances are precomputed and the geometry is kept
    immutable through the frozen dataclass contract.

    A mesh built from a runtime cell mesh keeps it in ``cell_mesh``: its edges
    are the edges of the cell mesh, in order, and its sides, river and cell
    location are read from the cell mesh. A mesh built from a mesh bundle (the
    validation cases) has no ``cell_mesh``; its sides come from the bounding box
    of the edge midpoints and its cells are located triangle by triangle.
    """

    bundle_dir: Path
    cell_ids: np.ndarray
    node_ids: np.ndarray
    node_x_m: np.ndarray
    node_y_m: np.ndarray
    cell_node_ids: tuple[tuple[int, ...], ...]
    cell_centroid_x_m: np.ndarray
    cell_centroid_y_m: np.ndarray
    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    hydraulic_conductivity_m_s: np.ndarray
    storage_coefficient: np.ndarray
    edge_ids: np.ndarray
    edge_node_a: np.ndarray
    edge_node_b: np.ndarray
    edge_cell_a: np.ndarray
    edge_cell_b: np.ndarray
    edge_length_m: np.ndarray
    edge_distance_m: np.ndarray
    edge_midpoint_distance_to_cell_a_m: np.ndarray
    edge_midpoint_distance_to_cell_b_m: np.ndarray
    edge_midpoint_x_m: np.ndarray
    edge_midpoint_y_m: np.ndarray
    edge_kind: tuple[str, ...]
    edge_is_river: np.ndarray
    cell_index_by_id: dict[int, int]
    node_index_by_id: dict[int, int]
    cell_mesh: PlanarCellMesh | None = None
    support_metadata: GmshSupportMetadata | None = None
    # solver.drain_bed_thickness_m, with the same default. The flow adapter sets it.
    drain_bed_thickness_m: float = 1.0

    def __post_init__(self) -> None:
        bed_thickness = float(self.drain_bed_thickness_m)
        if not np.isfinite(bed_thickness) or bed_thickness <= 0.0:
            raise ValueError(
                f"drain_bed_thickness_m must be finite and positive; got {bed_thickness}."
            )

    @property
    def planar_mesh(self) -> HydroMesh | None:
        """The planar ``HydroMesh`` of the cell mesh, ``None`` for a bundle mesh."""
        return None if self.cell_mesh is None else self.cell_mesh.mesh

    @property
    def n_cells(self) -> int:
        return int(self.cell_ids.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_ids.size)

    @property
    def n_nodes(self) -> int:
        return int(self.node_ids.size)

    @property
    def interior_edge_mask(self) -> np.ndarray:
        return self.edge_cell_b >= 0

    @property
    def boundary_edge_mask(self) -> np.ndarray:
        return self.edge_cell_b < 0

    @property
    def x_min_m(self) -> float:
        return float(np.min(self.node_x_m))

    @property
    def x_max_m(self) -> float:
        return float(np.max(self.node_x_m))

    @property
    def y_min_m(self) -> float:
        return float(np.min(self.node_y_m))

    @property
    def y_max_m(self) -> float:
        return float(np.max(self.node_y_m))

    def boundary_edge_indices_for_side(
        self,
        bc_id: str,
        *,
        tolerance_m: float | None = None,
    ) -> np.ndarray:
        """Return boundary edges that belong to one outer side.

        A mesh built from a cell mesh reads them in its ``boundary:<side>`` face
        family. A mesh built from a bundle infers the side from the edge
        midpoints and the mesh bounding box, which is sufficient for the
        rectangular strip-like domains of the validation cases; ``tolerance_m``
        is the distance to the box that bundle rule accepts.
        """
        if bc_id not in SIDE_IDS:
            raise ValueError(f"Unsupported side boundary id: {bc_id}.")
        if self.cell_mesh is not None:
            return family_edge_indices(self.cell_mesh, f"boundary:{bc_id.removesuffix('_side')}")
        boundary_mask = np.asarray(self.boundary_edge_mask, dtype=bool)
        if tolerance_m is None:
            span_x = max(self.x_max_m - self.x_min_m, 0.0)
            span_y = max(self.y_max_m - self.y_min_m, 0.0)
            tolerance_m = max(1.0e-9, 1.0e-8 * max(span_x, span_y, 1.0))

        midpoint, edge = {
            "west_side": (self.edge_midpoint_x_m, self.x_min_m),
            "east_side": (self.edge_midpoint_x_m, self.x_max_m),
            "south_side": (self.edge_midpoint_y_m, self.y_min_m),
            "north_side": (self.edge_midpoint_y_m, self.y_max_m),
        }[bc_id]
        side_mask = np.isclose(midpoint, edge, atol=float(tolerance_m), rtol=0.0)
        return np.flatnonzero(boundary_mask & side_mask).astype(int, copy=False)

    def boundary_cell_indices_for_side(
        self,
        bc_id: str,
        *,
        tolerance_m: float | None = None,
    ) -> np.ndarray:
        """Return owner-cell indices for one outer side of the domain."""
        if self.cell_mesh is not None:
            return side_cells(self.cell_mesh, bc_id)
        edge_indices = self.boundary_edge_indices_for_side(
            bc_id,
            tolerance_m=tolerance_m,
        )
        if edge_indices.size == 0:
            return np.asarray([], dtype=int)
        return np.unique(np.asarray(self.edge_cell_a[edge_indices], dtype=int)).astype(
            int, copy=False
        )

    def edge_indices_for_label(self, label: str) -> np.ndarray:
        """Return the edges of one support label: ``stream``, a side id or ``boundary:<name>``.

        Only a mesh built from a cell mesh knows its families.
        """
        cell_mesh = self._require_cell_mesh(f"the support label '{label}'")
        text = str(label).strip()
        if text in ("stream", "river"):
            return self.river_edge_indices()
        if text in SIDE_IDS:
            return self.boundary_edge_indices_for_side(text)
        if text.startswith("boundary:"):
            return family_edge_indices(cell_mesh, text)
        return np.empty(0, dtype=np.int64)

    def cell_indices_for_label(self, label: str) -> np.ndarray:
        """Return the cells of one support label, as :meth:`edge_indices_for_label` reads it."""
        return label_cells(self._require_cell_mesh(f"the support label '{label}'"), label)

    def _require_cell_mesh(self, what: str) -> PlanarCellMesh:
        """Return the cell mesh, or say that ``what`` needs one."""
        if self.cell_mesh is None:
            raise ValueError(
                f"{what} is read from the face families of a cell mesh, and this "
                "Boussinesq mesh was built from a mesh bundle."
            )
        return self.cell_mesh

    def locate_cell_index_for_point(
        self,
        x_m: float,
        y_m: float,
        *,
        allow_nearest: bool = True,
    ) -> int:
        """Return the cell index that contains one XY point.

        A point on an edge belongs to the cell of smallest index. If the point
        lies outside the mesh and ``allow_nearest`` is true, it takes the nearest
        cell centre, which is convenient for wells and observation points defined
        in approximate coordinates.
        """
        point_x_m = float(x_m)
        point_y_m = float(y_m)
        if self.cell_mesh is not None:
            cell = int(
                locate_cells(
                    self.cell_mesh,
                    np.array([[point_x_m, point_y_m]]),
                    allow_nearest=allow_nearest,
                )[0]
            )
            if cell < 0:
                raise ValueError(
                    f"Point ({point_x_m}, {point_y_m}) is outside the triangular mesh domain."
                )
            return cell
        for cell_index, node_ids in enumerate(self.cell_node_ids):
            if len(node_ids) != 3:
                continue
            node_indices = [self.node_index_by_id[int(node_id)] for node_id in node_ids]
            triangle_x_m = self.node_x_m[np.asarray(node_indices, dtype=int)]
            triangle_y_m = self.node_y_m[np.asarray(node_indices, dtype=int)]
            if point_in_triangle(point_x_m, point_y_m, triangle_x_m, triangle_y_m):
                return int(cell_index)

        if not allow_nearest:
            raise ValueError(
                f"Point ({point_x_m}, {point_y_m}) is outside the triangular mesh domain."
            )

        dx = self.cell_centroid_x_m - point_x_m
        dy = self.cell_centroid_y_m - point_y_m
        return int(np.argmin((dx * dx) + (dy * dy)))

    def river_edge_indices(self) -> np.ndarray:
        """Return all edges tagged as river support in the gmsh bundle."""
        return np.flatnonzero(np.asarray(self.edge_is_river, dtype=bool)).astype(
            int,
            copy=False,
        )

    def river_cell_indices(self) -> np.ndarray:
        """Return owner-cell indices for edges tagged as river support."""
        edge_indices = self.river_edge_indices()
        if edge_indices.size == 0:
            return np.asarray([], dtype=int)
        return np.unique(np.asarray(self.edge_cell_a[edge_indices], dtype=int)).astype(
            int, copy=False
        )

    @classmethod
    def from_cell_mesh(
        cls,
        cell_mesh: PlanarCellMesh,
        *,
        domain: DomainLike,
        hydraulic_conductivity_m_s,
        storage_coefficient,
        source_path: Path | None = None,
    ) -> BoussinesqMesh:
        """Build the solver mesh view directly from one runtime planar cell mesh.

        This path keeps the solver in the same architectural shape as the
        MODFLOW adapters: geometry comes from the runtime meshing workflow and
        hydraulic properties come from process-level parameter mapping rather
        than pre-exported CSV tables. The river is the ``rivers`` face family of
        the cell mesh.
        """
        runtime_bundle = build_runtime_bundle_from_cell_mesh(
            cell_mesh,
            domain=domain,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            storage_coefficient=storage_coefficient,
            source_path=source_path,
        )
        base_mesh = cls.from_bundle(runtime_bundle)
        return cls(**build_planar_mesh_kwargs(base_mesh=base_mesh, cell_mesh=cell_mesh))

    @classmethod
    def from_bundle(cls, bundle: CatchmentMeshBundle) -> BoussinesqMesh:
        """Build the solver mesh view from one gmsh catchment bundle.

        This constructor is the main translation layer between the generic gmsh
        exchange object and the compact arrays used by the solver. It also
        performs early validation so runtime code can assume the mesh is
        physically coherent.
        """
        return cls(**assemble_mesh_arrays_from_bundle(bundle))


__all__ = ["BoussinesqMesh"]
