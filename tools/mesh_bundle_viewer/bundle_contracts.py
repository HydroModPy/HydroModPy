"""Shared bundle contracts for the standalone ``mesh`` package.

The visualization tool manipulates two related views of the same bundle:

- concrete dataclasses produced by ``mesh.reader`` when CSV/JSON files are read;
- lightweight protocols consumed by plotting and summary code.

Keeping them together makes the bundle data model easy to discover for a new
reader of the package.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class MeshNodeLike(Protocol):
    """Minimal node contract expected by the visualization stack."""

    node_id: int
    x: float
    y: float
    z_top: float | None
    z_bottom: float | None


class MeshCellLike(Protocol):
    """Minimal cell contract expected by the visualization stack."""

    cell_id: int
    geom_type: str
    node_indices: tuple[int, ...]
    centroid_x: float
    centroid_y: float
    area_m2: float
    z_top_centroid: float | None
    z_top_mean: float | None
    z_bottom_centroid: float | None
    z_bottom_mean: float | None
    geology_code: int | None
    geology_key: str
    hydraulic_conductivity_m_s: float | None
    storage_coefficient: float | None


class MeshEdgeLike(Protocol):
    """Minimal edge contract expected by the visualization stack."""

    edge_id: int
    node_a: int
    node_b: int
    cell_a: int
    cell_b: int | None
    length_m: float
    edge_kind: str
    is_river: bool
    geology_a_key: str
    geology_b_key: str


class GeologyFractionLike(Protocol):
    """Minimal geology-fraction contract expected by the visualization stack."""

    cell_id: int
    geology_key: str
    fraction: float


class MeshBundleLike(Protocol):
    """Minimal bundle contract expected by the visualization stack."""

    bundle_dir: Path
    metadata: dict[str, Any]
    nodes: Sequence[MeshNodeLike]
    cells: Sequence[MeshCellLike]
    edges: Sequence[MeshEdgeLike]
    geology_fractions: Sequence[GeologyFractionLike]
    mesh_summary: dict[str, Any] | None

    @property
    def n_nodes(self) -> int: ...

    @property
    def n_cells(self) -> int: ...

    @property
    def n_edges(self) -> int: ...

    @property
    def mesh_path(self) -> Path: ...


@dataclass(frozen=True)
class CatchmentMeshBundleNode:
    """Concrete node loaded from ``nodes.csv``."""

    node_id: int
    x: float
    y: float
    z_top: float | None
    z_bottom: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleCell:
    """Concrete cell loaded from ``cells.csv``."""

    cell_id: int
    geom_type: str
    node_indices: tuple[int, ...]
    centroid_x: float
    centroid_y: float
    area_m2: float
    z_top_centroid: float | None
    z_top_mean: float | None
    z_bottom_centroid: float | None
    z_bottom_mean: float | None
    geology_code: int | None
    geology_key: str
    hydraulic_conductivity_m_s: float | None
    storage_coefficient: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleEdge:
    """Concrete edge loaded from ``edges.csv``."""

    edge_id: int
    node_a: int
    node_b: int
    cell_a: int
    cell_b: int | None
    length_m: float
    edge_kind: str
    is_river: bool
    geology_a_key: str
    geology_b_key: str


@dataclass(frozen=True)
class CatchmentMeshBundleGeologyFraction:
    """Concrete geology fraction loaded from ``cell_geology_fractions.csv``."""

    cell_id: int
    geology_key: str
    fraction: float


@dataclass(frozen=True)
class CatchmentMeshBundle:
    """Concrete in-memory bundle used by the standalone visualization package."""

    bundle_dir: Path
    metadata: dict[str, Any]
    nodes: tuple[CatchmentMeshBundleNode, ...]
    cells: tuple[CatchmentMeshBundleCell, ...]
    edges: tuple[CatchmentMeshBundleEdge, ...]
    geology_fractions: tuple[CatchmentMeshBundleGeologyFraction, ...]
    mesh_summary: dict[str, Any] | None = None

    @property
    def n_nodes(self) -> int:
        return int(len(self.nodes))

    @property
    def n_cells(self) -> int:
        return int(len(self.cells))

    @property
    def n_edges(self) -> int:
        return int(len(self.edges))

    @property
    def mesh_path(self) -> Path:
        filename = str(self.metadata.get("files", {}).get("mesh", "mesh_2d.msh"))
        return (self.bundle_dir / filename).resolve()


__all__ = [
    "CatchmentMeshBundle",
    "CatchmentMeshBundleCell",
    "CatchmentMeshBundleEdge",
    "CatchmentMeshBundleGeologyFraction",
    "CatchmentMeshBundleNode",
    "GeologyFractionLike",
    "MeshBundleLike",
    "MeshCellLike",
    "MeshEdgeLike",
    "MeshNodeLike",
]
