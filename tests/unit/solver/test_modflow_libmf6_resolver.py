"""Unit checks for the libmf6 shared-library resolver and runner gating.

These do not need a binary; they cover the per-OS filename mapping, the
resolver's success/absent paths, and the lazy optional-dependency guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hydromodpy.solver.modflow_common.binaries import (
    ensure_solver_library,
    exe_filename,
    locate_solver_binary,
    managed_bin_dir,
)


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
    from hydromodpy.solver.modflow6.api_runner import run_mf6_api

    with pytest.raises(FileNotFoundError):
        run_mf6_api(tmp_path, lambda ctx: None)


def test_api_runner_imports_without_modflowapi() -> None:
    # The module must import even when modflowapi is absent: the dependency
    # is imported lazily inside run_mf6_api, never at module top.
    import importlib

    import hydromodpy.solver.modflow6.api_runner as runner

    assert hasattr(runner, "run_mf6_api")
    assert hasattr(runner, "Mf6ApiContext")
    assert hasattr(runner, "Mf6ApiStep")
    # No top-level modflowapi/xmipy import dependency.
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "import modflowapi" in source  # present, but lazily inside the function
    module_top = source.split("def run_mf6_api", 1)[0]
    assert "import modflowapi" not in module_top
    assert "import xmipy" not in module_top
    importlib.reload(runner)
