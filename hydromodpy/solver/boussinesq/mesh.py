"""Solver-owned mesh view of a cell mesh.

The Boussinesq solver needs a compact subset of what a cell mesh and a mesh
bundle describe:

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
    family_edge_indices,
    mesh_arrays_from_cell_mesh,
)
from hydromodpy.spatial.mesh.cells.boundary import SIDE_IDS, label_cells, side_cells
from hydromodpy.spatial.mesh.cells.locate import locate_cells
from hydromodpy.spatial.mesh.io.bundle import (
    CatchmentMeshBundle,
    cell_mesh_from_bundle,
)

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


@dataclass(frozen=True)
class BoussinesqMesh:
    """Compact in-memory mesh view used by the Boussinesq backend.

    Every array is solver-oriented: ids are normalized to positional indices
    whenever useful, distances are precomputed and the geometry is kept
    immutable through the frozen dataclass contract.

    The mesh keeps its cell mesh in ``cell_mesh``, whether it was built from a
    runtime cell mesh or from a mesh bundle (the validation cases). The sides,
    the river and the cell location are read from it. The edge arrays keep the
    order of the source: the edge table of the cell mesh, or the edge file of the
    bundle.
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
    cell_mesh: PlanarCellMesh
    # solver.drain_bed_thickness_m, with the same default. The flow adapter sets it.
    drain_bed_thickness_m: float = 1.0

    def __post_init__(self) -> None:
        bed_thickness = float(self.drain_bed_thickness_m)
        if not np.isfinite(bed_thickness) or bed_thickness <= 0.0:
            raise ValueError(
                f"drain_bed_thickness_m must be finite and positive; got {bed_thickness}."
            )

    @property
    def planar_mesh(self) -> HydroMesh:
        """The planar ``HydroMesh`` of the cell mesh."""
        return self.cell_mesh.mesh

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

    def family_edge_indices(self, family: str) -> np.ndarray:
        """Return the edges of one face family, as indices into the edge arrays of this mesh."""
        node_ids = np.asarray(self.node_ids, dtype=np.int64)
        order = np.argsort(node_ids, kind="stable")

        def position(ids: np.ndarray) -> np.ndarray:
            return order[np.searchsorted(node_ids, ids, sorter=order)]

        edge_nodes = np.column_stack([position(self.edge_node_a), position(self.edge_node_b)])
        return family_edge_indices(self.cell_mesh, family, edge_nodes)

    def boundary_edge_indices_for_side(self, bc_id: str) -> np.ndarray:
        """Return the edges of one outer side: the face family ``boundary:<side>``."""
        if bc_id not in SIDE_IDS:
            raise ValueError(f"Unsupported side boundary id: {bc_id}.")
        return self.family_edge_indices(f"boundary:{bc_id.removesuffix('_side')}")

    def boundary_cell_indices_for_side(self, bc_id: str) -> np.ndarray:
        """Return owner-cell indices for one outer side of the domain."""
        return side_cells(self.cell_mesh, bc_id)

    def edge_indices_for_label(self, label: str) -> np.ndarray:
        """Return the edges of one support label: ``stream``, a side id or ``boundary:<name>``."""
        text = str(label).strip()
        if text in ("stream", "river"):
            return self.river_edge_indices()
        if text in SIDE_IDS:
            return self.boundary_edge_indices_for_side(text)
        if text.startswith("boundary:"):
            return self.family_edge_indices(text)
        return np.empty(0, dtype=np.int64)

    def cell_indices_for_label(self, label: str) -> np.ndarray:
        """Return the cells of one support label, as :meth:`edge_indices_for_label` reads it."""
        return label_cells(self.cell_mesh, label)

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
        cell = int(
            locate_cells(
                self.cell_mesh,
                np.array([[float(x_m), float(y_m)]]),
                allow_nearest=allow_nearest,
            )[0]
        )
        if cell < 0:
            raise ValueError(
                f"Point ({float(x_m)}, {float(y_m)}) is outside the triangular mesh domain."
            )
        return cell

    def river_edge_indices(self) -> np.ndarray:
        """Return all edges tagged as river support."""
        return np.flatnonzero(np.asarray(self.edge_is_river, dtype=bool)).astype(
            int,
            copy=False,
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
        arrays = mesh_arrays_from_cell_mesh(
            cell_mesh,
            domain=domain,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            storage_coefficient=storage_coefficient,
            source_path=source_path,
        )
        return cls(**arrays, cell_mesh=cell_mesh)

    @classmethod
    def from_bundle(cls, bundle: CatchmentMeshBundle) -> BoussinesqMesh:
        """Build the solver mesh view from one catchment mesh bundle.

        This constructor is the main translation layer between the generic
        exchange object and the compact arrays used by the solver. It also
        performs early validation so runtime code can assume the mesh is
        physically coherent. The bundle is read as a cell mesh in its CRS.
        """
        arrays = assemble_mesh_arrays_from_bundle(bundle)
        crs = bundle.metadata_view.crs
        if crs is None:
            raise ValueError(
                f"The mesh bundle {bundle.bundle_dir} declares no 'crs' in its metadata."
            )
        return cls(**arrays, cell_mesh=cell_mesh_from_bundle(bundle, crs_wkt=crs))


__all__ = ["BoussinesqMesh"]
