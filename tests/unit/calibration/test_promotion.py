"""What a promotion writes: the calibrated run beside its session, the kept trials inside it.

The pipeline is replaced by a recorder: what is under test is where each
promoted trial goes, what the run is told about its session, and what the
journal says afterwards. The equality of a promoted run with a replay on a
real model is ``tests/e2e/test_a_promoted_trial_is_not_solved_again_e2e.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import promotion as promotion_module
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
)
from hydromodpy.calibration.runners.session import calibration_case_name
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import FrozenValue
from tests._helpers.session_documents import calibration_window, session_opening

pytestmark = pytest.mark.unit

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
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values=values),
            EvaluationResult(
                trial_id=trial_id,
                sim_id=None,
                cost=cost,
                status="completed",
                metadata=metadata,
            ),
        )
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


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(promotion_module, "promote_prepared_trial", rec)
    return rec


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
    def test_the_stem_of_the_file_names_the_case(self, tmp_path) -> None:
        path = tmp_path / "calibration.toml"
        path.write_text('base_config = "project.toml"\n[calibration]\nmethod = "grid"\n')
        (tmp_path / "project.toml").write_text('[simulation]\nname = "nancon_monthly"\n')

        assert calibration_case_name(path) == "calibration"

    def test_its_own_simulation_name_wins(self, tmp_path) -> None:
        path = tmp_path / "calibration.toml"
        path.write_text('[simulation]\nname = "kept_solve"\n[calibration]\nmethod = "grid"\n')

        assert calibration_case_name(path) == "kept_solve"

    def test_a_name_inherited_through_base_config_never_names_a_calibration(self, tmp_path) -> None:
        (tmp_path / "base.toml").write_text(
            '[simulation]\nname = "inherited"\n[calibration]\nmethod = "grid"\n'
        )
        path = tmp_path / "calage.toml"
        path.write_text('base_config = "base.toml"\n[calibration]\nmax_trials = 2\n')

        assert calibration_case_name(path) == "calage"

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

    def test_the_default_promotes_the_best_trial_alone(self) -> None:
        cfg = CalibrationConfig()

        assert (cfg.save_runs, cfg.save_best_n, cfg.promote_phases) == ("best_n", 1, False)


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
        assert call["keep_per_cell_budget"] is None

    def test_the_run_is_told_its_session_phase_and_trial(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

        _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1), status="partial")

        (call,) = recorder.calls
        lineage, by = call["lineage"], call["calibrated_by"]
        assert (lineage.session_id, lineage.phase, lineage.trial, lineage.kind) == (
            "s" * 32,
            "main",
            2,
            "promoted",
        )
        assert lineage.parent_hint == "sessions/calage"
        assert (by.session_id, by.phase, by.trial, by.session_status) == (
            "s" * 32,
            "main",
            2,
            "partial",
        )
        assert (by.metric, by.cost, by.windows) == ("nse", 0.1, WINDOW)

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
        assert [call["keep_per_cell_budget"] for call in recorder.calls] == [None, False, False]
        assert [call["lineage"].kind for call in recorder.calls] == ["promoted", "trial", "trial"]
        assert [call["calibrated_by"] is None for call in recorder.calls] == [False, True, True]

    def test_the_session_and_the_run_share_their_version(self, tmp_path, recorder) -> None:
        _session(tmp_path, costs={1: 0.9})
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        assert persistence.directory.name == "calage.v2"

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))

        assert outcome.best_rel_dir == "runs/calage.v2"
        assert (tmp_path / "runs" / "calage.v2").is_dir()
        assert not (tmp_path / "runs" / "calage").exists()

    def test_the_journal_lines_name_the_runs_they_became(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_runs="all"))

        by_trial = {line.trial: line for line in read_trials(persistence.directory)}
        runs = {number: line.only_case for number, line in by_trial.items()}
        assert runs[2].sim_id == outcome.best_sim_id
        assert runs[2].rel_dir == "runs/calage"
        assert runs[1].rel_dir == "sessions/calage/trials/0001"
        assert runs[1].sim_id is not None

    def test_a_failed_promotion_leaves_no_link_and_names_the_trial(
        self, tmp_path, monkeypatch
    ) -> None:
        rec = _Recorder(fail_on={2})
        monkeypatch.setattr(promotion_module, "promote_prepared_trial", rec)
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=2))

        assert (outcome.count, outcome.best_sim_id, outcome.best_rel_dir) == (1, None, None)
        assert outcome.failures == ["trial 2: solver did not converge on trial 2"]
        by_trial = {line.trial: line for line in read_trials(persistence.directory)}
        assert by_trial[2].only_case.sim_id is None
        assert by_trial[1].only_case.rel_dir == "sessions/calage/trials/0001"

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

    def test_the_paired_run_is_never_overwritten_by_a_new_best(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        first = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))
        (tmp_path / "runs" / "calage" / "manifest.json").write_text("{}", encoding="utf-8")
        persistence.append_iteration(
            ParamSuggestion(trial_id=3, values={"K": 1e-3}),
            EvaluationResult(trial_id=3, sim_id=None, cost=0.05, status="completed"),
        )

        again = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))

        assert (again.count, again.best_sim_id, again.best_rel_dir) == (0, None, None)
        (failure,) = again.failures
        assert failure.startswith("trial 3: runs/calage already holds trial 2 of this session")
        assert "hmp project promote calage --trial 3" in failure
        assert len(recorder.calls) == 1
        assert (tmp_path / "runs" / "calage" / "manifest.json").is_file()
        by_trial = {line.trial: line for line in read_trials(persistence.directory)}
        assert by_trial[2].only_case.sim_id == first.best_sim_id
        assert by_trial[3].only_case.rel_dir is None and by_trial[3].only_case.sim_id is None

    def test_a_paired_run_taken_by_anything_else_is_a_named_failure(
        self, tmp_path, recorder
    ) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        (tmp_path / "runs" / "calage").mkdir(parents=True)

        outcome = _promote(tmp_path, persistence, cfg=_cfg(save_best_n=1))

        assert outcome.count == 0
        assert outcome.failures == [
            "trial 2: runs/calage already holds another run and is not overwritten; "
            "hmp project promote calage --trial 2 writes it under the next version."
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
        assert "hmp project promote calage --trial 2 replays it" in caplog.text

    def test_nothing_to_point_at_promotes_nothing(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={})

        assert self._after_abort(tmp_path, persistence, kept_solves=None) == PromotionOutcome()


class TestThePromotionOfAnEarlierPhase:
    def test_the_best_of_a_phase_goes_under_its_phase_directory(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={})
        from hydromodpy.calibration.persistence import PhaseContext

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
        assert call["keep_per_cell_budget"] is False
        assert call["calibrated_by"] is None
        assert call["lineage"].trial == 2
        lines = {line.trial: line for line in read_trials(persistence.directory)}
        assert lines[2].only_case.sim_id == sim_id


class TestAfterTheFact:
    def test_a_kept_trial_is_moved_to_runs(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        _promote(tmp_path, persistence, cfg=_cfg(save_runs="all"))
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        kept = tmp_path / "sessions" / "calage" / "trials" / "0001"
        (kept / "manifest.json").write_text("{}", encoding="utf-8")

        target = promote_trial_from_session(tmp_path, "calage", 1, as_name="k_high")

        assert target == tmp_path / "runs" / "k_high"
        assert (target / "manifest.json").is_file()
        assert not kept.exists()
        line = {item.trial: item for item in read_trials(persistence.directory)}[1]
        assert line.only_case.rel_dir == "runs/k_high"

    def test_a_trial_the_session_never_journaled_is_refused(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9})
        persistence.finalize_session(status="completed", best=None)

        with pytest.raises(CalibrationError, match="journals no trial 7"):
            promote_trial_from_session(tmp_path, "calage", 7)

    def test_a_kept_trial_takes_the_paired_run_when_it_is_free(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})
        _promote(tmp_path, persistence, cfg=_cfg(save_runs="none"))
        persistence.finalize_session(
            status="completed", best=persistence.best_pointer(persistence.best_trial())
        )
        kept = tmp_path / "sessions" / "calage" / "trials" / "0002"
        kept.mkdir(parents=True)
        (kept / "manifest.json").write_text("{}", encoding="utf-8")
        persistence.link_trial(2, sim_id="k" * 32, rel_dir="sessions/calage/trials/0002")

        target = promote_trial_from_session(tmp_path, "calage", 2)

        assert target == tmp_path / "runs" / "calage"
        assert (target / "manifest.json").is_file() and not kept.exists()
        assert read_session(persistence.directory).only_run.rel_dir == "runs/calage"

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


FROZEN_STAGED = """\
[site]
name = "nancon"

[calibration]
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.01, 0.3]
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
max_trials = 3
parameters = ["Sy"]
objective_blocks = ["q_block"]
depends_on = "steady_k"
"""

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
        from hydromodpy.calibration.persistence import PhaseContext

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
        persistence.append_iteration(
            ParamSuggestion(trial_id=1, values={"Sy": 0.05}),
            EvaluationResult(
                trial_id=1,
                sim_id=None,
                cost=0.3,
                status="completed",
                metadata={"params_hash": recorded},
            ),
            phase=phase,
        )
        persistence.finalize_session(status="completed", best=None)
        (persistence.directory / "config.toml").write_text(FROZEN_STAGED, encoding="utf-8")
        return persistence

    def test_its_params_hash_is_reproduced_and_it_is_replayed(
        self, tmp_path, recorder, monkeypatch
    ) -> None:
        from hydromodpy.calibration.runners import staged_runner as staged_module

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
        from hydromodpy.calibration.runners import staged_runner as staged_module

        self._staged_session(tmp_path)
        monkeypatch.setattr(staged_module, "prepare_trials", _staged_prepare)
        monkeypatch.setattr(staged_module, "_freeze_into_baseline", lambda *args: None)
        monkeypatch.setattr(state_module, "build_cache_context", _phase_marker)

        with pytest.raises(CalibrationError, match="scored on another model"):
            promote_trial_from_session(tmp_path, "calage", 1)
        assert recorder.calls == []


class TestWhatThePromotedRunIsToldOfItsSession:
    def test_the_best_carries_its_cost_and_the_parameters_it_set(self, tmp_path, recorder) -> None:
        persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

        _promote(tmp_path, persistence, cfg=_cfg(save_best_n=2))

        best, other = recorder.calls
        promotion = best["promotion"]
        assert (best["calibrated_by"].metric, best["calibrated_by"].cost) == ("nse", 0.1)
        assert promotion.converged is True
        assert [item.name for item in promotion.calibrated] == ["K"]
        assert other["promotion"] is None

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
