from __future__ import annotations

import os
import stat
from pathlib import Path

from hydromodpy.solver.modflow_common import ensure_platform_executable


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
