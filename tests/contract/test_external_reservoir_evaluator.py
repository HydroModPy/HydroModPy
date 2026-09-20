"""An installed foreign model completes a calibration described by TOML."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "evaluator_reservoir"
EVALUATOR_ID = "reservoir_recession"
CONFORMANCE_SUITE = REPO_ROOT / "tests/contract/test_trial_evaluator_contract.py"

# One worker for everything that builds a wheel out of this checkout. ``pip
# wheel`` writes into the repository's own ``build/`` directory, so two workers
# building at once collide there -- "File exists: .../hydromodpy-*.dist-info"
# and a red that names no test of the diff.
pytestmark = pytest.mark.xdist_group(name="wheel_build")


@pytest.fixture(scope="module")
def installed_evaluator(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build and unpack both wheels without installing dependencies."""
    root = tmp_path_factory.mktemp("reservoir_wheel")
    wheel_dir = root / "wheels"
    site = root / "site"
    wheel_dir.mkdir()
    site.mkdir()

    for package in (REPO_ROOT, PACKAGE_ROOT):
        built = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-build-isolation",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                str(package),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert built.returncode == 0, built.stdout + built.stderr
    wheels = sorted(wheel_dir.glob("*.whl"))
    assert len(wheels) == 2, wheels

    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(site),
            *(str(wheel) for wheel in wheels),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    return site


def _environment(site: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    environment["HMP_WHEEL_SITE"] = str(site.resolve())
    paths = [str(site), str(REPO_ROOT)]
    if previous := environment.get("PYTHONPATH"):
        paths.append(previous)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def _document(path: Path, workspace: Path) -> None:
    path.write_text(
        "[workspace]\n"
        f'project_root = "{workspace.as_posix()}"\n'
        "[calibration]\n"
        f'evaluator = "{EVALUATOR_ID}"\n'
        'method = "grid"\n'
        "max_iter = 9\n"
        "optimizer_kwargs = { points_per_dim = 3 }\n"
        "[calibration.parameters.k]\n"
        'path = "flow.properties.k_aquifer"\n'
        "bounds = [1e-6, 1e-2]\n"
        'transform = "log"\n'
        "[calibration.parameters.porosity]\n"
        'path = "flow.properties.porosity"\n'
        "bounds = [0.01, 0.3]\n",
        encoding="utf-8",
    )


def test_an_installed_foreign_model_is_calibrated_from_toml(
    installed_evaluator: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "declared_root"
    workspace.mkdir()
    document = tmp_path / "calibration.toml"
    _document(document, workspace)
    script = """
import inspect
import json
import sys

import hydromodpy as hmp
from hydromodpy.calibration.evaluation import registry
import hydromodpy.calibration.runners.cli_runner as cli_runner

def forbidden_prepare(*args, **kwargs):
    raise AssertionError("a foreign evaluator prepared the HydroModPy model")

cli_runner.prepare_trials = forbidden_prepare
evaluator = registry.get("reservoir_recession")
report = hmp.calibrate(sys.argv[1])
print("F9C_RESULT=" + json.dumps({
    "host_module": hmp.__file__,
    "module": inspect.getfile(evaluator),
    "builtin": "reservoir_recession" in registry.builtin_evaluator_ids(),
    "best": report["best_parameters"],
    "cost": report["best_objective"],
    "iterations": report["n_iterations"],
    "workspace": report["workspace"],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(document)],
        cwd=tmp_path,
        env=_environment(installed_evaluator),
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("F9C_RESULT=")]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0].removeprefix("F9C_RESULT="))
    assert Path(payload["host_module"]).is_relative_to(installed_evaluator.resolve())
    assert Path(payload["module"]).is_relative_to(installed_evaluator.resolve())
    assert payload["builtin"] is False
    assert payload["iterations"] == 9
    assert payload["best"]["k"] == pytest.approx(1e-4)
    assert payload["best"]["porosity"] == pytest.approx(0.155)
    assert payload["cost"] < 1e-20
    assert Path(payload["workspace"]) == workspace
    assert list(workspace.glob("sessions/*"))


def test_the_registry_driven_conformance_suite_runs_the_installed_model(
    installed_evaluator: Path, tmp_path: Path
) -> None:
    environment = _environment(installed_evaluator)
    script = """
import os
from pathlib import Path

import hydromodpy
import pytest
import sys

assert Path(hydromodpy.__file__).is_relative_to(Path(os.environ["HMP_WHEEL_SITE"]))
raise SystemExit(pytest.main(sys.argv[1:]))
"""
    command = [
        sys.executable,
        "-c",
        script,
        str(CONFORMANCE_SUITE),
        "-q",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        f"--basetemp={tmp_path / 'conformance'}",
        "-k",
        EVALUATOR_ID,
    ]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) >= 10, result.stdout
    assert " skipped" not in result.stdout
