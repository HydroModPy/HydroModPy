"""Tests of `runners.promotion`."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import DEFAULT_PHASE, CalibrationPersistence, PhaseContext
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import staged_runner as staged_module
from hydromodpy.calibration.runners import state as state_module
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.kept_solves import KeptSolve
from hydromodpy.calibration.runners.promotion import (
    PromotionOutcome,
    promote_best_after_abort,
    promote_phase_best,
    promote_session,
    promote_trial_from_session,
    promotion_name_check,
    prune_session,
    select_trials_to_promote,
    stored_parameter_value,
    trials_to_prune,
)
from hydromodpy.calibration.runners.session_scope import promote_and_close
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import FrozenValue
from tests._helpers.session_documents import calibration_window, session_opening
from tests.unit.calibration._factories_runners import (
    STEADY_K,
    TRANSIENT_SY,
    calibration_head,
    journal_trial,
    make_report,
    make_session,
    phases_toml,
)

# From test_a_promotion_without_a_catalog_says_nothing_was_written.py
# A promotion that cannot write a run says so instead of handing out a ``sim_id``.
#
# With ``[simulation.results.persistence] save_catalog = false`` a run opens no
# directory and writes no seal. The default ``save_runs = "best_n"`` still asked
# for the best trial to become ``runs/<case>/``: the promotion returned a
# ``sim_id``, the journal line pointed at an empty folder and nothing told the
# user. The pipeline is replaced by a recorder, as in ``test_runners_promotion.py``.


def _trial_ctx(*, save_catalog: bool) -> Any:
    persistence = SimpleNamespace(save_catalog=save_catalog)
    results = SimpleNamespace(persistence=persistence)
    base_cfg = SimpleNamespace(simulation=SimpleNamespace(results=results))
    return SimpleNamespace(kept_solves=None, base_cfg=base_cfg)


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(promotion_module, "promote_prepared_trial", rec)
    return rec


def test_a_run_that_cannot_be_written_gets_no_sim_id_and_a_named_reason(
    tmp_path, recorder, caplog
) -> None:
    persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

    with caplog.at_level(logging.WARNING):
        outcome = promote_session(
            cfg=_cfg(save_best_n=2),
            trial_ctx=_trial_ctx(save_catalog=False),
            persistence=persistence,
            project_root=tmp_path,
            phase="main",
            session_status="completed",
            override_paths={"K": K_PATH},
        )

    assert (outcome.count, outcome.best_sim_id, outcome.best_rel_dir) == (0, None, None)
    (failure,) = outcome.failures
    assert "save_catalog" in failure
    assert "save_runs" in failure
    assert recorder.calls == []
    assert all(
        line.only_case.sim_id is None and line.only_case.rel_dir is None
        for line in read_trials(persistence.directory)
    )
    assert "save_catalog" in caplog.text


def test_the_best_of_a_phase_is_not_promoted_without_a_catalog(tmp_path, recorder) -> None:
    persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

    sim_id = promote_phase_best(
        trial_ctx=_trial_ctx(save_catalog=False),
        persistence=persistence,
        phase="main",
        override_paths={"K": K_PATH},
    )

    assert sim_id is None
    assert recorder.calls == []


# From test_a_tie_names_the_same_trial_in_a_replay.py
# Two trials at the same cost: the kept run and its replay name the same one.
#
# The smaller trial number wins a tie, and a parallel batch is numbered in the
# order the optimizer made it, before any worker starts. A second session on
# the same search then gives each candidate the same number, so the run kept
# by one session and the run a replay writes are the same trial.


PHASE = PhaseContext("k_grid", 0, 0)


class _OneBatch:
    """Serve one batch of suggestions, then converge."""

    name = "one_batch"

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._told: list[EvaluationResult] = []

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        batch = [
            ParamSuggestion(trial_id=index, values={"K": value})
            for index, value in enumerate(self._values[:n])
        ]
        self._values = self._values[n:]
        return batch

    def tell(self, results: list[EvaluationResult]) -> None:
        self._told.extend(results)

    def best(self) -> EvaluationResult | None:
        return min(self._told, key=lambda r: r.cost) if self._told else None

    def converged(self) -> bool:
        return bool(self._told)


# From test_promotion.py
# What a promotion writes: the calibrated run beside its session, the kept trials inside it.
#
# The pipeline is replaced by a recorder: what is under test is where each
# promoted trial goes, what the run is told about its session, and what the
# journal says afterwards. The equality of a promoted run with a replay on a
# real model is ``tests/e2e/test_a_promoted_trial_is_not_solved_again_e2e.py``.


K_PATH = "flow.param.K.field.value"
WINDOW = calibration_window(date(2001, 1, 1), date(2002, 12, 31))


def _cfg(**updates: Any) -> CalibrationConfig:
    payload = {
        "method": "grid",
        "max_trials": 3,
        "objective": "nse",
        "variable": "discharge",
        "use_cache": False,
        "parameters": {"K": {"bounds": [1e-6, 1e-3], "search_space": "log", "path": K_PATH}},
    }
    payload.update(updates)
    return CalibrationConfig.model_validate(payload)


def _session(
    project: Path,
    *,
    costs: dict[int, float],
    name: str = "calage",
    hashed_under: str | None = None,
) -> CalibrationPersistence:
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    session_dir = reserve_version_dirname(project, "session", name)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        **session_opening(
            name,
            site="nancon",
            project=project.name,
            windows=WINDOW,
        )
    )
    for trial_id, cost in costs.items():
        values = {"K": 10.0**-trial_id}
        metadata = (
            {"params_hash": params_hash(values, context={"marker": hashed_under})}
            if hashed_under is not None
            else None
        )
        journal_trial(persistence, trial_id, cost, values=values, metadata=metadata)
    return persistence


FROZEN_CONFIG = """\
[site]
name = "nancon"

[calibration]
method = "grid"
max_trials = 3
objective = "nse"
variable = "discharge"
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
"""


def _freeze(persistence: CalibrationPersistence) -> None:
    (persistence.directory / "config.toml").write_text(FROZEN_CONFIG, encoding="utf-8")


def _persisting_cfg(**extra: Any) -> SimpleNamespace:
    """A base configuration whose runs persist, as a project file by default."""
    results = SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
    return SimpleNamespace(simulation=SimpleNamespace(results=results), **extra)


def _fake_prepare(
    cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
):
    return TrialContext(
        base_cfg=_persisting_cfg(),
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=dict(override_paths),
        workspace=cfg_path.parent,
        cfg_path=cfg_path,
        parameter_space=parameter_space,
    )


def _replay_under(monkeypatch, marker: str) -> None:
    """Stand the model preparation and the fingerprint context in, as a replay sees them."""
    monkeypatch.setattr(trial_module, "prepare_trials", _fake_prepare)
    monkeypatch.setattr(state_module, "build_cache_context", lambda **kwargs: {"marker": marker})


class _Recorder:
    """What ``promote_prepared_trial`` was asked for, promotion by promotion."""

    def __init__(self, *, fail_on: set[int] = frozenset()) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_on = fail_on

    def __call__(self, trial_ctx, values, **kwargs):
        del trial_ctx
        self.calls.append({"values": dict(values), **kwargs})
        trial = kwargs["lineage"].trial
        if trial in self.fail_on:
            raise RuntimeError(f"solver did not converge on trial {trial}")
        return kwargs["sim_id"]


def _promote(project: Path, persistence, *, cfg: CalibrationConfig, status: str = "completed"):
    return promote_session(
        cfg=cfg,
        trial_ctx=SimpleNamespace(kept_solves=None, base_cfg=_persisting_cfg()),
        persistence=persistence,
        project_root=project,
        phase="main",
        session_status=status,
        override_paths={"K": K_PATH},
    )


class TestTheCaseIsNamedByTheFileThatCarriesCalibration:
    def test_a_name_too_long_for_a_run_folder_is_refused_before_the_search(self) -> None:
        with pytest.raises(CalibrationError, match="Shorten"):
            promotion_name_check("n" * 95)


class TestWhatSaveRunsSelects:
    def test_best_n_takes_the_n_best_and_all_takes_every_completed_one(self, tmp_path) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

        assert [
            row["trial"]
            for row in select_trials_to_promote(_cfg(save_best_n=2), persistence, "main")
        ] == [2, 3]
        assert [
            row["trial"]
            for row in select_trials_to_promote(_cfg(save_runs="all"), persistence, "main")
        ] == [2, 3, 1]
        assert select_trials_to_promote(_cfg(save_runs="none"), persistence, "main") == []


class TestWhereThePromotedRunsGo:
    def test_the_best_takes_the_run_paired_with_the_session(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))

        assert outcome == PromotionOutcome(
            count=1,
            failures=[],
            best_sim_id=recorder.calls[0]["sim_id"],
            best_rel_dir="runs/calage",
        )
        (call,) = recorder.calls
        assert call["run_dir"] == tmp_path / "runs" / "calage"
        assert call["run_dir"].is_dir()
        assert call["name"] == "calage"
        assert call["values"] == {"K": pytest.approx(1e-2)}
        assert call["lineage"].kind == "promoted"
        assert "keep_per_cell_budget" not in call

    def test_the_other_kept_trials_go_under_the_session_with_the_consumers_budget(
        self, tmp_path, recorder
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=3))

        assert outcome.count == 3
        dirs = [call["run_dir"] for call in recorder.calls]
        assert dirs == [
            tmp_path / "runs" / "calage",
            tmp_path / "sessions" / "calage" / "trials" / "0003",
            tmp_path / "sessions" / "calage" / "trials" / "0001",
        ]
        assert all(path.is_dir() for path in dirs)
        assert all("keep_per_cell_budget" not in call for call in recorder.calls)
        assert [call["lineage"].kind for call in recorder.calls] == ["promoted", "trial", "trial"]
        assert [call["calibrated_by"] is None for call in recorder.calls] == [False, True, True]

    def test_promoting_nothing_writes_nothing(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9})

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_runs="none"))

        assert outcome == PromotionOutcome()
        assert recorder.calls == []
        assert not (tmp_path / "runs").exists()


class TestAReopenedSessionPromotesOnceMore:
    def test_a_trial_already_written_is_not_written_again(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        first = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=2))
        assert first.count == 2

        again = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=2))

        assert again == PromotionOutcome(
            count=0, failures=[], best_sim_id=first.best_sim_id, best_rel_dir="runs/calage"
        )
        assert len(recorder.calls) == 2, "the second promotion ran the pipeline for nothing"
        assert read_trials(persistence.directory)[1].only_case.rel_dir == "runs/calage"

    def test_a_paired_run_taken_by_anything_else_is_a_named_failure(
        self, tmp_path, recorder
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        (tmp_path / "runs" / "calage").mkdir(parents=True)

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))

        assert outcome.count == 0
        assert outcome.failures == [
            "trial 2: runs/calage already holds another run and is not overwritten; "
            "hmp campaign promote calage --trial 2 writes it under the next version."
        ]
        assert recorder.calls == []


class TestThePromotionAfterAnInterruption:
    def _after_abort(self, project, persistence, *, kept_solves):
        return promote_best_after_abort(
            cfg=_cfg(),
            trial_ctx=SimpleNamespace(kept_solves=kept_solves, base_cfg=_persisting_cfg()),
            persistence=persistence,
            project_root=project,
            phase="main",
            override_paths={"K": K_PATH},
        )

    def test_the_best_trial_is_promoted_from_its_kept_solve_as_aborted(
        self, tmp_path, recorder
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        taken: list[int] = []

        class _Retention:
            def take(self, trial_id):
                taken.append(trial_id)
                return KeptSolve(trial_id=trial_id, cost=0.1, folders=()), None

            def spared_folders(self, trial_id=None):
                return ()

            def promoted(self, trial_id):
                taken.append(-trial_id)

        outcome = self._after_abort(tmp_path, persistence, kept_solves=_Retention())

        assert outcome.count == 1 and outcome.best_rel_dir == "runs/calage"
        assert taken == [2, 2, -2], "the solve of the session trial number, taken and handed over"
        (call,) = recorder.calls
        assert call["kept"].trial_id == 2
        assert call["calibrated_by"].session_status == "aborted"
        assert call["lineage"].kind == "promoted"
        assert read_trials(persistence.directory)[1].only_case.rel_dir == "runs/calage"

    def test_a_best_trial_without_a_kept_solve_is_left_to_hmp_project_promote(
        self, tmp_path, recorder, caplog
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

        with caplog.at_level("INFO", logger="hydromodpy.calibration.runners.promotion"):
            outcome = self._after_abort(tmp_path, persistence, kept_solves=None)

        assert outcome == PromotionOutcome()
        assert recorder.calls == []
        assert not (tmp_path / "runs").exists()
        assert "hmp campaign promote calage --trial 2 replays it" in caplog.text

    def test_nothing_to_point_at_promotes_nothing(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={})

        assert self._after_abort(tmp_path, persistence, kept_solves=None) == PromotionOutcome()


class TestThePromotionOfAnEarlierPhase:
    def test_the_best_of_a_phase_goes_under_its_phase_directory(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={})

        steady = PhaseContext("steady_k", 0, 0)
        persistence.start_phase(steady, frozen={})
        for trial_id, cost in ((1, 0.5), (2, 0.2)):
            persistence.append_iteration(
                ParamSuggestion(trial_id=trial_id, values={"K": 1e-5}),
                EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status="completed"),
                phase=steady,
            )

        sim_id = promote_phase_best(
            trial_ctx=SimpleNamespace(kept_solves=None, base_cfg=_persisting_cfg()),
            persistence=persistence,
            phase="steady_k",
            override_paths={"K": K_PATH},
        )

        (call,) = recorder.calls
        assert sim_id == call["sim_id"]
        assert call["run_dir"] == persistence.directory / "phases" / "steady_k" / "best"
        assert "keep_per_cell_budget" not in call
        assert call["lineage"].kind == "promoted"
        assert call["calibrated_by"] is None
        assert call["lineage"].trial == 2
        lines = {line.trial: line for line in read_trials(persistence.directory)}
        assert lines[2].only_case.sim_id == sim_id


class TestAfterTheFact:
    def test_a_trial_the_session_never_journaled_is_refused(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9})
        persistence.finalize_session(status="completed", best=None)

        with pytest.raises(CalibrationError, match="journals no trial 7"):
            promote_trial_from_session(tmp_path, "calage", 7)

    def test_a_trial_that_did_not_complete_is_refused(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9})
        journal_trial(persistence, 2, status="crashed")
        persistence.finalize_session(status="completed", best=None)

        with pytest.raises(CalibrationError, match="trial 2 of calage is crashed, not completed"):
            promote_trial_from_session(tmp_path, "calage", 2)

    def test_a_session_that_kept_no_trial_has_nothing_to_prune(self, tmp_path) -> None:
        make_session(tmp_path)

        assert trials_to_prune(tmp_path, "calage") == []
        with pytest.raises(CalibrationError, match="keep='all': the only policy is 'best'"):
            trials_to_prune(tmp_path, "calage", keep="all")

    def test_a_trial_with_no_kept_run_is_replayed_from_the_frozen_document(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1}, hashed_under="v1")
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        _freeze(persistence)
        _replay_under(monkeypatch, "v1")

        target = promote_trial_from_session(tmp_path, "calage", 2)

        assert target == tmp_path / "runs" / "calage"
        (call,) = recorder.calls
        assert call["run_dir"] == target
        assert call["values"] == {"K": pytest.approx(1e-2)}
        assert call["lineage"].kind == "promoted" and call["lineage"].trial == 2
        assert call["calibrated_by"].session_status == "completed"
        assert call["calibrated_by"].windows == WINDOW
        line = {item.trial: item for item in read_trials(persistence.directory)}[2]
        assert (line.only_case.sim_id, line.only_case.rel_dir) == (call["sim_id"], "runs/calage")
        run = read_session(persistence.directory).only_run
        assert (run.sim_id, run.rel_dir) == (call["sim_id"], "runs/calage")

    def test_a_second_promotion_of_the_case_takes_the_next_version(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1}, hashed_under="v1")
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        _freeze(persistence)
        _replay_under(monkeypatch, "v1")
        promote_trial_from_session(tmp_path, "calage", 2)

        target = promote_trial_from_session(tmp_path, "calage", 1)

        assert target == tmp_path / "runs" / "calage.v2"
        assert read_session(persistence.directory).best.trial == 2, "the pointer did not move"

    def test_a_trial_scored_on_another_model_is_refused(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1}, hashed_under="v1")
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        _freeze(persistence)
        _replay_under(monkeypatch, "v2")

        with pytest.raises(CalibrationError, match="scored on another model"):
            promote_trial_from_session(tmp_path, "calage", 2)

        assert recorder.calls == []
        assert not (tmp_path / "runs").exists()

    def test_prune_keeps_the_best_and_trashes_the_others(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})
        _promote(tmp_path, persistence, cfg=_cfg(save_runs="all"))
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        trials_root = tmp_path / "sessions" / "calage" / "trials"
        assert sorted(p.name for p in trials_root.iterdir()) == ["0001", "0003"]
        (trials_root / "0003").mkdir(exist_ok=True)

        moved = prune_session(
            tmp_path, "calage", keep="best", now=datetime(2026, 10, 15, tzinfo=UTC)
        )

        assert [path.name.split("@")[0] for path in moved] == [
            "sessions__calage__trials__0001",
            "sessions__calage__trials__0003",
        ]
        assert list(trials_root.iterdir()) == []
        assert read_session(persistence.directory).best.trial == 2


FROZEN_STAGED = (
    '[site]\nname = "nancon"\n'
    + calibration_head("use_cache = false", log_k=False)
    + phases_toml(STEADY_K, {**TRANSIENT_SY, "max_trials": 3})
)

K_FROZEN = 2.5e-5


def _staged_prepare(
    cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
):
    """A prepared pipeline whose baseline holds the declared K, as a fresh load does."""
    declared_k = SimpleNamespace(field=SimpleNamespace(value=1e-4))
    base = _persisting_cfg(flow=SimpleNamespace(param=SimpleNamespace(K=declared_k)))
    return TrialContext(
        base_cfg=base,
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=dict(override_paths),
        workspace=cfg_path.parent,
        cfg_path=cfg_path,
        parameter_space=parameter_space,
    )


def _phase_marker(**kwargs) -> dict[str, Any]:
    """The parts of the hash context a phase changes: its configuration and its baseline."""
    cfg, trial_ctx = kwargs["cfg"], kwargs["trial_ctx"]
    return {
        "whole": cfg.phases is not None,
        "parameters": sorted(cfg.parameters),
        "method": cfg.method,
        "K": trial_ctx.base_cfg.flow.param.K.field.value,
    }


class TestATrialOfAStagedSessionIsReplayedOnItsPhase:
    def _staged_session(self, project: Path) -> CalibrationPersistence:
        persistence = _session(project, costs={})
        phase = PhaseContext("transient_sy", 1, 0)
        persistence.start_phase(
            phase,
            frozen={
                "K": FrozenValue(
                    value=K_FROZEN,
                    targets={"calage": K_PATH},
                    mode="replace",
                    from_phase="steady_k",
                )
            },
        )
        recorded = params_hash(
            {"Sy": 0.05},
            context={"whole": False, "parameters": ["Sy"], "method": "grid", "K": K_FROZEN},
        )
        journal_trial(
            persistence,
            1,
            0.3,
            values={"Sy": 0.05},
            phase=phase,
            metadata={"params_hash": recorded},
        )
        persistence.finalize_session(status="completed", best=None)
        (persistence.directory / "config.toml").write_text(FROZEN_STAGED, encoding="utf-8")
        return persistence

    def test_its_params_hash_is_reproduced_and_it_is_replayed(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        self._staged_session(tmp_path)
        monkeypatch.setattr(staged_module, "prepare_trials", _staged_prepare)
        monkeypatch.setattr(state_module, "build_cache_context", _phase_marker)

        target = promote_trial_from_session(tmp_path, "calage", 1)

        assert target == tmp_path / "runs" / "calage"
        (call,) = recorder.calls
        assert call["values"] == {"Sy": pytest.approx(0.05)}
        assert call["lineage"].phase == "transient_sy"

    def test_a_baseline_without_the_frozen_value_is_another_model(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        self._staged_session(tmp_path)
        monkeypatch.setattr(staged_module, "prepare_trials", _staged_prepare)
        monkeypatch.setattr(staged_module, "_freeze_into_baseline", lambda *args: None)
        monkeypatch.setattr(state_module, "build_cache_context", _phase_marker)

        with pytest.raises(CalibrationError, match="scored on another model"):
            promote_trial_from_session(tmp_path, "calage", 1)
        assert recorder.calls == []


class TestWhatThePromotedRunIsToldOfItsSession:
    def test_a_value_on_a_bound_is_named(self) -> None:
        row = {
            "status": "completed",
            "cost": 0.4,
            "parameters": {
                "K": {
                    "value": 1e-6,
                    "transformed_value": -6.0,
                    "bounds": [1e-6, 1e-4],
                    "transformed_bounds": [-6.0, -4.0],
                    "targets": {"calage": K_PATH},
                },
                "Sy": {
                    "value": 0.05,
                    "transformed_value": -1.30103,
                    "bounds": [0.01, 0.3],
                    "transformed_bounds": [-2.0, -0.52288],
                    "targets": {"calage": "flow.param.Sy.field.values_by_key.granite"},
                },
            },
        }

        promotion = promotion_module.promotion_facts(row)

        assert promotion.bounds_hit == ["K"]
        assert [(item.name, item.zone) for item in promotion.calibrated] == [
            ("K", None),
            ("Sy", "granite"),
        ]


# From test_the_promoted_trial_is_one_the_search_read.py
# The run promoted to ``runs/<case>`` is the trial the session reports.
#
# A parallel simplex solves candidates its rules never read, and the journal
# marks them ``speculative_unused``. One of them can score lower than the point
# the search froze. ``session.json`` already skipped it; the selection of the
# trials to promote ranks the same way, so the calibrated run and the reported
# best are one trial.


def test_the_best_trials_are_listed_per_phase(monkeypatch, tmp_path: Path) -> None:
    def line(trial, phase, cost, status="completed", unused=False):
        return SimpleNamespace(
            trial=trial, phase=phase, cost=cost, status=status, speculative_unused=unused
        )

    lines = [line(n, "a", 0.1 * (n + 1)) for n in range(6)]
    lines += [line(10, "b", 5.0), line(11, "b", 6.0)]
    lines += [
        line(20, "a", 0.01, status="failed"),
        line(21, "a", None),
        line(22, "a", 0.02, unused=True),
    ]
    sessions = tmp_path / "s"
    monkeypatch.setattr(
        promotion_module,
        "resolve_session_dir",
        lambda root, case: sessions if (root, case) == (tmp_path, "c") else pytest.fail(case),
    )
    monkeypatch.setattr(
        promotion_module,
        "CalibrationPersistence",
        lambda directory: SimpleNamespace(trials=lambda: lines if directory == sessions else []),
    )

    assert [t.trial for t in promotion_module.best_trials(tmp_path, "c", limit=2)] == [0, 1, 10, 11]
    assert [t.trial for t in promotion_module.best_trials(tmp_path, "c")] == [0, 1, 2, 3, 4, 10, 11]


class TestATieOnTheCost:
    """A bisection answers inside its last bracket, and two trials may share one cost."""

    @pytest.fixture
    def tied(self, tmp_path: Path) -> CalibrationPersistence:
        costs = [{"cost": cost, "k": 1e-5 * i} for i, cost in enumerate((0.3, 0.1, 0.2, 0.1), 1)]
        return make_session(tmp_path, "tie", costs=costs, method="bisection")

    def test_the_session_points_at_the_answer(self, tied, tmp_path) -> None:
        report = make_report(
            session_id=tied.descriptor.session_id,
            method="bisection",
            n_trials=4,
            best_trial=4,
            workspace=tmp_path,
            session_dir=tied.directory,
        )

        promote_and_close(
            cfg=SimpleNamespace(save_runs="none"),
            trial_ctx=None,
            persistence=tied,
            project_root=tmp_path,
            report=report,
            phase=DEFAULT_PHASE,
            status="completed",
        )

        assert tied.descriptor.best.trial == 4


def test_the_series_are_read_for_the_outputs_it_is_given(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        promotion_module,
        "series_at_the_stations",
        lambda ctx, outputs: seen.append(outputs) or {},
    )
    store = SimpleNamespace(write_timeseries_columns=lambda *args: pytest.fail("nothing to write"))

    promotion_module.write_station_series(SimpleNamespace(), store=store, outputs={"q": "output"})

    assert seen == [{"q": "output"}]


def test_the_station_series_are_written_in_utc_and_a_gauge_off_the_mesh_is_skipped(
    monkeypatch,
) -> None:
    def result(request_id, times, values):
        return SimpleNamespace(request_id=request_id, times=times, values=values, units="m")

    naive = pd.date_range("2020-01-01", periods=2)
    answers = {
        ("P1", "head"): result("cell", naive, [1.0, 2.0]),
        ("P2", "head"): result("cell", naive.tz_localize("UTC"), [3.0, 4.0]),
        ("Q", "discharge"): result(promotion_module.CATCHMENT, naive, [5.0, 6.0]),
    }
    monkeypatch.setattr(promotion_module, "series_at_the_stations", lambda *_: answers)
    written = []
    store = SimpleNamespace(
        sim_id="s", write_timeseries_columns=lambda sim_id, columns: written.append(columns)
    )
    ctx = SimpleNamespace(cfg=SimpleNamespace(site=SimpleNamespace()))

    promotion_module.write_station_series(ctx, store=store, outputs={})

    (columns,) = written
    assert list(columns["station_id"]) == ["P1", "P1", "P2", "P2"]
    assert list(columns["timestep"]) == [0, 1, 0, 1]
    assert list(columns["value"]) == [1.0, 2.0, 3.0, 4.0]
    assert list(columns["unit"]) == ["m"] * 4
    expected = pd.DatetimeIndex(list(naive) * 2).tz_localize("UTC")
    assert columns["time"].equals(expected)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ({"candidate_value": 2}, 2.0),
        ({"value": 1, "transformed_value": 5}, 1.0),
        ("3.5", 3.5),
        (4, 4.0),
    ],
)
def test_a_journaled_parameter_reads_as_its_physical_value(raw, value) -> None:
    assert stored_parameter_value(raw) == value


def test_a_journaled_parameter_without_a_value_is_refused() -> None:
    with pytest.raises(KeyError, match="no value"):
        stored_parameter_value({"targets": {}})


@pytest.mark.parametrize(
    ("payload", "parameter"),
    [
        (None, promotion_module.CalibratedParameter(name="K")),
        (
            {"targets": {"c": "flow.param.K.field.value"}},
            promotion_module.CalibratedParameter(name="K"),
        ),
        (
            {"targets": {"c": "flow.param.K.values_by_key.zone1.value"}},
            promotion_module.CalibratedParameter(name="K", zone="zone1"),
        ),
        (
            {"targets": {"c": "flow.param.K.values_by_key"}},
            promotion_module.CalibratedParameter(name="K"),
        ),
        ({"targets": {"c": "transport.alpha"}}, promotion_module.CalibratedParameter(name="alpha")),
    ],
)
def test_a_target_names_the_rows_a_parameter_sets(payload, parameter) -> None:
    assert promotion_module._calibrated_parameter("K", payload) == parameter


def test_a_phase_that_scored_nothing_promotes_nothing() -> None:
    persistence = SimpleNamespace(held_trial=lambda phase: None)

    assert (
        promote_phase_best(
            trial_ctx=None, persistence=persistence, phase="flow", override_paths={}, outputs=None
        )
        is None
    )
