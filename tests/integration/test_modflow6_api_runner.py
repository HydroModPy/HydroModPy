"""End-to-end checks for the developer-facing MF6 API runner.

We reuse the proven single-lake DISV builder, bump it to a few timesteps so
the per-step read hook sees an evolving series, write the simulation, then:

* TEST 1 (READ): drive the workspace through libmf6 with a read-only
  callback that records the lake stage at each ``timestep_end``; assert the
  series is finite and matches the saved subprocess LAK stage within a LOOSE
  tolerance (libmf6 is 6.7.0 vs the exe 6.6.3 -- never bit-equivalence).

* TEST 2 (WRITE): run two fresh copies of the same workspace through libmf6;
  the forced run overrides the lake stage mid-run via the API write path and
  the final stage differs demonstrably from the un-overridden control run
  (two same-version libmf6 runs, so immune to cross-version drift).

The optional ``modflowapi`` / ``xmipy`` dependency and the libmf6 shared
library are gated with importorskip / skipif so the suite SKIPS (not fails)
when they are absent. Only the registered ``mf6`` and ``binary`` markers are
used (pytest.ini runs with ``--strict-markers``).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

modflowapi = pytest.importorskip("modflowapi")
pytest.importorskip("xmipy")

from hydromodpy.solver.modflow6.api.api_runner import (  # noqa: E402
    Mf6ApiContext,
    Mf6ApiStep,
    run_mf6_api,
)
from hydromodpy.solver.modflow_common.binaries import (  # noqa: E402
    ensure_solver_binary,
    locate_solver_binary,
    managed_bin_dir,
)

# Reuse the proven single-lake DISV builder from the extractor e2e test.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_modflow6_lake_extractor_e2e import _build_single_lake_disv  # noqa: E402

_no_lib = locate_solver_binary(managed_bin_dir(), "libmf6") is None

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.skipif(_no_lib, reason="libmf6 shared library not in cache"),
]

_NSTP = 5


def _build_multistep_lake(ws: Path, exe: str):
    """Build the single-lake DISV sim, bumped to several timesteps, and write it."""
    sim = _build_single_lake_disv(ws, exe)
    sim.tdis.perioddata = [(86400.0, _NSTP, 1.0)]
    sim.write_simulation(silent=True)
    return sim


def _saved_stage_series(ws: Path) -> list[float]:
    """Return the per-step lake stage written by a subprocess MF6 run."""
    import flopy

    stagefile = flopy.utils.HeadFile(str(ws / "lakd.lak.stage"), text="STAGE")
    return [float(stagefile.get_data(totim=t).ravel()[0]) for t in stagefile.get_times()]


@pytest.mark.fast
def test_api_runner_reads_lake_stage(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))

    # Baseline subprocess run (6.6.3 exe) in its own copy.
    base = tmp_path / "base"
    base.mkdir()
    _build_multistep_lake(base, exe)

    sub = tmp_path / "sub"
    shutil.copytree(base, sub)
    import flopy

    sim_sub = flopy.mf6.MFSimulation.load(sim_ws=str(sub), exe_name=exe)
    ok, _ = sim_sub.run_simulation(silent=True)
    assert ok, "baseline subprocess run did not converge"
    expected_stage = _saved_stage_series(sub)
    assert len(expected_stage) == _NSTP

    # API run (libmf6 6.7.0) in a fresh copy with a read-only callback.
    api_ws = tmp_path / "api"
    shutil.copytree(base, api_ws)
    api_stage: list[float] = []

    def callback(ctx: Mf6ApiContext) -> None:
        if ctx.step is Mf6ApiStep.timestep_end:
            value = float(ctx.read_lake_stage()[0])
            assert np.isfinite(value)
            api_stage.append(value)

    success = run_mf6_api(api_ws, callback)
    assert success

    assert len(api_stage) == _NSTP
    assert all(np.isfinite(api_stage))
    # LOOSE tolerance: cross-version drift, NOT bit-equivalence.
    assert np.allclose(api_stage, expected_stage, rtol=1e-2, atol=0.05)


_FORCED_CHD_HEAD = 96.0


def _final_stage(ws: Path, callback) -> float:
    """Run ``ws`` through libmf6 and return the last solved lake stage."""
    series: list[float] = []

    def wrapped(ctx: Mf6ApiContext) -> None:
        callback(ctx)
        if ctx.step is Mf6ApiStep.timestep_end:
            series.append(float(ctx.read_lake_stage()[0]))

    assert run_mf6_api(ws, wrapped)
    assert series
    return series[-1]


@pytest.mark.fast
def test_api_runner_write_changes_solution(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    base = tmp_path / "base"
    base.mkdir()
    _build_multistep_lake(base, exe)

    # Control run: read-only callback, capture the final solved stage. The lake
    # drains to the low perimeter boundary, settling near the bed (~90 m).
    ctrl_ws = tmp_path / "ctrl"
    shutil.copytree(base, ctrl_ws)
    s_ctrl = _final_stage(ctrl_ws, lambda ctx: None)
    assert np.isfinite(s_ctrl)

    # Forced run: override the CHD perimeter head (the downgradient boundary the
    # lake leaks toward) before each solve. This forcing write must propagate
    # through the solver and lift the solved lake stage. We mutate the live
    # stress-period BOUND head via the raw modflowapi package handle exposed by
    # ctx.model().
    forced_ws = tmp_path / "forced"
    shutil.copytree(base, forced_ws)

    def forced_callback(ctx: Mf6ApiContext) -> None:
        if ctx.step is Mf6ApiStep.timestep_start:
            chd = ctx.model().get_package("chd_0")
            spd = chd.stress_period_data
            values = spd.values
            values["head"][:] = _FORCED_CHD_HEAD
            spd.values = values

    s_forced = _final_stage(forced_ws, forced_callback)

    # The write demonstrably changed the solution (same libmf6 version on both
    # sides, so this is immune to cross-version drift): raising the boundary
    # head pulls the solved lake stage up to that head.
    assert not np.isclose(s_forced, s_ctrl, rtol=0, atol=1e-3)
    assert abs(s_forced - s_ctrl) > 1.0
    assert 90.0 <= s_forced <= 100.0
    assert s_forced == pytest.approx(_FORCED_CHD_HEAD, abs=0.5)


@pytest.mark.fast
def test_api_runner_write_lake_stage_round_trips(tmp_path: Path) -> None:
    # The typed write_lake_stage accessor must mutate live solver state: after
    # writing the input stage forcing, reading it back returns the new value.
    exe = str(ensure_solver_binary("mf6"))
    ws = tmp_path / "ws"
    ws.mkdir()
    _build_multistep_lake(ws, exe)

    seen: list[float] = []

    def callback(ctx: Mf6ApiContext) -> None:
        if ctx.step is Mf6ApiStep.timestep_start and ctx.kstp == 0:
            ctx.write_lake_stage([93.5])
            seen.append(float(ctx.read_lake_stage(var="stage")[0]))

    assert run_mf6_api(ws, callback)
    assert seen == [pytest.approx(93.5)]
