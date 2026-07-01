"""Shared (calibration) recharge is byte-identical to the per-trial recharge.

The calibration fast path writes the trial-invariant recharge ``.bin`` once to a
shared dir and references them, instead of re-writing thousands of files per
trial. This must be OUTPUT-EQUIVALENT: the shared binary a trial references has
to match, byte for byte, what FloPy writes on the normal per-model path, and MF6
has to read it. This test builds a DISV model with a >64-period recharge stack
both ways and checks exactly that.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.recharge import externalize_recharge_spd
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

_NPER = 70  # above RECHARGE_BINARY_MIN_PERIODS so both paths externalize
_NCPL = 25


def _spd() -> dict[int, np.ndarray]:
    rng = np.random.default_rng(0)
    return {k: rng.uniform(1e-4, 1e-3, size=_NCPL).astype(np.float64) for k in range(_NPER)}


def _build(ws: Path, recharge, exe: str):
    import flopy

    ws.mkdir(parents=True, exist_ok=True)
    sim = flopy.mf6.MFSimulation(sim_name="m", sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=_NPER, perioddata=[(1.0, 1, 1.0)] * _NPER)
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m", save_flows=True)
    nrow = ncol = 5
    vertices = []
    vid = {}
    v = 0
    for j in range(nrow + 1):
        for i in range(ncol + 1):
            vid[(i, j)] = v
            vertices.append([v, float(i), float(nrow - j)])
            v += 1
    cell2d = []
    cid = 0
    for r in range(nrow):
        for c in range(ncol):
            nodes = [vid[(c, r)], vid[(c + 1, r)], vid[(c + 1, r + 1)], vid[(c, r + 1)]]
            cell2d.append([cid, c + 0.5, nrow - r - 0.5, 4, *nodes])
            cid += 1
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=_NCPL,
        nvert=len(vertices),
        top=10.0,
        botm=0.0,
        vertices=vertices,
        cell2d=cell2d,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0), 5.0]]})
    flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge, pname="RCHA")
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="m.hds", saverecord=[("HEAD", "ALL")])
    sim.write_simulation(silent=True)
    return sim


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_shared_recharge_matches_per_trial_and_runs(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    spd = _spd()

    # Per-model (default) path: FloPy writes m.rcha.{k}.bin in the model workspace.
    ws_a = tmp_path / "per_trial"
    _build(ws_a, externalize_recharge_spd(spd, basename="m"), exe)

    # Shared (calibration) path: the .bin are written once to shared_dir, and the
    # model only references them (no "data").
    shared = tmp_path / "_shared_recharge"
    ws_b = tmp_path / "shared"
    spec_b = externalize_recharge_spd(spd, basename="m", shared_dir=str(shared))
    assert all("data" not in rec for rec in spec_b.values()), (
        "shared path must reference, not embed"
    )
    _build(ws_b, spec_b, exe)

    # The array DATA (after the 52-byte header) is byte-identical to FloPy's
    # per-trial file; the header carries only metadata (kper / totim / text) that
    # MF6 ignores when reading an input array.
    _HEADER = 52
    for kper in range(_NPER):
        per_trial = (ws_a / f"m.rcha.{kper}.bin").read_bytes()
        shared_bin = next(shared.glob(f"rcha_*.{kper}.bin")).read_bytes()
        assert shared_bin[_HEADER:] == per_trial[_HEADER:], f"period {kper} recharge data differs"

    # Output equivalence: both models solve to the same heads, so referencing the
    # shared recharge is indistinguishable from writing it per trial.
    import flopy

    ok_a, _ = flopy.mf6.MFSimulation.load(sim_ws=str(ws_a), exe_name=exe).run_simulation(silent=True)
    ok_b, _ = flopy.mf6.MFSimulation.load(sim_ws=str(ws_b), exe_name=exe).run_simulation(silent=True)
    assert ok_a and ok_b, "a recharge model did not converge"
    head_a = flopy.utils.HeadFile(str(ws_a / "m.hds")).get_alldata()
    head_b = flopy.utils.HeadFile(str(ws_b / "m.hds")).get_alldata()
    assert np.allclose(head_a, head_b, atol=1e-9), "shared vs per-trial recharge give different heads"


def test_short_recharge_stays_internal() -> None:
    # Below the binary threshold the stack stays in-memory on both paths.
    small = {k: np.full(_NCPL, 1e-4) for k in range(10)}
    assert externalize_recharge_spd(small, basename="m") is small
    assert externalize_recharge_spd(small, basename="m", shared_dir="/tmp/x") is small


def test_shared_recharge_dir_detects_a_trial_anywhere_in_the_path() -> None:
    from types import SimpleNamespace

    from hydromodpy.solver.modflow6.build import _shared_recharge_dir

    # The trial folder can be the leaf, or a parent of a truncated mf6 model name;
    # either way the shared dir sits beside the trial folder.
    nested = SimpleNamespace(full_path="/p/.solver_scratch/run_trial000016/cheze_cal_377f4b")
    leaf = SimpleNamespace(full_path="/p/.solver_scratch/run_trial000001")
    single = SimpleNamespace(full_path="/p/.solver_scratch/plain_run")
    assert _shared_recharge_dir(nested) == "/p/.solver_scratch/_shared_recharge"
    assert _shared_recharge_dir(leaf) == "/p/.solver_scratch/_shared_recharge"
    assert _shared_recharge_dir(single) is None
    assert _shared_recharge_dir(SimpleNamespace(full_path=None)) is None
