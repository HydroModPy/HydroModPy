"""Unit tests for :mod:`hydromodpy.calibration.runners.cli_runner`.

Exercises the end-to-end wiring of ``run_calibration_cli`` without
touching MODFLOW: ``prepare_trials`` and ``promote_prepared_trial`` are
monkey-patched to return deterministic stubs, and a custom ``metric_fn``
is injected so each trial returns a closed-form objective. This lets us
verify:

- the session is written under ``sessions/<case>/`` and closed with its status,
- ``save_runs`` modes (``"none"`` / ``"best_n"`` / ``"all"``) promote the
  expected number of trials, to the directories the target names,
- the promoted runs are linked back into ``trials.jsonl``,
- the ``ParamsHashCache`` preloads the trials of an earlier session,
- the ``objective="module.path:fn"`` escape hatch resolves and invokes
  the user-supplied callable,
- an interrupted or failed search closes its session with the right status.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import ParamsHashCache
from hydromodpy.calibration.runners import cli_runner as runner_module
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners.cli_runner import (
    describe_dry_run,
    load_toml_calibration,
    run_calibration_cli,
)
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.session.descriptor import list_session_dirs, read_session
from hydromodpy.results.session.journal import read_trials
from tests._helpers.persisting_simulation import SimulationStub
from tests._helpers.session_documents import session_opening

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
solvers = ["modflow_nwt"]

[flow.param.K.field]
value = 1e-4

[calibration]
method = "grid"
max_trials = 5
save_runs = "{save_runs}"
save_best_n = 2
seed = 42
objective = "nse"
variable = "discharge"
use_cache = true

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
search_space = "log"
sampling = "log_uniform"
path = "flow.param.K.field.value"
"""


def _write(tmp_path: Path, *, save_runs: str, name: str = "run_calibration_k") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    toml = tmp_path / f"{name}.toml"
    toml.write_text(
        TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/"), save_runs=save_runs),
        encoding="utf-8",
    )
    return toml


@pytest.fixture
def calib_toml(tmp_path: Path) -> Path:
    return _write(tmp_path, save_runs="best_n")


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
        from pydantic import BaseModel

        class _Leaf(BaseModel):
            value: float = 1e-4

        class _Field(BaseModel):
            field: _Leaf = _Leaf()

        class _Param(BaseModel):
            K: _Field = _Field()

        class _Flow(BaseModel):
            param: _Param = _Param()

        class _Cfg(BaseModel):
            flow: _Flow = _Flow()
            simulation: SimulationStub = SimulationStub()

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

    def _fake_promote(trial_ctx, values, *, name=None, sim_id=None, run_dir=None, **kwargs):
        del trial_ctx
        promoted.append(
            {
                "sim_id": sim_id,
                "values": dict(values),
                "name": name,
                "run_dir": run_dir,
                "lineage": kwargs.get("lineage"),
                "calibrated_by": kwargs.get("calibrated_by"),
            }
        )
        return sim_id

    monkeypatch.setattr(runner_module, "prepare_trials", _fake_prepare)
    monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fake_promote)
    return promoted


@pytest.fixture
def quadratic_metric():
    """Toy metric: minimum at K = 1e-4 (log midpoint of [1e-6, 1e-3])."""
    import math

    def metric_fn(ctx, *, objective, variable):
        k = ctx.cfg.flow.param.K.field.value
        cost = (math.log10(k) - math.log10(1e-4)) ** 2
        return cost, {"nse@outlet": cost}

    return metric_fn


def _the_session(project: Path):
    (directory,) = list_session_dirs(project)
    return directory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunCalibrationCli:
    def test_run_completes_and_returns_summary(self, calib_toml, fake_pipeline, quadratic_metric):
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric, project="toy_project")
        assert summary.session_id
        assert summary.method == "grid"
        assert summary.n_trials == 5
        assert summary.save_runs == "best_n"
        assert summary.best_cost is not None
        assert summary.best_trial in range(1, 6)
        # best_n with 2: the best to runs/<case>, the next one under the session
        assert summary.promoted == 2
        assert summary.best_rel_dir == "runs/toy"
        assert len(fake_pipeline) == 2

    # The file writes [simulation] name = "toy" itself, so the case is "toy" (D3).
    def test_the_session_sits_under_the_case_and_the_runs_beside_it(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        project = calib_toml.parent
        assert _the_session(project) == project / "sessions" / "toy"
        assert (project / "sessions" / "toy" / "config.toml").is_file()
        dirs = [row["run_dir"] for row in fake_pipeline]
        assert dirs[0] == project / "runs" / "toy"
        assert dirs[1].parent == project / "sessions" / "toy" / "trials"
        assert fake_pipeline[0]["calibrated_by"] is not None
        assert fake_pipeline[0]["lineage"].kind == "promoted"
        assert fake_pipeline[1]["calibrated_by"] is None
        assert fake_pipeline[1]["lineage"].kind == "trial"

    def test_save_runs_none_skips_promotion(self, tmp_path, fake_pipeline, quadratic_metric):
        toml = _write(tmp_path, save_runs="none", name="run")
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary.save_runs == "none"
        assert summary.promoted == 0
        assert fake_pipeline == []
        assert not (tmp_path / "runs").exists()

    def test_save_runs_all_promotes_every_completed(
        self, tmp_path, fake_pipeline, quadratic_metric
    ):
        toml = _write(tmp_path, save_runs="all", name="run")
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary.save_runs == "all"
        # grid with max_trials=5: 5 trials, each one promoted
        assert summary.promoted == 5
        assert len(fake_pipeline) == 5

    def test_the_trials_are_journaled_and_linked_to_their_runs(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        trials = read_trials(_the_session(calib_toml.parent))
        assert [t.trial for t in trials] == [1, 2, 3, 4, 5]
        linked = [t for t in trials if t.only_case.sim_id is not None]
        assert len(linked) == 2
        best = next(t for t in trials if t.trial == summary.best_trial).only_case
        assert best.sim_id == summary.best_sim_id
        assert best.rel_dir == "runs/toy"

    def test_the_session_is_closed_with_its_best(self, calib_toml, fake_pipeline, quadratic_metric):
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        descriptor = read_session(_the_session(calib_toml.parent))
        assert descriptor.status == "completed"
        assert descriptor.case_id == "toy"
        assert descriptor.best is not None
        assert descriptor.best.trial == summary.best_trial
        assert descriptor.only_run.sim_id == summary.best_sim_id
        assert descriptor.only_run.rel_dir == "runs/toy"
        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.status == "completed"
        assert (_the_session(calib_toml.parent) / "README.md").is_file()

    def test_a_second_run_of_the_file_takes_the_next_version(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        assert summary.session_dir.name == "toy.v2"
        assert summary.best_rel_dir == "runs/toy.v2"

    def test_a_dry_run_writes_nothing(self, calib_toml, fake_pipeline):
        plan = describe_dry_run(
            load_toml_calibration(calib_toml)[0], calib_toml, workspace=calib_toml.parent
        )

        assert plan["case"] == "toy"
        assert plan["version"] == "toy"
        assert plan["session_dir"] == "sessions/toy"
        assert plan["phases"][0]["parameters"] == ["K"]
        assert not (calib_toml.parent / "sessions").exists()

    def test_a_dry_run_quotes_the_version_the_session_would_take(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        plan = describe_dry_run(
            load_toml_calibration(calib_toml)[0], calib_toml, workspace=calib_toml.parent
        )

        assert plan["version"] == "toy.v2"
        assert plan["session_dir"] == "sessions/toy.v2"
        assert plan["run_dir"] == "runs/toy.v2"
        assert not (calib_toml.parent / "sessions" / "toy.v2").exists()

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
max_trials = 3
objective = "nse"
variable = "discharge"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
# no path: cannot inject into simulation config
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must declare a 'path'"):
            run_calibration_cli(toml)


class TestCachePreload:
    def test_preload_populates_from_previous_session(
        self, calib_toml, fake_pipeline, quadratic_metric, monkeypatch
    ):
        """The second session sees cache hits for every trial the first one journaled."""
        summary_1 = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        assert summary_1.promoted == 2

        preloaded_snapshot: dict = {}
        from hydromodpy.calibration.runners import state as state_module

        real_preload = state_module.preload_hash_cache

        def spy(project_root, cache):
            n = real_preload(project_root, cache)
            preloaded_snapshot.update(cache._hits)
            return n

        monkeypatch.setattr(runner_module, "preload_hash_cache", spy)

        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)
        assert len(preloaded_snapshot) == 5
        assert all(key.startswith("v2:") for key in preloaded_snapshot)

    def test_preload_ignores_unscoped_hashes(self, tmp_path):
        from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
        from hydromodpy.calibration.persistence import CalibrationPersistence
        from hydromodpy.calibration.runners import state as state_module

        session_dir = tmp_path / "sessions" / "old"
        session_dir.mkdir(parents=True)
        persistence = CalibrationPersistence(session_dir)
        persistence.start_session(
            **session_opening("old", project="p", cost_name="rmse", bounds={})
        )
        for trial_id, params_hash in ((1, "legacyhash"), (2, "v2:scopedhash")):
            persistence.append_iteration(
                ParamSuggestion(trial_id=trial_id, values={"K": 1.0}),
                EvaluationResult(
                    trial_id=trial_id,
                    sim_id=None,
                    cost=float(trial_id),
                    status="completed",
                    components={"rmse": float(trial_id)},
                    metadata={"params_hash": params_hash},
                ),
            )

        cache = ParamsHashCache()
        n_preloaded = state_module.preload_hash_cache(tmp_path, cache)

        assert n_preloaded == 1
        assert "legacyhash" not in cache
        assert "v2:scopedhash" in cache


class TestObjectiveEscapeHatch:
    def test_module_fn_spec_is_loaded_and_invoked(self, calib_toml, fake_pipeline, monkeypatch):
        calls: list[dict] = []

        def my_metric(ctx, *, objective, variable):
            calls.append({"objective": objective, "variable": variable})
            k = ctx.cfg.flow.param.K.field.value
            return float(abs(k - 1e-4)), {}

        import sys
        import types

        mod = types.ModuleType("test_calib_metric_mod")
        mod.my_metric = my_metric
        sys.modules["test_calib_metric_mod"] = mod

        summary = run_calibration_cli(calib_toml, objective="test_calib_metric_mod:my_metric")
        assert summary.n_trials == 5
        assert len(calls) == 5
        assert all(c["variable"] == "discharge" for c in calls)


class TestDefaultEvaluatorIsGone:
    def test_no_default_evaluator_is_exported(self):
        """The user-facing path must not use the mock."""
        import hydromodpy.calibration.runners.cli_runner as runner

        assert not hasattr(runner, "_default_evaluator")


class TestConfigOverridePaths:
    def test_extracts_paths_correctly(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "max_trials": 5,
                "objective": "nse",
                "variable": "discharge",
                "parameters": {
                    "K": {
                        "bounds": [1e-6, 1e-3],
                        "search_space": "log",
                        "path": "flow.param.K.field.value",
                    },
                    "Sy": {
                        "bounds": [0.01, 0.3],
                        "path": "flow.param.Sy.field.value",
                    },
                },
            }
        )
        from hydromodpy.calibration.runners.state import override_paths as resolve_override_paths

        assert resolve_override_paths(cfg) == {
            "K": "flow.param.K.field.value",
            "Sy": "flow.param.Sy.field.value",
        }

    def test_all_parameters_missing_path_raises(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "max_trials": 5,
                "objective": "nse",
                "variable": "discharge",
                "parameters": {
                    "K": {"bounds": [1e-6, 1e-3]},  # no path
                },
            }
        )
        from hydromodpy.calibration.runners.state import override_paths as resolve_override_paths

        with pytest.raises(ValueError, match="must declare a 'path'"):
            resolve_override_paths(cfg)


class TestSessionLifecycle:
    """No zombie ``running`` session on disk: failures and aborts close it."""

    def test_engine_failure_marks_session_failed(self, calib_toml, fake_pipeline, monkeypatch):
        from hydromodpy.calibration.optim import engine as engine_mod

        def boom(self):
            raise RuntimeError("boom from engine")

        monkeypatch.setattr(engine_mod.CalibrationEngine, "run", boom)

        with pytest.raises(RuntimeError, match="boom from engine"):
            run_calibration_cli(calib_toml)

        descriptor = read_session(_the_session(calib_toml.parent))
        assert descriptor.status == "failed"
        assert descriptor.error_message == "boom from engine"
        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.status == "failed"

    def test_keyboard_interrupt_marks_session_aborted(self, calib_toml, fake_pipeline, monkeypatch):
        from hydromodpy.calibration.optim import engine as engine_mod

        def boom(self):
            raise KeyboardInterrupt

        monkeypatch.setattr(engine_mod.CalibrationEngine, "run", boom)

        with pytest.raises(KeyboardInterrupt):
            run_calibration_cli(calib_toml)

        descriptor = read_session(_the_session(calib_toml.parent))
        assert (descriptor.status, descriptor.error_message) == ("aborted", "SIGINT")
        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.status == "aborted"

    @staticmethod
    def _cut_after_two_trials(monkeypatch) -> None:
        """Make the engine raise SIGTERM's exception once two trials are scored."""
        from hydromodpy.calibration.optim import engine as engine_mod
        from hydromodpy.core.interrupts import TerminationRequested

        real_run_until = engine_mod.CalibrationEngine._run_until

        def _cut(self, budget, n_done, session, reporter):
            real_run_until(self, 2, n_done, session, reporter)
            raise TerminationRequested("signal 15")

        monkeypatch.setattr(engine_mod.CalibrationEngine, "_run_until", _cut)

    @staticmethod
    def _metric(ctx, *, objective, variable):
        import math

        k = ctx.cfg.flow.param.K.field.value
        return (math.log10(k) - math.log10(1e-4)) ** 2, {}

    def test_a_termination_points_at_the_best_trial_so_far(
        self, calib_toml, fake_pipeline, monkeypatch
    ):
        """SIGTERM: ``aborted`` and the pointer of the best completed trial.

        The fake pipeline keeps no solve, so nothing is promoted: a replay
        after a signal is left to ``hmp project promote``.
        """
        from hydromodpy.core.interrupts import TerminationRequested

        self._cut_after_two_trials(monkeypatch)

        with pytest.raises(TerminationRequested):
            run_calibration_cli(calib_toml, metric_fn=self._metric)

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert (descriptor.status, descriptor.error_message) == ("aborted", "SIGTERM")
        trials = read_trials(session_dir)
        assert len(trials) == 2
        assert descriptor.best is not None
        assert descriptor.best.trial == min(trials, key=lambda t: t.cost).trial
        assert descriptor.only_run.sim_id is None, "no kept solve: nothing to promote in the margin"
        assert fake_pipeline == []
        assert not (calib_toml.parent / "runs").exists()
        outcome = read_outcome(session_dir)
        assert outcome is not None and outcome.status == "aborted"

    def test_a_termination_promotes_the_best_trial_from_its_kept_solve(
        self, calib_toml, fake_pipeline, monkeypatch
    ):
        """After the pointer is written, the pointed trial is promoted from its kept solve."""
        from hydromodpy.calibration.runners.kept_solves import KeptSolve, TrialSolveRetention
        from hydromodpy.core.interrupts import TerminationRequested

        self._cut_after_two_trials(monkeypatch)
        monkeypatch.setattr(
            TrialSolveRetention,
            "take",
            lambda self, trial_id: (KeptSolve(trial_id=int(trial_id), cost=0.0, folders=()), None),
        )

        with pytest.raises(TerminationRequested):
            run_calibration_cli(calib_toml, metric_fn=self._metric)

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert descriptor.status == "aborted"
        (call,) = fake_pipeline
        assert call["run_dir"] == calib_toml.parent / "runs" / "toy"
        assert call["lineage"].kind == "promoted"
        assert call["calibrated_by"].session_status == "aborted"
        assert call["lineage"].trial == descriptor.best.trial
        run = descriptor.only_run
        assert (run.sim_id, run.rel_dir) == (call["sim_id"], "runs/toy")
        line = {t.trial: t for t in read_trials(session_dir)}[descriptor.best.trial].only_case
        assert (line.sim_id, line.rel_dir) == (call["sim_id"], "runs/toy")

    def test_the_abort_writes_its_pointer_in_under_a_second(self, tmp_path):
        """The pointer of a long session is written before any signal can follow."""
        import time

        from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
        from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
        from hydromodpy.calibration.runners.cli_runner import abort_session
        from hydromodpy.results.session.phase import read_phase

        session_dir = tmp_path / "sessions" / "long"
        session_dir.mkdir(parents=True)
        persistence = CalibrationPersistence(session_dir)
        persistence.start_session(**session_opening("long", project="p", bounds={}))
        for index, name in enumerate(("steady_k", "transient_sy", "transient_n")):
            context = PhaseContext(name, index, 0)
            persistence.start_phase(context, frozen={})
            for trial_id in range(300):
                persistence.append_iteration(
                    ParamSuggestion(trial_id=trial_id, values={"K": 1e-5}),
                    EvaluationResult(
                        trial_id=trial_id,
                        sim_id=None,
                        cost=float(trial_id),
                        status="completed",
                    ),
                    phase=context,
                )
            if index < 2:
                persistence.finish_phase(name, status="completed", best=None)

        started = time.perf_counter()
        pointed = abort_session(persistence, phase="transient_n", error="SIGTERM")
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0, f"the abort took {elapsed:.2f} s"
        assert pointed == "transient_sy", "the last completed phase, not the cut one"
        descriptor = read_session(session_dir)
        assert descriptor.status == "aborted"
        assert descriptor.best is not None and descriptor.best.trial == 301
        assert read_phase(session_dir, "transient_n").status == "aborted"
        assert read_phase(session_dir, "transient_sy").status == "completed"

    def test_all_iterations_crashed_stops_and_marks_failed(self, calib_toml, fake_pipeline):
        """A search that cannot score anything is refused, not run to its budget."""
        from hydromodpy.calibration.runners.failure_watch import EveryTrialFailedError

        def crashing_metric(ctx, *, objective, variable):
            raise RuntimeError("metric blew up")

        with pytest.raises(EveryTrialFailedError, match="metric blew up"):
            run_calibration_cli(calib_toml, metric_fn=crashing_metric)

        session_dir = _the_session(calib_toml.parent)
        assert read_session(session_dir).status == "failed"
        assert len(read_trials(session_dir)) == 5


class TestAFailedPromotion:
    def test_the_report_names_the_failed_promotions_and_keeps_the_search(
        self, calib_toml, fake_pipeline, quadratic_metric, monkeypatch
    ):
        """A promotion that fails leaves the search sound: the report says which one."""
        from hydromodpy.calibration.report import promotion_failures

        def _fail_promote(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("step 'display' failed")

        monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fail_promote)

        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        assert summary.best_parameters
        assert summary.promoted == 0
        failures = summary.extra["promotion_failures"]
        assert len(failures) == 2
        assert all("step 'display' failed" in line for line in failures)
        assert promotion_failures(summary) == failures
        descriptor = read_session(_the_session(calib_toml.parent))
        # The search completed: a promotion failure never writes it failed.
        assert descriptor.status == "partial"
        assert "step 'display' failed" in (descriptor.error_message or "")

    def test_a_calibration_whose_promotions_succeed_names_none(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        from hydromodpy.calibration.report import promotion_failures

        summary = run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        assert "promotion_failures" not in summary.extra
        assert promotion_failures(summary) == []


class TestWhatTheSessionSays:
    def test_the_session_names_the_project_it_ran_in(
        self, calib_toml, fake_pipeline, quadratic_metric
    ):
        """Not the placeholder 'calibration': the project the file sits in."""
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric)

        session_dir = _the_session(calib_toml.parent)
        outcome = read_outcome(session_dir)
        assert outcome is not None and outcome.project == calib_toml.parent.name
        assert read_session(session_dir).cost_name == "nse"

    def test_a_named_project_is_kept(self, calib_toml, fake_pipeline, quadratic_metric):
        run_calibration_cli(calib_toml, metric_fn=quadratic_metric, project="demo")

        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.project == "demo"

    def test_a_search_scored_by_blocks_names_its_blocks_not_the_default_pair(self):
        """A network phase used to journal objective 'nse' on variable 'head'."""
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {
                    "net": {"support": "network", "stream_geometry_path": "streams.gpkg"},
                    "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
                },
                "objective_blocks": [
                    {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
                    {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
                ],
            }
        )

        assert runner_module.session_cost_name(cfg) == "distance_gap + nse_log"

    def test_a_single_metric_search_keeps_the_pair_it_scores(self):
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "objective": "kge",
                "variable": "discharge",
                "outputs": {
                    "discharge": {"support": "point", "observes": "J0014", "variable": "discharge"}
                },
            }
        )

        assert runner_module.session_cost_name(cfg) == "kge"


class TestTheProjectDefaults:
    def test_the_site_gauge_is_the_station_of_the_outputs(self, tmp_path, fake_pipeline):
        from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

        toml = tmp_path / "calage.toml"
        toml.write_text(
            """\
[site]
name = "nancon"
gauge = "NANCON"

[metrics]
window = { start = "2001-01-01", end = "2002-12-31" }

[calibration]
method = "grid"
max_trials = 2

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
path = "flow.param.K.field.value"

[calibration.outputs.gauge]
support = "point"
variable = "discharge"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["gauge"]
""",
            encoding="utf-8",
        )

        cfg, _raw = load_toml_calibration(toml)

        assert cfg.outputs["gauge"].observes == "NANCON"
        assert cfg.observed_station_id == "NANCON"
        assert (cfg.scoring_window.start, cfg.scoring_window.end) == ("2001-01-01", "2002-12-31")

    def test_another_station_than_the_gauge_is_refused_with_both_keys(self, tmp_path):
        from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
        from hydromodpy.core.exceptions import ConfigError

        toml = tmp_path / "calage.toml"
        toml.write_text(
            """\
[site]
name = "nancon"
gauge = "NANCON"

[calibration]
method = "grid"
max_trials = 2
observed_station_id = "OTHER"

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
path = "flow.param.K.field.value"
""",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError, match="site.gauge = 'NANCON'") as caught:
            load_toml_calibration(toml)
        assert "calibration.observed_station_id" in str(caught.value)


class TestAnIntervalOfOneTrial:
    def test_the_log_says_no_other_trial_rather_than_a_zero_width_interval(self, caplog):
        import logging

        from hydromodpy.calibration.optim.cost_margin import ParameterInterval

        interval = ParameterInterval(
            name="K",
            best=1e-6,
            lower=1e-6,
            upper=1e-6,
            margin=0.05,
            kind="relative",
            threshold=0.0179,
            n_within=1,
            n_trials=5,
            reaches_lower_bound=False,
            reaches_upper_bound=False,
        )

        with caplog.at_level(logging.INFO, logger=runner_module.logger.name):
            runner_module._log_parameter_interval(interval, None)

        assert "no other trial within the cost margin" in caplog.text
        assert "[1e-06, 1e-06]" not in caplog.text
