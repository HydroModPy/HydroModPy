from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import NetworkError
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6.builders.recharge import build_evt_stress_period_data
from hydromodpy.solver.modflow6.extractors.flow import _listing_path
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common import binaries, ensure_platform_executable
from hydromodpy.solver.modflow_common.binaries import (
    ensure_solver_library,
    exe_filename,
    locate_solver_binary,
    managed_bin_dir,
)
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_ensure_platform_executable_returns_missing_path_unchanged(tmp_path: Path) -> None:
    missing = tmp_path / "missing_solver"

    assert ensure_platform_executable(missing) == missing


def test_ensure_platform_executable_adds_user_execute_bit_on_posix(tmp_path: Path) -> None:
    solver = tmp_path / "solver_binary"
    solver.write_text("echo solver\n", encoding="utf-8")
    solver.chmod(0o644)

    result = ensure_platform_executable(solver)

    assert result == solver
    mode = solver.stat().st_mode
    if os.name != "nt":
        assert mode & stat.S_IXUSR


# Unit checks for the libmf6 shared-library resolver and runner gating.
#
# These do not need a binary; they cover the per-OS filename mapping, the
# resolver's success/absent paths, and the lazy optional-dependency guard.


def test_libmf6_exe_filename_per_os() -> None:
    name = exe_filename("libmf6")
    if sys.platform.startswith("win"):
        assert name == "libmf6.dll"
    elif sys.platform == "darwin":
        assert name == "libmf6.dylib"
    else:
        assert name == "libmf6.so"


def test_ensure_solver_library_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_solver_library("libmf6", bin_path=tmp_path)


@pytest.mark.skipif(
    locate_solver_binary(managed_bin_dir(), "libmf6") is None,
    reason="libmf6 shared library not in cache",
)
def test_ensure_solver_library_returns_absolute_existing() -> None:
    resolved = ensure_solver_library("libmf6")
    assert resolved.is_absolute()
    assert resolved.is_file()


def test_run_mf6_api_missing_namefile_raises(tmp_path: Path) -> None:
    from hydromodpy.solver.modflow6.api.api_runner import run_mf6_api

    with pytest.raises(FileNotFoundError):
        run_mf6_api(tmp_path, lambda ctx: None)


def test_normal_termination_detection_keys_off_the_listing(tmp_path: Path) -> None:
    from hydromodpy.solver.modflow6.api.api_runner import _simulation_reached_normal_termination

    # No listing -> failure.
    assert _simulation_reached_normal_termination(tmp_path) is False
    # Listing without the banner (a non-converged run) -> failure.
    (tmp_path / "mfsim.lst").write_text("  ...\n  SOLUTION DID NOT CONVERGE\n", encoding="utf-8")
    assert _simulation_reached_normal_termination(tmp_path) is False
    # Listing with the banner (a converged run) -> success. MF6 may upper-case it,
    # so the check is case-insensitive.
    (tmp_path / "mfsim.lst").write_text(
        "  ...\n  NORMAL TERMINATION OF SIMULATION\n", encoding="utf-8"
    )
    assert _simulation_reached_normal_termination(tmp_path) is True


def test_resolve_api_success_maps_none_return_to_listing_verdict(tmp_path: Path) -> None:
    # modflowapi.run_simulation returns None on both success and divergence, so a
    # None return must be resolved from the listing, not assumed to be success.
    from hydromodpy.solver.modflow6.api.api_runner import _resolve_api_success

    # None + no/failed listing -> failure (the old code wrongly returned True).
    assert _resolve_api_success(None, tmp_path) is False
    (tmp_path / "mfsim.lst").write_text("SOLUTION DID NOT CONVERGE\n", encoding="utf-8")
    assert _resolve_api_success(None, tmp_path) is False
    # None + converged listing -> success.
    (tmp_path / "mfsim.lst").write_text("Normal termination of simulation.\n", encoding="utf-8")
    assert _resolve_api_success(None, tmp_path) is True
    # A future modflowapi that reports a real flag is honored directly.
    assert _resolve_api_success(False, tmp_path) is False
    assert _resolve_api_success(True, tmp_path) is True


def test_api_runner_imports_without_modflowapi() -> None:
    # The module must import even when modflowapi is absent: the dependency
    # is imported lazily inside run_mf6_api, never at module top.
    import hydromodpy.solver.modflow6.api.api_runner as runner

    assert hasattr(runner, "run_mf6_api")
    assert hasattr(runner, "Mf6ApiContext")
    assert hasattr(runner, "Mf6ApiStep")
    # No top-level modflowapi/xmipy import dependency.
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "import modflowapi" in source  # present, but lazily inside the function
    module_top = source.split("def run_mf6_api", 1)[0]
    assert "import modflowapi" not in module_top
    assert "import xmipy" not in module_top


# A stop asked through the flag is read by libmf6 at the end of each time step, and
# never by an executable.
#
# The callback of the run is composed with a read of the flag. The raised
# StopRequested is a KeyboardInterrupt, which the runner of libmf6 neither wraps in
# a solver error nor stops on, and finalizes the library for.


def _stop_flag(tmp_path: Path, *, written: bool) -> Path:
    flag = tmp_path / ".hmp" / "stop.json"
    if written:
        flag.parent.mkdir()
        flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')
    return flag


STOP_AT_STEP = (
    ("the library starts", "initialize", True, False),
    ("a time step starts", "timestep_start", True, False),
    ("a time step ends, no flag", "timestep_end", False, False),
    ("a time step ends, a flag", "timestep_end", True, True),
    ("the library ends", "finalize", True, False),
)


@pytest.mark.parametrize(
    ("case", "step", "flag_written", "stops"), STOP_AT_STEP, ids=[c[0] for c in STOP_AT_STEP]
)
def test_the_stop_flag_is_read_at_the_end_of_each_time_step_only(
    case: str, step: str, flag_written: bool, stops: bool, tmp_path: Path
) -> None:
    from hydromodpy.solver.modflow6.api.api_runner import Mf6ApiContext, Mf6ApiStep
    from hydromodpy.solver.modflow6.run import _stopping

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


def test_a_stop_is_no_exception_for_the_callback_of_libmf6_to_wrap() -> None:
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


def _api_model(stop_flag: Path | None, **extra: object):
    from types import SimpleNamespace

    slot = None if stop_flag is None else SimpleNamespace(stop_flag=stop_flag)
    return SimpleNamespace(
        full_path="run", bin_path=None, _mf6_api_lib_path="libmf6.so", slot=slot, **extra
    )


def test_a_run_by_libmf6_reads_the_stop_flag_of_its_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.solver.modflow6 import run as run_module
    from hydromodpy.solver.modflow6.api import api_runner

    api = _ApiRun()
    monkeypatch.setattr(api_runner, "run_mf6_api", api)
    developer: list[object] = []
    model = _api_model(
        _stop_flag(tmp_path, written=True), _mf6_api_callback=lambda ctx: developer.append(ctx)
    )

    assert run_module._run_via_api(model, verbose=False) is True
    ctx = api_runner.Mf6ApiContext(
        step=api_runner.Mf6ApiStep.timestep_end, kper=0, kstp=0, totim=0.0, _sim=None
    )

    with pytest.raises(StopRequested):
        api.callback(ctx)
    assert developer == []


@pytest.mark.parametrize(
    "stop_flag", [None, "absent"], ids=["a slot without a flag", "a flag nobody wrote"]
)
def test_a_run_by_libmf6_that_nobody_stops_calls_its_callback(
    stop_flag: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.solver.modflow6 import run as run_module
    from hydromodpy.solver.modflow6.api import api_runner

    api = _ApiRun()
    monkeypatch.setattr(api_runner, "run_mf6_api", api)
    developer: list[object] = []
    flag = None if stop_flag is None else _stop_flag(tmp_path, written=False)
    model = _api_model(flag, _mf6_api_callback=lambda ctx: developer.append(ctx))
    run_module._run_via_api(model, verbose=False)
    ctx = api_runner.Mf6ApiContext(
        step=api_runner.Mf6ApiStep.timestep_end, kper=0, kstp=0, totim=0.0, _sim=None
    )

    api.callback(ctx)

    assert developer == [ctx]


def test_a_run_by_the_executable_never_reads_the_stop_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child process writes its files until it ends: no exception is raised under it."""
    from types import SimpleNamespace

    from hydromodpy.model.model import ModelTime
    from hydromodpy.solver.modflow6 import run as run_module
    from hydromodpy.solver.modflow_common.options import ModflowRunOptions
    from tests._helpers.model_factory import make_model

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


# A solver binary that cannot be fetched raises a typed network error.
#
# A raw connection error used to reach the user as is: exit 1 from ``hmp
# install-binaries`` and a bare exception in the ``run_solver`` step of a run.


@pytest.mark.parametrize(
    ("raised", "cause"),
    [
        (
            NetworkError("HTTP GET x failed after 4 retries", last_exception="Connection refused"),
            "Connection refused",
        ),
        (NetworkError("HTTP GET x -> 503", status_code=503), "HTTP GET x -> 503"),
    ],
)
def test_a_network_failure_names_the_address_and_what_to_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raised: NetworkError, cause: str
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise raised

    monkeypatch.setattr(binaries, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(binaries, "fetch_pinned", refuse)

    with pytest.raises(NetworkError) as caught:
        binaries.download_solver_binaries(tmp_path, subset=["mf6"], release="23.0")

    message = str(caught.value)
    assert binaries.asset_url("23.0", binaries._release_asset()) in message
    assert cause in message
    assert "HTTPS_PROXY" in message
    assert "HMP_BIN" in message
    assert exit_code_for(caught.value) == EXIT_VALIDATION == 16


# The libmf6/exe version-parity warning (finding 6).
#
# The api runner solves with libmf6 while the subprocess runner and the per-trial
# steady-state init use the exe, so a version skew is surfaced once, loudly.


@pytest.fixture
def warnings(monkeypatch):
    """Reset the once-guard and capture logger.warning calls (routing-agnostic)."""
    monkeypatch.setattr(binaries, "_MF6_VERSION_PARITY_CHECKED", False, raising=False)
    monkeypatch.delenv(binaries._MISMATCH_ENV_VAR, raising=False)
    calls: list[tuple] = []
    monkeypatch.setattr(binaries.logger, "warning", lambda *a, **k: calls.append(a))
    return calls


def _patch_versions(monkeypatch, exe: str | None, lib: str | None) -> None:
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: exe)
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: lib)


def test_mismatch_warns_once(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.7.0")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")  # once-only guard
    assert len(warnings) == 1
    assert "6.6.3" in warnings[0] and "6.7.0" in warnings[0]


def test_matching_major_minor_is_silent(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.6.1")  # same major.minor
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_env_var_silences_the_mismatch(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.7.0")
    monkeypatch.setenv(binaries._MISMATCH_ENV_VAR, "1")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_unknown_version_does_not_warn(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, None, "6.7.0")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_solver_python_stack_reports_both_wrappers() -> None:
    stack = binaries.solver_python_stack()
    assert "modflowapi" in stack and "xmipy" in stack


def test_solver_python_stack_flags_dev_editable(monkeypatch) -> None:
    monkeypatch.setattr(
        binaries,
        "_package_version_and_editable",
        lambda name: ("0.3.0.dev0", True) if name == "modflowapi" else ("1.5.0", False),
    )
    stack = binaries.solver_python_stack()
    assert "modflowapi 0.3.0.dev0 (editable)" in stack
    assert "xmipy 1.5.0" in stack and "xmipy 1.5.0 (editable)" not in stack


def test_solver_python_stack_marks_absent(monkeypatch) -> None:
    monkeypatch.setattr(binaries, "_package_version_and_editable", lambda _name: (None, False))
    assert binaries.solver_python_stack() == "modflowapi (absent), xmipy (absent)"


# MF6 listing-file resolution: the mass balance follows the name MF6 was given.


def test_short_name_listing_matches_the_run_name() -> None:
    assert _listing_path(Path("/out"), "canut_paper_mf6") == Path("/out/canut_paper_mf6.lst")


def test_long_name_listing_follows_the_truncated_model_name() -> None:
    # The .hds/.cbc keep the full run name but MF6 wrote the listing under the
    # 16-char model name, so a raw-name lookup silently empties mass_balance.
    name = "nancon_intermittence_mf6"
    listing = _listing_path(Path("/out"), name)

    assert listing.stem == mf6_safe_name(name)
    assert listing.stem != name
    assert len(listing.stem) <= 16


def test_already_safe_name_is_left_alone() -> None:
    # Windows paths hand the extractor the safe name directly: no double hash.
    safe = mf6_safe_name("nancon_intermittence_mf6")

    assert _listing_path(Path("/out"), safe).stem == safe


def test_spaced_name_listing_matches_the_sanitised_model_name() -> None:
    assert _listing_path(Path("/out"), "run one").stem == "run_one"


def test_mf6_evt_extinction_depth_from_process_specific() -> None:
    model = toy_model()
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 2.5}}
    )
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
    )

    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    assert evt_spd is not None
    # Record layout: [layer, cell_id, surface, rate, extinction_depth].
    assert evt_spd[1][0][4] == pytest.approx(2.5)

    # Default config keeps the 1.0 m extinction depth.
    model.modflow_config = _coerce_modflow6_config({})
    evt_default = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert evt_default[1][0][4] == pytest.approx(1.0)


# Unit tests for solver output-file cleanup.


class TestCleanupSolverFiles:
    def test_remove_all(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.cbc").write_text("budget data")
        (d / "model.lst").write_text("listing")

        cleanup_solver_files(d)
        assert not d.exists()

    def test_keep_extensions(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.lst").write_text("listing")
        (d / "model.nam").write_text("name file")

        cleanup_solver_files(d, keep={".lst", ".nam"})
        assert (d / "model.lst").exists()
        assert (d / "model.nam").exists()
        assert not (d / "model.hds").exists()
