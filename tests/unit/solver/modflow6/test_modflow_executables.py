"""Solver binaries and the engine a run records.

Covers the executable and shared-library resolver, the engine recorded for a run, the
download failure message, the version-parity warning and the Python stack string.
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


def test_missing_executable_unchanged(tmp_path: Path) -> None:
    missing = tmp_path / "missing_solver"

    assert ensure_platform_executable(missing) == missing


def test_executable_gets_execute_bit(tmp_path: Path) -> None:
    solver = tmp_path / "solver_binary"
    solver.write_text("echo solver\n", encoding="utf-8")
    solver.chmod(0o644)

    result = ensure_platform_executable(solver)

    assert result == solver
    if os.name != "nt":
        assert solver.stat().st_mode & stat.S_IXUSR


def test_libmf6_filename_per_os() -> None:
    name = exe_filename("libmf6")
    if sys.platform.startswith("win"):
        assert name == "libmf6.dll"
    elif sys.platform == "darwin":
        assert name == "libmf6.dylib"
    else:
        assert name == "libmf6.so"


def test_missing_library_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_solver_library("libmf6", bin_path=tmp_path)


@pytest.mark.skipif(
    locate_solver_binary(Path(resolve_bin_path()), "libmf6") is None,
    reason="libmf6 shared library not in cache",
)
def test_library_resolves_to_file() -> None:
    resolved = ensure_solver_library("libmf6")

    assert resolved.is_absolute()
    assert resolved.is_file()


# The engine a run records is the one it executed. An api run solves through libmf6,
# so recording the mf6 executable would describe a file the solve never opened.


def _stub_engine_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    exe = tmp_path / "mf6"
    lib = tmp_path / "libmf6.so"
    exe.write_bytes(b"exe")
    lib.write_bytes(b"lib")
    monkeypatch.setattr(binaries, "ensure_solver_binary", lambda *_a, **_k: exe)
    monkeypatch.setattr(binaries, "ensure_solver_library", lambda *_a, **_k: lib)
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: "6.6.3")
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: "6.6.3")
    return {"executable": exe, "library": lib}


# Only MODFLOW 6 ships a shared library, so NWT keeps its executable under "api".
ENGINES = [
    pytest.param("modflow6", "api", "library", "api", id="mf6 api reads the library"),
    pytest.param(
        "modflow6", "subprocess", "executable", "subprocess", id="mf6 subprocess reads the exe"
    ),
    pytest.param("modflow_nwt", "api", "executable", "subprocess", id="nwt api falls back"),
]


@pytest.mark.parametrize(("solver", "asked", "kind", "mode"), ENGINES)
def test_engine_of_a_run(solver, asked, kind, mode, monkeypatch, tmp_path: Path) -> None:
    files = _stub_engine_files(monkeypatch, tmp_path)

    engine = binaries.resolve_solver_engine(solver, execution_mode=asked)

    assert engine is not None
    assert (engine.kind, engine.execution_mode) == (kind, mode)
    assert engine.path == files[kind]
    assert engine.version == "6.6.3"


def test_no_binary_no_engine() -> None:
    assert binaries.resolve_solver_engine("boussinesq") is None
    assert binaries.resolve_solver_engine("gr4j", execution_mode="api") is None


def test_engine_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Provenance must never be the reason a run refuses to start.
    def boom(*_args, **_kwargs):
        raise FileNotFoundError("no binary here")

    monkeypatch.setattr(binaries, "ensure_solver_binary", boom)
    monkeypatch.setattr(binaries, "ensure_solver_library", boom)

    assert binaries.resolve_solver_engine("modflow6") is None
    assert binaries.resolve_solver_engine("modflow6", execution_mode="api") is None


# A solver binary that cannot be fetched raises a typed network error, which
# hmp install-binaries maps to exit code 16.

NETWORK_FAILURES = [
    pytest.param(
        NetworkError("HTTP GET x failed after 4 retries", last_exception="Connection refused"),
        "Connection refused",
        id="connection refused",
    ),
    pytest.param(
        NetworkError("HTTP GET x -> 503", status_code=503), "HTTP GET x -> 503", id="http 503"
    ),
]


@pytest.mark.parametrize(("raised", "cause"), NETWORK_FAILURES)
def test_network_failure_names_the_fix(
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


# The api runner solves with libmf6 while the subprocess runner and the steady-state
# init use the exe, so a version skew is warned once.


@pytest.fixture
def warned(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """The warnings logged, with the once-guard and the silencing variable reset."""
    monkeypatch.setattr(binaries, "_MF6_VERSION_PARITY_CHECKED", False, raising=False)
    monkeypatch.delenv(binaries._MISMATCH_ENV_VAR, raising=False)
    calls: list[tuple] = []
    monkeypatch.setattr(binaries.logger, "warning", lambda *a, **k: calls.append(a))
    return calls


def _patch_versions(monkeypatch: pytest.MonkeyPatch, exe: str | None, lib: str | None) -> None:
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: exe)
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: lib)


def test_mismatch_warns_once(monkeypatch, warned) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.7.0")

    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")

    assert len(warned) == 1
    assert "6.6.3" in warned[0] and "6.7.0" in warned[0]


SILENT_VERSIONS = [
    pytest.param("6.6.3", "6.6.1", False, id="same major and minor"),
    pytest.param("6.6.3", "6.7.0", True, id="env var silences"),
    pytest.param(None, "6.7.0", False, id="unknown version"),
]


@pytest.mark.parametrize(("exe", "lib", "silenced"), SILENT_VERSIONS)
def test_no_warning(exe, lib, silenced, monkeypatch, warned) -> None:
    _patch_versions(monkeypatch, exe, lib)
    if silenced:
        monkeypatch.setenv(binaries._MISMATCH_ENV_VAR, "1")

    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")

    assert warned == []


def test_python_stack_reports_both_wrappers() -> None:
    stack = binaries.solver_python_stack()

    assert "modflowapi" in stack and "xmipy" in stack


def test_python_stack_flags_a_dev_editable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        binaries,
        "_package_version_and_editable",
        lambda name: ("0.3.0.dev0", True) if name == "modflowapi" else ("1.5.0", False),
    )

    stack = binaries.solver_python_stack()

    assert "modflowapi 0.3.0.dev0 (editable)" in stack
    assert "xmipy 1.5.0" in stack and "xmipy 1.5.0 (editable)" not in stack


def test_python_stack_marks_an_absent_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries, "_package_version_and_editable", lambda _name: (None, False))

    assert binaries.solver_python_stack() == "modflowapi (absent), xmipy (absent)"
