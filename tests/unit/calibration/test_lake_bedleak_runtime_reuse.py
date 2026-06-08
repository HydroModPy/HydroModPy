"""Calibration refreshes the LAK bedleak in place, like npf/sto/drn.

``bedleak`` (lake-bed leakance, 1/T) is the under-dam leakage calibration knob.
Under runtime reuse the lake grid and connection geometry are static, so a new
``bedleak`` must only rewrite the ``bedleak`` column of the cached LAK
``connectiondata`` (per 0-based lake index ``ifno``) -- not rebuild the model.
The runtime-reuse signature, which captures the static structure, must stay
unchanged because lake geometry did not move. The override values are SI (1/s).
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.runtime_reuse import (
    refresh_reused_lak_bedleak,
    runtime_reuse_signature,
)


def _flopy_lak_with_two_lakes() -> flopy.mf6.ModflowGwflak:
    sim = flopy.mf6.MFSimulation(sim_name="m")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    top = np.full((3, 3), 10.0)
    botm = [np.full((3, 3), 5.0), np.full((3, 3), 0.0)]
    flopy.mf6.ModflowGwfdis(gwf, nlay=2, nrow=3, ncol=3, delr=1.0, delc=1.0, top=top, botm=botm)
    # lac0 (ifno 0) has two connections, lac1 (ifno 1) has one. bedleak starts 1.0.
    connectiondata = [
        [0, 0, (1, 0, 0), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0],
        [0, 1, (1, 0, 1), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0],
        [1, 0, (1, 0, 2), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0],
    ]
    packagedata = [[0, 9.0, 2, "lac0"], [1, 9.0, 1, "lac1"]]
    return flopy.mf6.ModflowGwflak(
        gwf,
        nlakes=2,
        noutlets=0,
        boundnames=True,
        packagedata=packagedata,
        connectiondata=connectiondata,
    )


def _model_with_lakes(*, bedleak_lac0: float, bedleak_lac1: float) -> SimpleNamespace:
    lak = _flopy_lak_with_two_lakes()
    flow = SimpleNamespace(
        active_bc=["reservoir"],
        sinks_sources={
            "lakes": {
                "lac0": {"bedleak": bedleak_lac0, "bedleak_unit": "1/s"},
                "lac1": {"bedleak": bedleak_lac1, "bedleak_unit": "1/s"},
            }
        },
    )
    return SimpleNamespace(lak=lak, flow=flow, flow_regime="transient")


def _bedleak_by_ifno(lak: flopy.mf6.ModflowGwflak) -> dict[int, float]:
    cd = lak.connectiondata.get_data()
    ifno = np.asarray(cd["ifno"], dtype=int)
    bedleak = np.asarray(cd["bedleak"], dtype=float)
    return {int(i): float(bedleak[ifno == i][0]) for i in np.unique(ifno)}


def test_bedleak_refresh_updates_connectiondata_from_flow() -> None:
    # model.flow already carries the new (calibrated) bedleak; the refresh must
    # rewrite the connectiondata bedleak column per lake.
    model = _model_with_lakes(bedleak_lac0=3.0, bedleak_lac1=0.5)
    # The cached LAK still has the old default 1.0 on every connection.
    assert _bedleak_by_ifno(model.lak) == pytest.approx({0: 1.0, 1: 1.0})

    touched = refresh_reused_lak_bedleak(model, flow_runtime_overrides={"reuse_solver_model": True})

    assert touched is True
    # lac0 (ifno 0, two connections) and lac1 (ifno 1) both pick up their values.
    assert _bedleak_by_ifno(model.lak) == pytest.approx({0: 3.0, 1: 0.5})


def test_bedleak_override_takes_precedence_per_lake() -> None:
    model = _model_with_lakes(bedleak_lac0=1.0, bedleak_lac1=1.0)
    # A per-lake override (SI 1/s) overrides only lac0; lac1 keeps the flow value.
    touched = refresh_reused_lak_bedleak(
        model,
        flow_runtime_overrides={"reuse_solver_model": True, "bedleak": {"lac0": 7.0}},
    )
    assert touched is True
    assert _bedleak_by_ifno(model.lak) == pytest.approx({0: 7.0, 1: 1.0})


def test_bedleak_refresh_leaves_runtime_signature_unchanged() -> None:
    model = _model_with_lakes(bedleak_lac0=1.0, bedleak_lac1=1.0)
    flow, domain = model.flow, object()
    options = SimpleNamespace(time_grid=object())
    mesh_planar, mesh_support = object(), object()

    def _signature() -> tuple:
        return runtime_reuse_signature(
            model,
            flow=flow,
            domain=domain,
            options=options,
            mesh_planar=mesh_planar,
            mesh_support=mesh_support,
        )

    before = _signature()
    refresh_reused_lak_bedleak(
        model,
        flow_runtime_overrides={"reuse_solver_model": True, "bedleak": 9.0},
    )
    # Lake geometry / grid is static, so the reuse signature must not move.
    assert _signature() == before
    # The scalar override hit every lake.
    assert _bedleak_by_ifno(model.lak) == pytest.approx({0: 9.0, 1: 9.0})


def test_bedleak_refresh_is_noop_without_a_lake() -> None:
    model = SimpleNamespace(lak=None, flow=SimpleNamespace(active_bc=[], sinks_sources={}))
    assert refresh_reused_lak_bedleak(model, flow_runtime_overrides=None) is False
