"""In-memory calibration run on a project object, and how `Project.calibrate` reaches it.

The loop runs on fakes (no MODFLOW) while the session journal and the report stay real.
Costs are objective values, K is in m/s.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome
from hydromodpy.calibration.optim.fosm import ParameterUncertainty
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import document as document_module
from hydromodpy.calibration.runners import search, session_scope
from hydromodpy.calibration.runners.programmatic_runner import run_calibration_programmatic
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ConfigMissingError
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.project.facade import Project
from hydromodpy.results.session.descriptor import session_descriptor_path
from tests.unit.calibration._factories_runners import make_report

TOML_TEMPLATE = """\
[workspace]
root = "{workspace}"

[simulation]
name = "toy"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflownwt"]

[flow.param.K.field]
value = 1e-4
"""


def _fake_project(cfg_path: Path | None, workspace: Path | None) -> SimpleNamespace:
    """Duck-type the two attributes ``run_calibration_programmatic`` reads of a project.

    These are ``_config_path`` (the source TOML) and ``_ctx.setup.workspace``
    (shared data root plus project catalog root).
    """
    if cfg_path is None:
        # A project built in memory anchors its checks where project.toml would be.
        ctx = SimpleNamespace(config_path=Path.cwd() / "project.toml", setup=None)
        return SimpleNamespace(_config_path=None, _ctx=ctx, _cfg=None)
    workspace = SimpleNamespace(root=workspace, project_root=cfg_path.parent)
    ctx = SimpleNamespace(setup=SimpleNamespace(workspace=workspace))
    return SimpleNamespace(_config_path=cfg_path, _cfg=None, _ctx=ctx)


@pytest.fixture
def project_toml(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    toml = tmp_path / "hydromodpy.toml"
    toml.write_text(TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/")))
    return toml


@pytest.fixture
def fake_project(project_toml, tmp_path) -> SimpleNamespace:
    return _fake_project(project_toml, tmp_path / "ws")


LINEARIZED = {"method": "linearized", "perturbation": 0.01}


def _baseline_cfg(**overrides: object) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "max_trials": 3,
            "method_options": {"points_per_dim": 3},
            "save_runs": "none",
            "objective": "nse",
            "variable": "discharge",
            "use_cache": False,
            "parameters": {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "search_space": "log",
                    "sampling": "log_uniform",
                    "path": "flow.param.K.field.value",
                }
            },
            **overrides,
        }
    )


class _NoModel:
    """An evaluator with no model behind it."""

    evaluator_id = "test_no_model"
    needs_prepared_model = False

    def evaluate(self, request) -> TrialOutcome:
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


def test_width_reaches_the_report_before_promotion(
    fake_project, fake_pipeline, quadratic_metric, monkeypatch
):
    widths = []
    handed = []
    close = session_scope.promote_and_close
    width_of_k = (ParameterUncertainty("K", 2.0e-5, 4.0e-6, {"K": 1.0}),)

    def _width(report, *, cfg, trial_ctx, space, perturbation):
        widths.append((list(space.names), perturbation, trial_ctx is not None))
        return replace(report, parameter_uncertainty=width_of_k)

    def _close(**kwargs):
        handed.append(kwargs["report"].parameter_uncertainty)
        return close(**kwargs)

    monkeypatch.setattr(search, "attach_a_linearized_width", _width)
    monkeypatch.setattr(search, "promote_and_close", _close)
    report = run_calibration_programmatic(
        _baseline_cfg(uncertainty=LINEARIZED), project=fake_project, metric_fn=quadratic_metric
    )

    assert widths == [(["K"], 0.01, True)]
    assert handed == [width_of_k]
    assert report.parameter_uncertainty == width_of_k


def test_no_model_evaluator_is_refused_a_width(fake_project):
    evaluation_registry.evaluators.register(_NoModel, replace=True)
    try:
        with pytest.raises(CalibrationError, match="runs no HydroModPy model"):
            run_calibration_programmatic(
                _baseline_cfg(uncertainty=LINEARIZED, evaluator=_NoModel.evaluator_id),
                project=fake_project,
            )
    finally:
        evaluation_registry.evaluators.unregister(_NoModel.evaluator_id)


def test_phases_resume_the_session_of_the_case(fake_project, tmp_path, monkeypatch):
    """The document is named by the case, so the staged runner reopens the earlier session."""
    opened = []

    def staged(doc_path, *, resume, **_kwargs):
        _, root, _, _, case = document_module.load_calibration_document(doc_path, None)
        session, reopened = open_session_dir(root, case, resume=resume)
        session_descriptor_path(session).write_text("{}")
        opened.append((doc_path, session.name, reopened))
        return make_report()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration", staged
    )
    cfg = _baseline_cfg(phases=[{"name": "k", "parameters": ["K"], "max_trials": 3}])
    for resume in (False, True):
        run_calibration_programmatic(cfg, project=fake_project, resume=resume)

    document = tmp_path / "sessions" / "toy.toml"
    assert opened == [(document, "toy", False), (document, "toy", True)]


@pytest.fixture
def run(fake_project, fake_pipeline, quadratic_metric):
    """Run the in-memory calibration on the fake project; *updates* edit the configuration."""

    def _run(project=None, **updates):
        return run_calibration_programmatic(
            _baseline_cfg().model_copy(update=updates),
            project=project or fake_project,
            metric_fn=quadratic_metric,
        )

    return _run


def test_project_without_config_path(run, tmp_path):
    project = _fake_project(tmp_path / "unused.toml", tmp_path / "ws")
    project._config_path = None
    document = {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path / "ws")},
        "flow": {"param": {"K": {"field": {"value": 1e-4}}}},
    }
    project.config = SimpleNamespace(model_dump=lambda **kwargs: document)

    assert isinstance(run(project), CalibrationReport)


def test_save_runs_all_promotes_every_trial(run, fake_pipeline):
    report = run(save_runs="all")

    assert report.promoted == report.n_trials == 3
    assert len(fake_pipeline) == 3
    assert report.best_sim_id in {row["sim_id"] for row in fake_pipeline}


@pytest.mark.parametrize("in_memory", [False, True], ids=["file_project", "in_memory_project"])
def test_python_mode_calls_the_programmatic_runner(project_toml, tmp_path, in_memory):
    """When parameters= is supplied, calibrate() calls run_calibration_programmatic."""
    proj = _fake_project(None if in_memory else project_toml, tmp_path / "ws")
    sentinel = make_report(n_trials=2, best_cost=0.0)
    with patch(
        "hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic",
        return_value=sentinel,
    ) as mocked:
        result = Project.calibrate(
            proj,
            parameters={"K": {"bounds": [1e-6, 1e-3], "path": "flow.param.K.field.value"}},
            method="grid",
            max_trials=2,
            save_runs="none",
            resume=True,
        )
        assert result is sentinel
        assert mocked.call_count == 1
        kwargs = mocked.call_args.kwargs
        assert kwargs["project"] is proj
        assert kwargs["resume"] is True
        assert "return_report" not in kwargs


@pytest.mark.parametrize(
    ("call", "named"),
    [
        ({"config_path": "c.toml", "max_trials": 10, "seed": 1}, "max_trials, seed"),
        ({"method": "grid", "phases": []}, "phases, method"),
    ],
)
def test_ignored_arguments_are_named(call, named):
    proj = SimpleNamespace(_cfg=SimpleNamespace(calibration=SimpleNamespace()))
    with pytest.raises(ConfigError, match=f"ignores {named} when"):
        Project.calibrate(proj, **call)


def test_an_unknown_option_is_refused():
    proj = SimpleNamespace(_cfg=SimpleNamespace(calibration=SimpleNamespace()), _config_path=None)
    with pytest.raises(TypeError, match="'resum'"):
        Project.calibrate(proj, resum=True)


def test_python_mode_needs_parameters(project_toml, tmp_path):
    proj = _fake_project(project_toml, tmp_path / "ws")

    with pytest.raises(ConfigMissingError, match="parameters="):
        Project.calibrate(proj)
