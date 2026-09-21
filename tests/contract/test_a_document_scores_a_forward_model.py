"""The document holds the criteria, the model holds the physics, and they stay apart.

F9c proved that a model installed beside HydroModPy can be calibrated from a
TOML. It also showed what the evaluator port leaves in the implementation's
hands: an evaluator returns a cost, so it is the wheel that decides which
quantity is compared and how the comparison is weighed. Changing either means
editing the wheel.

This file holds the other half. A forward model answers with observables, the
``[calibration.outputs]`` and ``[[calibration.objective_blocks]]`` of the
document score them, and what each test asserts is that a change confined to the
document changes the number the search reports -- the model being byte for byte
the same object in both runs, which is checked rather than assumed.

The model here is the in-tree reference, whose recession is a closed form this
file recomputes independently. What it is worth as physics is beside the point:
what is under test is which side of the frontier decides what.
"""

from __future__ import annotations

import difflib
import hashlib
import math
from pathlib import Path

import pytest

import hydromodpy as hmp
import hydromodpy.calibration.evaluation.forward_registry as forward_registry

INITIAL_STORAGE_M3 = 1_000_000.0
RECESSION_DAYS = 30
"""The reservoir this build ships, restated rather than imported.

A test that read the model's own constants would move with it, and the point of
these documents is that they are written against a published answer.
"""


def _recession_discharge(k: float) -> list[float]:
    """``Q(t) = k * S0 * exp(-k t)``, daily, in m3/day. The closed form, by hand."""
    return [INITIAL_STORAGE_M3 * math.exp(-k * day) * k for day in range(RECESSION_DAYS)]


def _document(
    path: Path,
    workspace: Path,
    *,
    metric: str = "rmse",
    gauge_weight: float = 0.7,
    revised_weight: float = 0.3,
    revised_record_k: float = 1e-3,
    names_the_model: bool = True,
) -> str:
    """Write a calibration document and return its text.

    Two records of one gauge that disagree: the first says the recession ran at
    ``1e-4`` per day, the second at ``revised_record_k``. Both are scored on the
    same outlet, so nothing physical tells them apart and the weights are the
    whole of the arbitration.
    """
    names_model = 'forward_model = "linear_reservoir"\n' if names_the_model else ""
    gauge = ", ".join(repr(value) for value in _recession_discharge(1e-4))
    revised = ", ".join(repr(value) for value in _recession_discharge(revised_record_k))
    text = f"""[workspace]
project_root = "{workspace.as_posix()}"

[calibration]
evaluator = "scored_forward_model"
{names_model}method = "grid"
max_iter = 25
optimizer_kwargs = {{ points_per_dim = 5 }}

[calibration.parameters.k]
path = "flow.properties.k_aquifer"
bounds = [1e-6, 1e-2]
transform = "log"

[calibration.parameters.porosity]
path = "flow.properties.porosity"
bounds = [0.01, 0.3]

[calibration.outputs.gauge_record]
support = "boundary"
variable = "discharge"
boundary_id = "outlet"
time = "all"
observed_values = [{gauge}]

[calibration.outputs.revised_record]
support = "boundary"
variable = "discharge"
boundary_id = "outlet"
time = "all"
observed_values = [{revised}]

[[calibration.objective_blocks]]
name = "gauge"
metric = "{metric}"
uses_outputs = ["gauge_record"]
weight = {gauge_weight}

[[calibration.objective_blocks]]
name = "revised"
metric = "{metric}"
uses_outputs = ["revised_record"]
weight = {revised_weight}
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


def _calibrate(workspace: Path, name: str, **document: object) -> tuple[dict, str]:
    """Run one document to completion and return its report and its text.

    Both runs of a test share one workspace, so the only lines that can differ
    between their documents are the ones the test changed.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / f"{name}.toml"
    text = _document(path, workspace, **document)  # type: ignore[arg-type]
    return hmp.calibrate(str(path)), text


def _model_digest() -> tuple[str, str]:
    """What the registry resolves, as the class it is and the file it comes from.

    Compared across two runs, so "the model was not touched between them" is an
    assertion about the object that answered and not a file read against itself.
    """
    import inspect

    model_cls = forward_registry.get("linear_reservoir")
    source = Path(inspect.getfile(model_cls)).read_text(encoding="utf-8")
    return f"{model_cls.__module__}.{model_cls.__qualname__}", hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def test_the_criterion_of_the_document_moves_the_cost_and_not_the_model(tmp_path: Path) -> None:
    """Two runs, one metric changed, the model file identical before and after.

    ``rmse`` is a distance in m3/day and ``kge`` an efficiency turned into a
    cost, so the same simulations cannot report the same number under both. The
    model is asked for exactly the same observables in both runs: what changed
    is who is scoring.
    """
    before = _model_digest()
    squared_error, first_text = _calibrate(tmp_path, "rmse", metric="rmse")
    efficiency, second_text = _calibrate(tmp_path, "kge", metric="kge")

    assert _changed_lines(first_text, second_text) == [
        '-metric = "rmse"',
        '+metric = "kge"',
        '-metric = "rmse"',
        '+metric = "kge"',
    ]
    assert _model_digest() == before
    assert squared_error["best_parameters"]["k"] == pytest.approx(1e-4)
    assert efficiency["best_parameters"]["k"] == pytest.approx(1e-4)
    assert float(squared_error["best_objective"]) != pytest.approx(
        float(efficiency["best_objective"]), rel=1e-6
    )


def test_the_weights_of_the_document_choose_which_record_the_search_believes(
    tmp_path: Path,
) -> None:
    """Two runs, two weights swapped, and the search lands on a different recession.

    The two records are irreconcilable by construction and each is reproduced
    exactly by one node of the grid, so the weighting is the only thing that can
    decide. A plugin that carried its own objective could not be made to answer
    both ways without being edited.
    """
    before = _model_digest()
    trusts_gauge, first_text = _calibrate(
        tmp_path, "gauge_first", gauge_weight=0.7, revised_weight=0.3
    )
    trusts_revision, second_text = _calibrate(
        tmp_path, "revision_first", gauge_weight=0.3, revised_weight=0.7
    )

    assert _changed_lines(first_text, second_text) == [
        "-weight = 0.7",
        "+weight = 0.3",
        "-weight = 0.3",
        "+weight = 0.7",
    ]
    assert _model_digest() == before
    assert trusts_gauge["best_parameters"]["k"] == pytest.approx(1e-4)
    assert trusts_revision["best_parameters"]["k"] == pytest.approx(1e-3)
    # The same cost on both sides: what the weights moved is which record is
    # believed, not the scale of the number. A search that reported a different
    # cost here would be scoring something the swap was not supposed to touch.
    assert float(trusts_gauge["best_objective"]) == pytest.approx(
        float(trusts_revision["best_objective"]), rel=1e-9
    )


def test_no_hydromodpy_model_is_prepared_for_a_document_that_names_a_forward_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The geographic, mesh and data prefix is never paid for on this route.

    ``needs_prepared_model`` is what the runner reads before building anything,
    and this is the assertion that it is honoured end to end: ``prepare_trials``
    raises if it is called at all, and the search completes.
    """
    import hydromodpy.calibration.runners.cli_runner as cli_runner

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a forward model scored from a document prepared the pipeline")

    monkeypatch.setattr(cli_runner, "prepare_trials", refuse)
    report, _ = _calibrate(tmp_path, "unprepared")

    assert report["n_iterations"] == 25
    assert Path(report["workspace"]) == tmp_path


def test_the_session_records_the_model_the_document_named(tmp_path: Path) -> None:
    """What ran has to be readable afterwards, and a name is what makes it readable.

    Read back from the journal on disk rather than from the report object: the
    question is whether somebody opening the workspace in six months can tell
    which model produced these numbers. The document deliberately names neither
    the model nor a spelling of the evaluator, because a run that recorded the
    empty field it was given would say nothing about what actually answered.
    """
    from hydromodpy.results.session_journal import read_descriptor, session_dirs_for

    report, text = _calibrate(tmp_path, "recorded", names_the_model=False)

    assert "forward_model =" not in text, "the document says nothing, and the default runs"
    sessions = session_dirs_for(tmp_path)
    assert len(sessions) == 1
    descriptor = read_descriptor(sessions[0])
    assert descriptor.session_id == report["session_id"]
    assert descriptor.config["forward_model"] == "linear_reservoir"
    assert descriptor.config["evaluator"] == "scored_forward_model"
