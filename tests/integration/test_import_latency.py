"""Guard: ``import hydromodpy`` stays lean (interface refactor, C4).

The heavy work of a start-up (config validation, the DI wiring, which pulls
flopy, matplotlib, and the full physics/solver/workflow graph) is deferred to
first real use: a config validation, a verb, a Project, or the CLI handler.
A bare ``import hydromodpy`` must therefore NOT pull the heavy scientific
stack, so notebooks, scripts and ``hmp --help`` start fast.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def _probe_bare(expr: str) -> str:
    code = f"import sys\nimport hydromodpy\nprint({expr})\n"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _probe(expr: str) -> str:
    code = f"import sys\nfrom hydromodpy.config import HydroModPyConfig\nprint({expr})\n"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_bare_import_stays_lean() -> None:
    # A bare ``import hydromodpy`` loads neither the full config implementation
    # nor the workflow package.
    forbidden = (
        "hydromodpy.config.hydromodpy_config",
        "hydromodpy.workflow",
    )
    pulled = _probe_bare("[m for m in " + repr(forbidden) + " if m in sys.modules]")
    assert pulled == "[]", f"bare import pulled unexpected modules: {pulled}"


def test_bare_import_does_not_pull_heavy_stack() -> None:
    heavy = ("flopy", "matplotlib", "matplotlib.pyplot")
    present = _probe("[m for m in " + repr(heavy) + " if m in sys.modules]")
    assert present == "[]", f"bare import pulled heavy modules: {present}"
