"""Promotion of calibration trials to runs: the best beside its session, the others inside it.

The pipeline is replaced by a recorder, so the tests check where each promoted
trial goes, what the run is told about its session and what the journal says
afterwards. Costs are objective values (lower is better), K is in m/s.
"""

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

K_PATH = "flow.param.K.field.value"
WINDOW = calibration_window(date(2001, 1, 1), date(2002, 12, 31))
K_FROZEN = 2.5e-5  # m/s

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

FROZEN_STAGED = (
    '[site]\nname = "nancon"\n'
    + calibration_head("use_cache = false", log_k=False)
    + phases_toml(STEADY_K, {**TRANSIENT_SY, "max_trials": 3})
)


def cfg(**updates: Any) -> CalibrationConfig:
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


def session(
    project: Path,
    *,
    costs: dict[int, float],
    name: str = "calage",
    hashed_under: str | None = None,
) -> CalibrationPersistence:
    """A session whose trial n has K = 10**-n m/s and the given cost."""
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    persistence = CalibrationPersistence(reserve_version_dirname(project, "session", name))
    persistence.start_session(
        **session_opening(name, site="nancon", project=project.name, windows=WINDOW)
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


def finalized_session(project: Path, **kwargs: Any) -> CalibrationPersistence:
    persistence = session(project, costs={1: 0.9, 2: 0.1}, hashed_under="v1", **kwargs)
    persistence.finalize_session(
        status="completed", best=persistence.best_pointer(persistence.best_trial())
    )
    (persistence.directory / "config.toml").write_text(FROZEN_CONFIG, encoding="utf-8")
    return persistence


def persisting_cfg(**extra: Any) -> SimpleNamespace:
    """A base configuration whose runs persist, as a project file by default."""
    results = SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
    return SimpleNamespace(simulation=SimpleNamespace(results=results), **extra)


def trial_ctx(*, save_catalog: bool = True, kept_solves=None) -> Any:
    base_cfg = persisting_cfg()
    base_cfg.simulation.results.persistence.save_catalog = save_catalog
    return SimpleNamespace(kept_solves=kept_solves, base_cfg=base_cfg)


def fake_prepare(
    cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
):
    return TrialContext(
        base_cfg=persisting_cfg(),
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=dict(override_paths),
        workspace=cfg_path.parent,
        cfg_path=cfg_path,
        parameter_space=parameter_space,
    )


def replay_under(monkeypatch, marker: str) -> None:
    """Stand the model preparation and the fingerprint context in, as a replay sees them."""
    monkeypatch.setattr(trial_module, "prepare_trials", fake_prepare)
    monkeypatch.setattr(state_module, "build_cache_context", lambda **kwargs: {"marker": marker})


class Recorder:
    """What `promote_prepared_trial` was asked for, promotion by promotion."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, trial_ctx, values, **kwargs):
        del trial_ctx
        self.calls.append({"values": dict(values), **kwargs})
        return kwargs["sim_id"]


@pytest.fixture
def recorder(monkeypatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(promotion_module, "promote_prepared_trial", rec)
    return rec


def promote(project: Path, persistence, *, cfg: CalibrationConfig, status: str = "completed"):
    return promote_session(
        cfg=cfg,
        trial_ctx=trial_ctx(),
        persistence=persistence,
        project_root=project,
        phase="main",
        session_status=status,
        override_paths={"K": K_PATH},
    )


def test_no_catalog_gives_no_sim_id(tmp_path, recorder, caplog):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})

    with caplog.at_level(logging.WARNING):
        outcome = promote_session(
            cfg=cfg(save_best_n=2),
            trial_ctx=trial_ctx(save_catalog=False),
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


def test_phase_best_needs_catalog(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})

    sim_id = promote_phase_best(
        trial_ctx=trial_ctx(save_catalog=False),
        persistence=persistence,
        phase="main",
        override_paths={"K": K_PATH},
    )

    assert sim_id is None
    assert recorder.calls == []


def test_long_name_refused():
    with pytest.raises(CalibrationError, match="Shorten"):
        promotion_name_check("n" * 95)


SELECTED = [
    pytest.param({"save_best_n": 2}, [2, 3], id="best n"),
    pytest.param({"save_runs": "all"}, [2, 3, 1], id="all completed"),
    pytest.param({"save_runs": "none"}, [], id="none"),
]


@pytest.mark.parametrize(("updates", "trials"), SELECTED)
def test_selection_by_save_runs(tmp_path, updates, trials):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

    rows = select_trials_to_promote(cfg(**updates), persistence, "main")

    assert [row["trial"] for row in rows] == trials


def test_best_takes_session_run(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

    outcome = promote(tmp_path, persistence, cfg=cfg(save_best_n=1))

    assert outcome == PromotionOutcome(
        count=1, failures=[], best_sim_id=recorder.calls[0]["sim_id"], best_rel_dir="runs/calage"
    )
    (call,) = recorder.calls
    assert call["run_dir"] == tmp_path / "runs" / "calage"
    assert call["run_dir"].is_dir()
    assert call["name"] == "calage"
    assert call["values"] == {"K": pytest.approx(1e-2)}
    assert call["lineage"].kind == "promoted"
    assert "keep_per_cell_budget" not in call


def test_other_trials_under_session(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})

    outcome = promote(tmp_path, persistence, cfg=cfg(save_best_n=3))

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


def test_nothing_promoted_nothing_written(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9})

    outcome = promote(tmp_path, persistence, cfg=cfg(save_runs="none"))

    assert outcome == PromotionOutcome()
    assert recorder.calls == []
    assert not (tmp_path / "runs").exists()


def test_written_trial_not_repeated(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})
    first = promote(tmp_path, persistence, cfg=cfg(save_best_n=2))
    assert first.count == 2

    again = promote(tmp_path, persistence, cfg=cfg(save_best_n=2))

    assert again == PromotionOutcome(
        count=0, failures=[], best_sim_id=first.best_sim_id, best_rel_dir="runs/calage"
    )
    assert len(recorder.calls) == 2, "the second promotion ran the pipeline for nothing"
    assert read_trials(persistence.directory)[1].only_case.rel_dir == "runs/calage"


def test_taken_run_is_a_failure(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})
    (tmp_path / "runs" / "calage").mkdir(parents=True)

    outcome = promote(tmp_path, persistence, cfg=cfg(save_best_n=1))

    assert outcome.count == 0
    assert outcome.failures == [
        "trial 2: runs/calage already holds another run and is not overwritten; "
        "hmp campaign promote calage --trial 2 writes it under the next version."
    ]
    assert recorder.calls == []


def after_abort(project, persistence, *, kept_solves):
    return promote_best_after_abort(
        cfg=cfg(),
        trial_ctx=trial_ctx(kept_solves=kept_solves),
        persistence=persistence,
        project_root=project,
        phase="main",
        override_paths={"K": K_PATH},
    )


def test_abort_promotes_kept_solve(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})
    taken: list[int] = []

    class Retention:
        def take(self, trial_id):
            taken.append(trial_id)
            return KeptSolve(trial_id=trial_id, cost=0.1, folders=()), None

        def spared_folders(self, trial_id=None):
            return ()

        def promoted(self, trial_id):
            taken.append(-trial_id)

    outcome = after_abort(tmp_path, persistence, kept_solves=Retention())

    assert outcome.count == 1 and outcome.best_rel_dir == "runs/calage"
    assert taken == [2, 2, -2], "the solve of the session trial number, taken and handed over"
    (call,) = recorder.calls
    assert call["kept"].trial_id == 2
    assert call["calibrated_by"].session_status == "aborted"
    assert call["lineage"].kind == "promoted"
    assert read_trials(persistence.directory)[1].only_case.rel_dir == "runs/calage"


def test_abort_without_kept_solve(tmp_path, recorder, caplog):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1})

    with caplog.at_level("INFO", logger="hydromodpy.calibration.runners.promotion"):
        outcome = after_abort(tmp_path, persistence, kept_solves=None)

    assert outcome == PromotionOutcome()
    assert recorder.calls == []
    assert not (tmp_path / "runs").exists()
    assert "hmp campaign promote calage --trial 2 replays it" in caplog.text


def test_empty_session_promotes_nothing(tmp_path, recorder):
    persistence = session(tmp_path, costs={})

    assert after_abort(tmp_path, persistence, kept_solves=None) == PromotionOutcome()


def test_phase_best_under_phase_dir(tmp_path, recorder):
    persistence = session(tmp_path, costs={})
    steady = PhaseContext("steady_k", 0, 0)
    persistence.start_phase(steady, frozen={})
    for trial_id, cost in ((1, 0.5), (2, 0.2)):
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values={"K": 1e-5}),
            EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status="completed"),
            phase=steady,
        )

    sim_id = promote_phase_best(
        trial_ctx=trial_ctx(),
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


def test_unscored_phase_promotes_nothing():
    persistence = SimpleNamespace(held_trial=lambda phase: None)

    sim_id = promote_phase_best(
        trial_ctx=None, persistence=persistence, phase="flow", override_paths={}, outputs=None
    )

    assert sim_id is None


def test_unjournaled_trial_refused(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9})
    persistence.finalize_session(status="completed", best=None)

    with pytest.raises(CalibrationError, match="journals no trial 7"):
        promote_trial_from_session(tmp_path, "calage", 7)


def test_incomplete_trial_refused(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9})
    journal_trial(persistence, 2, status="crashed")
    persistence.finalize_session(status="completed", best=None)

    with pytest.raises(CalibrationError, match="trial 2 of calage is crashed, not completed"):
        promote_trial_from_session(tmp_path, "calage", 2)


def test_empty_session_prunes_nothing(tmp_path):
    make_session(tmp_path)

    assert trials_to_prune(tmp_path, "calage") == []
    with pytest.raises(CalibrationError, match="keep='all': the only policy is 'best'"):
        trials_to_prune(tmp_path, "calage", keep="all")


def test_trial_replayed_from_frozen_config(tmp_path, recorder, monkeypatch):
    persistence = finalized_session(tmp_path)
    replay_under(monkeypatch, "v1")

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


def test_second_promotion_next_version(tmp_path, recorder, monkeypatch):
    persistence = finalized_session(tmp_path)
    replay_under(monkeypatch, "v1")
    promote_trial_from_session(tmp_path, "calage", 2)

    target = promote_trial_from_session(tmp_path, "calage", 1)

    assert target == tmp_path / "runs" / "calage.v2"
    assert read_session(persistence.directory).best.trial == 2, "the pointer did not move"


def test_other_model_refused(tmp_path, recorder, monkeypatch):
    finalized_session(tmp_path)
    replay_under(monkeypatch, "v2")

    with pytest.raises(CalibrationError, match="scored on another model"):
        promote_trial_from_session(tmp_path, "calage", 2)

    assert recorder.calls == []
    assert not (tmp_path / "runs").exists()


def test_prune_keeps_the_best(tmp_path, recorder):
    persistence = session(tmp_path, costs={1: 0.9, 2: 0.1, 3: 0.5})
    promote(tmp_path, persistence, cfg=cfg(save_runs="all"))
    persistence.finalize_session(
        status="completed", best=persistence.best_pointer(persistence.best_trial())
    )
    trials_root = tmp_path / "sessions" / "calage" / "trials"
    assert sorted(p.name for p in trials_root.iterdir()) == ["0001", "0003"]
    (trials_root / "0003").mkdir(exist_ok=True)

    moved = prune_session(tmp_path, "calage", keep="best", now=datetime(2026, 10, 15, tzinfo=UTC))

    assert [path.name.split("@")[0] for path in moved] == [
        "sessions__calage__trials__0001",
        "sessions__calage__trials__0003",
    ]
    assert list(trials_root.iterdir()) == []
    assert read_session(persistence.directory).best.trial == 2


def staged_prepare(
    cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
):
    """A prepared pipeline whose baseline holds the declared K, as a fresh load does."""
    declared_k = SimpleNamespace(field=SimpleNamespace(value=1e-4))
    return TrialContext(
        base_cfg=persisting_cfg(flow=SimpleNamespace(param=SimpleNamespace(K=declared_k))),
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=dict(override_paths),
        workspace=cfg_path.parent,
        cfg_path=cfg_path,
        parameter_space=parameter_space,
    )


def phase_marker(**kwargs) -> dict[str, Any]:
    """The parts of the hash context a phase changes: its configuration and its baseline."""
    config, ctx = kwargs["cfg"], kwargs["trial_ctx"]
    return {
        "whole": config.phases is not None,
        "parameters": sorted(config.parameters),
        "method": config.method,
        "K": ctx.base_cfg.flow.param.K.field.value,
    }


def staged_session(project: Path) -> CalibrationPersistence:
    persistence = session(project, costs={})
    phase = PhaseContext("transient_sy", 1, 0)
    frozen_k = FrozenValue(
        value=K_FROZEN, targets={"calage": K_PATH}, mode="replace", from_phase="steady_k"
    )
    persistence.start_phase(phase, frozen={"K": frozen_k})
    recorded = params_hash(
        {"Sy": 0.05},
        context={"whole": False, "parameters": ["Sy"], "method": "grid", "K": K_FROZEN},
    )
    journal_trial(
        persistence, 1, 0.3, values={"Sy": 0.05}, phase=phase, metadata={"params_hash": recorded}
    )
    persistence.finalize_session(status="completed", best=None)
    (persistence.directory / "config.toml").write_text(FROZEN_STAGED, encoding="utf-8")
    return persistence


def test_staged_trial_replayed(tmp_path, recorder, monkeypatch):
    staged_session(tmp_path)
    monkeypatch.setattr(staged_module, "prepare_trials", staged_prepare)
    monkeypatch.setattr(state_module, "build_cache_context", phase_marker)

    target = promote_trial_from_session(tmp_path, "calage", 1)

    assert target == tmp_path / "runs" / "calage"
    (call,) = recorder.calls
    assert call["values"] == {"Sy": pytest.approx(0.05)}
    assert call["lineage"].phase == "transient_sy"


def test_baseline_without_frozen_value(tmp_path, recorder, monkeypatch):
    staged_session(tmp_path)
    monkeypatch.setattr(staged_module, "prepare_trials", staged_prepare)
    monkeypatch.setattr(staged_module, "_freeze_into_baseline", lambda *args: None)
    monkeypatch.setattr(state_module, "build_cache_context", phase_marker)

    with pytest.raises(CalibrationError, match="scored on another model"):
        promote_trial_from_session(tmp_path, "calage", 1)
    assert recorder.calls == []


def test_bounds_hit_named():
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


STORED_VALUES = [
    pytest.param({"candidate_value": 2}, 2.0, id="candidate value"),
    pytest.param({"value": 1, "transformed_value": 5}, 1.0, id="value before transformed"),
    pytest.param("3.5", 3.5, id="string"),
    pytest.param(4, 4.0, id="number"),
]


@pytest.mark.parametrize(("raw", "value"), STORED_VALUES)
def test_stored_parameter_value(raw, value):
    assert stored_parameter_value(raw) == value


def test_stored_parameter_without_value():
    with pytest.raises(KeyError, match="no value"):
        stored_parameter_value({"targets": {}})


TARGETS = [
    pytest.param(None, {"name": "K"}, id="no payload"),
    pytest.param({"targets": {"c": "flow.param.K.field.value"}}, {"name": "K"}, id="field value"),
    pytest.param(
        {"targets": {"c": "flow.param.K.values_by_key.zone1.value"}},
        {"name": "K", "zone": "zone1"},
        id="zone value",
    ),
    pytest.param({"targets": {"c": "flow.param.K.values_by_key"}}, {"name": "K"}, id="all zones"),
    pytest.param({"targets": {"c": "transport.alpha"}}, {"name": "alpha"}, id="other process"),
]


@pytest.mark.parametrize(("payload", "fields"), TARGETS)
def test_target_names_the_parameter(payload, fields):
    expected = promotion_module.CalibratedParameter(**fields)

    assert promotion_module._calibrated_parameter("K", payload) == expected


def test_best_trials_per_phase(monkeypatch, tmp_path: Path):
    # A parallel simplex solves candidates its rules never read (speculative_unused).
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


def test_tie_points_at_last_best(tmp_path: Path):
    # A bisection answers inside its last bracket, and two trials may share one cost.
    costs = [{"cost": cost, "k": 1e-5 * i} for i, cost in enumerate((0.3, 0.1, 0.2, 0.1), 1)]
    tied = make_session(tmp_path, "tie", costs=costs, method="bisection")
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


def test_series_read_for_outputs(monkeypatch):
    seen = []
    monkeypatch.setattr(
        promotion_module, "series_at_the_stations", lambda ctx, outputs: seen.append(outputs) or {}
    )
    store = SimpleNamespace(write_timeseries_columns=lambda *args: pytest.fail("nothing to write"))

    promotion_module.write_station_series(SimpleNamespace(), store=store, outputs={"q": "output"})

    assert seen == [{"q": "output"}]


def test_station_series_in_utc(monkeypatch):
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
