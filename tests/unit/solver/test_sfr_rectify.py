"""Unit tests for the mesh-native SFR channel re-derivation (SFD trace)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.modflow6.builders.sfr_rectify import (
    _prune_parallel_stub_cells,
    _reach_components,
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
    top = np.array([100.0 - i for i in range(n)])
    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n - 1):
        adj[i].add(i + 1)
        adj[i + 1].add(i)
    cen = np.array([[i * 10.0, 0.0] for i in range(n)])
    return top, adj, cen


def _rectify(records, top, adj, cen, *, lakes=None, boundary=None, n=None):
    n = n if n is not None else top.shape[0]
    return rectify_reach_graph(
        records,
        mesh_top=top,
        cell_adjacency=adj,
        cell_centroids=cen,
        lake_cell_to_number=lakes or {},
        boundary_cells=boundary or set(),
        idomain=np.ones((1, n), dtype=int),
        nlay=1,
        location="test",
    )


def test_channel_traces_a_seed_to_the_lake() -> None:
    # A single delineated seed at cell 2 becomes an SFD channel 2 -> 3 -> 4, ending at
    # the lake cell 5 (the lake itself is the sink, not a reach).
    top, adj, cen = _chain(6)
    nodes, edges = _rectify([_Rec(0, (0, 2))], top, adj, cen, lakes={5: 1})
    cells = sorted(nd["cellid"][1] for nd in nodes)
    assert cells == [2, 3, 4]
    for a, b in edges:  # every edge crosses a shared face (no geometric gap)
        assert nodes[b]["cellid"][1] in adj[nodes[a]["cellid"][1]]
    assert any(nd["is_terminal_to_lake"] and nd["terminal_lake"] == 1 for nd in nodes)


def test_channel_extends_a_seed_to_the_boundary_when_no_lake() -> None:
    top, adj, cen = _chain(6)
    nodes, edges = _rectify([_Rec(0, (0, 2))], top, adj, cen, boundary={5})
    cells = sorted(nd["cellid"][1] for nd in nodes)
    # traces 2 -> 3 -> 4 -> 5; cell 5 is the boundary outlet (leaves the model).
    assert cells == [2, 3, 4, 5]
    assert not any(nd["is_terminal_to_lake"] for nd in nodes)


def test_channel_spills_over_a_residual_pit_to_reach_the_boundary() -> None:
    # cell 1 is a local minimum, so strict steepest descent dead-ends there. The spill
    # step must carry the reach over it and on to the boundary outlet at cell 4.
    _, adj, cen = _chain(5)
    top = np.array([100.0, 96.0, 99.0, 98.0, 97.0])  # cell 1 sits below both neighbours
    nodes, edges = _rectify([_Rec(0, (0, 0))], top, adj, cen, boundary={4})
    cells = sorted(nd["cellid"][1] for nd in nodes)
    assert cells == [0, 1, 2, 3, 4]  # did not dead-end in the pit at cell 1
    for a, b in edges:  # still face-continuous after spilling
        assert nodes[b]["cellid"][1] in adj[nodes[a]["cellid"][1]]


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
    cen = np.array([[(i % ncol) * 10.0, (i // ncol) * 10.0] for i in range(n)])
    return top, adj, cen, n


def test_channel_is_one_cell_wide_and_face_continuous() -> None:
    # Two adjacent parallel seeds on an east-descending slope both trace down the same
    # SFD, so the rebuilt channel is a single face-continuous line (no braided clump).
    top, adj, cen, n = _grid(2, 4, lambda r, c: 100.0 - 10.0 * c + 0.1 * r)
    seeds = [_Rec(0, (0, 1)), _Rec(1, (0, 5))]  # cells 1 (row0,col1) and 5 (row1,col1)
    nodes, edges = _rectify(seeds, top, adj, cen, lakes={3: 1, 7: 1}, n=n)
    # one downstream per cell (single-flow-direction) => no braiding
    down_count: dict[int, int] = {}
    for a, _b in edges:
        down_count[a] = down_count.get(a, 0) + 1
    assert all(v <= 1 for v in down_count.values())
    # every edge crosses a shared face => no geometric gap
    for a, b in edges:
        assert nodes[b]["cellid"][1] in adj[nodes[a]["cellid"][1]]


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


def test_reach_components_separates_disconnected_chains() -> None:
    comps = _reach_components({0: 1, 1: None, 5: 6, 6: None, 9: None})
    assert sorted(len(c) for c in comps) == [1, 2, 2]  # {0,1}, {5,6}, {9}


def test_lone_single_cell_component_is_dropped() -> None:
    # Seed 2 traces a 3-cell channel to the lake at cell 5; seed 1 sits against the lake
    # at cell 0 and forms a lone one-cell "stream". With min_component_cells=2 the lone
    # reach is dropped (it becomes routed DRN), leaving only the real channel.
    top, adj, cen = _chain(6)
    nodes, _ = _rectify([_Rec(0, (0, 2)), _Rec(1, (0, 1))], top, adj, cen, lakes={0: 1, 5: 1})
    cells = sorted(nd["cellid"][1] for nd in nodes)
    assert cells == [2, 3, 4]  # lone reach at cell 1 dropped


def test_empty_records_return_no_channel() -> None:
    top, adj, cen = _chain(4)
    nodes, edges = _rectify([_Rec(0, None)], top, adj, cen, lakes={3: 1})
    assert nodes == [] or all(nd["cellid"] is None for nd in nodes)
    assert edges == []
