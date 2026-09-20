"""An installed foreign model is scored by criteria that live in the document.

F9c installed a foreign *evaluator* and calibrated it from a TOML. That proved
substitution and left one thing in the wheel: an evaluator returns a cost, so it
also decided which quantity was compared and how it was weighed.

This file proves the other half, in the same isolated way. ``hydromodpy-forward-
cascade`` is built and installed beside HydroModPy in a directory neither
package can reach from the checkout, and it implements the *forward-model* port:
a sample in, named observables out, and no cost. What is scored, under which
metric and with which weight, is written in the document.

Four things are shown, and the last two are what the port is for:

1. a calibration described by a TOML runs to its known optimum on a model no
   file of ``hydromodpy/`` names, without preparing a HydroModPy model;
2. the registry-driven conformance suite of the port runs against that model
   without naming it, and the installed model is what it ran on;
3. two documents that differ in two weight lines and nothing else make the same
   installed wheel report two different answers;
4. a document that changes only the metric moves the number the search reports
   and leaves the answer where it was -- the weights arbitrate, the metric
   measures, and neither is in the wheel.

The cascade's closed form is rewritten here rather than imported from the wheel:
a test that read the model's own constants would move with it, and the records
these documents are scored against have to be written against a published
answer.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "forward_cascade"
MODEL_ID = "two_reservoir_cascade"
DOCUMENT = PACKAGE_ROOT / "cascade_calibration.toml"
CONFORMANCE_SUITE = REPO_ROOT / "tests/contract/test_forward_model_contract.py"

# One worker for everything that builds a wheel out of this checkout. ``pip
# wheel`` writes into the repository's own ``build/`` directory, so two workers
# building at once collide there -- "File exists: .../hydromodpy-*.dist-info"
# and a red that names no test of the diff. The group is the one the sibling
# wheel proof uses, because the collision is between the two files as much as
# between two nodes of either.
pytestmark = pytest.mark.xdist_group(name="wheel_build")

INITIAL_STORAGE_M3 = 1_000_000.0
SPLIT_TO_SLOW = 0.9
RECESSION_DAYS = 30
REFERENCE = (0.25, 0.05)
"""The pair the wheel's own document is written at, and a node of the grid."""

RIVAL = (2.5, 0.5)
"""A second pair, also a node of the grid, and as far from the first as it goes."""


def _cascade_discharge(k_fast: float, k_slow: float) -> list[float]:
    """``Q(t)`` of two stores in series, in m3/day, daily. The closed form, by hand."""
    values = []
    for day in range(RECESSION_DAYS):
        upper = INITIAL_STORAGE_M3 * math.exp(-k_fast * day)
        lower = (
            SPLIT_TO_SLOW
            * INITIAL_STORAGE_M3
            * (k_fast / (k_slow - k_fast))
            * (math.exp(-k_fast * day) - math.exp(-k_slow * day))
        )
        values.append((1.0 - SPLIT_TO_SLOW) * k_fast * upper + k_slow * lower)
    return values


@pytest.fixture(scope="module")
def installed_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build and unpack both wheels without installing dependencies."""
    root = tmp_path_factory.mktemp("cascade_wheel")
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
            timeout=300,
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
        timeout=300,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    return site


def _environment(site: Path) -> dict[str, str]:
    """Run against the installed site, with the checkout last on the path."""
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    environment["HMP_WHEEL_SITE"] = str(site.resolve())
    paths = [str(site), str(REPO_ROOT)]
    if previous := environment.get("PYTHONPATH"):
        paths.append(previous)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def _installed_model_digest(site: Path) -> str:
    """Digest the installed model file, read off the site rather than the checkout."""
    installed = sorted(site.glob("hydromodpy_forward_cascade/model.py"))
    assert len(installed) == 1, installed
    return hashlib.sha256(installed[0].read_bytes()).hexdigest()


CALIBRATE = """
import hashlib
import inspect
import json
import sys

import hydromodpy as hmp
from hydromodpy.calibration.evaluation import forward_registry
import hydromodpy.calibration.runners.cli_runner as cli_runner

def forbidden_prepare(*args, **kwargs):
    raise AssertionError("a document-scored model prepared the HydroModPy model")

cli_runner.prepare_trials = forbidden_prepare
model_file = inspect.getfile(forward_registry.get(sys.argv[2]))
report = hmp.calibrate(sys.argv[1], workspace=sys.argv[3])
print("F9D_RESULT=" + json.dumps({
    "host_module": hmp.__file__,
    "module": model_file,
    "model_sha256": hashlib.sha256(open(model_file, "rb").read()).hexdigest(),
    "builtin": sys.argv[2] in forward_registry.builtin_model_ids(),
    "served": list(forward_registry.list_model_ids()),
    "best": report["best_parameters"],
    "cost": report["best_objective"],
    "iterations": report["n_iterations"],
}))
"""


def _calibrate(site: Path, document: Path, workspace: Path) -> dict:
    """Run one calibration in a process that cannot see this checkout's registry."""
    result = subprocess.run(
        [sys.executable, "-c", CALIBRATE, str(document), MODEL_ID, str(workspace)],
        cwd=document.parent,
        env=_environment(site),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("F9D_RESULT=")]
    assert len(lines) == 1, result.stdout
    return json.loads(lines[0].removeprefix("F9D_RESULT="))


def _two_record_document(
    path: Path,
    workspace: Path,
    *,
    reference_weight: float,
    rival_weight: float,
    metric: str = "rmse",
) -> str:
    """Write a document scoring one outlet against two records that disagree.

    The first record is the cascade at :data:`REFERENCE`, the second at
    :data:`RIVAL`. Both are a discharge at the same outlet, so nothing physical
    tells them apart and the weights are the whole of the arbitration.
    """
    reference = ", ".join(repr(value) for value in _cascade_discharge(*REFERENCE))
    rival = ", ".join(repr(value) for value in _cascade_discharge(*RIVAL))
    text = f"""[workspace]
project_root = "{workspace.as_posix()}"

[calibration]
evaluator = "scored_forward_model"
forward_model = "{MODEL_ID}"
method = "grid"
max_iter = 9
optimizer_kwargs = {{ points_per_dim = 3 }}

[calibration.parameters.k_fast]
path = "flow.properties.k_fast"
bounds = [0.025, 2.5]
transform = "log"

[calibration.parameters.k_slow]
path = "flow.properties.k_slow"
bounds = [0.005, 0.5]
transform = "log"

[calibration.outputs.gauge_record]
support = "boundary"
variable = "discharge"
boundary_id = "outlet"
time = "all"
observed_values = [{reference}]

[calibration.outputs.revised_record]
support = "boundary"
variable = "discharge"
boundary_id = "outlet"
time = "all"
observed_values = [{rival}]

[[calibration.objective_blocks]]
name = "gauge"
metric = "{metric}"
uses_outputs = ["gauge_record"]
weight = {reference_weight}

[[calibration.objective_blocks]]
name = "revised"
metric = "{metric}"
uses_outputs = ["revised_record"]
weight = {rival_weight}
"""
    path.write_text(text, encoding="utf-8")
    return text


def _changed_lines(first: str, second: str) -> list[str]:
    """Return the lines that differ between two documents, markers included."""
    return [
        line
        for line in difflib.unified_diff(first.splitlines(), second.splitlines(), n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def test_an_installed_model_is_calibrated_from_the_document_that_scores_it(
    installed_model: Path, tmp_path: Path
) -> None:
    """The wheel's own document, run where the checkout cannot answer for it.

    The optimum is the pair the records were produced at, and the search reaches
    it through the in-tree evaluator that owns no physics: what ran is the
    installed model, what scored it is the file.
    """
    payload = _calibrate(installed_model, DOCUMENT, tmp_path / "workspace")

    site = installed_model.resolve()
    assert Path(payload["host_module"]).is_relative_to(site), payload["host_module"]
    assert Path(payload["module"]).is_relative_to(site), payload["module"]
    assert payload["builtin"] is False, payload["served"]
    assert MODEL_ID in payload["served"]
    assert payload["iterations"] == 9
    assert payload["best"]["k_fast"] == pytest.approx(REFERENCE[0])
    assert payload["best"]["k_slow"] == pytest.approx(REFERENCE[1])
    assert payload["cost"] < 1e-12, payload["cost"]
    assert list((tmp_path / "workspace").glob("sessions/*"))


def test_two_weights_in_the_document_move_the_answer_of_one_unchanged_wheel(
    installed_model: Path, tmp_path: Path
) -> None:
    """The promise of the port, on a model this repository does not own.

    Two records of one outlet disagree; one document trusts the first, the other
    trusts the second, and they differ in two weight lines. The installed model
    is the same file with the same digest in both runs -- asserted, not assumed
    -- and the search reports the pair each document asked for.

    The two costs are equal by construction, because each document pays the same
    weighted distance to the record it distrusts. Asserting on the cost would
    therefore prove nothing; what moves is the answer.

    Both documents declare the same project root and both runs are given the
    same workspace, so the four weight lines are the whole of the difference
    between them: anything else that moved would be a second explanation for a
    moved answer.

    The digest is taken off the installed file before either run and compared
    with what each run reports, so it is the wheel that is held still rather
    than a value compared with itself.
    """
    declared_root = tmp_path / "declared_root"
    declared_root.mkdir()
    workspace = tmp_path / "workspace"
    before = _installed_model_digest(installed_model)
    trusts_reference = tmp_path / "trusts_reference.toml"
    trusts_rival = tmp_path / "trusts_rival.toml"
    first_text = _two_record_document(
        trusts_reference, declared_root, reference_weight=0.9, rival_weight=0.1
    )
    second_text = _two_record_document(
        trusts_rival, declared_root, reference_weight=0.1, rival_weight=0.9
    )
    assert len(_changed_lines(first_text, second_text)) == 4, _changed_lines(
        first_text, second_text
    )

    first = _calibrate(installed_model, trusts_reference, workspace)
    second = _calibrate(installed_model, trusts_rival, workspace)

    assert first["model_sha256"] == before
    assert second["model_sha256"] == before
    assert _installed_model_digest(installed_model) == before
    assert first["best"]["k_fast"] == pytest.approx(REFERENCE[0])
    assert first["best"]["k_slow"] == pytest.approx(REFERENCE[1])
    assert second["best"]["k_fast"] == pytest.approx(RIVAL[0])
    assert second["best"]["k_slow"] == pytest.approx(RIVAL[1])


def test_the_metric_in_the_document_moves_the_number_and_not_the_answer(
    installed_model: Path, tmp_path: Path
) -> None:
    """The other half of what the document owns, on the same unchanged wheel.

    Two documents differing in two ``metric`` lines. The mean absolute residual
    and the root mean square of the same residuals are not the same number, so
    the reported cost has to move; both are minimized where the records say, so
    the answer has to stay. A wheel that brought its own metric -- which is what
    an evaluator does -- could not produce either behaviour.
    """
    declared_root = tmp_path / "declared_root"
    declared_root.mkdir()
    workspace = tmp_path / "workspace"
    before = _installed_model_digest(installed_model)
    scored_on_rmse = tmp_path / "scored_on_rmse.toml"
    scored_on_mae = tmp_path / "scored_on_mae.toml"
    first_text = _two_record_document(
        scored_on_rmse, declared_root, reference_weight=0.9, rival_weight=0.1
    )
    second_text = _two_record_document(
        scored_on_mae, declared_root, reference_weight=0.9, rival_weight=0.1, metric="mae"
    )
    assert len(_changed_lines(first_text, second_text)) == 4, _changed_lines(
        first_text, second_text
    )

    first = _calibrate(installed_model, scored_on_rmse, workspace)
    second = _calibrate(installed_model, scored_on_mae, workspace)

    assert first["model_sha256"] == before
    assert second["model_sha256"] == before
    assert first["best"] == second["best"]
    assert first["best"]["k_fast"] == pytest.approx(REFERENCE[0])
    assert second["cost"] != pytest.approx(first["cost"], rel=1e-6)
    assert second["cost"] < first["cost"], (first["cost"], second["cost"])


REFUSALS = """
import json
import sys

from hydromodpy.calibration.evaluation import forward_registry
from hydromodpy.calibration.evaluation.forward import ForwardRequest
from hydromodpy.core.contracts.observables import ObservableRequest

model = forward_registry.create(sys.argv[1])
outlet = ObservableRequest(id="gauge", name="discharge", support="boundary", key="outlet")

def refusal(observables, values=None):
    try:
        model.simulate(
            ForwardRequest(trial_id=1, values=values or {}, observables=observables)
        )
    except Exception as exc:
        return {"type": type(exc).__name__, "message": str(exc)}
    return None

cases = {
    "a_variable_it_does_not_serve": [
        (ObservableRequest(id="gauge", name="salinity", support="boundary", key="outlet"),),
        None,
    ],
    "a_support_it_does_not_have": [
        (ObservableRequest(id="gauge", name="discharge", support="lake", key="cheze"),),
        None,
    ],
    "a_cell_that_is_not_its_own": [
        (ObservableRequest(id="piezo", name="head", support="cell", cell=(0, 5, 5)),),
        None,
    ],
    "one_variable_at_two_places": [
        (
            outlet,
            ObservableRequest(id="second", name="discharge", support="cell", cell=(0, 0, 0)),
        ),
        None,
    ],
    "a_parameter_it_cannot_place": [(outlet,), {"k_medium": 0.1}],
    "a_coefficient_that_is_not_positive": [(outlet,), {"k_fast": -1.0}],
}
print("F9D_REFUSALS=" + json.dumps(
    {name: refusal(observables, values) for name, (observables, values) in cases.items()}
))
"""


def test_the_installed_model_refuses_what_it_cannot_answer(
    installed_model: Path, tmp_path: Path
) -> None:
    """The wheel's own guards, exercised where the wheel actually lives.

    The conformance suite holds every model to the two refusals it can ask of
    any implementation. The rest of what this one refuses -- a support it does
    not have, a cell that is not its only one, one variable declared at two
    places -- is particular to a lumped model and has to be exercised against
    this model by name, or deleting a guard would leave the answer wrong and
    nothing red: an unplaced request would come back filled with the outlet's
    own values under another name.
    """
    result = subprocess.run(
        [sys.executable, "-c", REFUSALS, MODEL_ID],
        cwd=tmp_path,
        env=_environment(installed_model),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("F9D_REFUSALS=")]
    assert len(lines) == 1, result.stdout
    refusals = json.loads(lines[0].removeprefix("F9D_REFUSALS="))

    assert set(refusals) == {
        "a_variable_it_does_not_serve",
        "a_support_it_does_not_have",
        "a_cell_that_is_not_its_own",
        "one_variable_at_two_places",
        "a_parameter_it_cannot_place",
        "a_coefficient_that_is_not_positive",
    }
    for name, refusal in refusals.items():
        assert refusal is not None, f"{name}: the model answered instead of refusing"
        assert refusal["type"] == "ValueError", f"{name}: {refusal}"
        assert refusal["message"].strip(), f"{name}: the refusal says nothing"
    assert "salinity" in refusals["a_variable_it_does_not_serve"]["message"]
    assert "lake" in refusals["a_support_it_does_not_have"]["message"]
    assert "0, 5, 5" in refusals["a_cell_that_is_not_its_own"]["message"].replace("(", "").replace(
        ")", ""
    )
    assert "discharge" in refusals["one_variable_at_two_places"]["message"]
    assert "k_medium" in refusals["a_parameter_it_cannot_place"]["message"]


def test_the_registry_driven_conformance_suite_runs_the_installed_model(
    installed_model: Path, tmp_path: Path
) -> None:
    """The port's own suite, against a model no file of ``tests/`` names.

    ``-k`` selects the installed id, so a run that collected nothing would be
    green: the passed count is read back, and a skip is refused outright.
    """
    script = """
import os
from pathlib import Path

import hydromodpy
import pytest
import sys

assert Path(hydromodpy.__file__).is_relative_to(Path(os.environ["HMP_WHEEL_SITE"]))
raise SystemExit(pytest.main(sys.argv[1:]))
"""
    result = subprocess.run(
        [
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
            MODEL_ID,
        ],
        cwd=tmp_path,
        env=_environment(installed_model),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) >= 10, result.stdout
    assert " skipped" not in result.stdout
