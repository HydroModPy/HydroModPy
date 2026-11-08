"""The conformance suite of the optimizer port reaches an optimizer it does not name.

``add-a-calibration-method.rst`` tells a plugin author to run the suite from a
clone, with the plugin installed. This file installs an optimizer the suite has
never heard of and runs the suite on it, in a subprocess because
``importlib.metadata`` reads the entry points once (the reason the other
``test_*_conformance_reaches_an_installed_*`` files of this directory share a
probe in ``_installed_probe.py``).

The entry point carries the id the registry keys it on, the adapter's ``name``
attribute: a third-party method is published under the id its class declares,
exactly the rule the evaluators follow.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.calibration.optim.optimizer import ENTRY_POINT_GROUP

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

SUITE: ClassVar[str] = "tests/contract/test_optimizer_contract.py"
PROBE_ID: ClassVar[str] = "probe-shim"
CASES_PER_ID: ClassVar[int] = 1
"""One case per parametrized test that runs over the ids served, and the suite has one."""

PROBE_MODULE = """\\
from typing import ClassVar
from pydantic import BaseModel
from hydromodpy.calibration.optim.optimizer import ParamSuggestion


class ProbeOptions(BaseModel):
    max_steps: int = 10


class ProbeShim:
    name: ClassVar[str] = "probe-shim"
    options: ClassVar[type[BaseModel] | None] = ProbeOptions

    def __init__(self, space, **options):
        self.space = space
        self.options = options

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        return [ParamSuggestion(trial_id=i, values={"p": 0.0}) for i in range(n)]

    def tell(self, results: list) -> None:
        return None

    def best(self):
        return None

    def converged(self) -> bool:
        return False
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"),
        "hmp_optimizer_probe",
        PROBE_MODULE,
        ENTRY_POINT_GROUP,
        PROBE_ID,
        "ProbeShim",
    )  # fmt: skip


def _run_python_in_subprocess(code: str, site_packages: Path) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_suite_holds_an_installed_optimizer_to_the_port(
    installed_probe: Path, tmp_path: Path
) -> None:
    """The conformance suite reaches an installed optimizer, one group scan."""
    listing = run_suite(SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)  # fmt: skip
    assert listing.returncode == 0, listing.stdout[-4000:]
    nodes = collected(listing.stdout, SUITE, PROBE_ID)
    assert len(nodes) == CASES_PER_ID, listing.stdout[-4000:]

    result = run_suite(SUITE, tmp_path / "run", "-q", "-k", PROBE_ID, site_packages=installed_probe)  # fmt: skip
    assert result.returncode == 0, result.stdout[-8000:]


def test_installed_optimizer_accepted_by_calibration_method(
    installed_probe: Path,
) -> None:
    code = """
from pydantic import TypeAdapter
from hydromodpy.calibration.config import CalibrationMethod
from hydromodpy.calibration.optim.optimizer import optimizers

assert "probe-shim" in optimizers.names()
adapter = TypeAdapter(CalibrationMethod)
val = adapter.validate_python("probe-shim")
assert val == "probe-shim"
"""
    result = _run_python_in_subprocess(code, installed_probe)
    assert result.returncode == 0, result.stderr or result.stdout


def test_installed_optimizer_options_validated(
    installed_probe: Path,
) -> None:
    code = """
from hydromodpy.calibration.optim.method_config import validate_method_kwargs

# Valid options
validated = validate_method_kwargs("probe-shim", {"max_steps": 20})
assert validated.max_steps == 20

# Invalid options
try:
    validate_method_kwargs("probe-shim", {"max_steps": "not_an_int"})
except Exception as exc:
    assert "max_steps" in str(exc)
else:
    raise AssertionError("Should have raised exception on invalid options")
"""
    result = _run_python_in_subprocess(code, installed_probe)
    assert result.returncode == 0, result.stderr or result.stdout
