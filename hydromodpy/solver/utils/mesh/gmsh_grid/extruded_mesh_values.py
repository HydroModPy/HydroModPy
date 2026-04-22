"""Attach scalar values to an extruded prism mesh and export the result.

The mesh geometry lives in `extruded_prism_mesh`; this module adds the data
layer on top of it. It stores one scalar per prism, reshapes values between a
flat 3D ordering and a `(n_layers, n_cells_2d)` view, and computes compact
summaries for diagnostics.

It is the module to use once a 3D mesh already exists and the remaining task
is inspection, postprocessing, or export to formats such as `.npy` or `.vtu`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid._deps import require_meshio as _require_meshio
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
)


def _array_stats(arr) -> dict[str, float]:
    """Return simple finite-value statistics for one numeric array."""
    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("Cannot compute stats on an array without finite values")
    return {
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "sum": float(np.sum(finite)),
    }


def _reshape_flat_values(mesh_3d: ExtrudedPrismMesh3D, flat_values) -> np.ndarray:
    """Map flat prism ordering back to the logical `(layer, source_cell)` grid."""
    flat_arr = np.asarray(flat_values, dtype=float).reshape(-1)
    if flat_arr.size != mesh_3d.n_prisms:
        raise ValueError("Flat prism values must contain exactly one value per prism")
    # The flat 3D ordering follows prism storage order, not layer-major order.
    # Reindex once here so every downstream tool sees the same 2D-by-layer view.
    values_3d: np.ndarray[Any, Any] = np.full(
        (mesh_3d.n_layers, mesh_3d.planar_mesh.n_cells), np.nan, dtype=float
    )
    for prism_idx, (layer_idx, source_idx) in enumerate(
        zip(mesh_3d.layer_indices, mesh_3d.source_cell_indices, strict=True)
    ):
        values_3d[int(layer_idx), int(source_idx)] = float(flat_arr[prism_idx])
    if np.any(~np.isfinite(values_3d)):
        raise ValueError(
            "Flat prism values do not cover exactly one value per (layer, source_cell_2d) slot"
        )
    return values_3d


@dataclass(frozen=True)
class ExtrudedVerticalProfile:
    """Typed vertical profile extracted from one planar source cell."""

    source_cell_index: int
    layer_indices: tuple[int, ...]
    values: tuple[float, ...]
    depths: tuple[float, ...] | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_cell_index": int(self.source_cell_index),
            "layer_indices": [int(v) for v in self.layer_indices],
            "values": [float(v) for v in self.values],
        }
        if self.depths is not None:
            payload["depths"] = [float(v) for v in self.depths]
        return payload


@dataclass(frozen=True)
class ExtrudedMeshValuesSummary:
    """Typed summary of one valued extruded prism mesh."""

    label: str | None
    shape_3d: tuple[int, int]
    n_layers: int
    n_cells_2d: int
    n_cells_3d: int
    mesh_kind: str
    cell_type_3d: str
    stats: dict[str, float]
    layer_stats: tuple[dict[str, float], ...]
    values_signature_head: tuple[float, ...]
    depth_stats: dict[str, float] | None = None
    depth_signature_head: tuple[float, ...] | None = None
    metadata: dict[str, Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": None if self.label is None else str(self.label),
            "shape_3d": [int(v) for v in self.shape_3d],
            "n_layers": int(self.n_layers),
            "n_cells_2d": int(self.n_cells_2d),
            "n_cells_3d": int(self.n_cells_3d),
            "mesh_kind": str(self.mesh_kind),
            "cell_type_3d": str(self.cell_type_3d),
            "stats": {key: round(float(value), 12) for key, value in self.stats.items()},
            "layer_stats": [
                {key: round(float(value), 12) for key, value in layer_stats.items()}
                for layer_stats in self.layer_stats
            ],
            "values_signature_head": [round(float(v), 12) for v in self.values_signature_head],
        }
        if self.depth_stats is not None:
            payload["depth_stats"] = {
                key: round(float(value), 12) for key, value in self.depth_stats.items()
            }
        if self.depth_signature_head is not None:
            payload["depth_signature_head"] = [
                round(float(v), 12) for v in self.depth_signature_head
            ]
        if self.metadata is not None:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ExtrudedPrismMeshWithValues:
    """One extruded prism mesh carrying one scalar value per prism."""

    mesh: ExtrudedPrismMesh3D
    values_3d: np.ndarray
    label: str | None = None
    prism_center_depths: np.ndarray | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mesh, ExtrudedPrismMesh3D):
            raise TypeError("mesh must be an ExtrudedPrismMesh3D instance")
        values_3d: np.ndarray[Any, Any] = np.asarray(
            self.mesh.to_prism_values(self.values_3d), dtype=float
        )
        prism_center_depths = None
        if self.prism_center_depths is not None:
            prism_center_depths = np.asarray(
                self.mesh.to_prism_values(self.prism_center_depths),
                dtype=float,
            )
        metadata = None if self.metadata is None else dict(self.metadata)

        object.__setattr__(self, "values_3d", values_3d.copy())
        object.__setattr__(
            self,
            "prism_center_depths",
            None if prism_center_depths is None else prism_center_depths.copy(),
        )
        object.__setattr__(self, "metadata", metadata)

    @property
    def n_layers(self) -> int:
        return int(self.mesh.n_layers)

    @property
    def n_cells_2d(self) -> int:
        return int(self.mesh.planar_mesh.n_cells)

    @property
    def n_cells_3d(self) -> int:
        return int(self.mesh.n_prisms)

    @property
    def flat_values(self) -> np.ndarray:
        """Return one value per prism in the stored 3D prism ordering."""
        flat: np.ndarray[Any, Any] = np.empty(self.n_cells_3d, dtype=float)
        for prism_idx, (layer_idx, source_idx) in enumerate(
            zip(self.mesh.layer_indices, self.mesh.source_cell_indices, strict=True)
        ):
            flat[prism_idx] = float(self.values_3d[int(layer_idx), int(source_idx)])
        return flat

    @property
    def flat_prism_center_depths(self) -> np.ndarray | None:
        """Return prism-center depths in the stored 3D prism ordering."""
        if self.prism_center_depths is None:
            return None
        flat: np.ndarray[Any, Any] = np.empty(self.n_cells_3d, dtype=float)
        for prism_idx, (layer_idx, source_idx) in enumerate(
            zip(self.mesh.layer_indices, self.mesh.source_cell_indices, strict=True)
        ):
            flat[prism_idx] = float(self.prism_center_depths[int(layer_idx), int(source_idx)])
        return flat

    def extract_layer(self, layer_index: int, *, label: str | None = None):
        """Return one planar mesh-values object for a selected layer."""
        layer_idx = int(layer_index)
        if layer_idx < 0 or layer_idx >= self.n_layers:
            raise IndexError(f"layer_index out of range: {layer_idx}")
        layer_label = (
            label
            if label is not None
            else (None if self.label is None else f"{self.label}_layer_{layer_idx}")
        )
        return self.mesh.planar_mesh.attach_cell_values(
            self.values_3d[layer_idx, :],
            label=layer_label,
        )

    def build_vertical_profile(self, source_cell_index: int) -> ExtrudedVerticalProfile:
        """Return one typed layer-by-layer value profile for a planar source cell."""
        source_idx = int(source_cell_index)
        if source_idx < 0 or source_idx >= self.n_cells_2d:
            raise IndexError(f"source_cell_index out of range: {source_idx}")
        values = np.asarray(self.values_3d[:, source_idx], dtype=float)
        depths = None
        if self.prism_center_depths is not None:
            depths = tuple(
                float(v) for v in np.asarray(self.prism_center_depths[:, source_idx], dtype=float)
            )
        return ExtrudedVerticalProfile(
            source_cell_index=source_idx,
            layer_indices=tuple(int(v) for v in range(self.n_layers)),
            values=tuple(float(v) for v in values),
            depths=depths,
        )

    def extract_vertical_profile(self, source_cell_index: int) -> dict[str, Any]:
        """Return one layer-by-layer value profile for a planar source cell."""

        return self.build_vertical_profile(source_cell_index).to_mapping()

    def global_stats(self) -> dict[str, float]:
        """Return simple statistics on the full 3D value array."""
        return _array_stats(self.values_3d)

    def layer_stats(self) -> list[dict[str, float]]:
        """Return one statistics payload per vertical layer."""
        return [_array_stats(self.values_3d[layer_idx, :]) for layer_idx in range(self.n_layers)]

    def build_summary_contract(self) -> ExtrudedMeshValuesSummary:
        """Return the typed summary contract of the valued mesh."""

        summary = ExtrudedMeshValuesSummary(
            label=self.label,
            shape_3d=tuple(int(v) for v in self.values_3d.shape),
            n_layers=int(self.n_layers),
            n_cells_2d=int(self.n_cells_2d),
            n_cells_3d=int(self.n_cells_3d),
            mesh_kind=str(self.mesh.kind),
            cell_type_3d=str(self.mesh.cell_type_3d),
            stats=dict(self.global_stats()),
            layer_stats=tuple(dict(layer_stats) for layer_stats in self.layer_stats()),
            values_signature_head=tuple(float(v) for v in self.flat_values[:8]),
            metadata=None if self.metadata is None else dict(self.metadata),
        )
        if self.prism_center_depths is not None:
            flat_depths = self.flat_prism_center_depths
            if flat_depths is None:
                raise ValueError(
                    "flat_prism_center_depths should be available when prism_center_depths is set"
                )
            summary = ExtrudedMeshValuesSummary(
                label=summary.label,
                shape_3d=summary.shape_3d,
                n_layers=summary.n_layers,
                n_cells_2d=summary.n_cells_2d,
                n_cells_3d=summary.n_cells_3d,
                mesh_kind=summary.mesh_kind,
                cell_type_3d=summary.cell_type_3d,
                stats=summary.stats,
                layer_stats=summary.layer_stats,
                values_signature_head=summary.values_signature_head,
                depth_stats=dict(_array_stats(self.prism_center_depths)),
                depth_signature_head=tuple(float(v) for v in flat_depths[:8]),
                metadata=summary.metadata,
            )
        return summary

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a compact, JSON-friendly summary of the valued mesh."""

        return self.build_summary_contract().to_mapping()

    def to_meshio(
        self,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
    ):
        """Convert the valued mesh to a meshio object with scalar cell-data arrays."""
        mesh = self.mesh.to_meshio()
        mesh.cell_data[str(value_name)] = [np.asarray(self.flat_values, dtype=float)]
        if self.prism_center_depths is not None:
            mesh.cell_data[str(depth_name)] = [
                np.asarray(self.flat_prism_center_depths, dtype=float)
            ]
        return mesh

    def to_file(
        self,
        path: str | Path,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
        file_format: str | None = None,
    ) -> Path:
        """Persist the valued mesh to a meshio-supported file format."""
        meshio = _require_meshio()
        path_obj = Path(path).resolve()
        meshio.write(
            path_obj,
            self.to_meshio(value_name=value_name, depth_name=depth_name),
            file_format=file_format,
        )
        return path_obj

    def to_npy(self, path: str | Path) -> Path:
        """Persist only the canonical `(n_layers, n_cells_2d)` value array."""
        path_obj = Path(path).resolve()
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        np.save(path_obj, np.asarray(self.values_3d, dtype=float))
        return path_obj

    def write_summary_json(self, path: str | Path) -> Path:
        """Write `to_summary_dict()` to one JSON sidecar."""
        path_obj = Path(path).resolve()
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(
            json.dumps(self.to_summary_dict(), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path_obj

    @classmethod
    def from_meshio(
        cls,
        mesh,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
        label: str | None = None,
    ) -> ExtrudedPrismMeshWithValues:
        """Build the valued mesh from a meshio object carrying cell-data arrays."""
        mesh_3d = ExtrudedPrismMesh3D.from_meshio(mesh)
        cell_data = getattr(mesh, "cell_data", {})
        value_blocks = cell_data.get(str(value_name))
        if not value_blocks:
            raise KeyError(f"Mesh cell_data is missing '{value_name}'")
        values_3d = _reshape_flat_values(mesh_3d, value_blocks[0])

        depth_3d = None
        depth_blocks = cell_data.get(str(depth_name))
        if depth_blocks:
            depth_3d = _reshape_flat_values(mesh_3d, depth_blocks[0])

        return cls(
            mesh=mesh_3d,
            values_3d=values_3d,
            label=label if label is not None else str(value_name),
            prism_center_depths=depth_3d,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
        label: str | None = None,
    ) -> ExtrudedPrismMeshWithValues:
        """Read a valued prism mesh from disk."""
        meshio = _require_meshio()
        path_obj = Path(path).resolve()
        mesh = meshio.read(path_obj)
        mesh.path = path_obj
        return cls.from_meshio(
            mesh,
            value_name=value_name,
            depth_name=depth_name,
            label=label,
        )


def attach_extruded_values(
    mesh_3d: ExtrudedPrismMesh3D,
    values_3d,
    *,
    label: str | None = None,
    prism_center_depths=None,
    metadata: Mapping[str, Any] | None = None,
) -> ExtrudedPrismMeshWithValues:
    """Convenience wrapper returning a valued extrusion from mesh plus values."""
    return ExtrudedPrismMeshWithValues(
        mesh=mesh_3d,
        values_3d=values_3d,
        label=label,
        prism_center_depths=prism_center_depths,
        metadata=metadata,
    )


__all__ = [
    "ExtrudedMeshValuesSummary",
    "ExtrudedPrismMeshWithValues",
    "ExtrudedVerticalProfile",
    "attach_extruded_values",
]
