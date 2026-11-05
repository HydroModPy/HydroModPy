"""Tests of `runners.staged_runner`."""

from __future__ import annotations

import argparse
import logging
import math
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from hydromodpy.calibration.config import (
    CalibOutputPoint,
    CalibPhaseDecl,
    CalibrationConfig,
    MatchingHydrographicNetworkOptions,
    validate_calib_output,
)
from hydromodpy.calibration.optim.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optim.objective import CompositeObjective, build_objective_from_config
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace, set_by_path
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.protocols import protocol_record
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import cli_runner, staged_runner
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.cli_runner import _engine_kwargs, load_toml_calibration
from hydromodpy.calibration.runners.recap import staged_result_lines
from hydromodpy.calibration.runners.resume import best_parameters_of, reusable_stage
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.calibration.runners.staged_runner import (
    _frozen_by,
    _injected_paths,
    _methods_paragraph_for,
    _observed_source,
    _phase_config,
    _require_result_for_dependents,
    _why_unsettled,
    objective_comparison_table,
    phase_summaries,
    run_staged_calibration,
)
from hydromodpy.calibration.runners.state import preload_hash_cache
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.cli.commands.calibrate import _phase_line
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ConfigValidationError
from hydromodpy.core.runtime.interrupts import TerminationRequested
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.results.checks import BUDGET_RULE, FROZE_BUDGET_ONLY
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import list_phases, read_phase
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document
from tests._helpers.persisting_simulation import SimulationStub, persisting_simulation
from tests._helpers.session_documents import session_opening
from tests.unit.calibration._factories_runners import (
    H_SY,
    K_CALIBRATED,
    K_TOML,
    Q_BLOCK,
    Q_OUTPUT,
    STAGED_HEAD,
    STEADY_K,
    SY_CALIBRATED,
    SY_TOML,
    TRANSIENT_SY,
    TWO_PHASES,
    FakeCtx,
    FakeRunner,
    calibration_head,
    journal_trial,
    make_report,
    make_session,
    phases_toml,
    write_document,
)
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import PROJECT, _project

# From test_a_budget_only_phase_freezes_and_says_so.py
# A phase freezes what it found when its search settled, and says how.
#
# The rule, once (:func:`hydromodpy.calibration.optim.stopping.settled`): a phase
# passes its values on when its engine met its rule or exhausted its plan. An
# engine with no rule of its own (a random search) that spent its budget also
# passes them on, and the phase descriptor, ``session.json`` and the console say
# "froze the best of a budget-only search". An engine with a rule that the
# budget stopped first passes nothing on, and a phase that depends on it is
# refused.
#
# No solver runs: a toy configuration and a closed-form metric score each
# trial, so the real engines and the real staged runner are under test.


RANDOM_THEN_GRID = calibration_head(
    'method = "grid"\nmax_trials = 5\nseed = 7\nuse_cache = false\nsave_runs = "none"'
) + phases_toml(
    {**STEADY_K, "name": "coarse", "method": "random_search", "max_trials": 6},
    {**TRANSIENT_SY, "name": "storage", "max_trials": 5, "depends_on": "coarse"},
)


@pytest.fixture
def toy(monkeypatch) -> ToyPipeline:
    pipeline = ToyPipeline()
    monkeypatch.setattr(staged_runner, "prepare_trials", pipeline.prepare_trials)
    return pipeline


def test_a_random_search_first_phase_feeds_the_second_and_says_so(
    tmp_path: Path, toy: ToyPipeline, caplog
) -> None:
    path = write_document(tmp_path, RANDOM_THEN_GRID)

    with caplog.at_level(logging.WARNING):
        report = run_staged_calibration(path, metric_fn=toy.metric)

    coarse, storage = report.phases
    passed = coarse.report.best_parameters["K"]
    assert coarse.report.extra["search"]["stop_state"] == "budget_spent"
    assert coarse.report.extra["search"]["converged"] is False
    assert [item.name for item in coarse.frozen] == ["K"]
    assert coarse.stop_note == FROZE_BUDGET_ONLY
    assert storage.stop_note is None
    # Every trial of the second phase holds K at the value the first one found.
    held = [k for index, k, _ in toy.trials if index == 1]
    assert held == pytest.approx([passed] * 5)
    assert "Phase coarse froze the best of a budget-only search" in caplog.text

    session_dir = report.session_dir
    assert read_phase(session_dir, "coarse").stop_note == FROZE_BUDGET_ONLY
    assert read_phase(session_dir, "coarse").stop_state == "budget_spent"
    assert read_phase(session_dir, "storage").stop_state == "plan_exhausted"
    descriptor = read_session(session_dir)
    assert descriptor.status == "completed"
    assert descriptor.stop_state == "plan_exhausted"
    assert descriptor.stop_note == f"phase coarse {FROZE_BUDGET_ONLY}"

    lines = staged_result_lines(report)
    assert f"  {FROZE_BUDGET_ONLY}" in lines
    assert lines.index(f"  {FROZE_BUDGET_ONLY}") < lines.index("phase storage:")


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=1.0, upper=1.0e3, search_space="log")])


def _report(stop_state: str, rule: str) -> CalibrationReport:
    search = {
        "stop_state": stop_state,
        "converged": stop_state != "budget_spent",
        "stopping_rule": rule,
        "max_trials": 20,
        "extension": 0,
        "n_evaluations": 20,
    }
    return make_report(
        method="random_search",
        n_trials=20,
        best_cost=0.3,
        duration_s=1.0,
        best_parameters={"K": 20.0},
        extra={"search": search},
    )


DECL = SimpleNamespace(name="coarse", freeze_on_success=True, parameters=("K",))
DEPENDENT = [SimpleNamespace(decl=SimpleNamespace(name="fine", depends_on="coarse"))]


def test_a_budget_only_search_that_spent_its_budget_freezes_its_best(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", BUDGET_RULE), _space())

    assert [(item.name, item.value) for item in froze] == [("K", 20.0)]
    assert FROZE_BUDGET_ONLY in caplog.text
    _require_result_for_dependents(DECL, _report("budget_spent", BUDGET_RULE), DEPENDENT)


@pytest.mark.parametrize(
    ("state", "rule"), [("rule_met", "xatol"), ("plan_exhausted", "every grid point")]
)
def test_a_search_that_met_its_rule_or_its_plan_freezes_quietly(state, rule, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report(state, rule), _space())

    assert [item.name for item in froze] == ["K"]
    assert caplog.text == ""


def test_a_rule_engine_stopped_by_its_budget_freezes_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", "xatol"), _space())

    assert froze == ()
    assert "before its stopping rule (xatol) was met" in caplog.text
    with pytest.raises(CalibrationError, match="freezes what"):
        _require_result_for_dependents(DECL, _report("budget_spent", "xatol"), DEPENDENT)


# From test_a_phase_inherits_the_calibration_parallel.py
# A phase that sets no ``parallel`` takes the one of ``[calibration]``.
#
# The phases a protocol writes declare none, so ``[calibration] parallel = 4``
# used to reach none of them: every stage of the protocol ran its trials one by
# one whatever the section said.


def test_a_phase_without_its_own_takes_the_section_value() -> None:
    cfg = _cfg(_phase(), method="grid", parallel=4, batch_size=6)

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parallel == 4
    assert phase_cfg.batch_size == 6
    assert cfg.parallel_for(cfg.phases[0]) == 4


def test_a_phase_value_wins_over_the_section() -> None:
    cfg = _cfg(
        _phase("sy", parameters=["Sy"], parallel=2, batch_size=3),
        method="grid",
        parallel=4,
        batch_size=1,
    )

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parallel == 2
    assert phase_cfg.batch_size == 3
    assert cfg.parallel_for() == 4


# From test_a_phase_inherits_the_search_of_its_section.py
# A phase that writes no search key takes the one ``[calibration]`` writes.
#
# ``method``, ``max_trials``, ``precision`` and ``method_options`` were read in
# the phase or nowhere: a section that said ``method = "grid"`` left every phase
# to be chosen from its criteria, and a phase's budget was ``"auto"`` unless it
# wrote one. Key by key, the phase wins, then the section, then the default,
# the way ``batch_size``, ``parallel`` and ``uncertainty`` already read.


PARAMETERS = {
    "K": {"bounds": [1e-7, 1e-3], "search_space": "log", "path": "flow.param.K.field.value"},
    "Sy": {"bounds": [0.005, 0.35], "search_space": "log", "path": "flow.param.Sy.field.value"},
}


def _phase(name: str = "k", **fields: Any) -> dict[str, Any]:
    return {"name": name, "parameters": ["K"], "objective": "nse", **fields}


def _cfg(*phases: dict[str, Any], **section: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {"parameters": PARAMETERS, "phases": list(phases) or [_phase()], **section}
    )


def _findings(cfg: CalibrationConfig) -> list[Any]:
    class _Config:
        calibration = cfg

    return preflight_calibration(_Config(), source=Path("calibration.toml"))


# -- method ------------------------------------------------------------------
def test_a_phase_runs_the_method_the_section_writes() -> None:
    cfg = _cfg(_phase("a"), _phase("b", method="random_search"), method="grid")
    a, b = cfg.phases

    assert cfg.method_for(a) == ("grid", None)
    assert cfg.method_for(b) == ("random_search", None)


def test_a_phase_with_no_method_anywhere_is_chosen_from_its_criteria() -> None:
    method, reason = _cfg().method_for(_cfg().phases[0])

    assert method == "scipy_nelder_mead"
    assert reason is not None


# -- max_trials --------------------------------------------------------------
def test_a_phase_takes_the_budget_of_the_section_unless_it_writes_one() -> None:
    cfg = _cfg(_phase("a"), _phase("b", max_trials=7), max_trials=40)
    a, b = cfg.phases

    assert (a.max_trials, b.max_trials) == (None, 7)
    assert (cfg.max_trials_for(a), cfg.max_trials_for(b)) == (40, 7)


def test_the_budget_of_a_phase_and_of_a_section_left_unwritten_is_auto() -> None:
    cfg = _cfg()

    assert cfg.max_trials_for(cfg.phases[0]) == "auto"
    assert cfg.max_trials_for(None) == "auto"


def test_a_phase_may_ask_for_auto_against_a_section_budget() -> None:
    cfg = _cfg(_phase(max_trials="auto"), max_trials=40)

    assert cfg.max_trials_for(cfg.phases[0]) == "auto"


# -- precision ---------------------------------------------------------------
def test_a_precision_reaches_a_phase_whose_engine_reads_one() -> None:
    cfg = _cfg(
        _phase("a", method="scipy_nelder_mead"),
        _phase("b", method="scipy_nelder_mead", precision=0.1),
        _phase("c", method="bisection"),
        precision=0.01,
    )
    a, b, c = cfg.phases

    assert [cfg.precision_for(phase) for phase in (a, b, c)] == [0.01, 0.1, 0.01]


def test_a_precision_does_not_reach_an_engine_that_stops_on_its_budget() -> None:
    cfg = _cfg(_phase(method="grid"), _phase("b", method="optuna"), precision=0.01)

    assert [cfg.precision_for(phase) for phase in cfg.phases] == [None, None]
    assert not [finding for finding in _findings(cfg) if "precision" in finding.detail]


def test_a_precision_written_in_a_phase_of_a_budget_engine_is_still_refused() -> None:
    findings = _findings(_cfg(_phase(method="grid", precision=0.01)))

    assert [finding.severity for finding in findings if "precision" in finding.detail] == ["error"]


def test_an_engine_option_written_in_the_phase_wins_over_the_inherited_precision() -> None:
    cfg = _cfg(_phase(method="scipy_nelder_mead", method_options={"xatol": 0.02}), precision=0.01)

    assert cfg.precision_for(cfg.phases[0]) is None
    assert not [finding for finding in _findings(cfg) if "both set" in finding.detail]


# -- method_options ----------------------------------------------------------
def test_a_phase_takes_the_options_of_the_section_when_it_runs_its_method() -> None:
    cfg = _cfg(
        _phase("same"),
        _phase("also", method="bisection"),
        _phase("other", method="grid"),
        _phase("own", method_options={"sweep_points": 3}),
        _phase("none", method_options={}),
        method="bisection",
        method_options={"sweep_points": 5},
    )
    same, also, other, own, none = cfg.phases

    assert cfg.method_options_for(same) == {"sweep_points": 5}
    assert cfg.method_options_for(also) == {"sweep_points": 5}
    assert cfg.method_options_for(other) == {}
    assert cfg.method_options_for(own) == {"sweep_points": 3}
    assert cfg.method_options_for(none) == {}
    assert (same.method_options, none.method_options) == (None, {})


def test_the_options_of_a_phase_need_a_method_in_the_phase_or_in_the_section() -> None:
    with pytest.raises(ValidationError, match="phase 'k' gives method_options and no method"):
        _cfg(_phase(method_options={"sweep_points": 3}))

    inherited = _cfg(_phase(method_options={"sweep_points": 3}), method="bisection")
    assert inherited.method_options_for(inherited.phases[0]) == {"sweep_points": 3}


def test_the_options_of_a_phase_are_checked_against_the_method_it_inherits() -> None:
    with pytest.raises(ValidationError, match="phase 'k' method_options"):
        _cfg(_phase(method_options={"sweep_points": 3}), method="grid")


def test_a_protocol_stage_does_not_take_the_options_of_the_section() -> None:
    cfg = _cfg(
        _phase(method="bisection"),
        method="bisection",
        method_options={"sweep_points": 5},
        protocol={"name": "matching_hydrographic_network"},
    )

    assert cfg.method_options_for(cfg.phases[0]) == {}


# -- what a phase runs -------------------------------------------------------
def test_the_search_a_phase_runs_is_the_resolved_one() -> None:
    cfg = _cfg(
        _phase("a"),
        _phase("b", method="grid", max_trials=9),
        method="scipy_nelder_mead",
        max_trials=40,
        precision=0.02,
    )
    a, b = cfg.phases

    ran = _phase_config(cfg, a)
    assert (ran.method, ran.max_trials, ran.precision, ran.method_options) == (
        "scipy_nelder_mead",
        40,
        0.02,
        {},
    )
    ran = _phase_config(cfg, b)
    assert (ran.method, ran.max_trials, ran.precision) == ("grid", 9, None)


def test_the_listing_says_where_each_key_of_a_phase_comes_from() -> None:
    cfg = _cfg(
        _phase("a"),
        _phase("b", method="grid", max_trials=9, method_options={"points_per_dim": 4}),
        method="scipy_nelder_mead",
        max_trials=40,
        precision=0.02,
    )

    a, b = (row["search"] for row in phase_summaries(cfg))

    assert a == {
        "method": {"value": "scipy_nelder_mead", "source": "section"},
        "max_trials": {"value": 40, "source": "section"},
        "precision": {"value": 0.02, "source": "section"},
        "method_options": {"value": {}, "source": "default"},
    }
    assert b["method"]["source"] == "phase"
    assert b["max_trials"] == {"value": 9, "source": "phase"}
    assert b["precision"] == {"value": None, "source": "default"}
    assert b["method_options"] == {"value": {"points_per_dim": 4}, "source": "phase"}


def test_a_search_that_writes_nothing_lists_its_defaults() -> None:
    (row,) = phase_summaries(_cfg())

    assert row["search"]["max_trials"] == {"value": "auto", "source": "default"}
    assert row["search"]["method"]["source"] == "default"


# -- a protocol and a sealed run ---------------------------------------------
def test_a_protocol_stage_takes_the_section_precision_and_keeps_the_budget_it_wrote(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(PROJECT + "\n[calibration]\nprecision = 0.02\nmax_trials = 40\n", "utf-8")

    cfg = HydroModPyConfig.from_toml(toml).calibration
    steady, transient = cfg.phases

    assert [cfg.precision_for(phase) for phase in (steady, transient)] == [0.02, 0.02]
    assert [cfg.max_trials_for(phase) for phase in (steady, transient)] == ["auto", 120]

    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    sealed = run_dir / "config.toml"
    sealed.write_text(
        portable_config_document(HydroModPyConfig.from_toml(toml), run_dir, project), "utf-8"
    )
    replayed = HydroModPyConfig.from_toml(sealed).calibration
    assert [replayed.max_trials_for(phase) for phase in replayed.phases] == ["auto", 120]
    assert [replayed.precision_for(phase) for phase in replayed.phases] == [0.02, 0.02]


# From test_a_phase_moves_again_what_an_earlier_one_passed.py
# A phase that lists a parameter an earlier phase calibrated moves it again.
#
# The rule, in declaration order: a phase moves the parameters it lists. Every
# other parameter holds the last value an earlier converged phase passed on,
# otherwise the value of the model file. A phase that lists a parameter already
# passed on moves it again, starting from that value when its engine accepts a
# start point.
#
# No solver runs. The preparation is a toy configuration and a closed-form
# metric scores each trial, so the real engine, and the first point it asks
# for, is what is under test.


# Grid points of the first two phases: K on log10 [-9, -3], Sy on [0.001, 0.3],
# five points each. The metric's optimum sits on the K grid and near the Sy one.
K_BEST = 10**-4.5
SY_BEST = 0.1
SY_ON_THE_GRID = 0.001 + 0.25 * (0.3 - 0.001)


def _base(method: str, **last_phase) -> str:
    """Two grid phases, then a third one on both parameters with the given *method*."""
    return calibration_head(
        'method = "grid"\nmax_trials = 5\nseed = 7\nuse_cache = false'
    ) + phases_toml(
        {**STEADY_K, "name": "k_first", "method": "grid", "max_trials": 5},
        {**TRANSIENT_SY, "name": "sy_second", "max_trials": 5, "depends_on": None},
        {
            "name": "both_again",
            "method": method,
            "max_trials": 4,
            "parameters": ["K", "Sy"],
            "objective_blocks": ["q_block"],
            **last_phase,
        },
    )


# K is frozen twice: by k_first, then by k_again, which moves it again.
TWICE = calibration_head('method = "grid"\nmax_trials = 5') + phases_toml(
    {"name": "k_first", "method": "grid", "parameters": ["K"], "objective_blocks": ["q_block"]},
    {
        "name": "k_again",
        "method": "scipy_nelder_mead",
        "parameters": ["K"],
        "objective_blocks": ["q_block"],
    },
    {"name": "sy_last", "method": "grid", "parameters": ["Sy"], "objective_blocks": ["q_block"]},
)


# -- a toy model the real engine can run -------------------------------------
class _Value(BaseModel):
    value: float


class _Quantity(BaseModel):
    field: _Value


class _Param(BaseModel):
    K: _Quantity = Field(default_factory=lambda: _Quantity(field=_Value(value=K_TOML)))
    Sy: _Quantity = Field(default_factory=lambda: _Quantity(field=_Value(value=SY_TOML)))


class _Flow(BaseModel):
    param: _Param = Field(default_factory=_Param)


class _Model(BaseModel):
    flow: _Flow = Field(default_factory=_Flow)
    simulation: SimulationStub = Field(default_factory=SimulationStub)


class ToyPipeline:
    """Prepares a toy model per phase and scores each trial in closed form."""

    def __init__(self) -> None:
        self.phase = -1
        self.trials: list[tuple[int, float, float]] = []

    def prepare_trials(
        self,
        cfg_path: Path,
        *,
        override_paths,
        steps=None,
        parameter_space=None,
        config_overrides=None,
    ) -> TrialContext:
        self.phase += 1
        return TrialContext(
            base_cfg=_Model(),
            ctx=FakeCtx(None, cfg_path, {}, cfg_path.parent),
            earliest=9,
            downstream_steps=(),
            override_paths=dict(override_paths),
            workspace=cfg_path.parent,
            cfg_path=cfg_path,
            raw_toml={},
            parameter_space=parameter_space,
        )

    def metric(self, ctx, *, objective, variable):
        k = ctx.cfg.flow.param.K.field.value
        sy = ctx.cfg.flow.param.Sy.field.value
        self.trials.append((self.phase, k, sy))
        cost = (math.log10(k) - math.log10(K_BEST)) ** 2 + (sy - SY_BEST) ** 2
        return cost, {"q_block": cost}

    def first_trial_of(self, phase: int) -> tuple[float, float]:
        return next((k, sy) for index, k, sy in self.trials if index == phase)


def test_under_nelder_mead_the_first_trial_is_the_passed_value(tmp_path, toy) -> None:
    path = write_document(tmp_path, _base("scipy_nelder_mead"))

    report = run_staged_calibration(path, metric_fn=toy.metric)

    k_first, sy_second, both = report.phases
    k_passed = k_first.report.best_parameters["K"]
    sy_passed = sy_second.report.best_parameters["Sy"]
    assert k_passed == pytest.approx(K_BEST)
    assert sy_passed == pytest.approx(SY_ON_THE_GRID)
    # sy_second holds K at the value k_first passed on.
    held = [k for index, k, _ in toy.trials if index == 1]
    assert held == pytest.approx([K_BEST] * 5)
    # Before the rule, both_again started at the prior center (K = 1e-6,
    # Sy = 0.1505), with the passed values written under every trial.
    assert toy.first_trial_of(2) == (pytest.approx(k_passed), pytest.approx(sy_passed))
    assert [(item.name, item.phase) for item in both.reopened] == [
        ("K", "k_first"),
        ("Sy", "sy_second"),
    ]
    assert both.to_dict()["reopened"][0]["phase"] == "k_first"
    assert "reopened" not in k_first.to_dict()


def test_the_rows_say_which_phase_a_parameter_is_reopened_from(tmp_path) -> None:
    cfg, _raw = load_toml_calibration(write_document(tmp_path, _base("scipy_nelder_mead")))

    rows = phase_summaries(cfg)

    assert "reopens" not in rows[0]
    assert "reopens" not in rows[1]
    assert rows[2]["reopens"] == [
        {"parameter": "K", "from_phase": "k_first"},
        {"parameter": "Sy", "from_phase": "sy_second"},
    ]
    assert rows[2]["starts_from_passed_values"] is True


def test_under_grid_list_phases_says_the_engine_takes_no_start_point(tmp_path, capsys) -> None:
    path = write_document(tmp_path, _base("grid"))
    cfg, _raw = load_toml_calibration(path)

    assert phase_summaries(cfg)[2]["starts_from_passed_values"] is False
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )
    # A block the phase compares prints an indented line under its own; keep
    # only the phase lines, one per phase, the way phase_summaries lists them.
    lines = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert lines[0].split("\t")[:4] == ["0", "k_first", "grid", ""]
    assert lines[2].endswith(
        "\tre-opens K<-k_first, Sy<-sy_second, grid takes no start point and keeps its own"
    )


def test_under_grid_the_engine_keeps_its_own_start(tmp_path, toy) -> None:
    # Two points per parameter keep the 2 x 2 grid of the last phase within its 4 trials.
    document = _base("grid", method_options={"points_per_dim": 2})
    report = run_staged_calibration(write_document(tmp_path, document), metric_fn=toy.metric)

    # The grid's first point is its lower corner, not a passed value.
    k, sy = toy.first_trial_of(2)
    assert k == pytest.approx(1e-9)
    assert sy == pytest.approx(0.001)
    assert [item.name for item in report.phases[2].reopened] == ["K", "Sy"]


# -- two phases freezing the same parameter ----------------------------------
def test_two_phases_freezing_the_same_parameter_run_and_the_latest_wins(
    tmp_path, monkeypatch
) -> None:
    runner = FakeRunner()
    runner.per_phase = {"k_first": {"K": 2e-5}, "k_again": {"K": 4e-5}, "sy_last": {"Sy": 0.07}}
    runner.patch(monkeypatch)

    report = run_staged_calibration(write_document(tmp_path, TWICE))

    k_first, k_again, sy_last = runner.calls
    # k_again moves K again: the passed value is its start, not its baseline.
    assert k_again.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert 10 ** k_again.start_at[0] == pytest.approx(2e-5)
    # sy_last holds the later of the two values.
    assert sy_last.baseline.flow.param.K.field.value == pytest.approx(4e-5)
    assert sy_last.start_at is None
    # The report names both freezes, and the value k_again re-opened.
    assert [(item.name, item.phase, item.value) for item in report.frozen] == [
        ("K", "k_first", pytest.approx(2e-5)),
        ("K", "k_again", pytest.approx(4e-5)),
        ("Sy", "sy_last", pytest.approx(0.07)),
    ]
    assert [(item.name, item.phase) for item in report.phases[1].reopened] == [("K", "k_first")]


# K1 and K2 are two names for one path. phase_b freezes the path last, under
# K2, so phase_c, which lists K1, starts from phase_b's value and names it.
ALIASED = (
    '\n[calibration]\nmethod = "grid"\nmax_trials = 5\n'
    + "".join(
        f"\n[calibration.parameters.{name}]\nbounds = [1e-9, 1e-3]\n"
        'search_space = "log"\ntarget = "flow.param.K.field.value"\n'
        for name in ("K1", "K2")
    )
    + Q_OUTPUT
    + Q_BLOCK
    + phases_toml(
        {
            "name": "phase_a",
            "method": "grid",
            "parameters": ["K1"],
            "objective_blocks": ["q_block"],
        },
        {
            "name": "phase_b",
            "method": "grid",
            "parameters": ["K2"],
            "objective_blocks": ["q_block"],
        },
        {
            "name": "phase_c",
            "method": "scipy_nelder_mead",
            "parameters": ["K1"],
            "objective_blocks": ["q_block"],
        },
    )
)


def test_a_name_aimed_at_a_path_frozen_under_another_name_starts_from_the_latest(
    tmp_path, monkeypatch
) -> None:
    runner = FakeRunner()
    runner.per_phase = {"phase_a": {"K1": 1e-5}, "phase_b": {"K2": 4e-5}, "phase_c": {"K1": 3e-5}}
    runner.patch(monkeypatch)
    path = write_document(tmp_path, ALIASED)

    report = run_staged_calibration(path)

    phase_c = runner.calls[2]
    assert phase_c.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert 10 ** phase_c.start_at[0] == pytest.approx(4e-5)
    assert [(item.name, item.phase, item.value) for item in report.phases[2].reopened] == [
        ("K1", "phase_b", pytest.approx(4e-5))
    ]
    cfg, _raw = load_toml_calibration(path)
    rows = phase_summaries(cfg)
    assert rows[1]["reopens"] == [{"parameter": "K2", "from_phase": "phase_a"}]
    assert rows[2]["reopens"] == [{"parameter": "K1", "from_phase": "phase_b"}]


# From test_a_phase_narrows_the_bounds_of_its_parameters.py
# A phase may write its own ``bounds``, inside the ones ``[calibration]`` declares.
#
# A broad first phase and a narrow second one used to need two sections. Now a
# phase writes ``bounds = { K = [1e-6, 1e-4] }`` for the parameters it moves. They
# have to lie inside the section's bounds: refused at load against the bounds the
# file writes, and again before the first solve against the resolved ones (a
# field's own range when the section writes none).


def test_a_phase_takes_no_bounds_by_default() -> None:
    assert _cfg().phases[0].bounds is None


@pytest.mark.parametrize("bounds", [[1e-6, 1e-4], [1e-7, 1e-3]], ids=["inside", "equal"])
def test_a_phase_writes_its_bounds_inside_the_section_bounds(bounds: list[float]) -> None:
    assert _cfg(_phase(bounds={"K": bounds})).phases[0].bounds == {"K": bounds}


@pytest.mark.parametrize(
    ("bounds", "reason"),
    [
        ({"K": [1e-8, 1e-4]}, r"\[1e-08, 0.0001\].*\[1e-07, 0.001\]"),
        ({"K": [1e-6, 1e-2]}, r"\[1e-06, 0.01\].*\[1e-07, 0.001\]"),
        ({"Sy": [0.01, 0.2]}, "'Sy', which it does not move"),
        ({"K": [1e-4, 1e-6]}, "lower bound must be below the upper"),
        ({"K": [1e-6, 1e-6]}, "lower bound must be below the upper"),
        ({"K": [1e-6]}, "two values"),
        ({"K": [1e-6, 1e-5, 1e-4]}, "two values"),
    ],
)
def test_a_phase_bounds_that_cannot_hold_are_refused_when_the_file_loads(
    bounds: dict[str, list[float]], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        _cfg(_phase(bounds=bounds))


def test_the_refusal_names_the_phase_and_the_parameter() -> None:
    with pytest.raises(ValidationError, match="phase 'k'.*'K'"):
        _cfg(_phase(bounds={"K": [1e-8, 1e-4]}))


def test_a_phase_writes_its_bounds_into_the_calibration_it_runs() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parameters["K"].bounds == [1e-6, 1e-4]
    assert cfg.parameters["K"].bounds == [1e-7, 1e-3]


def test_a_phase_without_bounds_runs_the_section_bounds() -> None:
    cfg = _cfg()

    assert _phase_config(cfg, cfg.phases[0]).parameters["K"].bounds == [1e-7, 1e-3]


def test_bounds_written_below_the_resolved_bounds_are_refused_before_the_first_solve() -> None:
    """The section writes none; the catalog's range, filled in after load, is the frame."""
    cfg = _cfg(
        _phase(bounds={"K": [1e-8, 1e-4]}),
        parameters={"K": {"search_space": "log"}},
    )
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    with pytest.raises(ConfigValidationError, match=r"\[1e-08, 0.0001\].*\[1e-07, 0.001\]"):
        _phase_config(cfg, cfg.phases[0])


def test_bounds_inside_the_resolved_bounds_run() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}), parameters={"K": {"search_space": "log"}})
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    assert _phase_config(cfg, cfg.phases[0]).parameters["K"].bounds == [1e-6, 1e-4]


def test_the_preflight_refuses_bounds_outside_the_resolved_ones() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    cfg.parameters["K"].bounds = [1e-5, 1e-3]

    class _Config:
        calibration = cfg

    findings = preflight_calibration(_Config(), source=Path("calibration.toml"))
    refused = [finding for finding in findings if "bounds" in finding.where]

    assert [finding.severity for finding in refused] == ["error"]
    assert "[1e-05, 0.001]" in refused[0].detail


def test_list_phases_prints_the_bounds_of_a_phase() -> None:
    cfg = _cfg(_phase("wide"), _phase("narrow", bounds={"K": [1e-6, 1e-4]}))
    wide, narrow = phase_summaries(cfg)

    assert "bounds" not in wide
    assert narrow["bounds"] == {"K": [1e-6, 1e-4]}
    assert "bounds K [1e-06, 0.0001]" in _phase_line(1, narrow)
    assert "bounds" not in _phase_line(0, wide)


# From test_a_single_metric_phase_keeps_the_output_it_names.py
# A single-metric phase keeps the output its variable names.
#
# ``_phase_config`` used to empty the outputs of a phase scored on its own
# ``variable`` and ``objective``. A phase whose variable names a network output
# then lost the declaration of that output: its maps, its extent table. The
# root search read one root where the output scores two bounds.


NETWORK = {
    "support": "network",
    "map": {
        "complete": "streams.gpkg",
        "permanent": "permanent.gpkg",
        "calibrate_on": {"permanent": 0.5, "complete": 0.5},
    },
    "model": {"extent": {}},
}
POINT = {
    "support": "point",
    "variable": "head",
    "x": 0.0,
    "y": 0.0,
    "observed_values": [1.0, 2.0],
}


def _config__single_metric(phase: dict, **section) -> CalibrationConfig:
    k_network = {"name": "k_network", "method": "bisection", "parameters": ["K"], **phase}
    sy_heads = {"name": "sy_heads", "method": "grid", "parameters": ["Sy"]}
    sy_heads |= {"objective_blocks": ["heads"], "depends_on": "k_network"}
    return _cfg(
        k_network,
        sy_heads,
        method="bisection",
        outputs={"net": NETWORK, "well": POINT},
        objective_blocks=[
            {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]},
            {"name": "heads", "metric": "nse", "uses_outputs": ["well"]},
        ],
        **section,
    )


_SPACE = ParameterSpace([CalibParameter(name="K", lower=1e-7, upper=1e-3, search_space="log")])


@pytest.mark.parametrize(
    ("phase", "section"),
    [
        ({"variable": "net", "objective": "distance_gap"}, {}),
        ({"objective": "distance_gap"}, {"variable": "net"}),
    ],
    ids=["variable_in_the_phase", "variable_from_the_section"],
)
def test_the_network_output_the_variable_names_is_kept(phase, section) -> None:
    cfg = _config__single_metric(phase, **section)
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert set(phase_cfg.outputs) == {"net"}
    assert phase_cfg.outputs["net"].model.extent is not None
    assert str(phase_cfg.outputs["net"].map.permanent) == "permanent.gpkg"
    # The one block the whole-file (objective, variable) route builds, no other.
    [block] = phase_cfg.objective_blocks
    assert (str(block.metric), list(block.uses_outputs)) == ("distance_gap", ["net"])
    # The root search counts both bounds.
    assert _engine_kwargs(phase_cfg, _SPACE, start_at=None)["roots"] == 2


@pytest.mark.parametrize("variable", ["discharge", "well"])
def test_no_other_output_is_inherited(variable: str) -> None:
    cfg = _config__single_metric({"variable": variable, "objective": "nse", "method": "grid"})

    phase_cfg = _phase_config(cfg, cfg.phases[0])

    # The phase keeps the output its variable names and nothing else; a raw
    # variable names none.
    assert set(phase_cfg.outputs) == ({"well"} if variable == "well" else set())
    assert "net" not in phase_cfg.outputs


# From test_a_station_output_reads_its_record.py
# A point output that observes a station is placed by the station's record.
#
# The x and y written beside ``observes`` are not read, yet ``--list-phases``
# printed them as where the discharge came from, and for Nancon the discharge is
# the whole-catchment series. The listing now says what the run reads, and
# loading warns about a position nobody reads, unless a snap may fall back on it.


def _point(**fields: object) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate({"support": "point", **fields})


def test_x_and_y_beside_observes_are_warned_as_ignored() -> None:
    with pytest.warns(UserWarning, match="observes station 'NANCON' and also writes x, y"):
        _point(variable="discharge", observes="NANCON", x=389285.91, y=6816518.749)


def test_a_geometry_beside_observes_is_warned_as_ignored() -> None:
    geometry = {"type": "Point", "coordinates": [0.0, 0.0]}
    with pytest.warns(UserWarning, match="writes geometry"):
        _point(variable="discharge", observes="NANCON", geometry=geometry)


def test_a_snap_reads_the_written_position_so_nothing_is_warned() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _point(variable="discharge", observes="NANCON", x=1.0, y=2.0, snap_radius="150 m")


def test_an_output_that_writes_only_observes_loads_silently() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _point(variable="discharge", observes="NANCON")


def _quantity(output: dict) -> str:
    cfg = CalibrationConfig.model_validate(
        {
            "outputs": {"gauge": {"support": "point", **output}},
            "objective_blocks": [{"name": "fit", "metric": "nse", "uses_outputs": ["gauge"]}],
        }
    )
    return objective_comparison_table(cfg)[0]["quantity"]


STATION = "discharge, station NANCON (whole-catchment series)"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ({"variable": "discharge", "observes": "NANCON"}, STATION),
        (
            {"variable": "discharge", "observes": "NANCON", "snap_radius": "0.15 km"},
            "discharge, station NANCON (the most drained cell within 150 m of its record)",
        ),
        (
            {"variable": "head", "observes": "PZ1"},
            "head, station PZ1 (the cell its record falls in)",
        ),
        ({"variable": "head", "x": 10.0, "y": 20.0}, "head (point, (10, 20))"),
    ],
    ids=["discharge_station", "snapped_station", "head_station", "no_station"],
)
def test_a_point_output_says_where_its_value_is_read(output, expected) -> None:
    assert _quantity(output) == expected


def test_the_written_x_and_y_are_never_printed_as_where_the_value_comes_from() -> None:
    with pytest.warns(UserWarning):
        quantity = _quantity(
            {"variable": "discharge", "observes": "NANCON", "x": 389285.91, "y": 6816518.749}
        )

    assert quantity == STATION
    assert "389285" not in quantity


# From test_an_unconverged_phase_promises_only_what_the_cache_replays.py
# A phase that did not converge says what a re-run really replays.
#
# The message told the user to "raise max_trials or loosen the tolerance" and
# promised that a re-run replays the trials already solved. The cache key holds
# only what changes the cost of a trial, so a new max_trials, precision, seed,
# method or option replays the trials it proposes at values already solved, as the
# engine warning already says.


def test_a_new_search_setting_is_promised_the_cache_only_at_the_values_solved() -> None:
    message = _why_unsettled(_report("budget_spent", "xatol"))

    assert "loosen the tolerance" not in message
    assert (
        "Raise max_trials: a re-run of the same file replays the trials already solved from "
        "the cache. So does a new precision, seed, method or method_options, for every "
        "trial it proposes at values already solved"
    ) in message


# From test_objective_comparison_table.py
# ``--list-phases`` and ``--check`` show what each block compares with what.
#
# Per objective block: its criterion, its normalized share, the simulated
# quantity (support, variable, where) and the observed source: a station and
# the ``[data.<family>]`` section it comes from for a point output that
# ``observes`` one, or the mapped file for a network output. A phase that scores
# no block (or a phase-less calibration with none either) takes the
# single-metric route, one row.
#
# No solver runs: the table reads declarations only, which is also what lets
# ``--list-phases`` build it without the project's data on disk.


SECTION = """
[calibration]
max_trials = 5

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.005, 0.35]
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[calibration.outputs.gauge]
variable = "discharge"
support = "point"
x = 10.0
y = 20.0
observes = "G1"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["gauge"]
"""

PHASES = """
[[calibration.phases]]
name = "k_network"
parameters = ["K"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "sy_hydrograph"
parameters = ["Sy"]
objective_blocks = { hydrograph = 99, network = 1 }
depends_on = "k_network"
"""

SINGLE_METRIC_PHASE = """
[[calibration.phases]]
name = "sy_single"
parameters = ["Sy"]
variable = "discharge"
objective = "nse_log"
"""


def _config__objective_comparison(tmp_path: Path, text: str):
    cfg, _raw = load_toml_calibration(write_document(tmp_path, text))
    return cfg


def _rows_by_phase(cfg) -> dict[str, list[dict]]:
    return {row["name"]: row["comparisons"] for row in phase_summaries(cfg)}


@pytest.mark.fast
def test_a_network_block_names_the_mapped_file(tmp_path: Path) -> None:
    cfg = _config__objective_comparison(tmp_path, SECTION + PHASES)

    rows = _rows_by_phase(cfg)["k_network"]

    assert len(rows) == 1
    assert rows[0]["block"] == "network"
    assert rows[0]["metric"] == "distance_gap"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert rows[0]["quantity"] == "release_flux (network)"
    assert rows[0]["source"].endswith("streams.gpkg")


@pytest.mark.fast
def test_a_point_block_that_observes_names_the_station_and_its_data_family(
    tmp_path: Path,
) -> None:
    cfg = _config__objective_comparison(tmp_path, SECTION + PHASES)

    rows = {row["block"]: row for row in _rows_by_phase(cfg)["sy_hydrograph"]}

    hydrograph = rows["hydrograph"]
    assert hydrograph["metric"] == "nse_log"
    # The x and y written beside `observes` are never read, so the row says
    # what the run reads: the station's discharge, here the catchment series.
    assert hydrograph["quantity"] == "discharge, station G1 (whole-catchment series)"
    assert hydrograph["source"] == "station G1 ([data.hydrometry])"


@pytest.mark.fast
def test_a_share_table_normalises_like_the_composite_objective(tmp_path: Path) -> None:
    cfg = _config__objective_comparison(tmp_path, SECTION + PHASES)

    rows = {row["block"]: row for row in _rows_by_phase(cfg)["sy_hydrograph"]}

    # weights 99 and 1, normalized: 0.99 and 0.01.
    assert rows["hydrograph"]["share"] == pytest.approx(0.99)
    assert rows["network"]["share"] == pytest.approx(0.01)
    assert sum(row["share"] for row in rows.values()) == pytest.approx(1.0)


@pytest.mark.fast
def test_the_single_metric_route_is_one_row(tmp_path: Path) -> None:
    cfg = _config__objective_comparison(tmp_path, SECTION + PHASES + SINGLE_METRIC_PHASE)

    rows = _rows_by_phase(cfg)["sy_single"]

    assert len(rows) == 1
    assert rows[0]["block"] is None
    assert rows[0]["metric"] == "nse_log"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert "every loaded station" in rows[0]["source"]
    assert "[data.hydrometry]" in rows[0]["source"]


@pytest.mark.fast
def test_a_phase_less_calibration_still_gets_a_table_for_its_one_search(
    tmp_path: Path,
) -> None:
    cfg = _config__objective_comparison(tmp_path, SECTION)

    assert cfg.phases is None or cfg.phases == []
    rows = objective_comparison_table(cfg, None)

    assert {row["block"] for row in rows} == {"network", "hydrograph"}
    assert all(row["share"] == pytest.approx(0.5) for row in rows)


@pytest.mark.fast
def test_list_phases_still_works_without_the_project_data_on_disk(tmp_path: Path) -> None:
    """``streams.gpkg`` is never written to ``tmp_path``: the table must not need it."""
    cfg = _config__objective_comparison(tmp_path, SECTION + PHASES)

    rows = phase_summaries(cfg)

    assert [row["name"] for row in rows] == ["k_network", "sy_hydrograph"]
    assert all("comparisons" in row for row in rows)


@pytest.mark.fast
def test_a_network_output_mapped_from_the_project_names_its_source(tmp_path: Path) -> None:
    text = SECTION.replace('map.complete = "streams.gpkg"', 'map.complete = "data.hydrography"')
    cfg = _config__objective_comparison(tmp_path, text + PHASES)

    rows = _rows_by_phase(cfg)["k_network"]

    assert rows[0]["source"] == "data.hydrography"


@pytest.mark.fast
def test_observed_values_with_no_observes_names_the_count() -> None:
    output = validate_calib_output(
        dict(
            variable="discharge",
            support="boundary",
            boundary_id="outlet",
            observed_values=[1.0, 2.0, 3.0],
        )
    )

    assert _observed_source(output) == "3 value(s) written in the file"


@pytest.mark.fast
def test_nothing_declared_falls_back_to_saying_so() -> None:
    output = validate_calib_output(
        dict(variable="discharge", support="boundary", boundary_id="outlet")
    )

    assert _observed_source(output) == "nothing declared"


# From test_phase_metric_route.py
# Which scoring route a phase takes, and what it must not inherit.
#
# ``build_metric_extractor`` prefers the objective blocks over the single-metric
# variable whenever both reach it. A phase that declares ``variable`` and
# ``objective`` and inherits the blocks of another phase would therefore be
# scored on that other phase's criterion, silently and with a plausible number.


NETWORK_PHASE = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "objective_blocks": ["abherve_gap"],
    "freeze_on_success": True,
}
DISCHARGE_PHASE = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "variable": "discharge",
    "objective": "nse_log",
    "depends_on": "steady_k_over_r",
}


def _config__phase_metric(phases: list[dict]) -> CalibrationConfig:
    return _cfg(
        *phases,
        method="grid",
        outputs={"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
        objective_blocks=[
            {"name": "abherve_gap", "metric": "distance_gap", "uses_outputs": ["net"]}
        ],
    )


def test_a_single_metric_phase_inherits_no_block() -> None:
    cfg = _config__phase_metric([NETWORK_PHASE, DISCHARGE_PHASE])
    phase_cfg = _phase_config(cfg, cfg.phases[1])

    assert phase_cfg.objective_blocks == []
    assert phase_cfg.outputs == {}
    assert phase_cfg.variable == "discharge"
    assert phase_cfg.objective == "nse_log"


def test_a_block_phase_keeps_what_it_selected() -> None:
    cfg = _config__phase_metric([NETWORK_PHASE, DISCHARGE_PHASE])
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert [block.name for block in phase_cfg.objective_blocks] == ["abherve_gap"]
    assert set(phase_cfg.outputs) == {"net"}


def test_declaring_both_conventions_is_refused() -> None:
    with pytest.raises(ValueError, match="Pick one convention"):
        _config__phase_metric(
            [{**DISCHARGE_PHASE, "depends_on": None, "objective_blocks": ["abherve_gap"]}]
        )


def test_a_single_metric_phase_selecting_an_output_is_refused() -> None:
    with pytest.raises(ValueError, match="Pick one convention"):
        _config__phase_metric([{**DISCHARGE_PHASE, "depends_on": None, "outputs": ["net"]}])


@pytest.mark.parametrize("field", ["variable", "objective"])
def test_either_field_alone_picks_the_single_metric_route(field: str) -> None:
    cfg = _config__phase_metric([NETWORK_PHASE, {**DISCHARGE_PHASE, **{field: None}}])
    assert cfg.phases[1].is_single_metric is True
    assert _phase_config(cfg, cfg.phases[1]).objective_blocks == []


# From test_phase_objective_shares.py
# A phase gives each objective block its own share.
#
# ``objective_blocks`` on a phase is either a list of names, which keeps each
# selected block's declared weight, or a table ``{block: share}``, which
# replaces the selected blocks' weight with the phase's own share. Both forms
# select the same blocks; the table changes only what the composite objective
# sees, and shares are normalized to sum to one exactly like declared weights
# already are.


NETWORK_BLOCK = {
    "name": "network",
    "metric": "distance_gap",
    "uses_outputs": ["net"],
}
HYDROGRAPH_BLOCK = {
    "name": "hydrograph",
    "metric": "rmse",
    "uses_outputs": ["q"],
    "weight": 3.0,
    "normalize_cost": True,
}

SEVENTY_THIRTY = {
    "name": "seventy_thirty",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"network": 70, "hydrograph": 30},
}
FIFTY_FIFTY = {
    "name": "fifty_fifty",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"network": 50, "hydrograph": 50},
}
LIST_FORM = {
    "name": "list_form",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": ["network", "hydrograph"],
}
HYDROGRAPH_ONLY = {
    "name": "hydrograph_only",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"hydrograph": 1.0},
}


def _config__phase_objective(phases: list[dict]) -> CalibrationConfig:
    q_output = {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"}
    return _cfg(
        *phases,
        method="grid",
        outputs={
            "net": {"support": "network", "map": {"complete": "streams.gpkg"}},
            "q": {**q_output, "observed_values": [1.0, 2.0, 3.0]},
        },
        objective_blocks=[NETWORK_BLOCK, HYDROGRAPH_BLOCK],
    )


def _normalized_weights(cfg: CalibrationConfig, phase) -> dict[str, float]:
    phase_cfg = _phase_config(cfg, phase)
    obj = build_objective_from_config(phase_cfg)
    assert isinstance(obj, CompositeObjective)
    return {block.name: weight for block, weight in obj.blocks}


class TestShareTable:
    @pytest.mark.parametrize(
        ("phase", "network", "hydrograph"),
        [(SEVENTY_THIRTY, 0.7, 0.3), (FIFTY_FIFTY, 0.5, 0.5)],
        ids=["seventy_thirty", "fifty_fifty"],
    )
    def test_a_share_table_normalises_to_one(self, phase, network, hydrograph) -> None:
        cfg = _config__phase_objective([phase])
        weights = _normalized_weights(cfg, cfg.phases[0])

        assert weights["network"] == pytest.approx(network)
        assert weights["hydrograph"] == pytest.approx(hydrograph)

    def test_the_share_replaces_the_declared_weight(self) -> None:
        # hydrograph declares weight 3.0; the phase's share overrides it.
        cfg = _config__phase_objective([SEVENTY_THIRTY])
        phase_cfg = _phase_config(cfg, cfg.phases[0])
        weights = {block.name: block.weight for block in phase_cfg.objective_blocks}

        assert weights == {"network": 70, "hydrograph": 30}


class TestListFormUnchanged:
    def test_the_list_form_keeps_the_declared_weight(self) -> None:
        cfg = _config__phase_objective([LIST_FORM])
        phase_cfg = _phase_config(cfg, cfg.phases[0])
        weights = {block.name: block.weight for block in phase_cfg.objective_blocks}

        assert weights == {"network": 1.0, "hydrograph": 3.0}


class TestNoCrossPhaseMutation:
    def test_a_phase_built_twice_from_the_same_config_sees_the_same_shares(self) -> None:
        # Two phases of one config, built in turn, then the first one again:
        # a shared mutable block dict would let the second phase's share leak
        # into the first's re-read.
        cfg = _config__phase_objective([SEVENTY_THIRTY, FIFTY_FIFTY])

        first = _normalized_weights(cfg, cfg.phases[0])
        _normalized_weights(cfg, cfg.phases[1])
        first_again = _normalized_weights(cfg, cfg.phases[0])

        assert first == first_again
        assert first["network"] == pytest.approx(0.7)
        assert first["hydrograph"] == pytest.approx(0.3)

    def test_the_declared_blocks_keep_their_own_weight(self) -> None:
        cfg = _config__phase_objective([SEVENTY_THIRTY, FIFTY_FIFTY])

        _phase_config(cfg, cfg.phases[0])
        _phase_config(cfg, cfg.phases[1])

        weights = {block.name: block.weight for block in cfg.objective_blocks}
        assert weights == {"network": 1.0, "hydrograph": 3.0}


class TestPartialSelection:
    def test_a_table_naming_one_block_keeps_only_that_block_and_its_output(self) -> None:
        cfg = _config__phase_objective([HYDROGRAPH_ONLY])
        phase_cfg = _phase_config(cfg, cfg.phases[0])

        assert [block.name for block in phase_cfg.objective_blocks] == ["hydrograph"]
        assert set(phase_cfg.outputs) == {"q"}


class TestRefused:
    @pytest.mark.parametrize(
        ("shares", "message"),
        [
            ({"nowhere": 1.0}, "undeclared objective block"),
            ({"network": 0.0, "hydrograph": 1.0}, ""),
            ({"network": -1.0, "hydrograph": 1.0}, ""),
        ],
        ids=["unknown_block", "zero_share", "negative_share"],
    )
    def test_a_share_table_that_cannot_hold_is_refused(self, shares, message) -> None:
        with pytest.raises(ValueError, match=message or None):
            _config__phase_objective([{**SEVENTY_THIRTY, "objective_blocks": shares}])


# From test_phase_overrides.py
# A phase says what model it calibrates, not only how it searches.
#
# The two stages of a stream-network calibration are one steady and one transient.
# The flow regime is a property of the model, not of the search, so without this a
# phase table cannot express the paper's own workflow.


STEADY = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "variable": "discharge",
    "objective": "rmse",
    "freeze_on_success": True,
    "overrides": {"flow.flow_regime": "steady"},
}
TRANSIENT = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "depends_on": "steady_k_over_r",
    "variable": "discharge",
    "objective": "nse_log",
    "overrides": {
        "flow.flow_regime": "transient",
        "simulation.time.step_value": "1 day",
    },
}


def _config__phase_overrides(phases: list[dict]) -> CalibrationConfig:
    return _cfg(*phases, method="grid")


class TestAccepted:
    def test_a_phase_carries_its_own_model_settings(self) -> None:
        cfg = _config__phase_overrides([STEADY, TRANSIENT])

        assert cfg.phases[0].overrides == {"flow.flow_regime": "steady"}
        assert cfg.phases[1].overrides["simulation.time.step_value"] == "1 day"

    def test_no_override_is_the_default(self) -> None:
        cfg = _config__phase_overrides([{"name": "p", "parameters": ["K"]}])
        assert cfg.phases[0].overrides == {}


class TestRefused__phase_overrides:
    def test_overriding_a_path_another_phase_freezes(self) -> None:
        # The frozen value would be overwritten and nothing downstream would say
        # which of the two the model actually ran with.
        with pytest.raises(ValueError, match="freezes"):
            _config__phase_overrides(
                [
                    STEADY,
                    {
                        **TRANSIENT,
                        "overrides": {"flow.param.K.field.value": 1e-5},
                    },
                ]
            )

    def test_rewriting_the_calibration_section(self) -> None:
        with pytest.raises(ValueError, match="own search"):
            _config__phase_overrides([{**STEADY, "overrides": {"calibration.max_trials": 3}}])

    @pytest.mark.parametrize("path", ["", ".flow", "flow."])
    def test_a_path_that_is_not_dotted(self, path: str) -> None:
        with pytest.raises(ValueError, match="not a\n? *dotted path|dotted path"):
            _config__phase_overrides([{**STEADY, "overrides": {path: 1}}])


def test_the_overrides_reach_the_preparation_not_the_paths_that_vary_per_trial() -> None:
    """Not the baseline the forks copy afterwards (the prefix already built its time grid)."""
    cfg = _config__phase_overrides([STEADY, TRANSIENT])

    paths = _injected_paths(_phase_config(cfg, cfg.phases[1]), [])

    assert "flow.flow_regime" not in paths.values()
    assert "simulation.time.step_unit" not in paths.values()


# From test_resume_is_new.py
# ``hmp calibrate --resume`` reopens the session of the case instead of starting a new one.
#
# A phase that completed there with the same fingerprint is read back, the cut
# phase is solved again with its trials preloading the cache, and ``--phase``
# runs one phase on top of what the session already holds. The solver never
# runs here: :func:`run_calibration_core` and :func:`prepare_trials` are
# replaced by a recorder, as in ``test_runners_staged_runner.py``.


K_PATH = "flow.param.K.field.value"
SY_PATH = "flow.param.Sy.field.value"
K_FROM_DISK = 9.9e-5

RESUME_DOCUMENT = calibration_head(
    'method = "grid"\nmax_trials = 4\nsave_runs = "none"', log_k=False, outputs=Q_OUTPUT + Q_BLOCK
) + phases_toml(STEADY_K, TRANSIENT_SY)


def _write_resume(tmp_path: Path, document: str = RESUME_DOCUMENT) -> Path:
    (tmp_path / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    return write_document(tmp_path, document, "calage.toml")


@pytest.fixture
def fake(monkeypatch) -> FakeRunner:
    """A runner that journals one trial per phase, under the fingerprint ``v1``."""
    runner = FakeRunner(best_cost=0.1, journal=True)
    runner.patch(monkeypatch, marker="v1")
    return runner


def _completed_steady_session(project: Path, *, recorded_marker: str) -> CalibrationPersistence:
    """Write a session of the case whose ``steady_k`` completed, hashed under ``recorded_marker``."""
    persistence = make_session(
        project,
        "calage",
        site="nancon",
        project="p",
        method="bisection",
        cost_name="rmse",
        bounds={},
    )
    steady = PhaseContext("steady_k", 0, 0)
    persistence.start_phase(steady, frozen={})
    journal_trial(
        persistence,
        1,
        0.01,
        values={"K": K_FROM_DISK},
        phase=steady,
        components={"J": 0.01},
        metadata={
            "params_hash": params_hash({"K": K_FROM_DISK}, context={"marker": recorded_marker})
        },
    )
    persistence.finish_phase(
        "steady_k",
        status="completed",
        best=persistence.best_pointer(persistence.best_trial("steady_k")),
    )
    persistence.finalize_session(status="partial", best=None, error="cut at transient_sy")
    return persistence


class TestWithoutResumeEveryPhaseSolvesInANewSession:
    def test_a_completed_session_is_left_alone_and_a_new_one_opens(self, tmp_path, fake) -> None:
        cfg_path = _write_resume(tmp_path)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert report.session_dir == tmp_path / "sessions" / "calage.v2"
        assert read_session(tmp_path / "sessions" / "calage").status == "partial"


class TestResumeReusesWhatCompleted:
    def test_the_completed_phase_is_read_back_and_the_next_one_solves(self, tmp_path, fake) -> None:
        cfg_path = _write_resume(tmp_path)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["transient_sy"]
        assert report.reused_from_disk == ("steady_k",)
        assert report.session_dir == tmp_path / "sessions" / "calage"
        assert report.frozen[0].name == "K"
        assert report.frozen[0].value == pytest.approx(K_FROM_DISK)
        assert report.phases[0].report.best_trial == 1

    def test_the_reused_value_is_frozen_into_the_phase_that_still_solves(
        self, tmp_path, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        run_staged_calibration(cfg_path, resume=True)

        (transient_call,) = fake.calls
        assert transient_call.trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(
            K_FROM_DISK
        )

    def test_the_trial_numbers_go_on_in_the_same_journal(self, tmp_path, fake) -> None:
        cfg_path = _write_resume(tmp_path)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        run_staged_calibration(cfg_path, resume=True)

        trials = read_trials(tmp_path / "sessions" / "calage")
        assert [(t.trial, t.phase) for t in trials] == [(1, "steady_k"), (2, "transient_sy")]
        descriptor = read_session(tmp_path / "sessions" / "calage")
        assert descriptor.status == "completed"
        assert descriptor.best is not None and descriptor.best.trial == 2

    def test_a_different_fingerprint_today_re_solves_instead_of_trusting_it(
        self, tmp_path, monkeypatch, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path)
        # This run's own model/mesh/input-file context ("v2") is not the one the
        # session was scored under ("v1" below): not the same problem.
        fake.patch(monkeypatch, marker="v2")
        # The cost refusal is tested on its own; here it stands aside to see the re-solve.
        monkeypatch.setattr(staged_runner, "refuse_a_phase_another_cost_scored", lambda *_a: None)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.reused_from_disk == ()
        assert report.frozen[0].value == pytest.approx(K_CALIBRATED)
        phases = {
            p.name: p for p in CalibrationPersistence(tmp_path / "sessions" / "calage").phases()
        }
        assert phases["steady_k"].restarts == 1, "the re-solved phase counts a restart"

    def test_resume_without_a_session_starts_one(self, tmp_path, fake) -> None:
        cfg_path = _write_resume(tmp_path)

        report = run_staged_calibration(cfg_path, resume=True)

        assert fake.phases_run == ["steady_k", "transient_sy"]
        assert report.session_dir == tmp_path / "sessions" / "calage"


class TestOnePhaseOnTheSession:
    def test_a_phase_runs_alone_when_its_dependency_completed_in_the_session(
        self, tmp_path, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path)
        _completed_steady_session(tmp_path, recorded_marker="v1")

        report = run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.phases_run == ["transient_sy"]
        assert [p.name for p in report.phases] == ["transient_sy"]
        assert fake.calls[0].trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(
            K_FROM_DISK
        )

    def test_a_phase_whose_dependency_never_completed_is_refused(self, tmp_path, fake) -> None:
        cfg_path = _write_resume(tmp_path)

        with pytest.raises(CalibrationError, match="steady_k"):
            run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.calls == []


class TestTheSessionNamesTheMethodsItsPhasesRun:
    def test_a_document_whose_phases_name_their_methods_opens_its_session(
        self, tmp_path, fake
    ) -> None:
        """No top-level method: the descriptor still names what ran, phase by phase."""
        cfg_path = _write_resume(
            tmp_path, RESUME_DOCUMENT.replace('method = "grid"\nmax_trials = 4', "max_trials = 4")
        )

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


PROMOTING = RESUME_DOCUMENT.replace('save_runs = "none"', 'save_runs = "best_n"')


class TestASessionThatAlreadyPromotedIsReopened:
    def test_a_resume_that_reuses_every_phase_keeps_the_run_it_promoted(
        self, tmp_path, monkeypatch, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path, PROMOTING)
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
        assert descriptor.only_run.rel_dir == "runs/calage"

    def test_a_phase_run_again_with_a_better_trial_leaves_the_paired_run_alone(
        self, tmp_path, monkeypatch, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path, PROMOTING)
        recorder = _PromotionRecorder()
        monkeypatch.setattr(promotion_module, "promote_prepared_trial", recorder)
        first = run_staged_calibration(cfg_path)
        (tmp_path / "runs" / "calage" / "manifest.json").write_text("{}", encoding="utf-8")
        # The model changed since (another fingerprint): the phase is solved
        # again on top of what steady_k passed on, and finds a better trial.
        fake.patch(monkeypatch, marker="v2")
        monkeypatch.setattr(staged_runner, "refuse_a_phase_another_cost_scored", lambda *_a: None)
        fake.best_cost = 0.05

        again = run_staged_calibration(cfg_path, phase="transient_sy")

        assert fake.phases_run == ["steady_k", "transient_sy", "transient_sy"]
        assert again.promoted == 0 and again.best_rel_dir is None
        (failure,) = again.extra["promotion_failures"]
        assert failure.startswith("trial 3: runs/calage already holds trial 2 of this session")
        assert len(recorder.calls) == 1
        assert (tmp_path / "runs" / "calage" / "manifest.json").is_file()
        descriptor = read_session(tmp_path / "sessions" / "calage")
        assert descriptor.status == "partial", "the search is sound; only the run is missing"
        assert "hmp campaign promote calage --trial 3" in (descriptor.error_message or "")
        by_trial = {line.trial: line for line in read_trials(tmp_path / "sessions" / "calage")}
        assert by_trial[2].only_case.sim_id == first.best_sim_id
        assert by_trial[3].only_case.rel_dir is None


class TestAnInterruptedStagedSearch:
    def test_the_cut_phase_is_aborted_and_the_pointer_reads_the_completed_one(
        self, tmp_path, monkeypatch, fake
    ) -> None:
        cfg_path = _write_resume(tmp_path, PROMOTING)
        fake.cut_at = "transient_sy"
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
        # hmp campaign promote, nothing is written in the margin.
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


def test_a_reused_phase_passes_on_what_its_search_answered_not_the_first_of_a_tie(
    tmp_path: Path,
) -> None:
    """A root search answers inside its bracket, and two trials can tie on the cost."""
    persistence = CalibrationPersistence(tmp_path)
    persistence.start_session(**session_opening())
    steady = PhaseContext("steady_k", 0, 0)
    persistence.start_phase(steady, frozen={})
    for trial_id, value in enumerate((1.4e-4, 1.5e-4), start=1):
        journal_trial(persistence, trial_id, 11.0, values={"K": value}, phase=steady)
    answered = persistence.trial_line(2)
    persistence.finish_phase(
        "steady_k", status="completed", best=persistence.best_pointer(answered)
    )

    assert persistence.best_trial("steady_k").trial == 1
    assert persistence.held_trial("steady_k").trial == 2
    assert best_parameters_of(persistence, "steady_k") == {"K": 1.5e-4}
    assert reusable_stage(persistence, "steady_k").parameters == {"K": 1.5e-4}


# From test_staged_runner.py
# What a calibration run in phases hands from one stage to the next.
#
# The solver never runs here: :func:`run_calibration_core` and
# :func:`prepare_trials` are replaced by a recorder, so what is under test is
# the staging itself -- the order of the phases, the configuration each one
# runs under, where a frozen value lands, and the chain of sessions.


NO_FREEZE = phases_toml(
    {**STEADY_K, "freeze_on_success": False}, {**H_SY, "parameters": ["Sy", "K"]}
)
# Same two phases, but the second one is not written against what the first
# freezes. A phase nobody builds on may fail and hand nothing over; that is
# what the two "freezes nothing" tests below are about, and it is only
# observable on a table where no phase depends on the one that failed.
INDEPENDENT = phases_toml(STEADY_K, {**H_SY, "depends_on": None})
# ``rel_tol`` is a setting of the one-dimensional root search. The second phase
# searches on a grid, which has no such knob, so this table cannot build the
# calibration of its second phase. Loading the file says so, naming the phase.
BAD_SECOND_PHASE = phases_toml(
    STEADY_K, {**H_SY, "depends_on": None, "method_options": {"rel_tol": 0.01}}
)


def _write_staged(tmp_path: Path, phases: str = TWO_PHASES, section: str = "") -> Path:
    """Write the staged document: the head, the *section* tables, then the *phases*."""
    return write_document(tmp_path, STAGED_HEAD + section + phases)


@pytest.fixture
def runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    fake.patch(monkeypatch)
    return fake


@pytest.fixture
def report(tmp_path, runner) -> CalibrationReport:
    """The staged report of the two-phase document, run on the fake runner."""
    return run_staged_calibration(_write_staged(tmp_path))


# -- order and per-phase configuration --------------------------------------
def test_the_phases_run_in_declaration_order(report, runner) -> None:
    assert runner.phases_run == ["steady_k", "transient_sy"]
    assert [phase.name for phase in report.phases] == ["steady_k", "transient_sy"]
    assert [phase.index for phase in report.phases] == [0, 1]


def test_each_phase_runs_the_search_it_declares(report, runner) -> None:
    steady, transient = (call.cfg for call in runner.calls)
    assert (steady.method, steady.max_trials) == ("bisection", 12)
    assert (transient.method, transient.max_trials) == ("grid", 30)
    assert list(steady.parameters) == ["K"]
    assert list(transient.parameters) == ["Sy"]
    assert runner.calls[0].space.names == ("K",)
    assert runner.calls[1].space.names == ("Sy",)


def test_a_phase_config_is_an_ordinary_mono_phase_calibration(report, runner) -> None:
    assert all(call.cfg.phases is None for call in runner.calls)


def test_each_phase_scores_only_on_the_blocks_it_names(report, runner) -> None:
    # A staged table has to say this per phase: a phase that named nothing used
    # to inherit every declared block, so the transient stage was scored on the
    # steady stage's criterion too. The schema now refuses that silence.
    steady, transient = (call.cfg for call in runner.calls)
    assert list(steady.outputs) == ["q"]
    assert [block.name for block in steady.objective_blocks] == ["q_block"]
    assert [block.name for block in transient.objective_blocks] == ["h_block"]


def test_a_phase_that_names_no_output_gets_the_ones_its_blocks_read(report, runner) -> None:
    # The transient phase selects a block and no output. It used to inherit
    # every declared one, so the steady stage's discharge was extracted from
    # each of its trials and entered no cost. Worse where the two stages score
    # different families: a network output handed to a stage scored on a series
    # is refused outright, and the whole staged file stopped running.
    _, transient = (call.cfg for call in runner.calls)
    assert list(transient.outputs) == ["h"]


# -- freezing ----------------------------------------------------------------
def test_a_frozen_parameter_leaves_the_search_of_the_next_phase(report, runner) -> None:
    transient = runner.calls[1]
    assert "K" not in transient.cfg.parameters
    assert "K" not in transient.space.names


def test_a_frozen_parameter_enters_the_baseline_of_the_next_phase(report, runner) -> None:
    steady, transient = runner.calls
    assert steady.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_CALIBRATED)
    assert transient.baseline.flow.param.Sy.field.value == pytest.approx(SY_TOML)


def test_the_prepared_pipeline_treats_the_frozen_path_as_varying(report, runner) -> None:
    # A preparation step reading the frozen path has to re-run per trial,
    # otherwise the prepared prefix would keep the value the TOML declares.
    assert runner.prepared[0] == {"K": K_PATH}
    assert runner.prepared[1] == {"Sy": SY_PATH, "K": K_PATH}


def test_the_report_names_each_frozen_value_with_its_path(report) -> None:
    assert [item.to_dict() for item in report.frozen] == [
        {
            "name": "K",
            "path": K_PATH,
            "value": pytest.approx(K_CALIBRATED),
            "mode": "replace",
            "phase": "steady_k",
        },
        {
            "name": "Sy",
            "path": SY_PATH,
            "value": pytest.approx(SY_CALIBRATED),
            "mode": "replace",
            "phase": "transient_sy",
        },
    ]
    assert report.to_dict()["phases"][0]["frozen"][0]["path"] == K_PATH


def test_freeze_on_success_false_leaves_the_next_phase_free_to_move_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_staged(tmp_path, NO_FREEZE))

    transient = runner.calls[1]
    assert "K" in transient.cfg.parameters
    assert "K" in transient.space.names
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert report.phases[0].frozen == ()


@pytest.mark.parametrize("best_cost", [None, FAILED_EVAL_COST], ids=["no_result", "sentinel"])
def test_a_phase_that_did_not_converge_freezes_nothing(tmp_path, monkeypatch, best_cost) -> None:
    # No phase of INDEPENDENT is written against what another one freezes, so
    # the chain survives the failure and what it hands over stays observable.
    fake = FakeRunner(best_cost=best_cost)
    fake.patch(monkeypatch)

    report = run_staged_calibration(_write_staged(tmp_path, INDEPENDENT))

    assert report.frozen == ()
    assert fake.calls[1].baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert "K" not in fake.prepared[1]


def test_a_freezing_phase_that_produced_no_result_stops_the_chain(tmp_path, monkeypatch) -> None:
    """TWO_PHASES writes ``transient_sy`` against what ``steady_k`` freezes.

    When ``steady_k`` hands nothing over, running ``transient_sy`` would
    calibrate it against the values the TOML declares. Its dependency did run,
    so nothing else in the chain is in a position to notice.
    """
    fake = FakeRunner(best_cost=None)
    fake.patch(monkeypatch)

    with pytest.raises(CalibrationError) as refusal:
        run_staged_calibration(_write_staged(tmp_path))

    assert fake.phases_run == ["steady_k"]
    message = str(refusal.value)
    assert "steady_k" in message
    assert "transient_sy" in message
    assert fake.calls[0].session_id in message


# -- selecting one phase -----------------------------------------------------
def test_selecting_a_phase_whose_dependency_did_not_run_is_refused(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="steady_k"):
        run_staged_calibration(_write_staged(tmp_path), phase="transient_sy")

    assert runner.calls == []


def test_selecting_an_independent_phase_runs_only_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_staged(tmp_path), phase="steady_k")

    assert runner.phases_run == ["steady_k"]
    assert [(phase.name, phase.index) for phase in report.phases] == [("steady_k", 0)]
    assert runner.calls[0].session_id == report.session_id


def test_selecting_an_undeclared_phase_lists_the_declared_ones(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="transient_sy"):
        run_staged_calibration(_write_staged(tmp_path), phase="nowhere")


def test_a_calibration_without_phases_is_refused(tmp_path, runner) -> None:
    with pytest.raises(CalibrationError, match="run_calibration_cli"):
        run_staged_calibration(_write_staged(tmp_path, ""))


# -- what is checked before the first solve ----------------------------------
def test_a_phase_that_cannot_be_built_is_refused_before_the_first_one_runs(
    tmp_path, runner
) -> None:
    """A phase option its method does not take is refused when the file loads.

    ``transient_sy`` narrows to a grid search while carrying a setting of the
    root search, so its method_options name a key its own method refuses. The
    refusal used to wait for its turn, by which time ``steady_k`` had spent its
    twelve solves. Loading the file now refuses it, naming the phase and the key.
    """
    with pytest.raises(ConfigError, match="phase 'transient_sy' method_options: 'grid'"):
        run_staged_calibration(_write_staged(tmp_path, BAD_SECOND_PHASE))

    assert runner.calls == []
    assert runner.prepared == []


def test_a_phase_override_that_names_no_field_is_refused_with_its_path(
    tmp_path, monkeypatch
) -> None:
    """A dotted override is checked at every segment, not only at its leaf.

    The configuration below has a ``flow`` and no ``flowx``, so the answer is
    known before the writer runs. A non-leaf typo used to leave the runner as
    a bare ``AttributeError``, which the CLI has no code for.
    """
    from pydantic import BaseModel, ConfigDict

    class Flow(BaseModel):
        model_config = ConfigDict(extra="forbid")
        flow_regime: str = "steady"

    class Root(BaseModel):
        model_config = ConfigDict(extra="forbid")
        flow: Flow = Flow()

    monkeypatch.setattr(
        trial_module,
        "get_root_config_provider",
        lambda: SimpleNamespace(from_toml=lambda path: Root()),
    )
    cfg_path = tmp_path / "project.toml"
    cfg_path.write_text('[simulation]\nname = "toy"\n', encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=r"flowx\.flow_regime"):
        trial_module.prepare_trials(
            cfg_path,
            override_paths={"K": "flow.flow_regime"},
            config_overrides={"flowx.flow_regime": "transient"},
        )


def test_a_refused_preparation_is_reported_with_the_phase_that_asked_for_it(
    tmp_path, monkeypatch
) -> None:
    """The preparation does not know which phase asked; the runner does.

    A staged calibration prepares once per phase, so a refusal that names only
    the path leaves the reader to guess which of the declared phases owns it.
    """

    def refuse(*args, **kwargs):
        raise ConfigValidationError("config override 'flowx.flow_regime' cannot be written")

    monkeypatch.setattr(staged_runner, "prepare_trials", refuse)

    with pytest.raises(ConfigValidationError) as refusal:
        run_staged_calibration(_write_staged(tmp_path))

    message = str(refusal.value)
    assert "steady_k" in message
    assert "flowx.flow_regime" in message


# -- return shape ------------------------------------------------------------
def test_the_runner_always_returns_a_report_whose_summary_lists_the_phases(report) -> None:
    assert isinstance(report, CalibrationReport)
    payload = report.to_dict()
    assert [item["phase"] for item in payload["phases"]] == ["steady_k", "transient_sy"]
    assert payload["session_id"] == payload["phases"][0]["session_id"]


def test_the_report_carries_the_session_of_the_run(report) -> None:
    assert report.session_id == report.phases[0].session_id == report.phases[1].session_id
    assert report.to_dict()["session_dir"] == str(report.session_dir)


# -- one session, its phases --------------------------------------------------
def test_every_phase_writes_into_the_one_session_of_the_case(report, runner, tmp_path) -> None:
    first, second = runner.calls
    assert first.session_id == second.session_id == report.session_id
    assert first.session_dir == second.session_dir == tmp_path / "sessions" / "calibration"
    assert (first.phase.index, second.phase.index) == (0, 1)
    assert (first.phase.name, second.phase.name) == ("steady_k", "transient_sy")
    assert (first.phase.restart, second.phase.restart) == (0, 0)
    phases = list_phases(report.session_dir)
    assert [(p.name, p.index, p.status) for p in phases] == [
        ("steady_k", 0, "completed"),
        ("transient_sy", 1, "completed"),
    ]
    assert phases[1].frozen["K"].value == pytest.approx(K_CALIBRATED)
    assert phases[1].frozen["K"].from_phase == "steady_k"


def test_the_session_is_named_by_the_file_that_carries_calibration(report, tmp_path) -> None:
    assert report.session_dir == tmp_path / "sessions" / "calibration"
    descriptor = read_session(report.session_dir)
    assert descriptor.case_id == "calibration"
    assert descriptor.status == "completed"
    assert (report.session_dir / "config.toml").is_file()


def test_a_second_run_of_the_file_takes_the_next_version(tmp_path, runner) -> None:
    run_staged_calibration(_write_staged(tmp_path))
    report = run_staged_calibration(_write_staged(tmp_path))

    assert report.session_dir == tmp_path / "sessions" / "calibration.v2"


# -- restart-based uncertainty ------------------------------------------------
MULTISTART = """
[calibration.uncertainty]
method = "multistart"
restarts = 3
"""

NELDER_PHASES = phases_toml({**STEADY_K, "method": "scipy_nelder_mead", "outputs": ["q"]})


def _write_multistart(tmp_path: Path) -> Path:
    return _write_staged(tmp_path, NELDER_PHASES, MULTISTART)


def test_without_restarts_one_phase_is_one_search(report, runner) -> None:
    assert len(runner.calls) == 2
    assert all(call.start_at is None for call in runner.calls)


def test_restarts_run_the_phase_that_many_times(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_multistart(tmp_path))

    assert len(runner.calls) == 3
    assert [phase.name for phase in report.phases] == ["steady_k"]


def test_the_first_restart_is_the_search_that_would_have_run_alone(tmp_path, runner) -> None:
    # The answer a file already published stays in the set: the engine keeps its
    # own start and the declared seed for restart one.
    run_staged_calibration(_write_multistart(tmp_path))

    assert runner.calls[0].start_at is None
    assert all(call.start_at is not None for call in runner.calls[1:])


def test_each_restart_carries_its_own_seed(tmp_path, runner) -> None:
    run_staged_calibration(_write_multistart(tmp_path))

    assert len({call.seed for call in runner.calls}) == 3


ROOT_OUTSIDE = "root K = 1 closed OUTSIDE the declared bounds [1e-07, 0.001]"


def _closes_the_first_phase_outside(runner, monkeypatch) -> None:
    search = runner.run_calibration_core

    def outside_on_the_first_phase(cfg, *args, **kwargs):
        report = search(cfg, *args, **kwargs)
        if "K" not in cfg.parameters:
            return report
        extra = {**report.extra, "root_outside_bounds": ROOT_OUTSIDE, "search_status": "partial"}
        return replace(report, extra=extra)

    monkeypatch.setattr(cli_runner, "run_calibration_core", outside_on_the_first_phase)


def test_a_root_outside_its_bounds_closes_the_phase_partial_and_freezes_nothing(
    tmp_path, runner, monkeypatch
) -> None:
    _closes_the_first_phase_outside(runner, monkeypatch)

    report = run_staged_calibration(_write_staged(tmp_path, INDEPENDENT))

    steady = read_phase(report.session_dir, "steady_k")
    assert (steady.status, steady.stop_note) == ("partial", ROOT_OUTSIDE)
    assert read_phase(report.session_dir, "transient_sy").frozen == {}
    descriptor = read_session(report.session_dir)
    assert descriptor.status == "partial"
    assert descriptor.stop_note == f"phase steady_k {ROOT_OUTSIDE}"
    assert f"phase steady_k {ROOT_OUTSIDE}" in descriptor.error_message
    assert descriptor.widths == {}


def test_a_phase_built_on_a_root_outside_its_bounds_is_refused(
    tmp_path, runner, monkeypatch
) -> None:
    _closes_the_first_phase_outside(runner, monkeypatch)

    with pytest.raises(CalibrationError, match="not a solved value, so it is not passed on"):
        run_staged_calibration(_write_staged(tmp_path))


def test_the_report_publishes_the_spread_beside_the_value(tmp_path, runner, caplog) -> None:
    with caplog.at_level(logging.INFO):
        report = run_staged_calibration(_write_multistart(tmp_path))

    spread = {item.parameter: item for item in report.restart_spreads}
    assert "K" in spread
    # The fake returns the same optimum every time, so the spread is degenerate
    # and says so rather than inventing a width.
    assert spread["K"].lowest == pytest.approx(spread["K"].highest)
    assert spread["K"].best == pytest.approx(spread["K"].lowest)
    assert report.to_dict()["restart_spreads"][0]["n_restarts"] == 3
    # The phase prints the extent and writes it, and the session takes it from the phase.
    assert "restarts spanned" in caplog.text
    landed = read_phase(report.session_dir, "steady_k").widths["K"].restarts
    assert (landed.lowest, landed.highest) == (K_CALIBRATED, K_CALIBRATED)
    assert landed.values == [K_CALIBRATED] * 3
    assert read_session(report.session_dir).widths["K"].restarts == landed


def test_restarts_on_an_exhaustive_sweep_are_refused(tmp_path, runner) -> None:
    with pytest.raises(ValueError, match="same answer every time"):
        run_staged_calibration(_write_staged(tmp_path, section=MULTISTART))


def test_a_phase_may_ask_for_restarts_the_section_does_not(tmp_path, runner) -> None:
    # The uncertainty method is the phase's own over the section's: only the
    # phase that asks for restarts repeats its search.
    phases = phases_toml(
        {
            **STEADY_K,
            "method": "scipy_nelder_mead",
            "uncertainty": {"method": "multistart", "restarts": 3},
        },
        H_SY,
    )
    report = run_staged_calibration(_write_staged(tmp_path, phases))

    assert runner.phases_run == ["steady_k"] * 3 + ["transient_sy"]
    assert [len(item.values) for item in report.restart_spreads] == [3]


# -- the width each phase reads its interval with ----------------------------
def test_each_phase_hands_the_search_its_own_width(tmp_path, runner) -> None:
    section = '\n[calibration.uncertainty]\ncost_margin = "20%"\n'
    phases = phases_toml(
        {**STEADY_K, "outputs": ["q"]}, {**H_SY, "uncertainty": {"cost_margin": "10%"}}
    )
    run_staged_calibration(_write_staged(tmp_path, phases, section))

    steady, transient = (call.interval_width for call in runner.calls)
    assert (steady.margin, steady.kind, steady.source) == (
        pytest.approx(0.2),
        "relative",
        "section",
    )
    assert (transient.margin, transient.kind, transient.source) == (
        pytest.approx(0.1),
        "relative",
        "phase",
    )
    # The phase configuration carries the same keys, for the session and the report.
    assert runner.calls[1].cfg.uncertainty.cost_margin == "10%"


# -- linearized uncertainty ---------------------------------------------------
LINEARIZED = '\n[calibration.uncertainty]\nmethod = "linearized"\nperturbation = 0.01\n'


@pytest.fixture
def width(monkeypatch) -> list[SimpleNamespace]:
    """Stands in for the model rebuild a linearized width would run, and lists its calls.

    The real ``attach_a_linearized_width`` perturbs each parameter and reruns
    the model; what is under test here is that staged_runner calls it once per
    phase, with that phase's own configuration, not whether the derivative
    itself is right (covered where the real function is tested).
    """
    calls: list[SimpleNamespace] = []

    def attach(report, *, cfg, trial_ctx, space, perturbation):
        calls.append(SimpleNamespace(cfg=cfg))
        widened = SimpleNamespace(parameter=next(iter(cfg.parameters)), sigma=0.1)
        return replace(report, parameter_uncertainty=(widened,))

    monkeypatch.setattr(staged_runner, "attach_a_linearized_width", attach)
    return calls


@pytest.fixture
def linearized(tmp_path, runner, width) -> CalibrationReport:
    return run_staged_calibration(_write_staged(tmp_path, section=LINEARIZED))


def test_linearized_uncertainty_attaches_a_width_to_each_phase(linearized, width) -> None:
    assert len(width) == 2
    assert all(phase.report.parameter_uncertainty for phase in linearized.phases)
    assert read_phase(linearized.session_dir, "steady_k").widths["K"].sigma == 0.1
    assert read_session(linearized.session_dir).widths["Sy"].sigma == 0.1


def test_linearized_uncertainty_reads_the_phase_that_scored_it(linearized, width) -> None:
    # steady_k scores q_block/q, transient_sy scores h_block/h: the width has
    # to be taken through the phase's own configuration, not the document's.
    steady, transient = width
    assert list(steady.cfg.outputs) == ["q"]
    assert list(transient.cfg.outputs) == ["h"]
    assert next(iter(steady.cfg.parameters)) == "K"
    assert next(iter(transient.cfg.parameters)) == "Sy"


def test_a_width_conditional_on_an_earlier_freeze_says_so(linearized) -> None:
    # transient_sy depends_on steady_k and steady_k freezes K by default: the
    # second phase's width is conditional on a value it did not calibrate.
    steady, transient = linearized.phases
    assert "parameter_uncertainty_note" not in steady.report.extra
    assert "K" in transient.report.extra["parameter_uncertainty_note"]


# A phase without an evaluator that prepares a model never reaches
# ``_attach_linearized_width`` with ``trial_ctx=None``: ``run_staged_calibration``
# already refuses that evaluator up front, with a more precise message, and
# ``prepare_trials`` never returns ``None``. A second, less precise refusal
# behind it would be dead code reachable only by calling the private helper
# directly, which is what such a test would do -- covered instead below by
# giving the same evaluator to the public entry point.
def test_an_evaluator_that_prepares_no_model_is_refused_before_any_phase_solves(
    tmp_path, monkeypatch
) -> None:
    # The refusal itself predates this phase. What is asserted here is that it
    # still comes FIRST: an evaluator that prepares no model is turned away
    # before any phase runs, so the linearized width this document asks for is
    # never reached. Counting the calls is what makes the test fail if the
    # width dispatch is ever moved ahead of the refusal.
    calls: list[str] = []
    monkeypatch.setattr(
        staged_runner,
        "attach_a_linearized_width",
        lambda *args, **kwargs: calls.append("called"),
    )
    path = write_document(
        tmp_path,
        STAGED_HEAD.replace('method = "grid"', 'method = "grid"\nevaluator = "analytic_bowl"', 1)
        + LINEARIZED
        + TWO_PHASES,
    )

    with pytest.raises(CalibrationError, match="runs no HydroModPy model"):
        run_staged_calibration(path)

    assert calls == []


def test_a_single_metric_phase_keeps_its_report_and_names_why_no_width_is_attached(
    tmp_path, runner, monkeypatch
) -> None:
    # Single-metric route: no residual vector, structurally, so the width is
    # skipped before ``attach_a_linearized_width`` is even called -- cheap
    # enough to exercise the real ``_attach_linearized_width``, not a double.
    #
    # ``staged_runner.logger`` is patched directly rather than read through
    # ``caplog``: its underlying "hydromodpy" logger has ``propagate`` turned
    # off the moment anything in the process builds a ``LogManager``, which
    # would silently blind a root-attached capture handler.
    warnings: list[str] = []
    monkeypatch.setattr(
        staged_runner.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    single_metric = phases_toml(
        {**STEADY_K, "variable": "discharge", "objective": "nse", "objective_blocks": None}
    )
    path = _write_staged(tmp_path, single_metric, LINEARIZED)

    report = run_staged_calibration(path)

    (steady,) = report.phases
    assert not steady.report.parameter_uncertainty
    text = " ".join(warnings)
    assert "steady_k" in text
    assert "no linearized width is attached" in text


def test_a_phase_scoring_only_a_network_output_keeps_its_report(
    tmp_path, runner, monkeypatch
) -> None:
    # The regression this guard exists for, and the one that cost a whole
    # staged run. ``CalibOutputNetwork`` carries no ``observes`` field at all
    # -- the loader refuses one -- so a phase scored on it holds an output,
    # holds no station, and can never hold one. A guard reading
    # ``bool(phase_cfg.outputs)`` called the real width builder anyway, which
    # raised on the empty residual vector and killed the run AFTER the search
    # had been paid for. It is the shape of the only registered protocol:
    # ``matching_hydrographic_network`` scores its steady stage exactly here.
    warnings: list[str] = []
    monkeypatch.setattr(
        staged_runner.logger, "warning", lambda msg, *args: warnings.append(msg % args)
    )
    network = """
[calibration.outputs.net]
support = "network"
map.complete = "data.hydrography"

[calibration.outputs.net.verdict]
max_catchment_mismatch = false

[[calibration.objective_blocks]]
name = "net_block"
metric = "distance_gap"
uses_outputs = ["net"]
"""
    path = _write_staged(
        tmp_path, phases_toml({**STEADY_K, "objective_blocks": ["net_block"]}), LINEARIZED + network
    )

    report = run_staged_calibration(path)

    (steady,) = report.phases
    assert not steady.report.parameter_uncertainty
    assert "can name a station" in steady.report.extra["parameter_uncertainty_absent_note"]
    text = " ".join(warnings)
    assert "steady_k" in text
    assert "no linearized width is attached" in text


def _disk_report(tmp_path: Path) -> CalibrationReport:
    return make_report(
        session_id="disk-session",
        method="bisection",
        best_parameters={"K": K_CALIBRATED},
        workspace=tmp_path,
        extra={"reused_from_disk": True, "source_root_session_id": "root"},
    )


def test_a_phase_reused_from_disk_gets_a_note_instead_of_a_recomputed_width(
    tmp_path, runner, width, monkeypatch
) -> None:
    # A reused phase must not recompute a width -- that would rerun the model
    # on a path written precisely to avoid it -- but the absence has to be said,
    # not merely left silent.
    #
    # steady_k's stub freeze is NOT empty: an empty one would make the
    # transient phase's "conditional on a freeze" note fire for free, whether
    # or not the reuse branch is wired correctly, because ``frozen`` would
    # stay empty either way.
    disk_report = _disk_report(tmp_path)
    path = _write_staged(tmp_path, section=LINEARIZED)
    cfg, _raw = cli_runner.load_toml_calibration(path)
    declared = staged_runner.space_from_config(cfg)
    steady_froze = (
        staged_runner.FrozenParameter(
            parameter=declared["K"], value=K_CALIBRATED, phase="steady_k"
        ),
    )
    monkeypatch.setattr(
        staged_runner,
        "_reuse_from_disk",
        lambda **kwargs: (disk_report, steady_froze) if kwargs["decl"].name == "steady_k" else None,
    )

    report = run_staged_calibration(path, resume=True)

    steady, transient = report.phases
    # Reused phases must not pay for a recomputed width: only transient_sy,
    # which actually solved, may have called it.
    assert len(width) == 1
    assert next(iter(width[0].cfg.parameters)) == "Sy"
    assert (
        "reused from the reopened session"
        in (steady.report.extra["parameter_uncertainty_absent_note"])
    )
    assert transient.report.extra.get("parameter_uncertainty_absent_note") is None
    # The freeze IS non-empty this time, so this now measures the real thing:
    # transient_sy's width is conditional on the K reused from disk.
    assert "K" in transient.report.extra["parameter_uncertainty_note"]


def test_a_reused_single_metric_phase_gets_the_structural_note_not_the_reuse_one(
    tmp_path, runner, width, monkeypatch
) -> None:
    # steady_k is single-metric here: its phase_cfg carries no outputs at all
    # (_phase_config empties them), reused or not. The reuse note would blame
    # the wrong cause; the note has to name the true, structural one instead.
    disk_report = _disk_report(tmp_path)
    monkeypatch.setattr(
        staged_runner,
        "_reuse_from_disk",
        lambda **kwargs: (disk_report, ()) if kwargs["decl"].name == "steady_k" else None,
    )
    steady_single = {
        **STEADY_K,
        "variable": "discharge",
        "objective": "nse",
        "objective_blocks": None,
    }
    path = _write_staged(tmp_path, phases_toml(steady_single, H_SY), LINEARIZED)
    report = run_staged_calibration(path, resume=True)

    steady, _transient = report.phases
    note = steady.report.extra["parameter_uncertainty_absent_note"]
    assert "reused from the reopened session" not in note
    assert "can name a station" in note
    assert "no residual vector" in note


@pytest.mark.parametrize(
    ("document", "backend"),
    [
        pytest.param(
            {
                "simulation": {
                    "process": [
                        {"id": "tr", "kind": "transport", "solvers": ["modflow6"]},
                        {"id": "flow_main", "kind": "flow", "solvers": ["modflow_nwt"]},
                    ]
                }
            },
            "modflow_nwt",
            id="the_flow_process_names_the_backend",
        ),
        pytest.param(
            {
                "simulation": {"process": [{"kind": "flow", "solvers": ["boussinesq"]}]},
                "solver": {"backend": {"kind": "modflow6"}},
            },
            "boussinesq",
            id="the_flow_process_wins_over_a_solver_table",
        ),
        pytest.param(
            {"solver": {"backend": {"kind": "modflow_nwt"}}},
            "modflow_nwt",
            id="the_solver_table_is_read_without_a_flow_process",
        ),
        pytest.param(
            {"solver": {"backend": {"kind": "custom", "name": "myflow"}}},
            "myflow",
            id="a_plugin_backend_gives_its_name",
        ),
        pytest.param({}, "modflow6", id="a_document_that_names_none_runs_the_default"),
    ],
)
def test_the_methods_paragraph_names_the_solver_the_trials_run(document, backend) -> None:
    assert staged_runner._backend_name(document) == backend


def _steady_phase(**overrides):
    payload = {"name": "steady_conductivity", "regime": "steady", "parameters": ["K"]}
    payload.update(overrides)
    return CalibPhaseDecl.model_validate(payload)


def _phase_run(name: str, extra: dict) -> staged_runner.PhaseRun:
    report = make_report(session_id="s", method="bisection", duration_s=1.0, extra=extra)
    return staged_runner.PhaseRun(name=name, index=0, session_id="s", report=report, frozen=())


_DOCUMENT = {"simulation": {"time": {"start_datetime": "1995-01-01", "end_datetime": "2020-12-31"}}}


def _window(phases=None, runs=(), document=_DOCUMENT):
    cfg = SimpleNamespace(phases=[_steady_phase()] if phases is None else phases)
    return staged_runner._steady_window_summary(cfg, list(runs), document)


class TestSteadyWindowSummary:
    """The window a staged report publishes is the one the model actually ran with."""

    @pytest.mark.parametrize(
        ("phases", "document"),
        [
            ([_steady_phase(regime="transient")], _DOCUMENT),
            (None, _DOCUMENT),
            ([_steady_phase()], {}),
        ],
        ids=["no_steady_phase", "no_phases", "unresolvable_window"],
    )
    def test_no_window_is_none(self, phases, document) -> None:
        cfg = SimpleNamespace(phases=phases)
        assert staged_runner._steady_window_summary(cfg, [], document) is None

    def test_the_window_reads_back_from_regime_overrides(self) -> None:
        window = _window()

        assert window["start"] == "1995-01-01"
        assert window["end"] == "2020-12-31"
        assert window["days"] == 9497

    def test_recharge_is_reconstructed_from_k_over_r_and_k_optim(self) -> None:
        run = _phase_run("steady_conductivity", {"k_over_r": 15110.0, "k_optim_m_s": 2.1034e-4})

        assert _window(runs=[run])["mean_recharge_m_s"] == pytest.approx(2.1034e-4 / 15110.0)

    def test_recharge_is_absent_without_k_over_r(self) -> None:
        assert "mean_recharge_m_s" not in _window(runs=[_phase_run("steady_conductivity", {})])

    @pytest.mark.parametrize(
        ("start", "end", "warns"),
        [("2000-01-01", "2000-03-01", True), ("1995-01-01", "2020-12-31", False)],
        ids=["short", "long"],
    )
    def test_a_window_under_a_year_warns(self, caplog, start, end, warns) -> None:
        document = {"simulation": {"time": {"start_datetime": start, "end_datetime": end}}}
        with caplog.at_level(logging.WARNING):
            window = _window(document=document)

        assert (window["days"] < 365) is warns
        assert any("under a year" in record.message for record in caplog.records) is warns


# From test_the_methods_say_what_each_stage_scored.py
# ``methods.md`` says what each stage scored: metric, dates and pair count.
#
# The paragraph described the scoring in the generic words of the protocol,
# "scored after the first year of the run, the spin-up, unless the file declares
# a scoring window", which no longer even holds once ``[metrics] window`` is
# set. A reader citing the paragraph could not tell which dates the cost rests
# on, which metric it is, or on how many pairs. The paragraph now ends on what
# each stage minimized, read off its report.


NAME = "matching_hydrographic_network"


def _run(name: str, extra: dict) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.3, extra=extra),
    )


def _paragraph() -> str:
    net = validate_calib_output({"support": "network", "map": {"complete": "map.gpkg"}})
    cfg = SimpleNamespace(
        protocol=MatchingHydrographicNetworkOptions(name=NAME, storage="Sy"),
        outputs={"net": net},
    )
    runs = [
        _run(
            "steady_conductivity",
            {"cost_metric": "distance_gap", "cost_window": "no window, every paired sample"},
        ),
        _run(
            "transient_storage",
            {
                "cost_metric": "1 - nse_log",
                "cost_window": "window 2016-01-01 to 2020-12-31",
                "cost_samples": {
                    "hydrograph": {"n_paired": 1828, "start": "2016-01-01", "end": "2021-01-01"}
                },
            },
        ),
    ]
    text = _methods_paragraph_for(cfg, runs, [])
    assert text is not None
    return text


def test_each_stage_names_its_metric_and_the_pairs_of_its_cost() -> None:
    text = _paragraph()

    assert (
        "Scoring: stage 1 (steady_conductivity) minimised distance_gap; stage 2 "
        "(transient_storage) minimised 1 - nse_log on hydrograph 1828 pair(s), period "
        "ends 2016-01-01 to 2021-01-01, at its best trial (window 2016-01-01 to 2020-12-31)."
    ) in text


def test_the_stage_text_names_the_window_of_the_run_as_a_default() -> None:
    transient = protocol_record(NAME)["stages"][1]

    assert "[metrics] window" in transient


# From test_the_protocol_written_by_hand_runs_the_protocol.py
# Example 04 writes its protocol out as phases, and the two must run the same.
#
# ``run_calibration_by_hand.toml`` drops the protocol name and declares
# the stages it writes. If the protocol changes what it writes, or the file
# drifts, the two stop being the same calibration and this test says where.


EXAMPLE_04 = Path(__file__).resolve().parents[3] / (
    "examples/projects/04_streamflow_intermittence_in_transient"
)


@pytest.fixture(scope="module")
def calibrations():
    protocol = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration.toml").calibration
    by_hand = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration_by_hand.toml").calibration
    return protocol, by_hand


@pytest.mark.fast
def test_only_the_protocol_name_differs(calibrations) -> None:
    protocol, by_hand = calibrations

    assert protocol.protocol is not None
    assert by_hand.protocol is None
    first = protocol.model_dump(mode="json", exclude={"protocol"})
    second = by_hand.model_dump(mode="json", exclude={"protocol"})
    assert first == second


@pytest.mark.fast
def test_each_stage_runs_the_same_search(calibrations) -> None:
    protocol, by_hand = calibrations

    for ours, theirs in zip(protocol.phases, by_hand.phases, strict=True):
        assert staged_runner._phase_config(protocol, ours).model_dump(
            mode="json"
        ) == staged_runner._phase_config(by_hand, theirs).model_dump(mode="json")


# The refusals and the fallbacks of the helpers the staged run is built from.


def _staged_cfg(**phase: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {
                "K": {
                    "bounds": [1e-9, 1e-3],
                    "search_space": "log",
                    "path": "flow.param.K.field.value",
                }
            },
            "phases": [{"name": "stage", "parameters": ["K"], **phase}],
        }
    )


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("phase_overrides", "gives regime = None, which cannot be written: boom"),
        ("space_from_config", "a parameter space that cannot be built: boom"),
    ],
)
def test_a_phase_that_cannot_be_prepared_is_refused_before_the_first_solve(
    monkeypatch, target, message
) -> None:
    def refuse(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(staged_runner, target, refuse)
    cfg = _staged_cfg()

    with pytest.raises(ConfigValidationError, match=f"phase 'stage' .*{message}"):
        staged_runner._phase_plans(cfg, list(enumerate(cfg.phases)), {})


def test_a_phase_whose_search_its_optimizer_refuses_is_named(monkeypatch) -> None:
    def refuse(self):
        raise ValueError("boom")

    monkeypatch.setattr(CalibrationConfig, "validate_registry", refuse)
    cfg = _staged_cfg()

    with pytest.raises(
        ConfigValidationError, match="declares a search its optimizer refuses: boom"
    ):
        staged_runner._phase_plans(cfg, list(enumerate(cfg.phases)), {})


def test_a_phase_without_a_method_says_which_one_it_runs(caplog) -> None:
    cfg = _staged_cfg()
    method, reason = cfg.method_for(cfg.phases[0])

    with caplog.at_level(logging.INFO):
        staged_runner._phase_plans(cfg, list(enumerate(cfg.phases)), {})

    assert f"Phase stage names no method and runs {method}: {reason}." in caplog.text


def test_a_settled_phase_without_its_value_has_nothing_to_freeze(monkeypatch) -> None:
    monkeypatch.setattr(staged_runner, "_settled", lambda report: True)
    monkeypatch.setattr(staged_runner, "_froze_budget_only", lambda report: False)
    decl = CalibPhaseDecl.model_validate({"name": "stage", "parameters": ["K"]})

    with pytest.raises(CalibrationError, match=r"carries no value for \['K'\]"):
        staged_runner._frozen_by(decl, make_report(best_parameters={"Sy": 0.1}), None)


def test_a_phase_the_calibration_does_not_declare_cannot_be_replayed() -> None:
    cfg = _staged_cfg()

    with pytest.raises(CalibrationError, match="declares no phase 'other'"):
        staged_runner.replay_phase(cfg, {}, Path("."), "other", {})


@pytest.mark.parametrize(
    ("output", "where"),
    [
        (SimpleNamespace(support="point", geometry="g"), "its declared geometry"),
        (SimpleNamespace(support="cell", row=3, col=4), "cell (row 3, col 4)"),
        (SimpleNamespace(support="lake", lake_id=7), "lake 7"),
        (SimpleNamespace(support="boundary", boundary_id="outlet"), "boundary 'outlet'"),
        (SimpleNamespace(support="network"), ""),
        (SimpleNamespace(support="point", x=1, y=2.50), "(1, 2.5)"),
    ],
)
def test_an_output_says_where_it_reads_its_simulated_value(output, where) -> None:
    assert staged_runner._output_where(output) == where


def test_a_missing_coordinate_reads_as_unknown() -> None:
    assert staged_runner._length_text(None) == "?"


def test_a_block_less_selection_has_no_comparison_row() -> None:
    cfg = SimpleNamespace(
        objective_blocks=["declared"], objective_blocks_for=lambda phase: [], outputs=None
    )

    assert staged_runner.objective_comparison_table(cfg) == []


@pytest.mark.parametrize(
    ("document", "backend"),
    [
        (
            {
                "simulation": {
                    "process": ["text", {"kind": "heat"}, {"kind": "flow", "solvers": ["mf6"]}]
                }
            },
            "mf6",
        ),
        ({"simulation": {"process": [{"kind": " FLOW ", "solvers": [" nwt "]}]}}, "nwt"),
    ],
)
def test_the_backend_is_the_first_solver_of_the_first_flow_process(document, backend) -> None:
    assert staged_runner._backend_name(document) == backend


def test_a_calibration_without_a_protocol_has_no_methods_paragraph() -> None:
    assert staged_runner._methods_paragraph_for(_staged_cfg(), [], []) is None


def test_a_stage_that_counted_no_pair_reads_its_declared_window() -> None:
    def stage(name, **extra):
        return SimpleNamespace(name=name, report=SimpleNamespace(extra=extra))

    runs = [
        stage("silent"),
        stage("a", cost_metric="rmse", cost_window="window 2001-2002"),
        stage("b", cost_metric="nse", cost_window="calibration"),
    ]

    assert staged_runner._scoring_sentence(runs) == (
        "Scoring: stage 2 (a) minimised rmse over the window 2001-2002, pairs not counted; "
        "stage 3 (b) minimised nse."
    )
    assert staged_runner._scoring_sentence(runs[:1]) is None
