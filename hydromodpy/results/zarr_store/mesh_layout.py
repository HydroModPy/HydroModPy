"""What a run store keeps of its cell mesh, beyond vertices and connectivity.

``MeshLayout`` is the additive part of the ``mesh/`` group: cell centres, the
family bit fields, the zone codes, the edge tables and the attributes that say
which engine built the mesh. ``mesh_layout_from_cell_mesh`` derives it from a
``PlanarCellMesh``. The two family tables of the run (``mesh_cell_families`` and
``mesh_face_families``) come from the same mesh through the row builders below.

The store keeps the line families of its mesh as two int32 bit fields: one per
cell, one per mesh edge. Bit ``k`` of a cell is set when the cell belongs to the
family ``k`` (``PlanarCellMesh.family_cells``). Bit ``k`` of an edge is set when
the edge lies on a face row of the face family ``k``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "MAX_FAMILIES",
    "MeshLayout",
    "cell_family_bits",
    "cell_family_names",
    "cell_family_rows",
    "cf_flag_meanings",
    "edge_family_bits",
    "edge_family_names",
    "face_family_rows",
    "face_row_edges",
    "mesh_layout_from_cell_mesh",
]

MAX_FAMILIES = 31
"""Bits an int32 field holds without touching the sign."""

_INT32_MAX = np.iinfo(np.int32).max
_NOT_CF_NAME = re.compile(r"[^A-Za-z0-9_.+@-]")


@dataclass(frozen=True, eq=False)
class MeshLayout:
    """Arrays and attributes written under ``mesh/`` next to the geometry.

    ``face_*`` arrays have one entry per cell, ``edge_*`` arrays one per mesh
    edge. ``face_zone`` is ``None`` when the mesh has no zones. ``attrs`` are the
    attributes of the ``mesh/`` group.
    """

    face_x: np.ndarray
    face_y: np.ndarray
    center_kind: str
    face_family: np.ndarray
    family_names: tuple[str, ...]
    face_zone: np.ndarray | None
    zone_names: tuple[str, ...]
    edge_node_connectivity: np.ndarray
    edge_face_connectivity: np.ndarray
    edge_family: np.ndarray
    edge_family_names: tuple[str, ...]
    attrs: Mapping[str, object]

    def __post_init__(self) -> None:
        """Check that the per-cell and per-edge arrays agree in length."""
        n_cells = self.face_x.shape[0]
        per_cell = {"face_y": self.face_y, "face_family": self.face_family}
        if self.face_zone is not None:
            per_cell["face_zone"] = self.face_zone
        for name, values in per_cell.items():
            if values.shape != (n_cells,):
                raise MeshError(
                    f"mesh layout: {name} has shape {values.shape}, expected ({n_cells},)"
                )
        n_edges = self.edge_node_connectivity.shape[0]
        per_edge = {
            "edge_face_connectivity": self.edge_face_connectivity,
            "edge_family": self.edge_family,
        }
        for name, values in per_edge.items():
            if values.shape[0] != n_edges:
                raise MeshError(
                    f"mesh layout: {name} has {values.shape[0]} rows, expected {n_edges}"
                )


def mesh_layout_from_cell_mesh(
    cell_mesh: PlanarCellMesh,
    *,
    request_hash: str = "",
    qa: Mapping[str, object] | None = None,
    library_versions: Mapping[str, str] | None = None,
) -> MeshLayout:
    """Derive the stored layout of a cell mesh.

    ``request_hash``, ``qa`` and ``library_versions`` come from the mesh step
    summary; the attribute of a value that is absent is left out rather than
    invented.
    """
    n_nodes = cell_mesh.mesh.n_nodes
    if n_nodes >= _INT32_MAX or cell_mesh.n_cells >= _INT32_MAX:
        raise MeshError(f"the mesh ({n_nodes} nodes) does not fit int32 connectivity")
    geometry = cell_mesh.geometry
    identity = cell_mesh.identity
    attrs: dict[str, object] = {
        "engine": identity.engine_id,
        "engine_version": identity.engine_version,
        "crs": cell_mesh.crs_wkt,
    }
    if identity.seed is not None:
        attrs["engine_seed"] = int(identity.seed)
    if request_hash:
        attrs["mesh_request_hash"] = str(request_hash)
    if qa is not None:
        attrs["qa"] = _json_safe(qa)
    if library_versions:
        attrs["library_versions"] = {str(k): str(v) for k, v in library_versions.items()}
    if cell_mesh.structured_shape is not None:
        attrs["structured_shape"] = [int(v) for v in cell_mesh.structured_shape]
    return MeshLayout(
        face_x=np.ascontiguousarray(cell_mesh.centers[:, 0], dtype=np.float64),
        face_y=np.ascontiguousarray(cell_mesh.centers[:, 1], dtype=np.float64),
        center_kind=cell_mesh.center_kind,
        face_family=cell_family_bits(cell_mesh),
        family_names=cell_family_names(cell_mesh),
        face_zone=None if cell_mesh.cell_zone is None else cell_mesh.cell_zone.astype(np.int32),
        zone_names=cell_mesh.zone_names,
        edge_node_connectivity=geometry.edge_nodes.astype(np.int32),
        edge_face_connectivity=geometry.edge_cells.astype(np.int32),
        edge_family=edge_family_bits(cell_mesh),
        edge_family_names=edge_family_names(cell_mesh),
        attrs=attrs,
    )


def cf_flag_meanings(names: tuple[str, ...]) -> str:
    """Return the CF ``flag_meanings`` string of family names.

    CF allows letters, digits and ``_.+@-`` in a meaning; any other character
    becomes ``_``. Two names that collapse to the same meaning are refused.
    """
    meanings = tuple(_NOT_CF_NAME.sub("_", name) for name in names)
    if len(set(meanings)) != len(meanings):
        raise MeshError(f"family names collide once made CF-safe: {list(names)}")
    return " ".join(meanings)


def cell_family_rows(cell_mesh: PlanarCellMesh) -> list[dict[str, Any]]:
    """Return the rows of ``mesh_cell_families``: one per cell of every chain.

    ``position`` counts from upstream. ``offset_m`` is the distance from the cell
    centre to the family line, null for a chain that publishes no offset.
    """
    rows: list[dict[str, Any]] = []
    for chain in cell_mesh.cell_chains:
        offsets = (
            [None] * chain.cell_ids.size if chain.offset_m is None else chain.offset_m.tolist()
        )
        rows.extend(
            {
                "family": chain.family,
                "chain_id": int(chain.chain_id),
                "position": position,
                "cell_id": int(cell_id),
                "offset_m": offset,
            }
            for position, (cell_id, offset) in enumerate(
                zip(chain.cell_ids.tolist(), offsets, strict=True)
            )
        )
    return rows


def face_family_rows(cell_mesh: PlanarCellMesh) -> list[dict[str, Any]]:
    """Return the rows of ``mesh_face_families``: one per family face."""
    table = cell_mesh.face_families
    if table is None or table.n_rows == 0:
        return []
    edge_ids = face_row_edges(cell_mesh)
    zone_names = cell_mesh.zone_names

    def zone(index: int) -> str | None:
        return zone_names[index] if index >= 0 else None

    return [
        {
            "face_row": row,
            "family": table.names[int(table.family[row])],
            "edge_id": int(edge_ids[row]),
            "node_a": int(table.node_a[row]),
            "node_b": int(table.node_b[row]),
            "cell_a": int(table.cell_a[row]),
            "cell_b": int(table.cell_b[row]),
            "zone_left": zone(int(table.zone_left[row])),
            "zone_right": zone(int(table.zone_right[row])),
        }
        for row in range(table.n_rows)
    ]


def cell_family_names(cell_mesh: PlanarCellMesh) -> tuple[str, ...]:
    """Return the family names of the cell bit field, in order of first appearance.

    The families of the cell chains come first, then those of the face rows. A
    name met twice owns one bit.
    """
    names: dict[str, None] = {}
    for chain in cell_mesh.cell_chains:
        names.setdefault(chain.family)
    if cell_mesh.face_families is not None:
        for name in cell_mesh.face_families.names:
            names.setdefault(name)
    return _checked(tuple(names))


def edge_family_names(cell_mesh: PlanarCellMesh) -> tuple[str, ...]:
    """Return the family names of the edge bit field: the face family names."""
    if cell_mesh.face_families is None:
        return ()
    return _checked(cell_mesh.face_families.names)


def _checked(names: tuple[str, ...]) -> tuple[str, ...]:
    if len(names) > MAX_FAMILIES:
        raise MeshError(
            f"a mesh holds at most {MAX_FAMILIES} families in a bit field, got {len(names)}: "
            f"{list(names)}"
        )
    return names


def cell_family_bits(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the int32 family bit field of every cell."""
    bits = np.zeros(cell_mesh.n_cells, dtype=np.int32)
    for k, name in enumerate(cell_family_names(cell_mesh)):
        bits[cell_mesh.family_cells(name)] |= np.int32(1 << k)
    return bits


def face_row_edges(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return, for every row of the face family table, the rank of its mesh edge.

    The rank indexes ``cell_mesh.geometry.edge_nodes``. A row whose two nodes are
    not an edge of the mesh is a topology error.
    """
    table = cell_mesh.face_families
    if table is None or table.n_rows == 0:
        return np.empty(0, dtype=np.int64)
    n_nodes = np.int64(cell_mesh.mesh.n_nodes)
    edge_nodes = cell_mesh.geometry.edge_nodes
    edge_keys = edge_nodes[:, 0] * n_nodes + edge_nodes[:, 1]
    row_keys = np.minimum(table.node_a, table.node_b) * n_nodes + np.maximum(
        table.node_a, table.node_b
    )
    rank = np.searchsorted(edge_keys, row_keys)
    rank_in_range = np.minimum(rank, edge_keys.size - 1)
    missing = (rank >= edge_keys.size) | (edge_keys[rank_in_range] != row_keys)
    if missing.any():
        row = int(np.flatnonzero(missing)[0])
        raise MeshError(
            f"face family row {row} ('{table.names[int(table.family[row])]}') joins nodes "
            f"({int(table.node_a[row])}, {int(table.node_b[row])}), which are not an edge of the mesh"
        )
    return rank.astype(np.int64)


def edge_family_bits(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the int32 family bit field of every mesh edge."""
    bits = np.zeros(cell_mesh.geometry.edge_nodes.shape[0], dtype=np.int32)
    table = cell_mesh.face_families
    if table is None or table.n_rows == 0:
        return bits
    _checked(table.names)
    row_bits = np.int32(1) << table.family.astype(np.int32)
    np.bitwise_or.at(bits, face_row_edges(cell_mesh), row_bits)
    return bits


def _json_safe(value: object) -> object:
    """Return ``value`` with NaN and infinities as ``None`` and numpy scalars as Python ones."""
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
