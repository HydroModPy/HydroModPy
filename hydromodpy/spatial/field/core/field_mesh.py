"""
Abstract mesh contracts for field modules.

This module intentionally contains only gabarits (abstract templates):
1) `BaseFieldMesh` for mesh behavior,
2) `FieldMesh` for mesh-factory interface.

Concrete square-domain implementations are provided in
`hydromodpy.spatial.field.cases.square.field_mesh_square`.
"""

from __future__ import annotations

import tomllib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.rng import RngManager


@dataclass(frozen=True)
class MeshCell:
    """
    One mesh cell in geometric form.
    """

    index: int
    kind: str
    node_indices: tuple[int, ...]
    vertices: np.ndarray
    centroid: tuple[float, float]


@dataclass(frozen=True)
class MeshWithValues:
    """
    A mesh carrying one value per cell.
    """

    mesh: BaseFieldMesh
    cell_values: np.ndarray
    label: str | None = None

    @property
    def kind(self):
        return self.mesh.kind

    @property
    def n_cells(self):
        return self.mesh.n_cells


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve a nested TOML section from a dotted path."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


class BaseFieldMesh(ABC):
    """
    Abstract interface shared by all mesh types.
    """

    _kind = "base"

    def __init__(
        self,
        *,
        x_plot,
        y_plot,
        target_n_cells: int | None = None,
        resolution_hint: int | None = None,
        seed: int | None = None,
    ):
        x_arr = np.asarray(x_plot, dtype=float)
        y_arr = np.asarray(y_plot, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x_plot and y_plot must have the same shape")
        self.x_plot = x_arr
        self.y_plot = y_arr
        self.triangulation = None
        self.target_n_cells = int(target_n_cells) if target_n_cells is not None else None
        self.resolution_hint = int(resolution_hint) if resolution_hint is not None else None
        self.seed = int(seed) if seed is not None else None
        self._cells_cache: tuple[MeshCell, ...] | None = None

    @property
    def kind(self):
        return self._kind

    @property
    def shape(self):
        return self.x_plot.shape

    @property
    def n_nodes(self) -> int:
        return int(self.x_plot.size)

    def to_grid(self, values):
        """
        Convert node values to array shaped like x_plot/y_plot.
        """
        arr = np.asarray(values)
        if arr.ndim == 2:
            if arr.shape != self.shape:
                raise ValueError("2D values must match mesh shape")
            return arr
        if arr.ndim == 1:
            if arr.size != self.n_nodes:
                raise ValueError("1D values must contain one value per node")
            return arr.reshape(self.shape)
        raise ValueError("values must be 1D or 2D")

    @property
    @abstractmethod
    def n_cells(self) -> int:
        """
        Number of mesh cells.
        """

    @property
    def cells(self) -> tuple[MeshCell, ...]:
        if self._cells_cache is None:
            self._cells_cache = tuple(self.iter_cells())
        return self._cells_cache

    @abstractmethod
    def iter_cells(self):
        """
        Iterate over explicit mesh cells.
        """

    @abstractmethod
    def cell_centroids(self):
        """
        Return centroid coordinates of all mesh cells.
        """

    @abstractmethod
    def to_cell_values(self, values):
        """
        Normalize raw input as one value per mesh cell.
        """

    @abstractmethod
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
        """
        Plot one scalar value per cell.
        """

    def attach_cell_values(self, values, *, label: str | None = None):
        normalized = self.to_cell_values(values)
        return MeshWithValues(
            mesh=self,
            cell_values=np.asarray(normalized),
            label=label,
        )

    def to_hydro_mesh(self):
        """Convert this mesh to a ``HydroMesh`` pivot object.

        Subclasses with direct array access (e.g. ``GmshPlanarMesh2D``)
        override this for efficiency.  The base implementation falls back
        to ``hydromodpy.spatial.mesh.adapters.from_field_mesh()``.
        """
        from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_field_mesh

        return from_field_mesh(self)

    def as_dict(self):
        return {
            "kind": self.kind,
            "shape": tuple(int(v) for v in self.shape),
            "n_nodes": int(self.n_nodes),
            "n_cells": int(self.n_cells),
            "target_n_cells": (
                int(self.target_n_cells) if self.target_n_cells is not None else None
            ),
            "resolution_hint": (
                int(self.resolution_hint) if self.resolution_hint is not None else None
            ),
            "seed": int(self.seed) if self.seed is not None else None,
        }


class FieldMesh(ABC):
    """
    Abstract mesh-factory interface.

    Concrete factories (for example `FieldMeshSquare`) implement the actual
    mesh-generation strategies.
    """

    @classmethod
    @abstractmethod
    def from_unit_square(
        cls,
        *,
        target_n_cells: int,
        mesh_kind: str = "structured",
        rng_manager: RngManager | None = None,
    ) -> BaseFieldMesh:
        """Build a mesh instance from unit-square settings.

        ``rng_manager`` drives stochastic mesh kinds (e.g.
        ``triangular_unstructured``). When omitted, a fixed default seed is
        used for compatibility with non-stochastic mesh kinds and
        deterministic test fixtures.
        """

    @classmethod
    @abstractmethod
    def from_dict(cls, config: Mapping[str, Any]) -> BaseFieldMesh:
        """Build a mesh instance from a plain mapping."""

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "mesh") -> BaseFieldMesh:
        """Build a mesh instance from TOML by delegating to `from_dict`."""
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        section_cfg = _get_nested_section(payload, section)
        return cls.from_dict(section_cfg)
