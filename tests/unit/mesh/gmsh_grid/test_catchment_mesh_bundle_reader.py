"""A mesh bundle reads back whole, and its format is versioned and documented in the reader.

Every bundle committed to the repository declares the version the reader reads,
holds every column the schema requires, and holds no column the schema does not
name. A writer that drifts from the documented format fails here. A bundle
written here from a small mesh of cells of 3, 5 and 7 nodes reads back field by
field: Voronoi/PEBI cells carry 5, 7 or more nodes, the real count is in
``ncvert``, and the reader gives back every node list untouched.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    BUNDLE_COLUMNS,
    BUNDLE_SCHEMA_VERSION,
    OPTIONAL,
    load_catchment_mesh_bundle,
)

REPO = Path(__file__).resolve().parents[4]
COMMITTED = sorted(
    path.parent for path in (REPO / "validation_cases").rglob("mesh_bundles/*/metadata.json")
)

NODE_LISTS = [(0, 1, 2), (3, 4, 5, 6, 7), (8, 9, 10, 11, 12, 13, 14)]
"""A triangle, a pentagon and a heptagon."""


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as stream:
        return next(csv.reader(stream))


def _schema_name(column: str) -> str:
    return "n<k>" if re.fullmatch(r"n\d+", column) else column


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)


def _write_bundle(folder: Path, *, ncvert: bool = True, fractions: bool = True) -> Path:
    """Write the bundle of ``NODE_LISTS`` with every column of ``BUNDLE_COLUMNS``.

    Without ``ncvert`` the cell table has the fixed ``n<k>`` columns of the old
    bundles only. The bundle has no ``mesh_summary.json``.
    """
    folder.mkdir()
    n_nodes = 1 + max(max(nodes) for nodes in NODE_LISTS)
    node_rows = [
        {"node_id": k, "x": 100.0 + k, "y": 200.0 - k, "z_top": 10.0 + k, "z_bottom": ""}
        for k in range(n_nodes)
    ]
    _write_csv(folder / "nodes.csv", list(BUNDLE_COLUMNS["nodes.csv"]), node_rows)

    width = max(len(nodes) for nodes in NODE_LISTS)
    node_columns = [f"n{k}" for k in range(width)]
    cell_columns = [
        name
        for name in BUNDLE_COLUMNS["cells.csv"]
        if name != "n<k>" and (ncvert or name != "ncvert")
    ]
    cell_columns[2:2] = node_columns
    cell_rows = []
    for cell_id, nodes in enumerate(NODE_LISTS):
        row: dict[str, object] = {
            "cell_id": cell_id,
            "geom_type": "triangle" if len(nodes) == 3 else "polygon",
            "ncvert": len(nodes),
            "centroid_x": 1.0 + cell_id,
            "centroid_y": 2.0 + cell_id,
            "area_m2": 50.0 * (cell_id + 1),
            "z_top_centroid": 12.5,
            "geology_code": cell_id,
            "geology_key": f"unit_{cell_id}",
            "hydraulic_conductivity_m_s": 1e-5 * (cell_id + 1),
        }
        row.update({f"n{k}": node for k, node in enumerate(nodes)})
        if not ncvert:
            row.pop("ncvert")
        cell_rows.append(row)
    _write_csv(folder / "cells.csv", cell_columns, cell_rows)

    edge_rows = [
        {
            "edge_id": 0,
            "node_a": 1,
            "node_b": 2,
            "cell_a": 0,
            "cell_b": 1,
            "length_m": 3.5,
            "edge_kind": "internal",
            "is_river": "true",
            "geology_a_key": "unit_0",
            "geology_b_key": "unit_1",
        },
        {
            "edge_id": 1,
            "node_a": 0,
            "node_b": 1,
            "cell_a": 0,
            "length_m": 2.0,
            "edge_kind": "boundary",
            "is_river": "false",
        },
    ]
    _write_csv(folder / "edges.csv", list(BUNDLE_COLUMNS["edges.csv"]), edge_rows)

    if fractions:
        fraction_rows = [
            {"cell_id": 2, "geology_key": "unit_2", "fraction": 0.75},
            {"cell_id": 2, "geology_key": "unit_1", "fraction": 0.25},
        ]
        _write_csv(
            folder / "cell_geology_fractions.csv",
            list(BUNDLE_COLUMNS["cell_geology_fractions.csv"]),
            fraction_rows,
        )

    metadata = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "crs": "EPSG:2154",
        "n_nodes": n_nodes,
        "n_cells": len(NODE_LISTS),
        "files": {"mesh": "mesh_2d.msh", "nodes": "nodes.csv", "cells": "cells.csv"},
    }
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return folder


def test_the_repository_commits_bundles():
    assert len(COMMITTED) >= 13


@pytest.mark.parametrize("bundle", COMMITTED, ids=lambda path: path.name)
def test_a_committed_bundle_follows_the_documented_schema(bundle):
    metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["bundle_schema_version"] == BUNDLE_SCHEMA_VERSION
    assert load_catchment_mesh_bundle(bundle).metadata_view.crs

    for filename, columns in BUNDLE_COLUMNS.items():
        path = bundle / filename
        if not path.exists():
            assert filename == "cell_geology_fractions.csv"
            continue
        header = {_schema_name(column) for column in _header(path)}
        required = {name for name, text in columns.items() if not text.startswith(OPTIONAL)}
        assert required <= header, f"{path} lacks {required - header}"
        assert header <= set(columns), f"{path} holds undocumented {header - set(columns)}"


def test_a_written_bundle_follows_the_documented_schema(tmp_path: Path):
    bundle = _write_bundle(tmp_path / "bundle")

    for filename, columns in BUNDLE_COLUMNS.items():
        header = {_schema_name(column) for column in _header(bundle / filename)}
        assert header == set(columns)


def test_a_written_bundle_reads_back_field_by_field(tmp_path: Path):
    bundle = load_catchment_mesh_bundle(_write_bundle(tmp_path / "bundle"))

    assert bundle.n_nodes == 15
    assert bundle.nodes[4].x == 104.0 and bundle.nodes[4].y == 196.0
    assert bundle.nodes[4].z_top == 14.0 and bundle.nodes[4].z_bottom is None
    pentagon = bundle.cells[1]
    assert pentagon.geom_type == "polygon"
    assert (pentagon.centroid_x, pentagon.centroid_y, pentagon.area_m2) == (2.0, 3.0, 100.0)
    assert pentagon.z_top_centroid == 12.5 and pentagon.z_top_mean is None
    assert (pentagon.geology_code, pentagon.geology_key) == (1, "unit_1")
    assert pentagon.hydraulic_conductivity_m_s == pytest.approx(2e-5)
    assert pentagon.storage_coefficient is None
    river, side = bundle.edges
    assert (river.cell_a, river.cell_b, river.is_river, river.length_m) == (0, 1, True, 3.5)
    assert (river.geology_a_key, river.geology_b_key) == ("unit_0", "unit_1")
    assert (side.cell_b, side.is_river, side.edge_kind) == (None, False, "boundary")
    assert [(f.cell_id, f.geology_key, f.fraction) for f in bundle.geology_fractions] == [
        (2, "unit_2", 0.75),
        (2, "unit_1", 0.25),
    ]
    view = bundle.metadata_view
    assert (view.bundle_schema_version, view.crs) == (BUNDLE_SCHEMA_VERSION, "EPSG:2154")
    assert (view.n_nodes, view.n_cells) == (bundle.n_nodes, bundle.n_cells)
    assert bundle.mesh_summary is None


def test_cells_of_three_five_and_seven_nodes_read_back_intact(tmp_path: Path):
    folder = _write_bundle(tmp_path / "bundle")

    header = _header(folder / "cells.csv")
    assert "ncvert" in header
    assert header.count("n6") == 1
    assert "n7" not in header
    assert [cell.node_indices for cell in load_catchment_mesh_bundle(folder).cells] == NODE_LISTS


def test_an_old_bundle_without_ncvert_reads_every_filled_node_column(tmp_path: Path):
    folder = _write_bundle(tmp_path / "bundle", ncvert=False)

    assert "ncvert" not in _header(folder / "cells.csv")
    assert [cell.node_indices for cell in load_catchment_mesh_bundle(folder).cells] == NODE_LISTS


def test_the_bundle_gives_its_edges_its_mesh_file_and_its_cells_by_id(tmp_path: Path):
    folder = _write_bundle(tmp_path / "bundle")
    bundle = load_catchment_mesh_bundle(folder)

    assert bundle.n_edges == 2
    assert bundle.mesh_path == (folder / "mesh_2d.msh").resolve()
    assert bundle.node_coordinates()[4] == (104.0, 196.0)
    assert bundle.cell_connectivity() == NODE_LISTS
    assert bundle.cell_by_id(2).node_indices == NODE_LISTS[2]
    with pytest.raises(KeyError, match="Unknown cell_id=3"):
        bundle.cell_by_id(3)


def test_a_bundle_without_geology_fractions_has_none(tmp_path: Path):
    bundle = load_catchment_mesh_bundle(_write_bundle(tmp_path / "bundle", fractions=False))

    assert bundle.geology_fractions == ()


def test_a_folder_without_metadata_is_not_a_bundle(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Bundle metadata not found"):
        load_catchment_mesh_bundle(tmp_path)


def test_a_committed_bundle_keeps_its_mesh_summary_and_its_mesh_file():
    folder = COMMITTED[0]
    bundle = load_catchment_mesh_bundle(folder)

    summary = json.loads((folder / "mesh_summary.json").read_text(encoding="utf-8"))
    assert bundle.mesh_summary == summary
    assert bundle.mesh_path.is_file()
