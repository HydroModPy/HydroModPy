"""Guard: ``import hydromodpy`` stays lean (interface refactor, C4).

The heavy bootstrap (config rebuild + DI wiring, which pulls flopy, matplotlib,
the full physics/solver/workflow graph) is deferred to first real use via
``core.bootstrap_hook``. A bare ``import hydromodpy`` must therefore NOT run the
bootstrap nor pull the heavy scientific stack, so notebooks, scripts and
``hmp --help`` start fast.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def _probe(expr: str) -> str:
    code = (
        f"import sys, hydromodpy\nfrom hydromodpy._bootstrap import _BOOTSTRAPPED\nprint({expr})\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_bare_import_defers_bootstrap() -> None:
    assert _probe("_BOOTSTRAPPED") == "False"


def test_bare_import_does_not_pull_heavy_stack() -> None:
    heavy = ("flopy", "matplotlib", "matplotlib.pyplot")
    present = _probe("[m for m in " + repr(heavy) + " if m in sys.modules]")
    assert present == "[]", f"bare import pulled heavy modules: {present}"
