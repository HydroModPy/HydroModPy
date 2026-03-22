"""Read self-contained catchment mesh exchange bundles.

This module is intentionally lightweight so it can be copied next to one
exported bundle and used outside the full HydroModPy codebase. It depends only
on the Python standard library.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _parse_optional_float(raw_value: str) -> float | None:
    """Parse one CSV field where the empty string means "missing"."""
    text = str(raw_value).strip()
    if text == "":
        return None
    return float(text)


def _parse_optional_int(raw_value: str) -> int | None:
    """Parse one integer CSV field where the empty string means "missing"."""
    text = str(raw_value).strip()
    if text == "":
        return None
    return int(text)


def _parse_bool(raw_value: str) -> bool:
    """Parse permissive CSV booleans used by the bundle export."""
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CatchmentMeshBundleNode:
    """One exported mesh node with optional top and bottom elevations."""

    node_id: int
    x: float
    y: float
    z_top: float | None
    z_bottom: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleCell:
    """One exported 2D cell with geometry, geology and hydraulic summaries."""

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
    """One exported mesh edge with adjacency and river/interface flags."""

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
    """One non-zero geology fraction attached to one exported cell."""

    cell_id: int
    geology_key: str
    fraction: float


@dataclass(frozen=True)
class CatchmentMeshBundle:
    """In-memory view of one self-contained bundle directory.

    The object deliberately stays simple: it mirrors the exported CSV/JSON
    files so downstream scripts can inspect the bundle without importing the
    full HydroModPy mesh stack.
    """

    bundle_dir: Path
    metadata: dict[str, Any]
    nodes: tuple[CatchmentMeshBundleNode, ...]
    cells: tuple[CatchmentMeshBundleCell, ...]
    edges: tuple[CatchmentMeshBundleEdge, ...]
    geology_fractions: tuple[CatchmentMeshBundleGeologyFraction, ...]
    mesh_summary: dict[str, Any] | None = None

    @property
    def n_nodes(self) -> int:
        """Return the number of exported mesh nodes."""
        return int(len(self.nodes))

    @property
    def n_cells(self) -> int:
        """Return the number of exported 2D cells."""
        return int(len(self.cells))

    @property
    def n_edges(self) -> int:
        """Return the number of exported unique edges."""
        return int(len(self.edges))

    @property
    def mesh_path(self) -> Path:
        """Return the path of the copied `.msh` file inside the bundle."""
        filename = str(self.metadata.get("files", {}).get("mesh", "mesh_2d.msh"))
        return (self.bundle_dir / filename).resolve()

    def node_coordinates(self) -> list[tuple[float, float]]:
        """Return planar node coordinates in bundle node order."""
        return [(float(node.x), float(node.y)) for node in self.nodes]

    def cell_connectivity(self) -> list[tuple[int, ...]]:
        """Return 2D cell connectivity using the exported zero-based node ids."""
        return [tuple(int(node_idx) for node_idx in cell.node_indices) for cell in self.cells]

    def cell_by_id(self, cell_id: int) -> CatchmentMeshBundleCell:
        """Return one cell by its exported `cell_id`."""
        target = int(cell_id)
        for cell in self.cells:
            if int(cell.cell_id) == target:
                return cell
        raise KeyError(f"Unknown cell_id={target}")


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one bundle CSV file as a list of raw string dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return [dict(row) for row in reader]


def _load_nodes(path: Path) -> tuple[CatchmentMeshBundleNode, ...]:
    """Load the `nodes.csv` table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleNode(
            node_id=int(row["node_id"]),
            x=float(row["x"]),
            y=float(row["y"]),
            z_top=_parse_optional_float(row.get("z_top", "")),
            z_bottom=_parse_optional_float(row.get("z_bottom", "")),
        )
        for row in rows
    )


def _load_cells(path: Path) -> tuple[CatchmentMeshBundleCell, ...]:
    """Load the `cells.csv` table."""
    rows = _load_csv_rows(path)
    out: list[CatchmentMeshBundleCell] = []
    for row in rows:
        node_indices = tuple(
            int(row[column_name])
            for column_name in ("n0", "n1", "n2", "n3")
            if str(row.get(column_name, "")).strip() != ""
        )
        out.append(
            CatchmentMeshBundleCell(
                cell_id=int(row["cell_id"]),
                geom_type=str(row["geom_type"]),
                node_indices=node_indices,
                centroid_x=float(row["centroid_x"]),
                centroid_y=float(row["centroid_y"]),
                area_m2=float(row["area_m2"]),
                z_top_centroid=_parse_optional_float(row.get("z_top_centroid", "")),
                z_top_mean=_parse_optional_float(row.get("z_top_mean", "")),
                z_bottom_centroid=_parse_optional_float(
                    row.get("z_bottom_centroid", "")
                ),
                z_bottom_mean=_parse_optional_float(row.get("z_bottom_mean", "")),
                geology_code=_parse_optional_int(row.get("geology_code", "")),
                geology_key=str(row.get("geology_key", "")),
                hydraulic_conductivity_m_s=_parse_optional_float(
                    row.get("hydraulic_conductivity_m_s", "")
                ),
                storage_coefficient=_parse_optional_float(
                    row.get("storage_coefficient", "")
                ),
            )
        )
    return tuple(out)


def _load_edges(path: Path) -> tuple[CatchmentMeshBundleEdge, ...]:
    """Load the `edges.csv` table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleEdge(
            edge_id=int(row["edge_id"]),
            node_a=int(row["node_a"]),
            node_b=int(row["node_b"]),
            cell_a=int(row["cell_a"]),
            cell_b=_parse_optional_int(row.get("cell_b", "")),
            length_m=float(row["length_m"]),
            edge_kind=str(row["edge_kind"]),
            is_river=_parse_bool(row.get("is_river", "")),
            geology_a_key=str(row.get("geology_a_key", "")),
            geology_b_key=str(row.get("geology_b_key", "")),
        )
        for row in rows
    )


def _load_geology_fractions(path: Path) -> tuple[CatchmentMeshBundleGeologyFraction, ...]:
    """Load the optional per-cell geology fractions table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleGeologyFraction(
            cell_id=int(row["cell_id"]),
            geology_key=str(row["geology_key"]),
            fraction=float(row["fraction"]),
        )
        for row in rows
    )


def load_catchment_mesh_bundle(bundle_dir: str | Path) -> CatchmentMeshBundle:
    """Load one previously exported catchment mesh bundle.

    The loader is intentionally conservative: missing metadata is an error,
    while optional CSV companions simply become empty tuples.
    """
    bundle_path = Path(bundle_dir).resolve()
    metadata_path = bundle_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Bundle metadata not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    summary_path = bundle_path / "mesh_summary.json"
    mesh_summary = None
    if summary_path.exists():
        mesh_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    return CatchmentMeshBundle(
        bundle_dir=bundle_path,
        metadata=dict(metadata),
        nodes=_load_nodes(bundle_path / "nodes.csv"),
        cells=_load_cells(bundle_path / "cells.csv"),
        edges=_load_edges(bundle_path / "edges.csv"),
        geology_fractions=_load_geology_fractions(
            bundle_path / "cell_geology_fractions.csv"
        ),
        mesh_summary=mesh_summary,
    )


__all__ = [
    "CatchmentMeshBundle",
    "CatchmentMeshBundleCell",
    "CatchmentMeshBundleEdge",
    "CatchmentMeshBundleGeologyFraction",
    "CatchmentMeshBundleNode",
    "load_catchment_mesh_bundle",
]
