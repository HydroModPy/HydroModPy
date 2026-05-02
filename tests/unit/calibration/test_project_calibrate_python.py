"""Tests for :meth:`hydromodpy.Project.calibrate` Python mode.

Covers Phase 6 of the calibration integration: the in-memory route
through :func:`run_calibration_programmatic`. Verifies that the
``tempfile.mkdtemp`` hack is gone, that ``run_calibration_programmatic``
works against a duck-typed project, and that ``Project.calibrate``
delegates to :func:`run_calibration_cli` when a ``config_path`` is
supplied.

The Project setup is intentionally minimal: we monkey-patch
:func:`prepare_trials` and :func:`promote_trial` (the same fakes used
by ``test_calibration_cli``) so the calibration loop runs without
touching MODFLOW, while the catalog persistence and
:class:`CalibrationReport` assembly remain real. A duck-typed
``_FakeProject`` exposes the source TOML and workspace attributes used by
``run_calibration_programmatic`` so we never have to validate a full
:class:`HydroModPyConfig` in the common path.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from hydromodpy.calibration import CalibrationReport
from hydromodpy.calibration import runner as runner_module
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runner import run_calibration_programmatic

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
type = "flow"
solvers = ["modflownwt"]

[flow.param.K.field_homogeneous]
value = 1e-4
"""


class _FakeProject:
    """Minimal duck-typed Project for ``run_calibration_programmatic``.

    Exposes only the two attributes the public helper reads:
    ``_config_path`` (the source TOML) and ``_ctx.setup.workspace``
    (shared data root plus project catalog root).
    """

    def __init__(self, cfg_path: Path, workspace: Path) -> None:
        self._config_path = cfg_path

        class _Workspace:
            def __init__(self, root: Path, project_root: Path) -> None:
                self.root = root
                self.project_root = project_root

        class _Setup:
            def __init__(self, ws: Path, project_root: Path) -> None:
                self.workspace = _Workspace(ws, project_root)

        class _Ctx:
            def __init__(self, ws: Path, project_root: Path) -> None:
                self.setup = _Setup(ws, project_root)

        self._ctx = _Ctx(workspace, cfg_path.parent)


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Monkey-patch prepare_trials + promote_trial so calls run in seconds."""
    from hydromodpy.calibration.runners.trial import TrialContext

    promoted: list[dict] = []

    class _FakeSetup:
        def __init__(self):
            self.workspace = type(
                "_WS",
                (),
                {"root": tmp_path / "ws", "project_root": tmp_path},
            )()
            self.flow = None
            self.transport = None
            self.flow_runtime_overrides = None

    class _FakeCtx:
        def __init__(self, cfg, config_path, raw_toml):
            self.cfg = cfg
            self.config_path = config_path
            self.raw_toml = raw_toml
            self.setup = _FakeSetup()
            self.loaded_data = type("_LD", (), {})()
            self.data_plan = None

            from hydromodpy.core.state.execution import ExecutionRegistry

            self.execution = ExecutionRegistry()
            self.store = None

    def _fake_prepare(cfg_path, *, override_paths, steps=None, parameter_space=None):
        import tomllib

        with open(cfg_path, "rb") as f:
            raw = tomllib.load(f)
        from pydantic import BaseModel

        class _Leaf(BaseModel):
            value: float = 1e-4

        class _Field(BaseModel):
            field_homogeneous: _Leaf = _Leaf()

        class _Param(BaseModel):
            K: _Field = _Field()

        class _Flow(BaseModel):
            param: _Param = _Param()

        class _Cfg(BaseModel):
            flow: _Flow = _Flow()

        cfg = _Cfg()
        ctx = _FakeCtx(cfg, cfg_path, raw)
        paths = (
            dict(override_paths)
            if isinstance(override_paths, dict)
            else {p: p for p in override_paths}
        )
        return TrialContext(
            base_cfg=cfg,
            ctx=ctx,
            earliest=9,
            downstream_steps=(),
            override_paths=paths,
            workspace=tmp_path,
            cfg_path=cfg_path,
            raw_toml=raw,
        )

    def _fake_promote(cfg_path, values, *, paths=None, name=None, tags=(), session_id=None):
        sim_id = uuid.uuid4().hex
        promoted.append(
            {
                "sim_id": sim_id,
                "values": dict(values),
                "name": name,
                "session_id": session_id,
            }
        )
        return sim_id

    monkeypatch.setattr(runner_module, "prepare_trials", _fake_prepare)
    monkeypatch.setattr(runner_module, "promote_trial", _fake_promote)
    return promoted


@pytest.fixture
def quadratic_metric():
    """Toy metric: minimum at K = 1e-4 (log midpoint of [1e-6, 1e-3])."""
    import math

    def metric_fn(ctx, *, objective, variable):
        k = ctx.cfg.flow.param.K.field_homogeneous.value
        cost = (math.log10(k) - math.log10(1e-4)) ** 2
        return cost, {"nse@outlet": cost}

    return metric_fn


@pytest.fixture
def project_toml(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    toml = tmp_path / "project.toml"
    toml.write_text(TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/")))
    return toml


@pytest.fixture
def fake_project(project_toml, tmp_path) -> _FakeProject:
    return _FakeProject(project_toml, tmp_path / "ws")


def _baseline_cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "max_iter": 3,
            "save_runs": "none",
            "objective": "nse",
            "variable": "discharge",
            "use_cache": False,
            "parameters": {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "transform": "log",
                    "prior": "log_uniform",
                    "path": "flow.param.K.field_homogeneous.value",
                }
            },
        }
    )


# ---------------------------------------------------------------------------
# run_calibration_programmatic
# ---------------------------------------------------------------------------


class TestRunCalibrationProgrammatic:
    def test_returns_calibration_report(self, fake_project, fake_pipeline, quadratic_metric):
        cfg = _baseline_cfg()
        report = run_calibration_programmatic(
            cfg,
            project=fake_project,
            metric_fn=quadratic_metric,
        )
        assert isinstance(report, CalibrationReport)
        assert report.session_id
        assert report.method == "grid"
        assert report.n_iterations >= 1
        assert report.save_runs == "none"

    def test_to_dict_round_trip(self, fake_project, fake_pipeline, quadratic_metric):
        cfg = _baseline_cfg()
        report = run_calibration_programmatic(
            cfg,
            project=fake_project,
            metric_fn=quadratic_metric,
        )
        payload = report.to_dict()
        assert payload["session_id"] == report.session_id
        assert payload["method"] == "grid"

    def test_does_not_create_tempfile(self, fake_project, fake_pipeline, quadratic_metric):
        tempdir = Path(tempfile.gettempdir())
        before = {p.name for p in tempdir.iterdir() if p.name.startswith("hmp_calibrate_")}
        run_calibration_programmatic(
            _baseline_cfg(),
            project=fake_project,
            metric_fn=quadratic_metric,
        )
        after = {p.name for p in tempdir.iterdir() if p.name.startswith("hmp_calibrate_")}
        assert after == before

    def test_accepts_project_without_config_path(self, tmp_path, fake_pipeline, quadratic_metric):
        project = _FakeProject.__new__(_FakeProject)
        project._config_path = None
        project._ctx = _FakeProject(tmp_path / "unused.toml", tmp_path / "ws")._ctx

        class _Config:
            def model_dump(self, **kwargs):
                return {
                    "workflow": "simulation",
                    "workspace": {"root": str(tmp_path / "ws")},
                    "flow": {
                        "param": {
                            "K": {
                                "field_homogeneous": {
                                    "value": 1e-4,
                                }
                            }
                        }
                    },
                }

        project.cfg = _Config()

        report = run_calibration_programmatic(
            _baseline_cfg(),
            project=project,
            metric_fn=quadratic_metric,
        )

        assert isinstance(report, CalibrationReport)

    def test_iterations_persisted(self, fake_project, fake_pipeline, quadratic_metric, tmp_path):
        cfg = _baseline_cfg()
        report = run_calibration_programmatic(
            cfg,
            project=fake_project,
            metric_fn=quadratic_metric,
        )
        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(tmp_path) as catalog:
            rows = catalog.connection.execute(
                "SELECT COUNT(*) FROM calibration_iterations WHERE session_id = ?",
                [uuid.UUID(report.session_id)],
            ).fetchone()
        assert rows[0] == 3

    def test_save_runs_all_promotes_every_completed_iteration(
        self, fake_project, fake_pipeline, quadratic_metric
    ):
        cfg = _baseline_cfg().model_copy(update={"save_runs": "all"})
        report = run_calibration_programmatic(
            cfg,
            project=fake_project,
            metric_fn=quadratic_metric,
        )

        assert report.promoted == report.n_iterations == 3
        assert len(fake_pipeline) == 3
        assert report.best_sim_id in {row["sim_id"] for row in fake_pipeline}

    def test_failed_required_promotion_marks_session_failed(
        self, fake_project, fake_pipeline, quadratic_metric, monkeypatch, tmp_path
    ):
        def _fail_promote(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("promotion unavailable")

        monkeypatch.setattr(runner_module, "promote_trial", _fail_promote)
        cfg = _baseline_cfg().model_copy(update={"save_runs": "all"})

        report = run_calibration_programmatic(
            cfg,
            project=fake_project,
            metric_fn=quadratic_metric,
        )

        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(tmp_path) as catalog:
            row = catalog.connection.execute(
                "SELECT status, error_message FROM calibration_sessions WHERE session_id = ?",
                [uuid.UUID(report.session_id)],
            ).fetchone()
        assert report.promoted == 0
        assert row[0] == "failed"
        assert "promotion unavailable" in row[1]


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
max_iter = 2
save_runs = "none"
objective = "nse"
variable = "discharge"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
path = "flow.param.K.field_homogeneous.value"
"""
        )

        proj = _FakeProject(project_toml, tmp_path / "ws")

        from hydromodpy.project import Project

        with patch.object(runner_module, "run_calibration_cli") as mocked:
            mocked.return_value = {"session_id": "abc", "method": "grid"}
            Project.calibrate(proj, config_path=toml_calib)
            assert mocked.call_count == 1
            called_path = mocked.call_args[0][0]
            assert Path(called_path).name == "calib.toml"


class TestProjectCalibratePythonModeDispatch:
    def test_python_mode_invokes_run_calibration_programmatic(self, project_toml, tmp_path):
        """When parameters= is supplied, calibrate() calls run_calibration_programmatic."""
        proj = _FakeProject(project_toml, tmp_path / "ws")

        from hydromodpy.project import Project

        sentinel = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=2,
            best_objective=0.0,
            best_sim_id=None,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
        )
        with patch(
            "hydromodpy.calibration.runner.run_calibration_programmatic",
            return_value=sentinel,
        ) as mocked:
            result = Project.calibrate(
                proj,
                parameters={
                    "K": {
                        "bounds": [1e-6, 1e-3],
                        "path": "flow.param.K.field_homogeneous.value",
                    }
                },
                method="grid",
                max_iter=2,
                save_runs="none",
            )
            assert result is sentinel
            assert mocked.call_count == 1
            kwargs = mocked.call_args.kwargs
            assert kwargs["project"] is proj
            assert kwargs["return_report"] is True

    def test_python_mode_requires_parameters(self, project_toml, tmp_path):
        proj = _FakeProject(project_toml, tmp_path / "ws")
        from hydromodpy.core.exceptions import ConfigMissingError
        from hydromodpy.project import Project

        with pytest.raises(ConfigMissingError, match="parameters="):
            Project.calibrate(proj)

    def test_python_mode_accepts_in_memory_project(self, tmp_path):
        proj = _FakeProject.__new__(_FakeProject)
        proj._config_path = None
        proj._ctx = None
        from hydromodpy.project import Project

        sentinel = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=2,
            best_objective=0.0,
            best_sim_id=None,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
        )
        with patch(
            "hydromodpy.calibration.runner.run_calibration_programmatic",
            return_value=sentinel,
        ) as mocked:
            result = Project.calibrate(
                proj,
                parameters={
                    "K": {
                        "bounds": [1e-6, 1e-3],
                        "path": "flow.param.K.field_homogeneous.value",
                    }
                },
                method="grid",
                max_iter=2,
                save_runs="none",
            )
            assert result is sentinel
            assert mocked.call_args.kwargs["project"] is proj
