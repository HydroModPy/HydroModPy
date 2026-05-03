"""Build and persist 3D prism meshes obtained by extruding one 2D Gmsh mesh.

This module takes a validated planar mesh and repeats it along the vertical
axis to create wedge or hexahedron prisms, depending on whether the base mesh
uses triangles or quads.

Implementation is split across:
- ``_prism_data`` - dataclasses and constants,
- ``_prism_extrusion_builder`` - planar -> 3D builder helpers,
- ``_prism_meshio_io`` - meshio interop and disk persistence.

The high-level ``ExtrudedPrismMesh3D`` class composes these helpers and is the
canonical entry point for downstream consumers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid._prism_data import (
    INTERNAL_3D_KIND_BY_2D,
    ExtrudedPrismMeshData,
    PrismCell3D,
    resolve_z_interfaces,
)
from hydromodpy.spatial.mesh.gmsh_grid._prism_extrusion_builder import (
    build_default_components,
    build_planar_mesh_from_data,
)
from hydromodpy.spatial.mesh.gmsh_grid._prism_meshio_io import (
    extruded_mesh_data_to_meshio,
    meshio_to_extruded_mesh_data,
    read_extruded_prism_mesh,
    write_extruded_prism_mesh,
)
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

__all__ = (
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "PrismCell3D",
    "extruded_mesh_data_to_meshio",
    "meshio_to_extruded_mesh_data",
    "read_extruded_prism_mesh",
    "write_extruded_prism_mesh",
)


class ExtrudedPrismMesh3D:
    """3D prism mesh built by vertical extrusion of one planar 2D mesh."""

    _kind = "extruded_prism_3d"

    def __init__(
        self,
        *,
        planar_mesh: GmshPlanarMesh2D,
        z_interfaces,
        points_xyz=None,
        prism_connectivity=None,
        layer_indices=None,
        source_cell_indices=None,
        point_layer_indices=None,
        point_base_indices=None,
        source_path: str | Path | None = None,
    ) -> None:
        if not isinstance(planar_mesh, GmshPlanarMesh2D):
            raise TypeError("planar_mesh must be a GmshPlanarMesh2D instance")
        z_arr = resolve_z_interfaces(z_interfaces=z_interfaces, top_z=None, layer_thicknesses=None)

        if points_xyz is None:
            (
                points_xyz,
                prism_connectivity,
                layer_indices,
                source_cell_indices,
                point_layer_indices,
                point_base_indices,
            ) = build_default_components(planar_mesh, z_arr)
        elif any(
            v is None
            for v in (
                prism_connectivity,
                layer_indices,
                source_cell_indices,
                point_layer_indices,
                point_base_indices,
            )
        ):
            raise ValueError("Explicit 3D components must be passed together")

        mesh_data = ExtrudedPrismMeshData(
            points_xyz=np.asarray(points_xyz, dtype=float),
            prism_connectivity=np.asarray(prism_connectivity, dtype=int),
            cell_type_2d=planar_mesh.cell_type,
            z_interfaces=z_arr,
            layer_indices=np.asarray(layer_indices, dtype=int),
            source_cell_indices=np.asarray(source_cell_indices, dtype=int),
            point_layer_indices=np.asarray(point_layer_indices, dtype=int),
            point_base_indices=np.asarray(point_base_indices, dtype=int),
            source_path=None if source_path is None else Path(source_path),
        )
        self.planar_mesh = planar_mesh
        self.z_interfaces = np.asarray(mesh_data.z_interfaces, dtype=float)
        self.points_xyz = np.asarray(mesh_data.points_xyz, dtype=float)
        self.prism_connectivity = np.asarray(mesh_data.prism_connectivity, dtype=int)
        self.layer_indices = np.asarray(mesh_data.layer_indices, dtype=int)
        self.source_cell_indices = np.asarray(mesh_data.source_cell_indices, dtype=int)
        self.point_layer_indices = np.asarray(mesh_data.point_layer_indices, dtype=int)
        self.point_base_indices = np.asarray(mesh_data.point_base_indices, dtype=int)
        self.source_path = (
            None if mesh_data.source_path is None else Path(mesh_data.source_path).resolve()
        )
        self._prisms_cache: tuple[PrismCell3D, ...] | None = None

    @classmethod
    def from_planar_mesh(
        cls,
        planar_mesh: GmshPlanarMesh2D,
        *,
        z_interfaces,
    ) -> ExtrudedPrismMesh3D:
        """Build one extrusion directly from explicit vertical interfaces."""
        return cls(planar_mesh=planar_mesh, z_interfaces=z_interfaces)

    @classmethod
    def from_layer_thicknesses(
        cls,
        planar_mesh: GmshPlanarMesh2D,
        *,
        top_z: float,
        layer_thicknesses,
    ) -> ExtrudedPrismMesh3D:
        """Build one extrusion from a top elevation and layer thicknesses."""
        z_interfaces = resolve_z_interfaces(
            z_interfaces=None,
            top_z=top_z,
            layer_thicknesses=layer_thicknesses,
        )
        return cls(planar_mesh=planar_mesh, z_interfaces=z_interfaces)

    @classmethod
    def from_mesh_data(cls, mesh_data: ExtrudedPrismMeshData) -> ExtrudedPrismMesh3D:
        """Rebuild the high-level mesh object from the raw payload form."""
        planar_mesh = build_planar_mesh_from_data(mesh_data)
        return cls(
            planar_mesh=planar_mesh,
            z_interfaces=mesh_data.z_interfaces,
            points_xyz=mesh_data.points_xyz,
            prism_connectivity=mesh_data.prism_connectivity,
            layer_indices=mesh_data.layer_indices,
            source_cell_indices=mesh_data.source_cell_indices,
            point_layer_indices=mesh_data.point_layer_indices,
            point_base_indices=mesh_data.point_base_indices,
            source_path=mesh_data.source_path,
        )

    @classmethod
    def from_meshio(cls, mesh) -> ExtrudedPrismMesh3D:
        """Build one extrusion from a meshio mesh object."""
        return cls.from_mesh_data(meshio_to_extruded_mesh_data(mesh))

    @classmethod
    def from_file(cls, path: str | Path) -> ExtrudedPrismMesh3D:
        """Read one persisted extrusion from disk."""
        return cls.from_mesh_data(read_extruded_prism_mesh(path))

    @property
    def kind(self) -> str:
        """Return the stable HydroModPy mesh kind identifier."""
        return self._kind

    @property
    def cell_type_2d(self) -> str:
        """Return the base 2D cell type (`triangle` or `quadrilateral`)."""
        return str(self.planar_mesh.cell_type)

    @property
    def cell_type_3d(self) -> str:
        """Return the logical 3D prism type derived from the base 2D mesh."""
        return INTERNAL_3D_KIND_BY_2D[self.cell_type_2d]

    @property
    def n_layers(self) -> int:
        """Return the number of vertical prism layers."""
        return int(self.z_interfaces.size - 1)

    @property
    def n_nodes(self) -> int:
        """Return the total number of 3D nodes."""
        return int(self.points_xyz.shape[0])

    @property
    def n_prisms(self) -> int:
        """Return the total number of 3D prism cells."""
        return int(self.prism_connectivity.shape[0])

    @property
    def n_cells(self) -> int:
        """Alias for `n_prisms` to match broader mesh APIs."""
        return self.n_prisms

    @property
    def shape(self) -> tuple[int, int]:
        """Return the logical `(n_layers, n_cells_2d)` grid shape."""
        return (int(self.n_layers), int(self.planar_mesh.n_cells))

    @property
    def bounds(self) -> tuple[float, float, float, float, float, float]:
        """Return the full 3D bounding box `(xmin, ymin, zmin, xmax, ymax, zmax)`."""
        x = np.asarray(self.points_xyz[:, 0], dtype=float)
        y = np.asarray(self.points_xyz[:, 1], dtype=float)
        z = np.asarray(self.points_xyz[:, 2], dtype=float)
        return (
            float(np.nanmin(x)),
            float(np.nanmin(y)),
            float(np.nanmin(z)),
            float(np.nanmax(x)),
            float(np.nanmax(y)),
            float(np.nanmax(z)),
        )

    @property
    def layer_centers_z(self) -> np.ndarray:
        """Return one representative Z coordinate per vertical layer."""
        return 0.5 * (self.z_interfaces[:-1] + self.z_interfaces[1:])

    @property
    def prisms(self) -> tuple[PrismCell3D, ...]:
        """Return cached explicit prism objects for inspection-oriented workflows."""
        if self._prisms_cache is None:
            self._prisms_cache = tuple(self.iter_prisms())
        return self._prisms_cache

    def iter_prisms(self):
        """Yield prisms in the stored 3D ordering."""
        for prism_idx, node_ids in enumerate(np.asarray(self.prism_connectivity, dtype=int)):
            vertices = np.asarray(self.points_xyz[node_ids], dtype=float)
            centroid = (
                float(np.mean(vertices[:, 0])),
                float(np.mean(vertices[:, 1])),
                float(np.mean(vertices[:, 2])),
            )
            yield PrismCell3D(
                index=int(prism_idx),
                kind=self.cell_type_3d,
                node_indices=tuple(int(v) for v in node_ids),
                vertices=vertices,
                centroid=centroid,
                layer_index=int(self.layer_indices[prism_idx]),
                source_cell_index=int(self.source_cell_indices[prism_idx]),
            )

    def prism_centroids(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return prism centroid coordinates split as `(x, y, z)` arrays."""
        centroids = np.array([cell.centroid for cell in self.prisms], dtype=float)
        return centroids[:, 0], centroids[:, 1], centroids[:, 2]

    def to_prism_values(self, values):
        """Normalize prism values to the canonical `(n_layers, n_cells_2d)` shape."""
        arr = np.asarray(values)
        expected_shape = (self.n_layers, self.planar_mesh.n_cells)
        if arr.ndim == 2:
            if arr.shape != expected_shape:
                raise ValueError("3D prism values must match shape (n_layers, n_cells_2d)")
            return arr
        flat = arr.reshape(-1)
        if flat.size != self.n_prisms:
            raise ValueError("3D prism values must contain exactly one value per prism")
        return flat.reshape(expected_shape)

    def to_hydro_mesh(self):
        """Convert to a ``HydroMesh`` pivot (3D, with layer/source metadata)."""
        from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_extruded_prism

        return from_extruded_prism(self)

    def to_mesh_data(self) -> ExtrudedPrismMeshData:
        """Return the serialization-oriented raw payload."""
        return ExtrudedPrismMeshData(
            points_xyz=self.points_xyz,
            prism_connectivity=self.prism_connectivity,
            cell_type_2d=self.cell_type_2d,
            z_interfaces=self.z_interfaces,
            layer_indices=self.layer_indices,
            source_cell_indices=self.source_cell_indices,
            point_layer_indices=self.point_layer_indices,
            point_base_indices=self.point_base_indices,
            source_path=self.source_path,
        )

    def to_meshio(self):
        """Convert the extrusion to one meshio mesh."""
        return extruded_mesh_data_to_meshio(self.to_mesh_data())

    def to_file(self, path: str | Path, *, file_format: str | None = None) -> Path:
        """Persist the extrusion to disk."""
        return write_extruded_prism_mesh(path, self.to_mesh_data(), file_format=file_format)

    def as_dict(self):
        """Return a compact JSON-friendly summary of the extrusion."""
        return {
            "kind": self.kind,
            "cell_type_2d": self.cell_type_2d,
            "cell_type_3d": self.cell_type_3d,
            "n_layers": int(self.n_layers),
            "n_nodes_2d": int(self.planar_mesh.n_nodes),
            "n_cells_2d": int(self.planar_mesh.n_cells),
            "n_nodes_3d": int(self.n_nodes),
            "n_cells_3d": int(self.n_prisms),
            "shape": tuple(int(v) for v in self.shape),
            "bounds": tuple(float(v) for v in self.bounds),
            "z_interfaces": [float(v) for v in self.z_interfaces],
            "source_path": None if self.source_path is None else str(self.source_path),
        }
