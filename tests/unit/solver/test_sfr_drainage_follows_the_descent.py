"""The hillslope drainage follows the receivers of the descent D.

D is a filled copy of the model top on the descended graph, handed in as a
receiver array. The routing stops at the first reach or lake cell, only routes
the basin, and keeps the DRN provider ids aligned on the static DRN rows. On a
quad mesh a diagonal step between two reach cells ends on the lower one.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    SfrReachRecord,
    build_drainage_mover_records,
)

_LOGGER = "hydromodpy.solver.modflow6.builders._sfr_drainage"


def _reach(ifno: int, cell2d: int) -> SfrReachRecord:
    return SfrReachRecord(
        ifno=ifno,
        cellid=(0, cell2d),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=97.0,
        upstream=(),
        downstream=(),
    )


def _network(*reach_cells: int, route_drainage: bool = True) -> dict[str, ResolvedSfrNetwork]:
    reaches = tuple(_reach(i, c) for i, c in enumerate(reach_cells))
    return {"net0": ResolvedSfrNetwork("net0", reaches, {"route_drainage": route_drainage})}


def _chain(n: int) -> np.ndarray:
    """Receivers of the chain 0 -> 1 -> ... -> n-1, the last one leaving the model."""
    receiver = np.arange(1, n + 1)
    receiver[-1] = -1
    return receiver


def _static_drn(cells: list[int]) -> dict[int, list[list[float]]]:
    return {0: [[0, c, 100.0, 0.05] for c in cells]}


def _everywhere(n: int) -> np.ndarray:
    return np.ones(n, dtype=bool)


def _route(networks, *, drn_spd, receiver, basin_cell_mask, lake_cells_by_number=None):
    """Route with the faces of the receiver links: no step is diagonal."""
    receiver = np.asarray(receiver)
    faces: list[set[int]] = [set() for _ in range(receiver.size)]
    for cell, down in enumerate(receiver.tolist()):
        if down >= 0:
            faces[cell].add(down)
            faces[down].add(cell)
    return build_drainage_mover_records(
        networks,
        drn_spd=drn_spd,
        receiver=receiver,
        basin_cell_mask=basin_cell_mask,
        face_adjacency=faces,
        mesh_top=np.zeros(receiver.size),
        lake_cells_by_number=lake_cells_by_number,
    )


def test_a_hillslope_chain_reaches_its_reach() -> None:
    records = _route(
        _network(3),
        drn_spd=_static_drn([0, 1, 2]),
        receiver=_chain(5),
        basin_cell_mask=_everywhere(5),
    )

    assert [(r.provider_id, r.receiver, r.receiver_id) for r in records] == [
        (0, "SFR", 0),
        (1, "SFR", 0),
        (2, "SFR", 0),
    ]
    assert all(r.provider == "DRN" and r.mvrtype == "FACTOR" and r.value == 1.0 for r in records)


def test_a_chain_meeting_a_lake_before_a_reach_routes_to_the_lake() -> None:
    # Lake at cell 2, reach at cell 4: the lake is met first and is a sink.
    records = _route(
        _network(4),
        drn_spd=_static_drn([0, 1, 3]),
        receiver=_chain(6),
        basin_cell_mask=_everywhere(6),
        lake_cells_by_number={7: [2]},
    )

    assert [(r.provider_id, r.receiver, r.receiver_id) for r in records] == [
        (0, "LAK", 7),
        (1, "LAK", 7),
        (2, "SFR", 0),
    ]


def test_every_lake_is_a_sink_not_only_the_outflow_one() -> None:
    network = {
        "net0": ResolvedSfrNetwork("net0", (), {"route_drainage": True, "outflow_to_lake": 1})
    }

    records = _route(
        network,
        drn_spd=_static_drn([2]),
        receiver=_chain(5),
        basin_cell_mask=_everywhere(5),
        lake_cells_by_number={0: [0], 1: [4]},
    )

    assert [(r.receiver, r.receiver_id) for r in records] == [("LAK", 1)]


def test_a_basin_cell_whose_chain_leaves_the_model_first_stays_plain() -> None:
    # Cell 1 drains off the domain (-1) before the chain could meet the reach at 2.
    receiver = np.array([1, -1, -1])

    records = _route(
        _network(2),
        drn_spd=_static_drn([0, 1]),
        receiver=receiver,
        basin_cell_mask=_everywhere(3),
    )

    assert records == []


def test_a_cell_outside_the_basin_is_not_routed_even_if_its_chain_reaches_a_reach() -> None:
    basin = np.array([True, False, True, True, True])

    records = _route(
        _network(4),
        drn_spd=_static_drn([0, 1, 2]),
        receiver=_chain(5),
        basin_cell_mask=basin,
    )

    assert {r.provider_id for r in records} == {0, 2}


def test_the_provider_id_is_the_row_index_of_the_static_drn() -> None:
    # Rows are not sorted by cell: the id must follow the row, not the cell number.
    records = _route(
        _network(4),
        drn_spd=_static_drn([3, 0, 2]),
        receiver=_chain(5),
        basin_cell_mask=_everywhere(5),
    )

    assert [r.provider_id for r in records] == [0, 1, 2]


def test_skipped_cells_keep_their_row_index_so_the_others_stay_aligned() -> None:
    basin = np.array([True, True, False, True, True])

    records = _route(
        _network(4),
        drn_spd=_static_drn([0, 2, 3]),
        receiver=_chain(5),
        basin_cell_mask=basin,
    )

    assert [r.provider_id for r in records] == [0, 2]


def test_a_multi_period_drn_is_refused() -> None:
    rows = [[0, 0, 100.0, 0.05]]

    with pytest.raises(ValueError, match="single-period"):
        _route(
            _network(2),
            drn_spd={0: rows, 1: rows},
            receiver=_chain(3),
            basin_cell_mask=_everywhere(3),
        )


def test_nothing_is_routed_without_the_opt_in() -> None:
    records = _route(
        _network(2, route_drainage=False),
        drn_spd=_static_drn([0]),
        receiver=_chain(3),
        basin_cell_mask=_everywhere(3),
    )

    assert records == []


def test_a_cycle_in_the_descent_is_reported_not_looped_on() -> None:
    receiver = np.array([1, 0, -1])

    with pytest.raises(ValueError, match="cycles at cell"):
        _route(
            _network(2),
            drn_spd=_static_drn([0]),
            receiver=receiver,
            basin_cell_mask=_everywhere(3),
        )


def test_the_coverage_line_reports_routed_reach_lake_and_plain_counts(caplog) -> None:
    # Cells 0..5 on a chain, lake at 2, reach at 4, plus an isolated cell 6 that
    # leaves the model and a cell 7 outside the basin (not counted).
    receiver = np.array([1, 2, 3, 4, 5, -1, -1, 4])
    basin = np.array([True] * 7 + [False])

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _route(
            _network(4),
            drn_spd=_static_drn([0, 1, 3, 6, 7]),
            receiver=receiver,
            basin_cell_mask=basin,
            lake_cells_by_number={0: [2]},
        )

    lines = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
    assert lines == [
        "Drainage routing on the descent: 3 of 4 basin DRN cells routed (75.0 %), "
        "1 to a reach, 2 to a lake, 1 kept plain; 0 of 1 reach(es) of the routed "
        "network(s) receive no drainage."
    ]


def test_the_coverage_line_counts_the_reaches_that_receive_no_drainage(caplog) -> None:
    # Reach 0 at cell 2 is fed by cells 0 and 1; reach 1 at cell 4 is fed by none.
    receiver = np.array([1, 2, 3, 4, -1])

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _route(
            _network(2, 3),
            drn_spd=_static_drn([0, 1]),
            receiver=receiver,
            basin_cell_mask=_everywhere(5),
        )

    assert "1 of 2 reach(es) of the routed network(s) receive no drainage" in caplog.text


def _quad_faces(nrow: int, ncol: int) -> list[set[int]]:
    faces: list[set[int]] = [set() for _ in range(nrow * ncol)]
    for row in range(nrow):
        for col in range(ncol):
            cell = row * ncol + col
            if col + 1 < ncol:
                faces[cell].add(cell + 1)
                faces[cell + 1].add(cell)
            if row + 1 < nrow:
                faces[cell].add(cell + ncol)
                faces[cell + ncol].add(cell)
    return faces


def test_a_diagonal_step_across_a_reach_line_ends_on_the_lower_flank() -> None:
    # 3 x 3 quads. The reach line runs on the anti-diagonal cells 2 -> 4 -> 6,
    # touching only at corners. Cell 1 steps diagonally to cell 5 (receiver of D),
    # between the reach cells 2 and 4; then 5 drains off the model. The walk must
    # end on the lower flank (cell 4, top 1.0) instead of crossing the line.
    networks = _network(2, 4, 6)
    receiver = np.full(9, -1)
    receiver[1] = 5
    top = np.array([5.0, 4.0, 3.0, 4.0, 1.0, 3.0, 2.0, 2.0, 2.0])

    records = build_drainage_mover_records(
        networks,
        drn_spd=_static_drn([1]),
        receiver=receiver,
        basin_cell_mask=_everywhere(9),
        face_adjacency=_quad_faces(3, 3),
        mesh_top=top,
    )

    assert [(r.receiver, r.receiver_id) for r in records] == [("SFR", 1)]


def test_a_diagonal_step_beside_a_single_reach_cell_is_not_stopped() -> None:
    # Same step, but only cell 2 is a reach: nothing is crossed, the chain goes on.
    networks = _network(2)
    receiver = np.full(9, -1)
    receiver[1] = 5

    records = build_drainage_mover_records(
        networks,
        drn_spd=_static_drn([1]),
        receiver=receiver,
        basin_cell_mask=_everywhere(9),
        face_adjacency=_quad_faces(3, 3),
        mesh_top=np.zeros(9),
    )

    assert records == []
