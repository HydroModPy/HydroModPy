"""Expose one Gmsh planar mesh through the HydroModPy mesh interface.

This module turns raw 2D Gmsh connectivity into a `BaseFieldMesh` object that
the rest of the field/discretization stack can consume without knowing
anything about meshio or `.msh` files.

In practice it validates triangle or quadrilateral cells, provides per-cell
geometry such as centroids and bounds, and offers plotting plus file
round-trips through `gmsh_reader`.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.tri as mtri
import numpy as np

from hydromodpy.field.core.field_mesh import BaseFieldMesh, MeshCell
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
    mesh_data_to_meshio,
    meshio_to_mesh_data,
    normalize_cell_type,
    read_gmsh_2d_mesh,
    write_gmsh_2d_mesh,
)


class GmshPlanarMesh2D(BaseFieldMesh):
    """Planar 2D mesh exposing explicit triangle or quadrilateral cells."""

    _kind = "gmsh_2d"

    def __init__(
        self,
        *,
        points_xy,
        connectivity,
        cell_type: str,
        source_path: str | Path | None = None,
        target_n_cells: int | None = None,
        resolution_hint: int | None = None,
        seed: int | None = None,
    ) -> None:
        points_arr = np.asarray(points_xy, dtype=float)
        if points_arr.ndim != 2 or points_arr.shape[1] != 2:
            raise ValueError("points_xy must have shape (n_nodes, 2)")

        normalized_cell_type = normalize_cell_type(cell_type)
        expected_width = 3 if normalized_cell_type == "triangle" else 4
        connectivity_arr = np.asarray(connectivity, dtype=int)
        if connectivity_arr.ndim != 2 or connectivity_arr.shape[1] != expected_width:
            raise ValueError(
                f"{normalized_cell_type} connectivity must have shape (n_cells, {expected_width})"
            )
        if np.any(connectivity_arr < 0) or np.any(
            connectivity_arr >= points_arr.shape[0]
        ):
            raise ValueError("connectivity references node indices outside points_xy")

        super().__init__(
            x_plot=points_arr[:, 0],
            y_plot=points_arr[:, 1],
            target_n_cells=target_n_cells,
            resolution_hint=resolution_hint,
            seed=seed,
        )
        self.points_xy = points_arr.copy()
        self.connectivity = connectivity_arr.copy()
        self.cell_type = normalized_cell_type
        self.source_path = None if source_path is None else Path(source_path).resolve()
        if self.cell_type == "triangle":
            self.triangulation = mtri.Triangulation(
                self.points_xy[:, 0],
                self.points_xy[:, 1],
                triangles=self.connectivity,
            )

    @classmethod
    def from_mesh_data(cls, mesh_data: GmshMeshData) -> "GmshPlanarMesh2D":
        return cls(
            points_xy=mesh_data.points_xy,
            connectivity=mesh_data.connectivity,
            cell_type=mesh_data.cell_type,
            source_path=mesh_data.source_path,
            target_n_cells=mesh_data.n_cells,
        )

    @classmethod
    def from_meshio(cls, mesh, *, cell_type: str | None = None) -> "GmshPlanarMesh2D":
        return cls.from_mesh_data(meshio_to_mesh_data(mesh, cell_type=cell_type))

    @classmethod
    def from_file(
        cls, path: str | Path, *, cell_type: str | None = None
    ) -> "GmshPlanarMesh2D":
        return cls.from_mesh_data(read_gmsh_2d_mesh(path, cell_type=cell_type))

    @classmethod
    def from_hydro_mesh(cls, hydro_mesh) -> "GmshPlanarMesh2D":
        """Build a ``GmshPlanarMesh2D`` from a 2D ``HydroMesh``."""
        from hydromodpy.mesh.hydro_mesh import HydroMesh

        if not isinstance(hydro_mesh, HydroMesh):
            raise TypeError("Expected a HydroMesh instance")
        if hydro_mesh.ndim != 2:
            raise ValueError("GmshPlanarMesh2D requires a 2D HydroMesh")
        return cls(
            points_xy=hydro_mesh.vertices,
            connectivity=hydro_mesh.flat_connectivity,
            cell_type=hydro_mesh.single_cell_type.value,
        )

    @property
    def n_cells(self) -> int:
        return int(self.connectivity.shape[0])

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        x = np.asarray(self.points_xy[:, 0], dtype=float)
        y = np.asarray(self.points_xy[:, 1], dtype=float)
        return (
            float(np.nanmin(x)),
            float(np.nanmin(y)),
            float(np.nanmax(x)),
            float(np.nanmax(y)),
        )

    def iter_cells(self):
        for idx, nodes in enumerate(np.asarray(self.connectivity, dtype=int)):
            vertices = np.asarray(self.points_xy[nodes], dtype=float)
            centroid = (float(vertices[:, 0].mean()), float(vertices[:, 1].mean()))
            yield MeshCell(
                index=int(idx),
                kind=self.cell_type,
                node_indices=tuple(int(v) for v in nodes),
                vertices=vertices,
                centroid=centroid,
            )

    def cell_centroids(self):
        centroids = np.array([cell.centroid for cell in self.cells], dtype=float)
        return centroids[:, 0], centroids[:, 1]

    def to_cell_values(self, values):
        arr = np.asarray(values)
        flat = arr.reshape(-1)
        if flat.size != self.n_cells:
            raise ValueError("Gmsh cell values must contain exactly one value per cell")
        return flat

    def to_hydro_mesh(self):
        """Convert to a ``HydroMesh`` pivot (optimized: direct array access)."""
        from hydromodpy.mesh.adapters.field_mesh_adapter import from_gmsh_planar

        return from_gmsh_planar(self)

    def plot_cell_values(
        self,
        ax,
        cell_values,
        *,
        cmap="viridis",
        show_mesh=False,
        vmin=None,
        vmax=None,
    ):
        from hydromodpy.mesh.plotting import plot_cell_values as _unified_plot

        values1d = np.asarray(self.to_cell_values(cell_values), dtype=float)
        return _unified_plot(
            ax,
            self.to_hydro_mesh(),
            values1d,
            cmap=cmap,
            show_mesh=show_mesh,
            vmin=vmin,
            vmax=vmax,
        )

    def to_mesh_data(self) -> GmshMeshData:
        return GmshMeshData(
            points_xy=self.points_xy,
            cell_blocks=(
                GmshCellBlock(cell_type=self.cell_type, connectivity=self.connectivity),
            ),
            source_path=self.source_path,
        )

    def to_meshio(self):
        return mesh_data_to_meshio(self.to_mesh_data())

    def to_file(self, path: str | Path, *, file_format: str | None = None) -> Path:
        return write_gmsh_2d_mesh(path, self.to_mesh_data(), file_format=file_format)

    def as_dict(self):
        payload = super().as_dict()
        payload.update(
            {
                "cell_type": self.cell_type,
                "bounds": tuple(float(v) for v in self.bounds),
                "source_path": (
                    None if self.source_path is None else str(self.source_path)
                ),
            }
        )
        return payload
