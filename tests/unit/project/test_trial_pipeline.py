"""Tests of `project.trial_pipeline`."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.project.trial_pipeline import (
    WorkflowTrialPipeline,
    fill_trial_pipeline,
)
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


@pytest.fixture
def project_toml(tmp_path: Path) -> Path:
    (tmp_path / "net.gpkg").write_bytes(b"")
    path = tmp_path / "project.toml"
    path.write_text(PROJECT_TOML, encoding="utf-8")
    return path


def test_filling_installs_the_workflow_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", None)
    monkeypatch.setattr(trial_module, "_INITIALIZER", None)

    fill_trial_pipeline()

    installed = trial_module.trial_pipeline()
    assert isinstance(installed, WorkflowTrialPipeline)
    assert trial_module.trial_pipeline_initializer() is not None


def test_the_installed_initializer_resolves_to_the_filler_itself(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", None)
    monkeypatch.setattr(trial_module, "_INITIALIZER", None)

    fill_trial_pipeline()

    module_name, function_name = trial_module.trial_pipeline_initializer().split(":")
    module = importlib.import_module(module_name)
    assert getattr(module, function_name) is fill_trial_pipeline


def test_two_instances_are_equal_because_the_pipeline_carries_no_state() -> None:
    assert WorkflowTrialPipeline() == WorkflowTrialPipeline()


def test_load_document_reads_what_the_loader_reads_with_the_root(project_toml: Path) -> None:
    document = WorkflowTrialPipeline().load_document(project_toml)

    assert document == load_toml_with_base_config(project_toml, root=ROOT_CONFIG)


def test_load_config_reads_what_the_root_class_reads(project_toml: Path) -> None:
    config = WorkflowTrialPipeline().load_config(project_toml)

    assert config == HydroModPyConfig.from_toml(project_toml)


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
