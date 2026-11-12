"""The streambed profile must hold the cell band AND the downstream order.

Every check the SFR path had before this verified that water ROUTES correctly.
None compared a reach bed to the top of its own cell, so a bed could sit tens of
meters under the land surface or perched above it with a perfect topology.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders._sfr_bed import solve_reach_bed_profile

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


def test_an_impossible_band_is_refused_by_name():
    # bed_incision drives the ceiling under the floor: 30 m of incision in a 5 m
    # aquifer cannot hold a bed, and the build must say so instead of writing it.
    top = [140.0, 139.0]
    botm = [[135.0, 134.0]]
    with pytest.raises(ValueError, match="cannot hold a streambed"):
        _solve(_chain([139.5, 138.5]), top=top, botm=botm, incision=30.0)


def test_without_bed_incision_the_historical_behaviour_is_unchanged():
    # Default None: floor on the cell bottom, no ceiling, so a delineated bed
    # well under the surface is kept as-is. Existing runs must not move.
    top = [140.0, 139.0]
    botm = [[110.0, 109.0]]
    solved = _solve(_chain([115.0, 114.0]), top=top, botm=botm, incision=None)
    assert solved[0] == pytest.approx(115.0)
    assert solved[1] == pytest.approx(114.0)


def test_one_climbing_step_counts_one_relaxed_reach(caplog) -> None:
    # Both passes meet the same step, once from each side. Only the downstream
    # reach is left above the downhill order, so the log counts one reach.
    top = [140.0, 139.0, 175.0]
    botm = [[110.0, 109.0, 145.0]]
    with caplog.at_level("WARNING"):
        _solve(_chain([139.5, 138.5, 174.5]), top=top, botm=botm, incision=0.5)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "1/3 reach(es) could not hold the downhill order" in text
    assert "at reach 2" in text


def test_the_warning_says_how_far_the_worst_cell_stands_above_its_traced_bed(caplog) -> None:
    # The worst reach has a traced bed at 150 m under a cell whose ceiling is at
    # 174.5 m: the log names that gap, since it tells a coarse cell on a valley
    # side from a trace that really climbs.
    top = [140.0, 175.0]
    botm = [[110.0, 145.0]]
    with caplog.at_level("WARNING"):
        _solve(_chain([139.5, 150.0]), top=top, botm=botm, incision=0.5)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "whose cell ceiling stands 24.50 m above its traced bed" in text
