"""Invariants and helpers of the planar cell mesh."""

from __future__ import annotations

import dataclasses
from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    CellChain,
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from tests._helpers.mesh_cases import regular_mesh

NROW, NCOL = 3, 4
DECLARATIONS = {"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False}


def _table(**overrides) -> FaceFamilyTable:
    columns = {
        "names": ("boundary:north", "geology"),
        "family": [0, 0, 1],
        "cell_a": [0, 1, 1],
        "cell_b": [-1, -1, 2],
        "node_a": [0, 1, 7],
        "node_b": [1, 2, 2],
        "zone_left": [-1, -1, 0],
        "zone_right": [-1, -1, 1],
    }
    columns.update(overrides)
    return FaceFamilyTable(**columns)


def _cell_mesh() -> PlanarCellMesh:
    mesh = regular_mesh(NROW, NCOL, dx=10.0).mesh
    xx, yy = np.meshgrid(5.0 + 10.0 * np.arange(NCOL), 25.0 - 10.0 * np.arange(NROW))
    return build_planar_cell_mesh(
        mesh,
        np.column_stack([xx.ravel(), yy.ravel()]),
        center_kind="cell_center",
        crs_wkt="EPSG:2154",
        identity=MeshIdentity("regular", "1.0.0", "", None),
        declarations=DECLARATIONS,
        cell_chains=(
            CellChain("rivers", 0, np.array([4, 5, 6])),
            CellChain("rivers", 1, np.array([6, 10])),
        ),
        face_families=_table(),
        cell_zone=np.array([0, 0, 1] + [-1] * 9),
        zone_names=("granite", "schist"),
        structured_shape=(NROW, NCOL),
    )


def test_a_valid_mesh_exposes_its_families() -> None:
    cell_mesh = _cell_mesh()

    assert cell_mesh.n_cells == NROW * NCOL
    assert [c.chain_id for c in cell_mesh.chains("rivers")] == [0, 1]
    assert cell_mesh.chains("lakes") == ()
    assert cell_mesh.face_rows("geology").tolist() == [False, False, True]
    assert cell_mesh.face_rows("lakes").tolist() == [False, False, False]
    assert cell_mesh.family_cells("rivers").tolist() == [4, 5, 6, 10]
    assert cell_mesh.family_cells("boundary:north").tolist() == [0, 1]
    assert cell_mesh.family_cells("geology").tolist() == [1, 2]
    assert cell_mesh.cell_zone.dtype == np.int32
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_geometry_is_derived_once() -> None:
    cell_mesh = _cell_mesh()

    assert cell_mesh.geometry is cell_mesh.geometry
    assert cell_mesh.geometry.areas.sum() == pytest.approx(NROW * NCOL * 100.0)


def test_the_smoothed_outline_keeps_the_geometry_already_derived() -> None:
    cell_mesh = _cell_mesh()
    geometry = cell_mesh.geometry
    outline = box(0.0, 0.0, 40.0, 30.0)

    carried = cell_mesh.with_smoothed_catchment(outline)

    assert carried.smoothed_catchment is outline
    assert carried.geometry is geometry


def test_another_qa_keeps_the_mesh_and_its_geometry() -> None:
    cell_mesh = _cell_mesh()
    geometry = cell_mesh.geometry
    qa = dataclasses.replace(cell_mesh.qa, notes=("a note",))

    carried = cell_mesh.with_qa(qa)

    assert carried.qa is qa and cell_mesh.qa.notes == ()
    assert carried.geometry is geometry
    assert carried.mesh is cell_mesh.mesh


@pytest.mark.parametrize("crs_wkt", ["", "   "])
def test_a_missing_crs_raises(crs_wkt: str) -> None:
    with pytest.raises(ValueError, match="CRS"):
        replace(_cell_mesh(), crs_wkt=crs_wkt)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"centers": np.zeros((NROW * NCOL - 1, 2))}, "centers"),
        ({"centers": np.full((NROW * NCOL, 2), np.nan)}, "centers"),
        ({"center_kind": "centroid"}, "center_kind"),
        ({"cell_chains": (CellChain("rivers", 0, np.array([0, NROW * NCOL])),)}, "chain"),
        ({"face_families": _table(cell_b=[-1, -1, NROW * NCOL])}, "cell id"),
        ({"face_families": _table(node_b=[1, 2, 99])}, "vertex id"),
        ({"face_families": _table(zone_right=[-1, -1, 2])}, "zone"),
        ({"cell_zone": np.zeros(5)}, "cell_zone"),
        ({"cell_zone": np.full(NROW * NCOL, 2)}, "cell_zone"),
        ({"structured_shape": (NCOL, NCOL)}, "structured_shape"),
    ],
)
def test_out_of_range_ids_and_bad_shapes_raise(changes: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        replace(_cell_mesh(), **changes)


def test_a_mesh_of_two_blocks_raises() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0]])
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(CellType.QUADRILATERAL, [[0, 1, 2, 3]]),
            CellBlock(CellType.TRIANGLE, [[1, 4, 2]]),
        ),
    )
    with pytest.raises(ValueError, match="one block"):
        replace(_cell_mesh(), mesh=mesh, centers=np.zeros((2, 2)), structured_shape=None)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"cell_a": [0, 1]}, "one length"),
        ({"family": [0, 0, 2]}, "index outside names"),
        ({"cell_b": [-2, -1, 2]}, "cell_b"),
        ({"names": ("geology", "geology")}, "repeat"),
        ({"node_a": [0, -1, 7]}, "face node ids must be non-negative"),
        ({"zone_left": [-1, -2, 0]}, "zone indices must be -1 or more"),
    ],
)
def test_face_family_columns_are_checked(changes: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _table(**changes)


def test_an_empty_face_family_table_keeps_its_names() -> None:
    empty = {name: [] for name in ("family", "cell_a", "cell_b", "node_a", "node_b")}
    table = _table(**empty, zone_left=[], zone_right=[])

    assert table.n_rows == 0
    assert table.names == ("boundary:north", "geology")
    assert not replace(_cell_mesh(), face_families=table).face_rows("geology").any()


def _stacked() -> FaceFamilyTable:
    return FaceFamilyTable.stack(
        [
            (
                "boundary:north",
                {"cell_a": [0, 1], "cell_b": [-1, -1], "node_a": [0, 1], "node_b": [1, 2]},
            ),
            (
                "geology",
                {
                    "cell_a": np.array([1]),
                    "cell_b": np.array([2]),
                    "node_a": np.array([7]),
                    "node_b": np.array([2]),
                    "zone_left": np.array([0], dtype=np.int32),
                    "zone_right": np.array([1], dtype=np.int32),
                },
            ),
        ]
    )


def test_stacking_families_gives_the_table_of_their_rows_in_order() -> None:
    stacked, written = _stacked(), _table()

    assert stacked.names == written.names
    for column in ("family", "cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right"):
        assert getattr(stacked, column).dtype == getattr(written, column).dtype
        assert np.array_equal(getattr(stacked, column), getattr(written, column))


def test_a_stacked_family_without_zones_has_unknown_zones() -> None:
    stacked = _stacked()
    north = stacked.family == stacked.names.index("boundary:north")

    assert np.all(stacked.zone_left[north] == -1)
    assert np.all(stacked.zone_right[north] == -1)


def test_a_stacked_family_without_rows_keeps_its_name_and_index() -> None:
    no_row = {column: np.empty(0, dtype=np.int64) for column in ("cell_a", "cell_b", "node_a")}
    stacked = FaceFamilyTable.stack(
        [
            ("lakes", {**no_row, "node_b": np.empty(0, dtype=np.int64)}),
            ("geology", {"cell_a": [3], "cell_b": [4], "node_a": [5], "node_b": [6]}),
        ]
    )

    assert stacked.names == ("lakes", "geology")
    assert stacked.family.tolist() == [1]


def test_stacking_no_family_gives_an_empty_table() -> None:
    stacked = FaceFamilyTable.stack([])

    assert stacked.names == ()
    assert stacked.n_rows == 0


def test_stacked_families_are_checked_like_a_written_table() -> None:
    with pytest.raises(ValueError, match="repeat"):
        FaceFamilyTable.stack(
            [
                ("geology", {"cell_a": [0], "cell_b": [-1], "node_a": [0], "node_b": [1]}),
                ("geology", {"cell_a": [1], "cell_b": [-1], "node_a": [1], "node_b": [2]}),
            ]
        )


def test_a_mesh_with_3d_vertices_raises() -> None:
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2]]),))
    with pytest.raises(ValueError, match="2-column vertices"):
        replace(_cell_mesh(), mesh=mesh, centers=np.zeros((1, 2)), structured_shape=None)


def test_identity_and_chain_refuse_empty_names() -> None:
    with pytest.raises(ValueError, match="engine_id"):
        MeshIdentity("", "1.0.0", "", None)
    with pytest.raises(ValueError, match="family"):
        CellChain(" ", 0, np.array([0]))
    with pytest.raises(ValueError, match="negative"):
        CellChain("rivers", 0, np.array([0, -1]))


def test_a_chain_keeps_its_offsets_as_float64_or_none() -> None:
    chain = CellChain("rivers", 0, np.array([1, 2, 3]), offset_m=[0, 2, 0.5])

    assert chain.offset_m.dtype == np.float64
    assert chain.offset_m.tolist() == [0.0, 2.0, 0.5]
    assert CellChain("rivers", 1, np.array([1])).offset_m is None
    cell_mesh = replace(_cell_mesh(), cell_chains=(chain,))
    assert cell_mesh.chains("rivers")[0].offset_m.tolist() == [0.0, 2.0, 0.5]


@pytest.mark.parametrize(
    ("offset_m", "match"),
    [([0.0, 1.0], "offsets"), ([0.0, -1.0, 0.0], "negative"), ([0.0, np.nan, 0.0], "not finite")],
)
def test_a_chain_refuses_bad_offsets(offset_m: list[float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        CellChain("rivers", 0, np.array([1, 2, 3]), offset_m=offset_m)
