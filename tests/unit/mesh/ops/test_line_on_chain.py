"""The length of a river line shared among the cells of a mesh, in order along it."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain
from hydromodpy.spatial.mesh.ops.line_on_chain import (
    MIN_PIECE_LENGTH_M,
    chain_pieces,
    crossing_pieces,
)
from tests._helpers.mesh_cases import regular_mesh

GRID = regular_mesh(3, 4, dx=10.0)
"""Four columns and three rows of 10 m cells on [0, 40] x [0, 30], row 0 north."""

MIDDLE_ROW = np.array([4, 5, 6, 7])


def _with_river(cells: np.ndarray):
    return dataclasses.replace(GRID, cell_chains=(CellChain("rivers", 0, cells),))


def test_a_line_along_the_chain_shares_its_length_among_its_cells() -> None:
    line = LineString([(0.0, 15.0), (40.0, 15.0)])

    [pieces] = chain_pieces(_with_river(MIDDLE_ROW), [line], family="rivers")

    assert [piece.cell for piece in pieces] == MIDDLE_ROW.tolist()
    assert sum(piece.length for piece in pieces) == pytest.approx(line.length)
    assert [piece.middle for piece in pieces] == pytest.approx([5.0, 15.0, 25.0, 35.0])


def test_a_mesh_without_chains_or_without_lines_gives_no_piece() -> None:
    line = LineString([(0.0, 15.0), (40.0, 15.0)])

    assert chain_pieces(GRID, [line], family="rivers") == [[]]
    assert chain_pieces(_with_river(MIDDLE_ROW), [], family="rivers") == []


def test_a_line_farther_than_a_cell_size_from_every_chain_cell_gets_no_piece() -> None:
    near = LineString([(0.0, 15.0), (40.0, 15.0)])
    far = LineString([(0.0, 60.0), (40.0, 60.0)])

    pieces = chain_pieces(_with_river(MIDDLE_ROW), [near, far], family="rivers")

    assert len(pieces[0]) == 4
    assert pieces[1] == []


def test_a_line_shorter_than_the_smallest_share_stays_in_one_piece() -> None:
    stub = LineString([(14.0, 15.0), (14.0 + 0.5 * MIN_PIECE_LENGTH_M, 15.0)])

    [pieces] = chain_pieces(_with_river(MIDDLE_ROW), [stub], family="rivers")

    assert len(pieces) == 1
    assert pieces[0].length == pytest.approx(stub.length)


def test_without_chains_each_cell_gets_the_length_of_the_line_inside_it() -> None:
    line = LineString([(5.0, 15.0), (35.0, 15.0)])

    pieces = crossing_pieces(GRID, line)

    assert [piece.cell for piece in pieces] == MIDDLE_ROW.tolist()
    assert [piece.length for piece in pieces] == pytest.approx([5.0, 10.0, 10.0, 5.0])


def test_a_line_off_the_mesh_crosses_no_cell() -> None:
    assert crossing_pieces(GRID, LineString([(50.0, 0.0), (60.0, 10.0)])) == []


def test_a_line_that_grazes_a_corner_leaves_that_cell_out() -> None:
    # Within a micrometre of the node (20, 10), the diagonal cuts a sliver off cell 6.
    graze = 0.5 * MIN_PIECE_LENGTH_M
    line = LineString([(10.0 + graze, 0.0), (30.0 + graze, 20.0)])

    pieces = crossing_pieces(GRID, line)

    assert sum(piece.length for piece in pieces) == pytest.approx(line.length, abs=1e-5)
    assert all(piece.length >= MIN_PIECE_LENGTH_M for piece in pieces)
