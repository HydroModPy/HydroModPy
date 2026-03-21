"""Read self-contained catchment mesh exchange bundles.

This reader is intentionally lightweight so the standalone ``mesh`` package can
reload standard bundles without requiring a per-bundle ``reader.py`` helper.
It depends only on the Python standard library.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _parse_optional_float(raw_value: str) -> float | None:
    text = str(raw_value).strip()
    if text == "":
        return None
    return float(text)


def _parse_optional_int(raw_value: str) -> int | None:
    text = str(raw_value).strip()
    if text == "":
        return None
    return int(text)


def _parse_bool(raw_value: str) -> bool:
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CatchmentMeshBundleNode:
    node_id: int
    x: float
    y: float
    z_top: float | None
    z_bottom: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleCell:
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
    cell_id: int
    geology_key: str
    fraction: float


@dataclass(frozen=True)
class CatchmentMeshBundle:
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


def _load_csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return tuple(dict(row) for row in reader)


def _load_required_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _parse_node(row: dict[str, str]) -> CatchmentMeshBundleNode:
    return CatchmentMeshBundleNode(
        node_id=int(row["node_id"]),
        x=float(row["x"]),
        y=float(row["y"]),
        z_top=_parse_optional_float(row.get("z_top", "")),
        z_bottom=_parse_optional_float(row.get("z_bottom", "")),
    )


def _get_cell_node_indices(row: dict[str, str]) -> tuple[int, ...]:
    return tuple(
        int(row[column_name])
        for column_name in ("n0", "n1", "n2", "n3")
        if str(row.get(column_name, "")).strip() != ""
    )


def _parse_cell(row: dict[str, str]) -> CatchmentMeshBundleCell:
    return CatchmentMeshBundleCell(
        cell_id=int(row["cell_id"]),
        geom_type=str(row["geom_type"]),
        node_indices=_get_cell_node_indices(row),
        centroid_x=float(row["centroid_x"]),
        centroid_y=float(row["centroid_y"]),
        area_m2=float(row["area_m2"]),
        z_top_centroid=_parse_optional_float(row.get("z_top_centroid", "")),
        z_top_mean=_parse_optional_float(row.get("z_top_mean", "")),
        z_bottom_centroid=_parse_optional_float(row.get("z_bottom_centroid", "")),
        z_bottom_mean=_parse_optional_float(row.get("z_bottom_mean", "")),
        geology_code=_parse_optional_int(row.get("geology_code", "")),
        geology_key=str(row.get("geology_key", "")),
        hydraulic_conductivity_m_s=_parse_optional_float(
            row.get("hydraulic_conductivity_m_s", "")
        ),
        storage_coefficient=_parse_optional_float(row.get("storage_coefficient", "")),
    )


def _parse_edge(row: dict[str, str]) -> CatchmentMeshBundleEdge:
    return CatchmentMeshBundleEdge(
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


def _parse_geology_fraction(row: dict[str, str]) -> CatchmentMeshBundleGeologyFraction:
    return CatchmentMeshBundleGeologyFraction(
        cell_id=int(row["cell_id"]),
        geology_key=str(row["geology_key"]),
        fraction=float(row["fraction"]),
    )


def _load_nodes(path: Path) -> tuple[CatchmentMeshBundleNode, ...]:
    return tuple(
        _parse_node(row)
        for row in _load_csv_rows(path)
    )


def _load_cells(path: Path) -> tuple[CatchmentMeshBundleCell, ...]:
    return tuple(
        _parse_cell(row)
        for row in _load_csv_rows(path)
    )


def _load_edges(path: Path) -> tuple[CatchmentMeshBundleEdge, ...]:
    return tuple(
        _parse_edge(row)
        for row in _load_csv_rows(path)
    )


def _load_geology_fractions(path: Path) -> tuple[CatchmentMeshBundleGeologyFraction, ...]:
    return tuple(
        _parse_geology_fraction(row)
        for row in _load_csv_rows(path)
    )


def load_catchment_mesh_bundle(bundle_dir: str | Path) -> CatchmentMeshBundle:
    """Load one previously exported catchment mesh bundle."""
    bundle_path = Path(bundle_dir).resolve()
    metadata = _load_required_json(bundle_path / "metadata.json", label="Bundle metadata")
    mesh_summary = _load_optional_json(bundle_path / "mesh_summary.json")

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
