"""Unit tests for the rewritten :mod:`hydromodpy.calibration.runner`.

Exercises the end-to-end wiring of ``run_calibration_cli`` without
touching MODFLOW: ``prepare_trials`` and ``promote_prepared_trial`` are
monkey-patched to return deterministic stubs, and a custom ``metric_fn``
is injected so each trial returns a closed-form objective. This lets us
verify:

- session + iteration rows land in the DuckDB calibration tables,
- ``save_runs`` modes (``"none"`` / ``"best_n"`` / ``"all"``) promote the
  expected number of trials,
- promoted ``sim_id`` values are back-filled into
  ``calibration_iterations``,
- the ``ParamsHashCache`` preloads previously-promoted objective values
  at the start of a new session,
- the ``objective="module.path:fn"`` escape hatch resolves and invokes
  the user-supplied callable.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.calibration import runner as runner_module
from hydromodpy.calibration.cache import ParamsHashCache
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runner import run_calibration_cli

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

[calibration]
method = "grid"
max_iter = 5
save_runs = "{save_runs}"
save_best_n = 2
seed = 42
objective = "nse"
variable = "discharge"
use_cache = true

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
transform = "log"
prior = "log_uniform"
path = "flow.param.K.field_homogeneous.value"
"""


@pytest.fixture
def calib_toml(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    toml = tmp_path / "run_calibration_k.toml"
    toml.write_text(
        TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/"), save_runs="best_n"),
        encoding="utf-8",
    )
    return toml


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Monkey-patch prepare_trials + promote_prepared_trial so the CLI runs in seconds."""
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
        # Toy config - we only need something Pydantic-friendly downstream.
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
            earliest=9,  # never run downstream - our metric_fn ignores ctx
            downstream_steps=(),
            override_paths=paths,
            workspace=tmp_path,
            cfg_path=cfg_path,
            raw_toml=raw,
        )

    def _fake_promote(trial_ctx, values, *, name=None, tags=(), session_id=None):
        del trial_ctx, tags
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
    monkeypatch.setattr(runner_module, "promote_prepared_trial", _fake_promote)
    return promoted


@pytest.fixture
def quadratic_metric():
    """Toy metric: minimum at K ≈ 1e-4 (log midpoint of [1e-6, 1e-3])."""
    import math

    def metric_fn(ctx, *, objective, variable):
        k = ctx.cfg.flow.param.K.field_homogeneous.value
        cost = (math.log10(k) - math.log10(1e-4)) ** 2
        return cost, {"nse@outlet": cost}

    return metric_fn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunCalibrationCli:
    def test_run_completes_and_returns_summary(self, calib_toml, fake_pipeline, quadratic_metric):
        summary = run_calibration_cli(
            calib_toml,
            metric_fn=quadratic_metric,
            project="toy_project",
        )
        assert summary["session_id"]
        assert summary["method"] == "grid"
        assert summary["n_iterations"] == 5
        assert summary["save_runs"] == "best_n"
        assert summary["best_objective"] is not None
        # best_n with 2 → 2 promotions
        assert summary["promoted"] == 2
        assert len(fake_pipeline) == 2

    def test_save_runs_none_skips_promotion(
        self, tmp_path, monkeypatch, fake_pipeline, quadratic_metric
    ):
        ws = tmp_path / "ws"
        ws.mkdir()
        toml = tmp_path / "run.toml"
        toml.write_text(
            TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/"), save_runs="none"),
            encoding="utf-8",
        )
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary["save_runs"] == "none"
        assert summary["promoted"] == 0
        assert fake_pipeline == []

    def test_save_runs_all_promotes_every_completed(
        self, tmp_path, fake_pipeline, quadratic_metric
    ):
        ws = tmp_path / "ws"
        ws.mkdir()
        toml = tmp_path / "run.toml"
        toml.write_text(
            TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/"), save_runs="all"),
            encoding="utf-8",
        )
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary["save_runs"] == "all"
        # grid with max_iter=5 → 5 trials, each one promoted
        assert summary["promoted"] == 5
        assert len(fake_pipeline) == 5

    def test_iterations_persisted_to_duckdb(self, calib_toml, fake_pipeline, quadratic_metric):
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = calib_toml.parent
        with SimulationCatalog(workspace_root) as catalog:
            rows = catalog.connection.execute(
                "SELECT COUNT(*) FROM calibration_iterations WHERE session_id = ?",
                [uuid.UUID(summary["session_id"])],
            ).fetchone()
            assert rows[0] == 5
            # best_n=2 means 2 rows should have non-null sim_id
            rows = catalog.connection.execute(
                "SELECT COUNT(*) FROM calibration_iterations "
                "WHERE session_id = ? AND sim_id IS NOT NULL",
                [uuid.UUID(summary["session_id"])],
            ).fetchone()
            assert rows[0] == 2

    def test_session_row_is_finalized(self, calib_toml, fake_pipeline, quadratic_metric):
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = calib_toml.parent
        with SimulationCatalog(workspace_root) as catalog:
            row = catalog.connection.execute(
                "SELECT status, n_iterations, best_objective, best_sim_id "
                "FROM calibration_sessions WHERE session_id = ?",
                [uuid.UUID(summary["session_id"])],
            ).fetchone()
        assert row[0] == "completed"
        assert row[1] == 5
        assert row[2] is not None
        # best_sim_id back-filled from promotion
        assert row[3] is not None

    def test_missing_calibration_section_raises(self, tmp_path, fake_pipeline):
        toml = tmp_path / "bad.toml"
        toml.write_text("[simulation]\nname = 'nope'\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No \\[calibration\\] section"):
            run_calibration_cli(toml)

    def test_parameters_without_path_raises(self, tmp_path, fake_pipeline):
        toml = tmp_path / "pathless.toml"
        toml.write_text(
            """\
[calibration]
method = "grid"
max_iter = 3
objective = "nse"
variable = "discharge"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
# no path → cannot inject into simulation config
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must declare a 'path'"):
            run_calibration_cli(toml)


class TestCachePreload:
    def test_preload_populates_from_previous_session(
        self, calib_toml, fake_pipeline, quadratic_metric, monkeypatch
    ):
        """The second session should see cache hits for every trial already
        promoted in the first session."""
        # Session 1: populate the DB
        summary_1 = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        assert summary_1["promoted"] == 2

        # Intercept cache to observe what gets preloaded.
        preloaded_snapshot: dict = {}
        real_preload = runner_module._preload_hash_cache

        def spy(conn, cache):
            n = real_preload(conn, cache)
            preloaded_snapshot.update(cache._hits)
            return n

        monkeypatch.setattr(runner_module, "_preload_hash_cache", spy)

        # Session 2 - same TOML, cache should preload.
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        # Each promoted row should have left a params_hash cache entry that
        # the second session's preload picked up.
        assert len(preloaded_snapshot) >= 2
        assert all(key.startswith("v2:") for key in preloaded_snapshot)

    def test_preload_ignores_legacy_unscoped_hashes(self):
        import duckdb

        conn = duckdb.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE calibration_iterations (
                params_hash VARCHAR,
                sim_id VARCHAR,
                objective_value DOUBLE,
                status VARCHAR,
                metrics JSON
            )
            """
        )
        conn.execute(
            """
            INSERT INTO calibration_iterations VALUES
                ('legacyhash', NULL, 1.0, 'completed', NULL),
                ('v2:scopedhash', NULL, 2.0, 'completed', '{"rmse": 2.0}')
            """
        )

        cache = ParamsHashCache()
        n_preloaded = runner_module._preload_hash_cache(conn, cache)

        assert n_preloaded == 1
        assert "legacyhash" not in cache
        assert "v2:scopedhash" in cache


class TestObjectiveEscapeHatch:
    def test_module_fn_spec_is_loaded_and_invoked(self, calib_toml, fake_pipeline, monkeypatch):
        calls: list[dict] = []

        def my_metric(ctx, *, objective, variable):
            calls.append({"objective": objective, "variable": variable})
            # deterministic value based on K
            k = ctx.cfg.flow.param.K.field_homogeneous.value
            return float(abs(k - 1e-4)), {}

        # Register in a temporary module so importlib can find it.
        import sys
        import types

        mod = types.ModuleType("test_calib_metric_mod")
        mod.my_metric = my_metric
        sys.modules["test_calib_metric_mod"] = mod

        summary = run_calibration_cli(
            calib_toml,
            objective="test_calib_metric_mod:my_metric",
        )
        assert summary["n_iterations"] == 5
        assert len(calls) == 5
        assert all(c["variable"] == "discharge" for c in calls)


class TestDefaultEvaluatorIsGone:
    def test_no_default_evaluator_is_exported(self):
        """The P1→P2 contract: the user-facing path must not use the mock."""
        import hydromodpy.calibration.runner as runner

        assert not hasattr(runner, "_default_evaluator")


class TestConfigOverridePaths:
    def test_extracts_paths_correctly(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "max_iter": 5,
                "objective": "nse",
                "variable": "discharge",
                "parameters": {
                    "K": {
                        "bounds": [1e-6, 1e-3],
                        "transform": "log",
                        "path": "flow.param.K.value",
                    },
                    "Sy": {
                        "bounds": [0.01, 0.3],
                        "path": "flow.param.Sy.value",
                    },
                },
            }
        )
        assert runner_module._override_paths(cfg) == {
            "K": "flow.param.K.value",
            "Sy": "flow.param.Sy.value",
        }

    def test_all_parameters_missing_path_raises(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "max_iter": 5,
                "objective": "nse",
                "variable": "discharge",
                "parameters": {
                    "K": {"bounds": [1e-6, 1e-3]},  # no path
                },
            }
        )
        with pytest.raises(ValueError, match="must declare a 'path'"):
            runner_module._override_paths(cfg)


class TestSessionLifecycle:
    """No zombie ``status='running'`` rows: failures and aborts must finalize."""

    def _read_session(self, workspace_root, session_id):
        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(workspace_root) as catalog:
            return catalog.connection.execute(
                "SELECT status, error_message, n_iterations "
                "FROM calibration_sessions WHERE session_id = ?",
                [uuid.UUID(session_id)],
            ).fetchone()

    def test_engine_failure_marks_session_failed(self, calib_toml, fake_pipeline, monkeypatch):
        from hydromodpy.calibration import engine as engine_mod

        def boom(self):
            raise RuntimeError("boom from engine")

        monkeypatch.setattr(engine_mod.CalibrationEngine, "run", boom)

        from hydromodpy.calibration.persistence import CalibrationPersistence

        captured: list[str] = []
        real_start = CalibrationPersistence.start_session

        def spy_start(self, *, session_id, **kw):
            captured.append(session_id)
            return real_start(self, session_id=session_id, **kw)

        monkeypatch.setattr(CalibrationPersistence, "start_session", spy_start)

        with pytest.raises(RuntimeError, match="boom from engine"):
            run_calibration_cli(calib_toml)

        assert captured, "start_session should have been invoked"
        row = self._read_session(calib_toml.parent, captured[-1])
        assert row[0] == "failed"
        assert row[1] == "boom from engine"
        assert row[2] == 0

    def test_keyboard_interrupt_marks_session_aborted(self, calib_toml, fake_pipeline, monkeypatch):
        from hydromodpy.calibration import engine as engine_mod

        def boom(self):
            raise KeyboardInterrupt

        monkeypatch.setattr(engine_mod.CalibrationEngine, "run", boom)

        from hydromodpy.calibration.persistence import CalibrationPersistence

        captured: list[str] = []
        real_start = CalibrationPersistence.start_session

        def spy_start(self, *, session_id, **kw):
            captured.append(session_id)
            return real_start(self, session_id=session_id, **kw)

        monkeypatch.setattr(CalibrationPersistence, "start_session", spy_start)

        with pytest.raises(KeyboardInterrupt):
            run_calibration_cli(calib_toml)

        row = self._read_session(calib_toml.parent, captured[-1])
        assert row[0] == "aborted"
        assert row[1] == "SIGINT"

    def test_all_iterations_crashed_marks_failed(self, calib_toml, fake_pipeline):
        def crashing_metric(ctx, *, objective, variable):
            raise RuntimeError("metric blew up")

        summary = run_calibration_cli(calib_toml, metric_fn=crashing_metric)
        row = self._read_session(calib_toml.parent, summary["session_id"])
        assert row[0] == "failed"
        assert row[2] == 5
