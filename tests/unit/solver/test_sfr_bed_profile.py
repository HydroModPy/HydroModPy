"""The streambed profile must hold the cell band AND the downstream order.

Every check the SFR path had before this verified that water ROUTES correctly.
None compared a reach bed to the top of its own cell, so a bed could sit tens of
metres under the land surface or perched above it with a perfect topology.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders._sfr_bed import (
    RTP_ABOVE_BOTTOM_M,
    solve_reach_bed_profile,
)

_RBTH = 0.1
_MIN_SLOPE = 1e-4


@dataclasses.dataclass(frozen=True)
class _Reach:
    ifno: int
    cellid: tuple[int, int] | None
    rlen: float
    rtp: float
    upstream: tuple[int, ...]
    downstream: tuple[int, ...]


def _chain(rtps, *, cells=None):
    """A headwater-to-outlet chain, ifno increasing downstream."""
    n = len(rtps)
    cells = cells if cells is not None else [(0, i) for i in range(n)]
    return [
        _Reach(
            ifno=i,
            cellid=cells[i],
            rlen=25.0,
            rtp=float(rtps[i]),
            upstream=() if i == 0 else (i - 1,),
            downstream=() if i == n - 1 else (i + 1,),
        )
        for i in range(n)
    ]


def _solve(reaches, *, top, botm, incision, sag=5.0):
    return solve_reach_bed_profile(
        reaches,
        top=np.asarray(top, dtype=float),
        botm=np.asarray(botm, dtype=float),
        rbth=_RBTH,
        min_slope=_MIN_SLOPE,
        bed_incision=incision,
        max_bed_sag=sag,
        location="flow.sinks_sources.sfr.t",
    )


def test_a_perched_bed_is_pulled_back_under_the_land_surface():
    # The Nancon failure: reach 1 came out of the delineation 0.59 m ABOVE its
    # own cell top, toggled connected/disconnected, and stalled the solver.
    top = [140.0, 139.9, 139.0]
    botm = [[110.0, 109.9, 109.0]]
    reaches = _chain([139.4, 140.49, 138.4])
    solved = _solve(reaches, top=top, botm=botm, incision=0.5)
    for i, cell_top in enumerate(top):
        assert solved[i] <= cell_top - 0.5 + 1e-9, f"reach {i} still perched"


def test_the_profile_stays_monotone_downstream():
    top = [140.0, 139.9, 139.0]
    botm = [[110.0, 109.9, 109.0]]
    solved = _solve(_chain([139.4, 140.49, 138.4]), top=top, botm=botm, incision=0.5)
    for up, down in ((0, 1), (1, 2)):
        assert solved[up] > solved[down], f"{up} -> {down} steps up"


def test_the_bed_never_sinks_into_the_cell_bottom():
    # The delineation put both beds BELOW the aquifer floor; the floor wins over
    # the delineated elevation, and MF6 would refuse a bed under its own cell.
    top = [140.0, 139.0]
    botm = [[130.0, 129.0]]
    solved = _solve(_chain([125.0, 124.0]), top=top, botm=botm, incision=0.5, sag=50.0)
    for i in range(2):
        assert solved[i] >= botm[0][i] + _RBTH + RTP_ABOVE_BOTTOM_M - 1e-9
    assert solved[0] > solved[1], "the floor must not break the downstream order"


def test_an_impossible_band_is_refused_by_name():
    # bed_incision drives the ceiling under the floor: 30 m of incision in a 5 m
    # aquifer cannot hold a bed, and the build must say so instead of writing it.
    top = [140.0, 139.0]
    botm = [[135.0, 134.0]]
    with pytest.raises(ValueError, match="cannot hold a streambed"):
        _solve(_chain([139.5, 138.5]), top=top, botm=botm, incision=30.0)


def test_the_cell_top_of_a_deeper_reach_is_the_layer_above_its_bottom():
    # SolverMesh.top is (n_cells,), the top of LAYER 0 only, while a reach can
    # land on a deeper first-active layer. Reading top[cell] there would place
    # the ceiling one whole layer too high.
    top = [140.0, 139.0]
    botm = [[120.0, 119.0], [100.0, 99.0]]
    reaches = _chain([119.0, 118.0], cells=[(1, 0), (1, 1)])
    solved = _solve(reaches, top=top, botm=botm, incision=0.5)
    assert solved[0] <= 120.0 - 0.5 + 1e-9
    assert solved[1] <= 119.0 - 0.5 + 1e-9


def test_without_bed_incision_the_historical_behaviour_is_unchanged():
    # Default None: floor on the cell bottom, no ceiling, so a delineated bed
    # well under the surface is kept as-is. Existing runs must not move.
    top = [140.0, 139.0]
    botm = [[110.0, 109.0]]
    solved = _solve(_chain([115.0, 114.0]), top=top, botm=botm, incision=None)
    assert solved[0] == pytest.approx(115.0)
    assert solved[1] == pytest.approx(114.0)


def test_a_confluence_keeps_both_branches_above_the_shared_reach():
    outlet = _Reach(2, (0, 2), 25.0, 130.0, upstream=(0, 1), downstream=())
    branches = [
        _Reach(0, (0, 0), 25.0, 131.0, upstream=(), downstream=(2,)),
        _Reach(1, (0, 1), 25.0, 129.5, upstream=(), downstream=(2,)),
    ]
    solved = _solve(
        [*branches, outlet],
        top=[135.0, 134.0, 133.0],
        botm=[[105.0, 104.0, 103.0]],
        incision=0.5,
    )
    assert solved[0] > solved[2]
    assert solved[1] > solved[2]


def test_a_climbing_trace_keeps_the_cell_and_reports_the_step_up(caplog):
    # The Nancon refusal: the traced channel climbs ~28 m, so the downhill order
    # would push a reach above its own cell top. The cell wins, and the build
    # says so instead of either refusing or writing a bed outside its cell.
    top = [140.0, 175.0]  # the DOWNSTREAM cell sits 35 m higher
    botm = [[110.0, 145.0]]
    with caplog.at_level("WARNING"):
        solved = _solve(_chain([139.5, 174.5]), top=top, botm=botm, incision=0.5)
    assert solved[0] <= top[0] - 0.5 + 1e-9
    assert solved[1] <= top[1] - 0.5 + 1e-9
    assert solved[1] > solved[0], "the climb is kept, not absorbed into a wrong bed"
    assert any("could not hold the downhill order" in r.message for r in caplog.records)


def test_a_reach_is_never_left_above_the_ground_of_its_own_cell() -> None:
    # A reach top is delineated once per link, at its outlet, then rebuilt along
    # the link gradient. A concave profile hands a mid-link reach an elevation
    # above its own ground, which the stream burn used to absorb. The cap holds
    # even when the user declared no incision.
    reaches = _chain([100.0, 95.0, 90.0])
    top = [100.0, 88.0, 90.0]
    botm = [[70.0, 60.0, 60.0]]
    solved = _solve(reaches, top=top, botm=botm, incision=None)
    assert solved[1] <= 88.0
    assert all(solved[i] <= top[i] for i in range(3))


def test_the_log_says_where_each_bed_landed_inside_its_cell(caplog) -> None:
    # A bed on the ceiling is one the delineation put above its own ground, a bed
    # on the floor is one the downhill order dragged down. Both are trace-quality
    # signals, and neither is readable from the move count alone.
    reaches = _chain([100.0, 95.0, 90.0])
    with caplog.at_level("INFO"):
        _solve(reaches, top=[100.0, 88.0, 90.0], botm=[[70.0, 60.0, 60.0]], incision=0.5)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "sit on the ceiling" in text
    assert "on the floor" in text
