"""The streambed-top floor must not re-break the monotone-downhill order.

The per-cell cell-bottom floor lifts a reach's streambed top so its bed stays
inside the aquifer cell. A lake-enforced routing DEM can hand a DOWNSTREAM reach
a much higher cell bottom than its upstream neighbour, so flooring it up would
push it above the upstream reach and re-break the monotone order the single-Picard
routing (``maximum_picard_iterations=1``) relies on. ``build_sfr_package_args``
floors every reach first, then re-sweeps outlet->head lifting upstream reaches so
both the floor and monotonicity hold.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    SfrReachRecord,
    build_sfr_package_args,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

# Defaults the builder applies when the definition omits them.
_RBTH = 1.0  # streambed_thickness default
_RTP_ABOVE_BOTTOM_M = 0.1  # bed keep-out above the cell bottom
_MIN_SLOPE = 1e-4  # min_slope default


def _fake_model():
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={}),
        nper=1,
        perlen=np.asarray([86400.0], dtype=float),
        steady=(False,),
        time_grid=None,
        time_units="seconds",
        model_output_name="rtptest",
    )


def _two_cell_mesh(*, up_bottom: float, down_bottom: float) -> SolverMesh:
    # One row of two cells: cell2d 0 (upstream), cell2d 1 (downstream). The
    # downstream cell gets a HIGH bottom so its floor lifts rtp above the upstream.
    top = np.full((1, 2), 100.0)
    botm = np.array([[[up_bottom, down_bottom]]], dtype=float)  # (nlay=1, nrow=1, ncol=2)
    return SolverMesh.from_structured_arrays(nrow=1, ncol=2, top=top, botm=botm, dx=10.0, dy=10.0)


def _chain_network(*, rtp_up: float, rtp_down: float) -> ResolvedSfrNetwork:
    up = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_up,
        upstream=(),
        downstream=(1,),
        is_headwater=True,
    )
    down = SfrReachRecord(
        ifno=1,
        cellid=(0, 1),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_down,
        upstream=(0,),
        downstream=(),
    )
    return ResolvedSfrNetwork(network_id="net0", reaches=(up, down), definition={})


def _rtp_by_ifno(packagedata: list[list]) -> dict[int, float]:
    # PACKAGEDATA row layout: [ifno, cellid, rlen, rwid, rgrd, rtp, rbth, ...].
    return {int(row[0]): float(row[5]) for row in packagedata}


def test_floor_lifting_a_downstream_reach_restores_monotone_order() -> None:
    # Start monotone (up 60.0 > down 59.9). The downstream cell bottom (65.0)
    # floors rtp[down] up to 66.1, above the upstream reach: without the re-sweep
    # the package would ship an uphill step. The fix lifts the upstream reach back
    # above its floored downstream neighbour.
    mesh = _two_cell_mesh(up_bottom=40.0, down_bottom=65.0)
    network = _chain_network(rtp_up=60.0, rtp_down=59.9)
    args = build_sfr_package_args(_fake_model(), networks={"net0": network}, solver_mesh=mesh)

    # This network is downstream-increasing, so the single-Picard fast path is on:
    # that is exactly the routing the monotone order must hold for.
    assert args["maximum_picard_iterations"] == 1

    rtp = _rtp_by_ifno(args["packagedata"])
    floor_down = 65.0 + _RBTH + _RTP_ABOVE_BOTTOM_M
    # The downstream reach kept its floor (its bed stays inside the aquifer cell).
    assert rtp[1] == pytest.approx(floor_down)
    # The upstream reach was lifted above the floored downstream one: order restored.
    assert rtp[0] > rtp[1]
    drop = _MIN_SLOPE * 0.5 * (10.0 + 10.0)
    assert rtp[0] == pytest.approx(floor_down + drop)
    # Both beds still sit above their own cell bottom (the floor held).
    assert rtp[0] - _RBTH >= 40.0
    assert rtp[1] - _RBTH >= 65.0


def test_floor_that_does_not_break_order_leaves_the_upstream_reach_untouched() -> None:
    # When the floor does not fire (both cells sit far below the streambed), the
    # re-sweep is a no-op: the reaches keep their declared tops.
    mesh = _two_cell_mesh(up_bottom=40.0, down_bottom=40.0)
    network = _chain_network(rtp_up=60.0, rtp_down=59.9)
    args = build_sfr_package_args(_fake_model(), networks={"net0": network}, solver_mesh=mesh)

    rtp = _rtp_by_ifno(args["packagedata"])
    assert rtp[0] == pytest.approx(60.0)
    assert rtp[1] == pytest.approx(59.9)
    assert rtp[0] > rtp[1]
