"""The libmf6 runner and its stop flag.

An api run solves through libmf6 and reads a success flag, or the listing when the flag
is None. A stop asked through the flag file is read at the end of each time step of
libmf6, never by an executable.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import NetworkError
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.workspace.workspace import resolve_bin_path
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6 import run as run_module
from hydromodpy.solver.modflow6.api import api_runner
from hydromodpy.solver.modflow6.api.api_runner import (
    Mf6ApiContext,
    Mf6ApiStep,
    _resolve_api_success,
    _simulation_reached_normal_termination,
    run_mf6_api,
)
from hydromodpy.solver.modflow6.builders.recharge import build_evt_stress_period_data
from hydromodpy.solver.modflow6.extractors.flow import _listing_path
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.run import _stopping
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common import binaries
from hydromodpy.solver.modflow_common.binaries import (
    ensure_platform_executable,
    ensure_solver_library,
    exe_filename,
    locate_solver_binary,
)
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_namefile_required(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_mf6_api(tmp_path, lambda ctx: None)


# modflowapi.run_simulation returns None on success and on divergence, so a None
# return is resolved from the listing. MF6 may upper-case the banner.
LISTINGS = [
    pytest.param(None, "  ...\n  NORMAL TERMINATION OF SIMULATION\n", True, id="converged"),
    pytest.param(None, "Normal termination of simulation.\n", True, id="lower case banner"),
    # A future modflowapi that reports a real flag is honored directly.
    pytest.param(False, None, False, id="flag false"),
    pytest.param(True, None, True, id="flag true"),
]


@pytest.mark.parametrize(("returned", "listing", "success"), LISTINGS)
def test_api_success_from_the_listing(returned, listing, success, tmp_path: Path) -> None:
    if listing is not None:
        (tmp_path / "mfsim.lst").write_text(listing, encoding="utf-8")

    assert _resolve_api_success(returned, tmp_path) is success


def test_api_failure_from_the_listing(tmp_path: Path) -> None:
    # The same run read twice, with no listing and then with a listing that failed.
    assert _simulation_reached_normal_termination(tmp_path) is False
    assert _resolve_api_success(None, tmp_path) is False

    (tmp_path / "mfsim.lst").write_text("  ...\n  SOLUTION DID NOT CONVERGE\n", encoding="utf-8")

    assert _simulation_reached_normal_termination(tmp_path) is False
    assert _resolve_api_success(None, tmp_path) is False


def test_api_runner_imports_without_modflowapi() -> None:
    # modflowapi is imported lazily inside run_mf6_api, never at module top.
    source = Path(api_runner.__file__).read_text(encoding="utf-8")
    module_top = source.split("def run_mf6_api", 1)[0]

    assert "import modflowapi" in source
    assert "import modflowapi" not in module_top
    assert "import xmipy" not in module_top


# A stop asked through the flag is read by libmf6 at the end of each time step, and
# never by an executable. StopRequested is a KeyboardInterrupt, so the libmf6 runner
# neither wraps it in a solver error nor stops on it, and finalizes the library.


def _stop_flag(tmp_path: Path, *, written: bool) -> Path:
    flag = tmp_path / ".hmp" / "stop.json"
    if written:
        flag.parent.mkdir()
        flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')
    return flag


STOP_AT_STEP = [
    pytest.param("initialize", True, False, id="the library starts"),
    pytest.param("timestep_start", True, False, id="a time step starts"),
    pytest.param("timestep_end", False, False, id="a time step ends, no flag"),
    pytest.param("timestep_end", True, True, id="a time step ends, a flag"),
    pytest.param("finalize", True, False, id="the library ends"),
]


@pytest.mark.parametrize(("step", "flag_written", "stops"), STOP_AT_STEP)
def test_stop_flag_read_at_step_end(step, flag_written, stops, tmp_path: Path) -> None:
    seen: list[Mf6ApiStep] = []
    composed = _stopping(
        lambda ctx: seen.append(ctx.step), _stop_flag(tmp_path, written=flag_written)
    )
    ctx = Mf6ApiContext(step=Mf6ApiStep[step], kper=0, kstp=0, totim=0.0, _sim=None)

    if stops:
        with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
            composed(ctx)
        assert seen == []
    else:
        composed(ctx)
        assert seen == [Mf6ApiStep[step]]


def test_stop_is_not_an_exception() -> None:
    assert issubclass(StopRequested, KeyboardInterrupt)
    assert not issubclass(StopRequested, Exception)


class _ApiRun:
    """Stands for ``run_mf6_api``: keeps the callback it receives."""

    def __init__(self) -> None:
        self.callback = None

    def __call__(self, workspace, callback, **kwargs) -> bool:
        del workspace, kwargs
        self.callback = callback
        return True


def _api_model(stop_flag: Path | None, **extra: object) -> SimpleNamespace:
    slot = None if stop_flag is None else SimpleNamespace(stop_flag=stop_flag)
    return SimpleNamespace(
        full_path="run", bin_path=None, _mf6_api_lib_path="libmf6.so", slot=slot, **extra
    )


def _step_end() -> Mf6ApiContext:
    return Mf6ApiContext(step=Mf6ApiStep.timestep_end, kper=0, kstp=0, totim=0.0, _sim=None)


def test_libmf6_run_reads_stop_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ApiRun()
    monkeypatch.setattr(api_runner, "run_mf6_api", api)
    developer: list[object] = []
    model = _api_model(
        _stop_flag(tmp_path, written=True), _mf6_api_callback=lambda ctx: developer.append(ctx)
    )

    assert run_module._run_via_api(model, verbose=False) is True

    with pytest.raises(StopRequested):
        api.callback(_step_end())
    assert developer == []


@pytest.mark.parametrize("flag_exists", [None, "absent"], ids=["no flag on the slot", "no file"])
def test_callback_runs_without_stop(
    flag_exists, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _ApiRun()
    monkeypatch.setattr(api_runner, "run_mf6_api", api)
    developer: list[object] = []
    flag = None if flag_exists is None else _stop_flag(tmp_path, written=False)
    model = _api_model(flag, _mf6_api_callback=lambda ctx: developer.append(ctx))
    run_module._run_via_api(model, verbose=False)
    ctx = _step_end()

    api.callback(ctx)

    assert developer == [ctx]


def test_executable_ignores_stop_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The child process writes its files until it ends: no exception is raised under it.
    solved: list[int] = []

    def simulate(sim, nper):
        solved.append(nper)
        return True, None

    monkeypatch.setattr(run_module, "run_simulation_with_progress", simulate)
    monkeypatch.setattr(run_module, "check_mf6_workspace_paths", lambda sim: None)
    monkeypatch.setattr(run_module, "warn_on_throttled_wells", lambda model: [])
    model = SimpleNamespace(
        inputs=make_model(time=ModelTime(grid=None, regime="steady", first_period_steady=True)),
        sim=SimpleNamespace(write_simulation=lambda **kwargs: None),
        nper=1,
        full_path=str(tmp_path),
        slot=SimpleNamespace(stop_flag=_stop_flag(tmp_path, written=True)),
    )

    done = run_module.run_processing(
        model, ModflowRunOptions(write_model=True, run_model=True, runner="subprocess")
    )

    assert done is True
    assert solved == [1]
    assert model.last_flow_solve_time_seconds is not None
