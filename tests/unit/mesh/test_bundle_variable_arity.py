"""Round-trip the variable-arity ``cells.csv`` bundle table.

Voronoi/PEBI meshes carry cells with 5, 7 or more vertices. A bundle records the
real node count in ``ncvert`` and widens the ``n<k>`` columns to the largest cell;
the reader must give back every node list untouched (no silent truncation to four
nodes).
"""

from __future__ import annotations

import csv
from pathlib import Path

from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import _load_cells

_OPTIONAL_CELL_FIELDS = [
    "centroid_x",
    "centroid_y",
    "area_m2",
    "z_top_centroid",
    "z_top_mean",
    "z_bottom_centroid",
    "z_bottom_mean",
    "geology_code",
    "geology_key",
    "hydraulic_conductivity_m_s",
    "storage_coefficient",
]


def _write_cells_bundle(path: Path, node_lists: list[tuple[int, ...]]) -> None:
    """Write the ``cells.csv`` of a tiny mesh, padding the short node lists."""
    n_node_columns = max(3, max(len(nodes) for nodes in node_lists))
    fieldnames = [
        "cell_id",
        "geom_type",
        "ncvert",
        *[f"n{position}" for position in range(n_node_columns)],
        *_OPTIONAL_CELL_FIELDS,
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for cell_id, nodes in enumerate(node_lists):
            row: dict[str, object] = {
                "cell_id": cell_id,
                "geom_type": "polygon",
                "ncvert": len(nodes),
                "centroid_x": 0.0,
                "centroid_y": 0.0,
                "area_m2": 1.0,
            }
            for position in range(n_node_columns):
                row[f"n{position}"] = nodes[position] if position < len(nodes) else ""
            writer.writerow(row)


def test_variable_arity_cells_round_trip(tmp_path: Path) -> None:
    """A 3-, 5- and 7-vertex cell are read back intact."""
    node_lists = [
        (0, 1, 2),
        (3, 4, 5, 6, 7),
        (8, 9, 10, 11, 12, 13, 14),
    ]
    cells_path = tmp_path / "cells.csv"
    _write_cells_bundle(cells_path, node_lists)

    header = cells_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "ncvert" in header
    assert header.count("n6") == 1
    assert "n7" not in header

    loaded = _load_cells(cells_path)
    assert [cell.node_indices for cell in loaded] == node_lists
    assert [len(cell.node_indices) for cell in loaded] == [3, 5, 7]


def test_legacy_fixed_columns_still_read(tmp_path: Path) -> None:
    """Old bundles without ``ncvert`` (fixed n0..n3) keep loading unchanged."""
    cells_path = tmp_path / "cells.csv"
    cells_path.write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2",
                "0,triangle,0,1,2,,0.0,0.0,1.0",
                "1,quad,3,4,5,6,0.0,0.0,1.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loaded = _load_cells(cells_path)
    assert [cell.node_indices for cell in loaded] == [(0, 1, 2), (3, 4, 5, 6)]
