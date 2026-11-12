"""Unit tests for the mesh-native SFR channel re-derivation (SFD trace)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.sfr_rectify import (
    _prune_parallel_stub_cells,
    rectify_reach_graph,
)


@dataclass
class _Rec:
    ifno: int
    cellid: tuple[int, int] | None
    rtp: float = 97.0
    rlen: float = 10.0
    rgrd: float = 1e-3
    rwid: float = 2.0
    strahler: int = 1
    area_km2: float = 1.0
    ustrf: float = 1.0
    is_headwater: bool = False
    is_terminal_to_lake: bool = False
    terminal_lake: object = None
    upstream: tuple[int, ...] = ()
    downstream: tuple[int, ...] = ()


def _chain(n: int):
    """A 1-D chain of cells: T falls to the east, the receiver of D steps east, the last exits."""
    top = np.array([100.0 - i for i in range(n)])
    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n - 1):
        adj[i].add(i + 1)
        adj[i + 1].add(i)
    receiver = np.array([i + 1 for i in range(n - 1)] + [-1])
    return top, adj, receiver


def _rectify(records, top, adj, receiver, *, lakes=None, spillway=frozenset(), n=None, **kwargs):
    n = n if n is not None else top.shape[0]
    return rectify_reach_graph(
        records,
        receiver=receiver,
        face_adjacency=adj,
        mesh_top=top,
        lake_cell_to_number=lakes or {},
        idomain=np.ones((1, n), dtype=int),
        location="test",
        spillway_seeds=set(spillway),
        **kwargs,
    )


def test_a_shore_cell_ends_terminal_to_its_lake() -> None:
    top, adj, receiver = _chain(6)
    nodes, _ = _rectify([_Rec(0, (0, 2))], top, adj, receiver, lakes={5: 1})
    terminal = [nd["cellid"][1] for nd in nodes if nd["is_terminal_to_lake"]]
    assert terminal == [4]
    assert 5 not in {nd["cellid"][1] for nd in nodes}


def test_a_cycle_in_the_receiver_raises() -> None:
    _, adj, _ = _chain(4)
    top = np.array([100.0, 99.0, 98.0, 97.0])
    receiver = np.array([1, 2, 0, -1])
    with pytest.raises(ValueError, match="cell 0"):
        _rectify([_Rec(0, (0, 0))], top, adj, receiver)


def test_a_spillway_walk_onto_a_lake_adds_no_reach(caplog) -> None:
    # The dam toe at cell 1 descends onto the lake cell 2: nothing is added, and the
    # walk is reported by its seed. The delineated seed at cell 4 is untouched.
    top, adj, receiver = _chain(6)
    with caplog.at_level("WARNING"):
        nodes, _ = _rectify(
            [_Rec(0, (0, 4))],
            top,
            adj,
            receiver,
            lakes={2: 1},
            spillway={1},
            max_stub_upstream=-1,
            min_component_cells=1,
        )
    assert sorted(nd["cellid"][1] for nd in nodes) == [4, 5]
    assert any("spillway seed cell 1" in rec.getMessage() for rec in caplog.records)


def test_a_spillway_walk_merges_into_the_channel() -> None:
    # Toe at cell 1 walks 1 -> 2 and joins the channel traced from the seed at cell 3.
    top, adj, receiver = _chain(6)
    nodes, edges = _rectify(
        [_Rec(0, (0, 3))],
        top,
        adj,
        receiver,
        spillway={1},
        max_stub_upstream=-1,
        min_component_cells=1,
    )
    cells = [nd["cellid"][1] for nd in nodes]
    assert sorted(cells) == [1, 2, 3, 4, 5]
    assert len(edges) == len(nodes) - 1


def _grid(nrow: int, ncol: int, top_of):
    n = nrow * ncol
    top = np.array([top_of(i // ncol, i % ncol) for i in range(n)], dtype=float)
    adj: list[set[int]] = [set() for _ in range(n)]
    for r in range(nrow):
        for c in range(ncol):
            i = r * ncol + c
            if c + 1 < ncol:
                adj[i].add(i + 1)
                adj[i + 1].add(i)
            if r + 1 < nrow:
                adj[i].add(i + ncol)
                adj[i + ncol].add(i)
    receiver = np.array([i + 1 if (i % ncol) + 1 < ncol else -1 for i in range(n)])
    return top, adj, receiver, n


def test_prune_demotes_a_low_order_parallel_stub() -> None:
    # Main stem 0->1->2->3; a stub cell 4 flows into cell 2 and sits beside cell 1 (a
    # reach carrying more upstream). The stub is demoted, the main stem is untouched.
    downstream = {0: 1, 1: 2, 2: 3, 3: None, 4: 2}
    adj = [{1}, {0, 2, 4}, {1, 3, 4}, {2}, {1, 2}]
    kept = _prune_parallel_stub_cells(downstream, adj, max_stub_upstream=2)
    assert kept == {0, 1, 2, 3}  # cell 4 demoted, headwater 0 kept


def test_prune_keeps_a_stub_with_no_bigger_neighbour() -> None:
    # Same graph but cell 4 only touches its own downstream (cell 2): it heads a distinct
    # channel, not a redundant thread, so it stays SFR.
    downstream = {0: 1, 1: 2, 2: 3, 3: None, 4: 2}
    adj = [{1}, {0, 2}, {1, 3, 4}, {2}, {2}]
    kept = _prune_parallel_stub_cells(downstream, adj, max_stub_upstream=2)
    assert kept == {0, 1, 2, 3, 4}


def test_lone_single_cell_component_is_dropped() -> None:
    # Seed 2 traces a 3-cell channel to the lake at cell 5; seed 1 sits against the lake
    # at cell 0 and forms a lone one-cell "stream". With min_component_cells=2 the lone
    # reach is dropped (it becomes routed DRN), leaving only the real channel.
    top, adj, receiver = _chain(6)
    nodes, _ = _rectify([_Rec(0, (0, 2)), _Rec(1, (0, 1))], top, adj, receiver, lakes={0: 1, 5: 1})
    cells = sorted(nd["cellid"][1] for nd in nodes)
    assert cells == [2, 3, 4]  # lone reach at cell 1 dropped


def test_empty_records_return_no_channel() -> None:
    top, adj, receiver = _chain(4)
    nodes, edges = _rectify([_Rec(0, None)], top, adj, receiver, lakes={3: 1})
    assert nodes == [] or all(nd["cellid"] is None for nd in nodes)
    assert edges == []


def _faces(nrow: int, ncol: int) -> list[set[int]]:
    """Shared-face neighbors of a structured grid (no diagonal)."""
    faces: list[set[int]] = [set() for _ in range(nrow * ncol)]
    for r in range(nrow):
        for c in range(ncol):
            i = r * ncol + c
            if c + 1 < ncol:
                faces[i].add(i + 1)
                faces[i + 1].add(i)
            if r + 1 < nrow:
                faces[i].add(i + ncol)
                faces[i + ncol].add(i)
    return faces


def test_a_lone_staircase_channel_keeps_every_cell() -> None:
    # One staircase channel of 11 cells, no braid. On D8 a head cell neighbors its
    # downstream's downstream, which would read as a bigger parallel channel and
    # demote the head; on shared faces the whole channel stays.
    n = 6
    path = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (4, 5), (5, 5)]
    cells = [r * n + c for r, c in path]
    receiver = np.full(n * n, -1)
    for up, down in zip(cells[:-1], cells[1:], strict=True):
        receiver[up] = down
    top = np.full(n * n, 100.0)
    records = [_Rec(i, (0, c)) for i, c in enumerate(cells)]

    nodes, _ = _rectify(records, top, _faces(n, n), receiver)

    assert sorted(nd["cellid"][1] for nd in nodes) == sorted(cells)
