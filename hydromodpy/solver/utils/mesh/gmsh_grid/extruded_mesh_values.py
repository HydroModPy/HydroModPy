"""3D values attached to one extruded prism mesh for postprocessing/export."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
)


def _require_meshio():
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for 3D value export/readback support. "
            "Install the 'meshio' package to use .vtu export."
        ) from exc
    return meshio


def _array_stats(arr) -> dict[str, float]:
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
    flat_arr = np.asarray(flat_values, dtype=float).reshape(-1)
    if flat_arr.size != mesh_3d.n_prisms:
        raise ValueError("Flat prism values must contain exactly one value per prism")
    values_3d = np.full((mesh_3d.n_layers, mesh_3d.planar_mesh.n_cells), np.nan, dtype=float)
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
        values_3d = np.asarray(self.mesh.to_prism_values(self.values_3d), dtype=float)
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
        flat = np.empty(self.n_cells_3d, dtype=float)
        for prism_idx, (layer_idx, source_idx) in enumerate(
            zip(self.mesh.layer_indices, self.mesh.source_cell_indices, strict=True)
        ):
            flat[prism_idx] = float(self.values_3d[int(layer_idx), int(source_idx)])
        return flat

    @property
    def flat_prism_center_depths(self) -> np.ndarray | None:
        if self.prism_center_depths is None:
            return None
        flat = np.empty(self.n_cells_3d, dtype=float)
        for prism_idx, (layer_idx, source_idx) in enumerate(
            zip(self.mesh.layer_indices, self.mesh.source_cell_indices, strict=True)
        ):
            flat[prism_idx] = float(self.prism_center_depths[int(layer_idx), int(source_idx)])
        return flat

    def extract_layer(self, layer_index: int, *, label: str | None = None):
        layer_idx = int(layer_index)
        if layer_idx < 0 or layer_idx >= self.n_layers:
            raise IndexError(f"layer_index out of range: {layer_idx}")
        layer_label = label if label is not None else (
            None if self.label is None else f"{self.label}_layer_{layer_idx}"
        )
        return self.mesh.planar_mesh.attach_cell_values(
            self.values_3d[layer_idx, :],
            label=layer_label,
        )

    def extract_vertical_profile(self, source_cell_index: int) -> dict[str, Any]:
        source_idx = int(source_cell_index)
        if source_idx < 0 or source_idx >= self.n_cells_2d:
            raise IndexError(f"source_cell_index out of range: {source_idx}")
        values = np.asarray(self.values_3d[:, source_idx], dtype=float)
        profile = {
            "source_cell_index": source_idx,
            "layer_indices": [int(v) for v in range(self.n_layers)],
            "values": [float(v) for v in values],
        }
        if self.prism_center_depths is not None:
            profile["depths"] = [
                float(v) for v in np.asarray(self.prism_center_depths[:, source_idx], dtype=float)
            ]
        return profile

    def global_stats(self) -> dict[str, float]:
        return _array_stats(self.values_3d)

    def layer_stats(self) -> list[dict[str, float]]:
        return [_array_stats(self.values_3d[layer_idx, :]) for layer_idx in range(self.n_layers)]

    def to_summary_dict(self) -> dict[str, Any]:
        summary = {
            "label": None if self.label is None else str(self.label),
            "shape_3d": [int(v) for v in self.values_3d.shape],
            "n_layers": int(self.n_layers),
            "n_cells_2d": int(self.n_cells_2d),
            "n_cells_3d": int(self.n_cells_3d),
            "mesh_kind": str(self.mesh.kind),
            "cell_type_3d": str(self.mesh.cell_type_3d),
            "stats": {
                key: round(float(value), 12)
                for key, value in self.global_stats().items()
            },
            "layer_stats": [
                {key: round(float(value), 12) for key, value in layer_stats.items()}
                for layer_stats in self.layer_stats()
            ],
            "values_signature_head": [
                round(float(v), 12) for v in self.flat_values[:8]
            ],
        }
        if self.prism_center_depths is not None:
            summary["depth_stats"] = {
                key: round(float(value), 12)
                for key, value in _array_stats(self.prism_center_depths).items()
            }
            summary["depth_signature_head"] = [
                round(float(v), 12) for v in self.flat_prism_center_depths[:8]
            ]
        if self.metadata is not None:
            summary["metadata"] = dict(self.metadata)
        return summary

    def to_meshio(
        self,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
    ):
        mesh = self.mesh.to_meshio()
        mesh.cell_data[str(value_name)] = [np.asarray(self.flat_values, dtype=float)]
        if self.prism_center_depths is not None:
            mesh.cell_data[str(depth_name)] = [np.asarray(self.flat_prism_center_depths, dtype=float)]
        return mesh

    def to_file(
        self,
        path: str | Path,
        *,
        value_name: str = "field_param_value",
        depth_name: str = "prism_center_depth",
        file_format: str | None = None,
    ) -> Path:
        meshio = _require_meshio()
        path_obj = Path(path).resolve()
        meshio.write(
            path_obj,
            self.to_meshio(value_name=value_name, depth_name=depth_name),
            file_format=file_format,
        )
        return path_obj

    def to_npy(self, path: str | Path) -> Path:
        path_obj = Path(path).resolve()
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        np.save(path_obj, np.asarray(self.values_3d, dtype=float))
        return path_obj

    def write_summary_json(self, path: str | Path) -> Path:
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
    ) -> "ExtrudedPrismMeshWithValues":
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
    ) -> "ExtrudedPrismMeshWithValues":
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
    return ExtrudedPrismMeshWithValues(
        mesh=mesh_3d,
        values_3d=values_3d,
        label=label,
        prism_center_depths=prism_center_depths,
        metadata=metadata,
    )
