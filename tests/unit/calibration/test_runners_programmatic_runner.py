"""Tests of `runners.programmatic_runner`."""

from __future__ import annotations

import math
import tempfile
import tomllib
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hydromodpy.calibration import CalibrationReport
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome
from hydromodpy.calibration.optim.fosm import ParameterUncertainty
from hydromodpy.calibration.runners import cli_runner as cli_runner_module
from hydromodpy.calibration.runners import document as document_module
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import search, session_scope
from hydromodpy.calibration.runners.programmatic_runner import run_calibration_programmatic
from hydromodpy.calibration.runners.session import calibration_case_name, open_session_dir
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ConfigMissingError
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.project.facade import Project
from hydromodpy.results.session.descriptor import read_session, session_descriptor_path
from hydromodpy.results.session.journal import read_trials
from tests.unit.calibration._factories_runners import make_report

# From test_project_calibrate_python.py
# Tests for :meth:`hydromodpy.Project.calibrate` Python mode.
#
# Covers Phase 6 of the calibration integration: the in-memory route
# through :func:`run_calibration_programmatic`. Verifies that the
# ``tempfile.mkdtemp`` hack is gone, that ``run_calibration_programmatic``
# works against a duck-typed project, and that ``Project.calibrate``
# delegates to :func:`run_calibration_cli` when a ``config_path`` is
# supplied.
#
# The Project setup is intentionally minimal: we monkey-patch
# :func:`prepare_trials` and :func:`promote_prepared_trial` (the same fakes used
# by ``test_runners_cli_runner``) so the calibration loop runs without
# touching MODFLOW, while the session journal and
# :class:`CalibrationReport` assembly remain real. A duck-typed
# ``_fake_project`` exposes the source TOML and workspace attributes used by
# ``run_calibration_programmatic`` so we never have to validate a full
# :class:`HydroModPyConfig` in the common path.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# run_calibration_programmatic
# ---------------------------------------------------------------------------
class TestALinearizedWidthWithoutPhases:
    def test_the_width_reaches_the_report_before_the_promotion(
        self, fake_project, fake_pipeline, quadratic_metric, monkeypatch
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

    def test_an_evaluator_with_no_model_is_refused_the_width(self, fake_project):
        evaluation_registry.evaluators.register(_NoModel, replace=True)
        try:
            with pytest.raises(CalibrationError, match="runs no HydroModPy model"):
                run_calibration_programmatic(
                    _baseline_cfg(uncertainty=LINEARIZED, evaluator=_NoModel.evaluator_id),
                    project=fake_project,
                )
        finally:
            evaluation_registry.evaluators.unregister(_NoModel.evaluator_id)


def test_a_call_with_phases_resumes_the_session_of_its_case(fake_project, tmp_path, monkeypatch):
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


def test_a_project_on_a_file_names_its_case_as_the_cli_does(tmp_path, monkeypatch):
    """The name a parent writes is not the case: ``hmp calibrate run.toml`` writes sessions/run."""
    (tmp_path / "base.toml").write_text('[simulation]\nname = "inherited"\n')
    run_file = tmp_path / "run.toml"
    run_file.write_text('base_config = "base.toml"\n[calibration]\nseed = 1\n')
    seen = []

    def staged(doc_path, **_kwargs):
        seen.append((doc_path, document_module.load_calibration_document(doc_path, None)[4]))
        return make_report()

    monkeypatch.setattr(
        "hydromodpy.calibration.runners.staged_runner.run_staged_calibration", staged
    )
    cfg = _baseline_cfg(phases=[{"name": "k", "parameters": ["K"], "max_trials": 3}])

    run_calibration_programmatic(cfg, project=_fake_project(run_file, tmp_path))

    assert calibration_case_name(run_file) == "run"
    assert seen == [(tmp_path / "sessions" / "run.toml", "run")]
    written = tomllib.loads(seen[0][0].read_text(encoding="utf-8"))
    assert written["simulation"]["name"] == "run"


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


class TestRunCalibrationProgrammatic:
    def test_returns_calibration_report(self, run):
        report = run()

        assert isinstance(report, CalibrationReport)
        assert report.session_id
        assert report.method == "grid"
        assert report.n_trials >= 1
        assert report.save_runs == "none"

    def test_to_dict_round_trip(self, run):
        report = run()
        payload = report.to_dict()

        assert payload["session_id"] == report.session_id
        assert payload["method"] == "grid"

    def test_does_not_create_tempfile(self, run):
        tempdir = Path(tempfile.gettempdir())
        before = {p.name for p in tempdir.iterdir() if p.name.startswith("hmp_calibrate_")}
        run()
        after = {p.name for p in tempdir.iterdir() if p.name.startswith("hmp_calibrate_")}
        assert after == before

    def test_accepts_project_without_config_path(self, run, tmp_path):
        project = _fake_project(tmp_path / "unused.toml", tmp_path / "ws")
        project._config_path = None
        document = {
            "workflow": {"mode": "simulation"},
            "workspace": {"root": str(tmp_path / "ws")},
            "flow": {"param": {"K": {"field": {"value": 1e-4}}}},
        }
        project.config = SimpleNamespace(model_dump=lambda **kwargs: document)

        assert isinstance(run(project), CalibrationReport)

    def test_iterations_persisted(self, run, tmp_path):
        report = run()

        # The case takes the simulation name the project file writes; the session
        # sits at the project root the fake declares.
        assert report.session_dir == tmp_path / "sessions" / "toy"
        assert read_session(report.session_dir).session_id == report.session_id
        assert len(read_trials(report.session_dir)) == 3

    def test_save_runs_all_promotes_every_completed_iteration(self, run, fake_pipeline):
        report = run(save_runs="all")

        assert report.promoted == report.n_trials == 3
        assert len(fake_pipeline) == 3
        assert report.best_sim_id in {row["sim_id"] for row in fake_pipeline}

    def test_a_failed_promotion_closes_the_session_partial(self, run, monkeypatch):
        def _fail_promote(*args, **kwargs):
            raise RuntimeError("promotion unavailable")

        monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fail_promote)

        report = run(save_runs="all")

        descriptor = read_session(report.session_dir)
        assert report.promoted == 0
        assert descriptor.status == "partial", "the search completed; only the runs are missing"
        assert "promotion unavailable" in (descriptor.error_message or "")


# ---------------------------------------------------------------------------
# Project.calibrate dispatch
# ---------------------------------------------------------------------------
class TestProjectCalibrateTomlModeDelegates:
    def test_with_config_path_delegates_to_cli(self, project_toml, tmp_path):
        """When config_path= is supplied, calibrate() calls run_calibration_cli."""
        toml_calib = tmp_path / "calib.toml"
        toml_calib.write_text(
            f"""\
base_config = "{project_toml.as_posix()}"

[calibration]
method = "grid"
max_trials = 2
save_runs = "none"
objective = "nse"
variable = "discharge"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
"""
        )

        proj = _fake_project(project_toml, tmp_path / "ws")

        with patch.object(cli_runner_module, "run_calibration_cli") as mocked:
            mocked.return_value = {"session_id": "abc", "method": "grid"}
            Project.calibrate(proj, config_path=toml_calib)
            assert mocked.call_count == 1
            called_path = mocked.call_args[0][0]
            assert Path(called_path).name == "calib.toml"


class TestProjectCalibratePythonModeDispatch:
    @pytest.mark.parametrize("in_memory", [False, True], ids=["file_project", "in_memory_project"])
    def test_python_mode_invokes_run_calibration_programmatic(
        self, project_toml, tmp_path, in_memory
    ):
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
    def test_arguments_the_mode_ignores_are_refused_by_name(self, call, named):

        proj = SimpleNamespace(_cfg=SimpleNamespace(calibration=SimpleNamespace()))
        with pytest.raises(ConfigError, match=f"ignores {named} when"):
            Project.calibrate(proj, **call)

    def test_an_unknown_option_is_refused_on_a_declaration_read_from_the_config(self):

        proj = SimpleNamespace(
            _cfg=SimpleNamespace(calibration=SimpleNamespace()), _config_path=None
        )
        with pytest.raises(TypeError, match="'resum'"):
            Project.calibrate(proj, resum=True)

    def test_python_mode_requires_parameters(self, project_toml, tmp_path):
        proj = _fake_project(project_toml, tmp_path / "ws")

        with pytest.raises(ConfigMissingError, match="parameters="):
            Project.calibrate(proj)
