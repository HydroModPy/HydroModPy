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

import numpy as np

from hydromodpy.solver.boussinesq._mesh_builders import (
    assemble_mesh_arrays_from_bundle,
    build_planar_mesh_kwargs,
    build_runtime_bundle_from_planar_mesh,
)
from hydromodpy.solver.boussinesq._mesh_geometry import point_in_triangle
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
)


@dataclass(frozen=True)
class BoussinesqMesh:
    """Compact in-memory mesh view used by the Boussinesq backend.

    Every array is solver-oriented: ids are normalized to positional indices
    whenever useful, distances are precomputed and the geometry is kept
    immutable through the frozen dataclass contract.
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
    planar_mesh: GmshPlanarMesh2D | None = None
    support_metadata: GmshSupportMetadata | None = None

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
        """Return boundary edges that geometrically belong to one outer side.

        The side is inferred from edge midpoints and the mesh bounding box,
        which is sufficient for the rectangular strip-like domains used by the
        current Boussinesq validation cases.
        """
        boundary_mask = np.asarray(self.boundary_edge_mask, dtype=bool)
        if tolerance_m is None:
            span_x = max(self.x_max_m - self.x_min_m, 0.0)
            span_y = max(self.y_max_m - self.y_min_m, 0.0)
            tolerance_m = max(1.0e-9, 1.0e-8 * max(span_x, span_y, 1.0))

        if bc_id == "west_side":
            side_mask = np.isclose(
                self.edge_midpoint_x_m,
                self.x_min_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "east_side":
            side_mask = np.isclose(
                self.edge_midpoint_x_m,
                self.x_max_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "south_side":
            side_mask = np.isclose(
                self.edge_midpoint_y_m,
                self.y_min_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        elif bc_id == "north_side":
            side_mask = np.isclose(
                self.edge_midpoint_y_m,
                self.y_max_m,
                atol=float(tolerance_m),
                rtol=0.0,
            )
        else:
            raise ValueError(f"Unsupported side boundary id: {bc_id}.")
        return np.flatnonzero(boundary_mask & side_mask).astype(int, copy=False)

    def boundary_cell_indices_for_side(
        self,
        bc_id: str,
        *,
        tolerance_m: float | None = None,
    ) -> np.ndarray:
        """Return owner-cell indices for one outer side of the domain."""
        edge_indices = self.boundary_edge_indices_for_side(
            bc_id,
            tolerance_m=tolerance_m,
        )
        if edge_indices.size == 0:
            return np.asarray([], dtype=int)
        return np.unique(np.asarray(self.edge_cell_a[edge_indices], dtype=int)).astype(
            int, copy=False
        )

    def locate_cell_index_for_point(
        self,
        x_m: float,
        y_m: float,
        *,
        allow_nearest: bool = True,
    ) -> int:
        """Return the cell index that contains one XY point.

        The method first performs an exact point-in-triangle search. If the
        point lies outside the mesh and ``allow_nearest`` is true, it falls back
        to the nearest cell centroid. That fallback is convenient for wells and
        observation points defined in approximate coordinates.
        """
        point_x_m = float(x_m)
        point_y_m = float(y_m)
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
    def from_planar_mesh(
        cls,
        mesh: GmshPlanarMesh2D,
        *,
        domain: object,
        hydraulic_conductivity_m_s,
        storage_coefficient,
        river_trace: object | None = None,
    ) -> BoussinesqMesh:
        """Build the solver mesh view directly from one runtime Gmsh mesh.

        This path keeps the solver in the same architectural shape as the
        MODFLOW adapters: geometry comes from the runtime meshing workflow and
        hydraulic properties come from process-level parameter mapping rather
        than pre-exported CSV tables.
        """
        runtime_bundle = build_runtime_bundle_from_planar_mesh(
            mesh,
            domain=domain,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            storage_coefficient=storage_coefficient,
            river_trace=river_trace,
        )
        base_mesh = cls.from_bundle(runtime_bundle)
        return cls(**build_planar_mesh_kwargs(base_mesh=base_mesh, planar_mesh=mesh))

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
