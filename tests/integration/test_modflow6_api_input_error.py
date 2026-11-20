"""An MF6 input error at initialize must raise in Python, not end the process.

libmf6 stops on an input error with a Fortran ``stop``: the calling process
exits with code 2, with no exception and no console message. Only
``mfsim.stdout`` carries the error. The in-process API runner must survive
that and raise :class:`SolverInputError` with the tail of ``mfsim.stdout``.

The call runs in a child interpreter, so a regression shows up as a failed
assertion instead of killing the pytest process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("modflowapi")
pytest.importorskip("xmipy")

from hydromodpy.core.workspace.workspace import resolve_bin_path  # noqa: E402
from hydromodpy.solver.modflow_common.binaries import (  # noqa: E402
    locate_solver_binary,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_modflow6_lake_extractor_e2e import _build_single_lake_disv  # noqa: E402

_no_lib = locate_solver_binary(Path(resolve_bin_path()), "libmf6") is None

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.skipif(_no_lib, reason="libmf6 shared library not in cache"),
]

_BAD_OPTION = "NOT_AN_NPF_OPTION"

_CALLER = textwrap.dedent(
    """
    import sys
    from hydromodpy.core.exceptions import SolverInputError
    from hydromodpy.solver.modflow6.api.api_runner import run_mf6_api

    try:
        run_mf6_api(sys.argv[1], lambda ctx: None)
    except SolverInputError as exc:
        print("RAISED SolverInputError", exc.code)
        print(exc)
        sys.exit(0)
    print("NO EXCEPTION")
    sys.exit(3)
    """
)


def _write_bad_npf(ws: Path) -> Path:
    sim = _build_single_lake_disv(ws, "mf6")
    sim.write_simulation(silent=True)
    npf = next(ws.glob("*.npf"))
    text = npf.read_text()
    npf.write_text(text.replace("BEGIN options", f"BEGIN options\n  {_BAD_OPTION}", 1))
    return ws


def test_library_is_present() -> None:
    # Guard against a silent skip of the whole module.
    assert not _no_lib


def test_api_input_error_at_initialize_raises(tmp_path: Path) -> None:
    ws = _write_bad_npf(tmp_path / "bad")
    script = tmp_path / "caller.py"
    script.write_text(_CALLER)
    proc = subprocess.run(
        [sys.executable, str(script), str(ws)],
        capture_output=True,
        text=True,
        timeout=300,
        env=dict(os.environ),
        cwd=str(tmp_path),
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"caller exited with {proc.returncode}:\n{out}"
    assert "RAISED SolverInputError" in proc.stdout
    assert "HMPY.E405" in proc.stdout
    # The tail of mfsim.stdout names the bad keyword.
    assert _BAD_OPTION in proc.stdout.upper()
    assert "mfsim.stdout" in proc.stdout
