"""The calibration trial pipeline filled by the project: its steps and its refusal when empty."""

from __future__ import annotations

import pytest

from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.project.trial_pipeline import WorkflowTrialPipeline
from hydromodpy.workflow.steps.run_solver import RunSolverStep

PROJECT_TOML = """
[workspace]
[workflow]
mode = "calibration"
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"
[geographic]
source_mode = "synthetic"
[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5
"""


def test_two_instances_are_equal_because_the_pipeline_carries_no_state() -> None:
    assert WorkflowTrialPipeline() == WorkflowTrialPipeline()


def test_the_solver_step_is_the_only_one_the_launcher_replaces() -> None:
    pipeline = WorkflowTrialPipeline()
    steps = tuple(pipeline.standard_steps())

    swapped = pipeline.with_solver_launcher(steps, object())

    assert [step.name for step in swapped] == [step.name for step in steps]
    replaced = [step for step in swapped if isinstance(step, RunSolverStep)]
    assert len(replaced) == 1
    assert all(
        new is old for new, old in zip(swapped, steps, strict=True) if new.name != "run_solver"
    )


def test_a_pipeline_refused_here_is_named_with_what_to_call(monkeypatch) -> None:
    """The refusal of :func:`trial_pipeline` names the filler of this package."""
    monkeypatch.setattr(trial_module, "_PIPELINE", None)

    with pytest.raises(CalibrationError, match="hydromodpy.project.trial_pipeline"):
        trial_module.trial_pipeline()
