"""Convergence and recovery checks for the MF6 API runner.

These tests drive a real libmf6 solve. They must not skip in silence: the
library is linked into ``$HMP_CACHE_HOME/bin`` by the test environment.

* A solve that fails to converge raises ``SolverDivergedError`` (E401),
  like the exe path, with the period, step and iteration count.
* A failed run (divergence or callback error) finalizes libmf6, so a second
  API run in the same process still works.
* ATS is refused under the API, since the modflowapi loop skips its retry.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("modflowapi")
pytest.importorskip("xmipy")

from hydromodpy.core.exceptions import SolverDivergedError, SolverError  # noqa: E402
from hydromodpy.solver.modflow6.api.api_runner import Mf6ApiContext, run_mf6_api  # noqa: E402
from hydromodpy.solver.modflow_common.binaries import (  # noqa: E402
    locate_solver_binary,
    managed_bin_dir,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_modflow6_lake_extractor_e2e import _build_single_lake_disv  # noqa: E402

_no_lib = locate_solver_binary(managed_bin_dir(), "libmf6") is None

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.skipif(_no_lib, reason="libmf6 shared library not in cache"),
]


def _noop(ctx: Mf6ApiContext) -> None:
    return None


def _write(ws: Path, *, diverge: bool = False, ats: bool = False) -> Path:
    sim = _build_single_lake_disv(ws, "mf6")
    sim.tdis.perioddata = [(86400.0, 3, 1.0)]
    if diverge:
        ims = sim.get_package("ims")
        ims.outer_maximum = 1
        ims.inner_maximum = 1
        ims.outer_dvclose = 1.0e-30
        ims.inner_dvclose = 1.0e-30
    if ats:
        sim.tdis.ats.initialize(maxats=1, perioddata=[(0, 86400.0 / 3, 1.0, 86400.0, 2.0, 5.0)])
    sim.write_simulation(silent=True)
    return ws


def test_library_is_present() -> None:
    # Guard against a silent skip of the whole module.
    assert not _no_lib


def test_api_divergence_raises_e401(tmp_path: Path) -> None:
    ws = _write(tmp_path / "div", diverge=True)
    with pytest.raises(SolverDivergedError) as info:
        run_mf6_api(ws, _noop)
    message = str(info.value)
    assert "HMPY.E401" in message
    assert "period 1" in message and "step 1" in message
    assert "iterations" in message


def test_api_runs_again_after_divergence(tmp_path: Path) -> None:
    with pytest.raises(SolverDivergedError):
        run_mf6_api(_write(tmp_path / "div", diverge=True), _noop)
    assert run_mf6_api(_write(tmp_path / "ok"), _noop) is True


def test_api_runs_again_after_callback_error(tmp_path: Path) -> None:
    def _boom(ctx: Mf6ApiContext) -> None:
        if ctx.step.name == "timestep_end":
            raise RuntimeError("boom")

    with pytest.raises(SolverError, match="boom"):
        run_mf6_api(_write(tmp_path / "boom"), _boom)
    assert run_mf6_api(_write(tmp_path / "ok"), _noop) is True


def test_api_refuses_ats(tmp_path: Path) -> None:
    ws = _write(tmp_path / "ats", ats=True)
    with pytest.raises(SolverError, match="ATS"):
        run_mf6_api(ws, _noop)
