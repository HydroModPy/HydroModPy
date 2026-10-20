"""``hmp calibrate --resume`` reopens the session of the case instead of starting a new one.

A phase that completed there with the same fingerprint is read back, the cut
phase is solved again with its trials preloading the cache, and ``--phase``
runs one phase on top of what the session already holds. The solver never
runs here: :func:`run_calibration_core` and :func:`prepare_trials` are
replaced by a recorder, as in ``test_staged_runner.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext, best_pointer
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.state import preload_hash_cache
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.interrupts import TerminationRequested
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import read_phase
from tests._helpers.persisting_simulation import persisting_simulation

pytestmark = pytest.mark.unit

K_PATH = "flow.param.K.field.value"
K_TOML = 1e-5
SY_TOML = 0.1
K_SOLVED = 2.5e-5
SY_SOLVED = 0.07
K_FROM_DISK = 9.9e-5

BASE = """
[calibration]
method = "grid"
max_trials = 4
save_runs = "none"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0]

[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]

[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_trials = 12
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_trials = 30
parameters = ["Sy"]
objective_blocks = ["q_block"]
depends_on = "steady_k"
"""


def _write(tmp_path: Path, document: str = BASE) -> Path:
    (tmp_path / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    path = tmp_path / "calage.toml"
    path.write_text(document, encoding="utf-8")
    return path


def _baseline() -> SimpleNamespace:
    return SimpleNamespace(
        simulation=persisting_simulation(),
        flow=SimpleNamespace(
            param=SimpleNamespace(
                K=SimpleNamespace(field=SimpleNamespace(value=K_TOML)),
                Sy=SimpleNamespace(field=SimpleNamespace(value=SY_TOML)),
            )
        ),
    )


class FakeRunner:
    """Stands in for the preparation and the calibration loop of one phase."""

    def __init__(self) -> None:
        self.values = {"K": K_SOLVED, "Sy": SY_SOLVED}
        self.objective = 0.1
        self.marker = "v1"
        self.cut_at: str | None = None
        self.calls: list[SimpleNamespace] = []

    @property
    def phases_run(self) -> list[str]:
        return [call.phase.name for call in self.calls]

    def prepare_trials(
        self, cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
    ):
        baseline = _baseline()
        for dotted, value in (config_overrides or {}).items():
            set_by_path(baseline, str(dotted), value)
        return TrialContext(
            base_cfg=baseline,
            ctx=None,
            earliest=0,
            downstream_steps=(),
            override_paths=dict(override_paths),
            workspace=cfg_path.parent,
            cfg_path=cfg_path,
            parameter_space=parameter_space,
        )

    def run_calibration_core(
        self,
        cfg,
        trial_ctx,
        *,
        persistence,
        space,
        project_root,
        cfg_path=None,
        metric_fn=None,
        objective=None,
        phase=None,
        start_at=None,
        interval_width=None,
    ):
        self.calls.append(SimpleNamespace(cfg=cfg, phase=phase, trial_ctx=trial_ctx))
        best = {name: self.values[name] for name in cfg.parameters}
        line = persistence.append_iteration(
            ParamSuggestion(trial_id=1, values=best),
            EvaluationResult(
                trial_id=1,
                sim_id=None,
                objective_value=self.objective,
                status="completed",
                metadata={"params_hash": params_hash(best, context={"marker": self.marker})},
            ),
            phase=phase,
        )
        if phase is not None and phase.name == self.cut_at:
            raise TerminationRequested("signal 15")
        return CalibrationReport(
            session_id=persistence.descriptor.session_id,
            method=cfg.method,
            n_iterations=cfg.max_trials,
            best_objective=self.objective,
            best_sim_id=None,
            best_trial=line.trial,
            duration_s=1.0,
            save_runs="none",
            promoted=0,
            best_parameters=best,
            workspace=project_root,
            session_dir=persistence.directory,
            extra={"search_status": "completed", "search": {"converged": True}},
        )


def _apply(monkeypatch: pytest.MonkeyPatch, fake: FakeRunner, *, marker: str) -> None:
    """Fake the solver and the fingerprint's raw material; keep the guard real."""
    fake.marker = marker
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)
    monkeypatch.setattr(staged_runner, "build_cache_context", lambda **kwargs: {"marker": marker})


def _completed_steady_session(project: Path, *, recorded_marker: str) -> CalibrationPersistence:
    """Write a session of the case whose ``steady_k`` completed, hashed under ``recorded_marker``."""
    session_dir, _ = open_session_dir(project, "calage", resume=False)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="s" * 32,
        case_id="calage",
        site="nancon",
        project="p",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="bisection",
        objective_name="rmse",
        search_space={},
        objective_window=None,
    )
    steady = PhaseContext("steady_k", 0, 0)
    persistence.start_phase(steady, frozen={})
    persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"K": K_FROM_DISK}),
        EvaluationResult(
            trial_id=1,
            sim_id=None,
            objective_value=0.01,
            status="completed",
            metadata={
                "params_hash": params_hash({"K": K_FROM_DISK}, context={"marker": recorded_marker})
            },
        ),
        phase=steady,
    )
    persistence.finish_phase(
        "steady_k", status="completed", best=best_pointer(persistence.best_trial("steady_k"))
    )
    persistence.finalize_session(status="partial", best=None, error="cut at transient_sy")
    return persistence


class TestWithoutResumeEveryPhaseSolvesInANewSession:
    def test_a_completed_session_is_left_alone_and_a_new_one_opens(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert report.session_dir == tmp_path / "sessions" / "calage.v2"
        assert read_session(tmp_path / "sessions" / "calage").status == "partial"


class TestResumeReusesWhatCompleted:
    def test_the_completed_phase_is_read_back_and_the_next_one_solves(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["transient_sy"]
        assert report.reused_from_disk == ("steady_k",)
        assert report.session_dir == tmp_path / "sessions" / "calage"
        assert report.frozen[0].name == "K"
        assert report.frozen[0].value == pytest.approx(K_FROM_DISK)
        assert report.phases[0].report.best_trial == 1

    def test_the_reused_value_is_frozen_into_the_phase_that_still_solves(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        run_staged_calibration(cfg_path, resume=True)

        (transient_call,) = fake.calls
        assert transient_call.trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(
            K_FROM_DISK
        )

    def test_the_trial_numbers_go_on_in_the_same_journal(self, tmp_path, monkeypatch) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        run_staged_calibration(cfg_path, resume=True)

        trials = read_trials(tmp_path / "sessions" / "calage")
        assert [(t.trial, t.phase) for t in trials] == [(1, "steady_k"), (2, "transient_sy")]
        descriptor = read_session(tmp_path / "sessions" / "calage")
        assert descriptor.status == "completed"
        assert descriptor.best is not None and descriptor.best.trial == 2

    def test_a_different_fingerprint_today_re_solves_instead_of_trusting_it(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        # This run's own model/mesh/input-file context ("v2") is not the one the
        # session was scored under ("v1" below): not the same problem.
        _apply(monkeypatch, fake, marker="v2")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert report.frozen[0].value == pytest.approx(K_SOLVED)
        phases = {
            p.name: p for p in CalibrationPersistence(tmp_path / "sessions" / "calage").phases()
        }
        assert phases["steady_k"].restarts == 1, "the re-solved phase counts a restart"

    def test_resume_without_a_session_starts_one(self, tmp_path, monkeypatch) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.session_dir == tmp_path / "sessions" / "calage"


class TestOnePhaseOnTheSession:
    def test_a_phase_runs_alone_when_its_dependency_completed_in_the_session(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.phases_run == ["transient_sy"]
        assert [p.name for p in report.phases] == ["transient_sy"]
        assert fake.calls[0].trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(
            K_FROM_DISK
        )

    def test_a_phase_whose_dependency_never_completed_is_refused(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")

        with pytest.raises(CalibrationError, match="steady_k"):
            run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.calls == []


class TestTheSessionNamesTheMethodsItsPhasesRun:
    def test_a_document_whose_phases_name_their_methods_opens_its_session(
        self, tmp_path, monkeypatch
    ) -> None:
        """No top-level method: the descriptor still names what ran, phase by phase."""
        cfg_path = _write(
            tmp_path, BASE.replace('method = "grid"\nmax_trials = 4', "max_trials = 4")
        )
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")

        report = run_staged_calibration(cfg_path)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert read_session(report.session_dir).method == "bisection + grid"


class _PromotionRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, trial_ctx, values, **kwargs):
        del trial_ctx
        self.calls.append({"values": dict(values), **kwargs})
        return kwargs["sim_id"]


PROMOTING = BASE.replace('save_runs = "none"', 'save_runs = "best_n"')


class TestASessionThatAlreadyPromotedIsReopened:
    def test_a_resume_that_reuses_every_phase_keeps_the_run_it_promoted(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, PROMOTING)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        recorder = _PromotionRecorder()
        monkeypatch.setattr(promotion_module, "promote_prepared_trial", recorder)
        first = run_staged_calibration(cfg_path)
        assert first.promoted == 1 and first.best_rel_dir == "runs/calage"
        assert (tmp_path / "runs" / "calage").is_dir()

        again = run_staged_calibration(cfg_path, resume=True)

        assert again.reused_from_disk == ("steady_k", "transient_sy")
        assert again.promoted == 0, "nothing solved, nothing written again"
        assert again.best_rel_dir == "runs/calage"
        assert again.best_sim_id == first.best_sim_id
        assert len(recorder.calls) == 1
        descriptor = read_session(tmp_path / "sessions" / "calage")
        assert descriptor.status == "completed"
        assert descriptor.best.rel_dir == "runs/calage"

    def test_a_phase_run_again_with_a_better_trial_leaves_the_paired_run_alone(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, PROMOTING)
        fake = FakeRunner()
        _apply(monkeypatch, fake, marker="v1")
        recorder = _PromotionRecorder()
        monkeypatch.setattr(promotion_module, "promote_prepared_trial", recorder)
        first = run_staged_calibration(cfg_path)
        (tmp_path / "runs" / "calage" / "manifest.json").write_text("{}", encoding="utf-8")
        # The model changed since (another fingerprint): the phase is solved
        # again on top of what steady_k passed on, and finds a better trial.
        _apply(monkeypatch, fake, marker="v2")
        fake.objective = 0.05

        again = run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.phases_run == ["steady_k", "transient_sy", "transient_sy"]
        assert again.promoted == 0 and again.best_rel_dir is None
        (failure,) = again.extra["promotion_failures"]
        assert failure.startswith("trial 3: runs/calage already holds trial 2 of this session")
        assert len(recorder.calls) == 1
        assert (tmp_path / "runs" / "calage" / "manifest.json").is_file()
        descriptor = read_session(tmp_path / "sessions" / "calage")
        assert descriptor.status == "partial", "the search is sound; only the run is missing"
        assert "hmp project promote calage --trial 3" in (descriptor.error_message or "")
        by_trial = {line.trial: line for line in read_trials(tmp_path / "sessions" / "calage")}
        assert by_trial[2].sim_id == first.best_sim_id
        assert by_trial[3].rel_dir is None


class TestAnInterruptedStagedSearch:
    def test_the_cut_phase_is_aborted_and_the_pointer_reads_the_completed_one(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg_path = _write(tmp_path, PROMOTING)
        fake = FakeRunner()
        fake.cut_at = "transient_sy"
        _apply(monkeypatch, fake, marker="v1")
        recorder = _PromotionRecorder()
        monkeypatch.setattr(promotion_module, "promote_prepared_trial", recorder)

        with pytest.raises(TerminationRequested):
            run_staged_calibration(cfg_path)

        session_dir = tmp_path / "sessions" / "calage"
        descriptor = read_session(session_dir)
        assert (descriptor.status, descriptor.error_message) == ("aborted", "SIGTERM")
        assert descriptor.best.trial == 1, "the best of steady_k, the last completed phase"
        assert read_phase(session_dir, "steady_k").status == "completed"
        assert read_phase(session_dir, "transient_sy").status == "aborted"
        assert read_phase(session_dir, "transient_sy").best.trial == 2
        # The solve of steady_k went with its phase: its promotion is left to
        # hmp project promote, nothing is written in the margin.
        assert recorder.calls == []
        assert not (tmp_path / "runs").exists()


class TestTheCacheIsPreloadedFromTheJournals:
    def test_every_completed_scoped_trial_of_the_project_enters_the_cache(self, tmp_path) -> None:
        _completed_steady_session(tmp_path, recorded_marker="v1")
        cache = ParamsHashCache()

        assert preload_hash_cache(tmp_path, cache) == 1
        assert params_hash({"K": K_FROM_DISK}, context={"marker": "v1"}) in cache
        assert preload_hash_cache(tmp_path / "nowhere", ParamsHashCache()) == 0


class TestTheOldKeyIsRefused:
    def test_reuse_completed_phases_is_refused_by_name(self) -> None:
        with pytest.raises(ValidationError, match="reuse_completed_phases") as caught:
            CalibrationConfig.model_validate({"reuse_completed_phases": True})

        assert "--resume" in str(caught.value)
