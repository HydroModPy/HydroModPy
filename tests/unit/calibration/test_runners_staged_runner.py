"""A calibration run in phases, and the report it publishes.

Phases run in order inside one session. A converged phase freezes its values (K in
m/s, Sy as given) into the model of the next one, and its stop state, widths and
scoring are written to the session. No solver runs: a fake runner or a closed-form
metric stands in for each trial.
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_outputs import CalibOutputPoint, validate_calib_output
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.objective import CompositeObjective, build_objective_from_config
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace, set_by_path
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import document, staged_report, staged_runner
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import search as search_module
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.document import load_toml_calibration
from hydromodpy.calibration.runners.recap import staged_result_lines
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.calibration.runners.staged_report import (
    _observed_source,
    methods_paragraph_for,
    objective_comparison_table,
    phase_summaries,
)
from hydromodpy.calibration.runners.staged_runner import (
    _frozen_by,
    _phase_config,
    _require_result_for_dependents,
    run_staged_calibration,
)
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.cli.commands.calibrate import phase_line
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ConfigValidationError
from hydromodpy.core.runtime.interrupts import TerminationRequested
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.results.record.checks import BUDGET_RULE, FROZE_BUDGET_ONLY
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import list_phases, read_phase
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document
from tests._helpers.persisting_simulation import SimulationStub, persisting_simulation
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
    FakePipeline,
    FakeRunner,
    calibration_head,
    journal_trial,
    make_report,
    make_session,
    phases_toml,
    write_document,
)

# Every phase here runs real trials, so the module asks for the trial pipeline
# the way a session would: filled once by the project package, before the first
# trial forks.
pytestmark = pytest.mark.usefixtures("ensure_bootstrap")

# A phase passes its values on when its engine met its rule or spent its plan. A
# random search with no rule of its own that spent its budget passes them on too, and
# says "froze the best of a budget-only search". An engine with a rule that the budget
# stopped first passes nothing on, and a phase that depends on it is refused.


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


def test_random_search_feeds_next_phase(tmp_path: Path, toy: ToyPipeline, caplog) -> None:
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


def test_budget_only_search_freezes_best(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", BUDGET_RULE), _space())

    assert [(item.name, item.value) for item in froze] == [("K", 20.0)]
    assert FROZE_BUDGET_ONLY in caplog.text
    _require_result_for_dependents(DECL, _report("budget_spent", BUDGET_RULE), DEPENDENT)


def test_rule_engine_cut_by_budget(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", "xatol"), _space())

    assert froze == ()
    assert "before its stopping rule (xatol) was met" in caplog.text
    with pytest.raises(CalibrationError, match="freezes what"):
        _require_result_for_dependents(DECL, _report("budget_spent", "xatol"), DEPENDENT)


# Key by key (method, max_trials, precision, method_options) the phase wins, then
# the `[calibration]` section, then the default.


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


MAX_TRIALS = [
    pytest.param(
        [_phase("a"), _phase("b", max_trials=7)],
        {"max_trials": 40},
        [40, 7],
        id="section budget unless the phase writes one",
    ),
    pytest.param([_phase()], {}, ["auto"], id="nothing written"),
    pytest.param(
        [_phase(max_trials="auto")], {"max_trials": 40}, ["auto"], id="phase asks for auto"
    ),
]


@pytest.mark.parametrize(("phases", "section", "budgets"), MAX_TRIALS)
def test_phase_budget(phases, section, budgets) -> None:
    cfg = _cfg(*phases, **section)

    assert [cfg.max_trials_for(phase) for phase in cfg.phases] == budgets


def test_unwritten_phase_budget() -> None:
    cfg = _cfg(_phase("a"), _phase("b", max_trials=7), max_trials=40)
    a, b = cfg.phases

    assert (a.max_trials, b.max_trials) == (None, 7)
    assert _cfg().max_trials_for(None) == "auto"


def test_precision_skips_budget_engines() -> None:
    cfg = _cfg(_phase(method="grid"), _phase("b", method="optuna"), precision=0.01)

    assert [cfg.precision_for(phase) for phase in cfg.phases] == [None, None]
    assert not [finding for finding in _findings(cfg) if "precision" in finding.detail]


def test_phase_precision_on_budget_engine_refused() -> None:
    findings = _findings(_cfg(_phase(method="grid", precision=0.01)))

    assert [finding.severity for finding in findings if "precision" in finding.detail] == ["error"]


def test_phase_method_options() -> None:
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


def test_method_options_need_a_method() -> None:
    with pytest.raises(ValidationError, match="phase 'k' gives method_options and no method"):
        _cfg(_phase(method_options={"sweep_points": 3}))

    inherited = _cfg(_phase(method_options={"sweep_points": 3}), method="bisection")
    assert inherited.method_options_for(inherited.phases[0]) == {"sweep_points": 3}


def test_listing_gives_source_of_each_key() -> None:
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


NANCON_PROJECT = """\
[site]
name = "nancon"
gauge = "NANCON"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem", "hydrography", "hydrometry"]

[[data.dem.sources]]
source = "file"
path = "inputs/DEM_armorican_massif.tif"

[[data.hydrography.sources]]
source = "file"
path = "inputs/nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "file"
path = "inputs/hydrometry"
station_ids = ["NANCON"]

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"

[calibration.outputs.seepage_network.map]
complete = "inputs/nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
"""


def nancon_project(root: Path) -> Path:
    project = root / "projects" / "nancon"
    for relative in ("DEM_armorican_massif.tif", "nancon_stream_network.gpkg"):
        (project / "inputs" / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / "inputs" / relative).write_bytes(b"x")
    (project / "inputs" / "hydrometry").mkdir(parents=True)
    (project / "project.toml").write_text(NANCON_PROJECT, encoding="utf-8")
    return project


def test_protocol_stage_search_keys(
    tmp_path: Path,
) -> None:
    project = nancon_project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        NANCON_PROJECT + "\n[calibration]\nprecision = 0.02\nmax_trials = 40\n", "utf-8"
    )

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


# A phase moves the parameters it lists. Every other parameter holds the last value
# an earlier converged phase passed on, else the value of the model file. A phase that
# lists a parameter already passed on moves it again, from that value when its engine
# accepts a start point.


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
        bounds=None,
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


def test_nelder_mead_starts_at_passed_value(tmp_path, toy) -> None:
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


def test_grid_takes_no_start_point(tmp_path, capsys) -> None:
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


def test_grid_keeps_its_own_start(tmp_path, toy) -> None:
    # Two points per parameter keep the 2 x 2 grid of the last phase within its 4 trials.
    document = _base("grid", method_options={"points_per_dim": 2})
    report = run_staged_calibration(write_document(tmp_path, document), metric_fn=toy.metric)

    # The grid's first point is its lower corner, not a passed value.
    k, sy = toy.first_trial_of(2)
    assert k == pytest.approx(1e-9)
    assert sy == pytest.approx(0.001)
    assert [item.name for item in report.phases[2].reopened] == ["K", "Sy"]


def test_latest_freeze_wins(tmp_path, monkeypatch) -> None:
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


def test_aliased_name_starts_from_latest(tmp_path, monkeypatch) -> None:
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


# A phase may narrow `bounds` inside the ones `[calibration]` declares. They are
# refused at load against the bounds the file writes, and again before the first solve
# against the resolved ones (a field's own range when the section writes none).


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
        ({"K": [1e-8, 1e-4]}, "phase 'k'.*'K'"),
    ],
)
def test_bounds_refused_at_load(bounds: dict[str, list[float]], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        _cfg(_phase(bounds=bounds))


def test_phase_bounds_enter_its_calibration() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert phase_cfg.parameters["K"].bounds == [1e-6, 1e-4]
    assert cfg.parameters["K"].bounds == [1e-7, 1e-3]


def test_bounds_outside_resolved_refused() -> None:
    """The section writes none; the catalog's range, filled in after load, is the frame."""
    cfg = _cfg(
        _phase(bounds={"K": [1e-8, 1e-4]}),
        parameters={"K": {"search_space": "log"}},
    )
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    with pytest.raises(ConfigValidationError, match=r"\[1e-08, 0.0001\].*\[1e-07, 0.001\]"):
        _phase_config(cfg, cfg.phases[0])


def test_bounds_inside_resolved_run() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}), parameters={"K": {"search_space": "log"}})
    cfg.parameters["K"].bounds = [1e-7, 1e-3]

    assert _phase_config(cfg, cfg.phases[0]).parameters["K"].bounds == [1e-6, 1e-4]


def test_preflight_refuses_outside_bounds() -> None:
    cfg = _cfg(_phase(bounds={"K": [1e-6, 1e-4]}))
    cfg.parameters["K"].bounds = [1e-5, 1e-3]

    class _Config:
        calibration = cfg

    findings = preflight_calibration(_Config(), source=Path("calibration.toml"))
    refused = [
        finding for finding in findings if finding.detail.partition(": ")[0].endswith(" bounds")
    ]

    assert [finding.severity for finding in refused] == ["error"]
    assert "[1e-05, 0.001]" in refused[0].detail


def test_list_phases_prints_bounds() -> None:
    cfg = _cfg(_phase("wide"), _phase("narrow", bounds={"K": [1e-6, 1e-4]}))
    wide, narrow = phase_summaries(cfg)

    assert "bounds" not in wide
    assert narrow["bounds"] == {"K": [1e-6, 1e-4]}
    assert "bounds K [1e-06, 0.0001]" in phase_line(1, narrow)
    assert "bounds" not in phase_line(0, wide)


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
def test_point_output_location(output, expected) -> None:
    assert _quantity(output) == expected


# `--list-phases` and `--check` show, per objective block, its criterion, its
# normalized share, the simulated quantity and the observed source. A phase that
# scores no block takes the single-metric route, one row. The table reads
# declarations only, so it needs no data on disk.


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


def _calibration_from(tmp_path: Path, text: str):
    cfg, _raw = load_toml_calibration(write_document(tmp_path, text))
    return cfg


def _rows_by_phase(cfg) -> dict[str, list[dict]]:
    return {row["name"]: row["comparisons"] for row in phase_summaries(cfg)}


@pytest.mark.fast
def test_network_block_names_the_file(tmp_path: Path) -> None:
    cfg = _calibration_from(tmp_path, SECTION + PHASES)

    rows = _rows_by_phase(cfg)["k_network"]

    assert len(rows) == 1
    assert rows[0]["block"] == "network"
    assert rows[0]["metric"] == "distance_gap"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert rows[0]["quantity"] == "release_flux (network)"
    assert rows[0]["source"].endswith("streams.gpkg")


@pytest.mark.fast
def test_shares_normalise(tmp_path: Path) -> None:
    cfg = _calibration_from(tmp_path, SECTION + PHASES)

    rows = {row["block"]: row for row in _rows_by_phase(cfg)["sy_hydrograph"]}

    # weights 99 and 1, normalized: 0.99 and 0.01.
    assert rows["hydrograph"]["share"] == pytest.approx(0.99)
    assert rows["network"]["share"] == pytest.approx(0.01)
    assert sum(row["share"] for row in rows.values()) == pytest.approx(1.0)


@pytest.mark.fast
def test_single_metric_is_one_row(tmp_path: Path) -> None:
    cfg = _calibration_from(tmp_path, SECTION + PHASES + SINGLE_METRIC_PHASE)

    rows = _rows_by_phase(cfg)["sy_single"]

    assert len(rows) == 1
    assert rows[0]["block"] is None
    assert rows[0]["metric"] == "nse_log"
    assert rows[0]["share"] == pytest.approx(1.0)
    assert "every loaded station" in rows[0]["source"]
    assert "[data.hydrometry]" in rows[0]["source"]


@pytest.mark.fast
def test_phase_less_calibration_table(
    tmp_path: Path,
) -> None:
    cfg = _calibration_from(tmp_path, SECTION)

    assert cfg.phases is None or cfg.phases == []
    rows = objective_comparison_table(cfg, None)

    assert {row["block"] for row in rows} == {"network", "hydrograph"}
    assert all(row["share"] == pytest.approx(0.5) for row in rows)


@pytest.mark.fast
def test_undeclared_source() -> None:
    output = validate_calib_output(
        dict(variable="discharge", support="boundary", boundary_id="outlet")
    )

    assert _observed_source(output) == "nothing declared"


# A phase that declares `variable` and `objective` must not inherit the blocks of
# another phase, or it would be scored on that other phase's criterion.


DISCHARGE_PHASE = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "variable": "discharge",
    "objective": "nse_log",
    "depends_on": "steady_k_over_r",
}


def _metric_route_cfg(phases: list[dict]) -> CalibrationConfig:
    return _cfg(
        *phases,
        method="grid",
        outputs={"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
        objective_blocks=[
            {"name": "abherve_gap", "metric": "distance_gap", "uses_outputs": ["net"]}
        ],
    )


METRIC_ROUTE_REFUSALS = [
    pytest.param({"objective_blocks": ["abherve_gap"]}, id="variable and blocks"),
    pytest.param({"outputs": ["net"]}, id="variable and an output"),
]


@pytest.mark.parametrize("extra", METRIC_ROUTE_REFUSALS)
def test_both_conventions_refused(extra) -> None:
    with pytest.raises(ValueError, match="Pick one convention"):
        _metric_route_cfg([{**DISCHARGE_PHASE, "depends_on": None, **extra}])


# `objective_blocks` on a phase is a list of names (declared weights are kept) or a
# table {block: share} (the phase's share replaces the weight). Shares are normalized
# to sum to one.


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


def _share_cfg(phases: list[dict]) -> CalibrationConfig:
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


@pytest.mark.parametrize(
    ("phase", "network", "hydrograph"),
    [(SEVENTY_THIRTY, 0.7, 0.3), (FIFTY_FIFTY, 0.5, 0.5)],
    ids=["seventy_thirty", "fifty_fifty"],
)
def test_share_table_sums_to_one(phase, network, hydrograph) -> None:
    cfg = _share_cfg([phase])
    weights = _normalized_weights(cfg, cfg.phases[0])

    assert weights["network"] == pytest.approx(network)
    assert weights["hydrograph"] == pytest.approx(hydrograph)


def test_phase_built_twice_keeps_shares() -> None:
    # Two phases of one config, built in turn, then the first one again:
    # a shared mutable block dict would let the second phase's share leak
    # into the first's re-read.
    cfg = _share_cfg([SEVENTY_THIRTY, FIFTY_FIFTY])

    first = _normalized_weights(cfg, cfg.phases[0])
    _normalized_weights(cfg, cfg.phases[1])
    first_again = _normalized_weights(cfg, cfg.phases[0])

    assert first == first_again
    assert first["network"] == pytest.approx(0.7)
    assert first["hydrograph"] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("shares", "message"),
    [
        ({"nowhere": 1.0}, "undeclared objective block"),
        ({"network": 0.0, "hydrograph": 1.0}, ""),
        ({"network": -1.0, "hydrograph": 1.0}, ""),
    ],
    ids=["unknown_block", "zero_share", "negative_share"],
)
def test_share_table_refusals(shares, message) -> None:
    with pytest.raises(ValueError, match=message or None):
        _share_cfg([{**SEVENTY_THIRTY, "objective_blocks": shares}])


# A phase says what model it calibrates (steady, then transient), not only how it searches.


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


def _overrides_cfg(phases: list[dict]) -> CalibrationConfig:
    return _cfg(*phases, method="grid")


OVERRIDE_REFUSALS = [
    # The frozen value would be overwritten and nothing downstream would say
    # which of the two the model actually ran with.
    pytest.param(
        [STEADY, {**TRANSIENT, "overrides": {"flow.param.K.field.value": 1e-5}}],
        "freezes",
        id="path frozen by another phase",
    ),
    pytest.param(
        [{**STEADY, "overrides": {"calibration.max_trials": 3}}],
        "own search",
        id="calibration section",
    ),
    pytest.param([{**STEADY, "overrides": {"": 1}}], "dotted path", id="empty path"),
    pytest.param([{**STEADY, "overrides": {".flow": 1}}], "dotted path", id="leading dot"),
    pytest.param([{**STEADY, "overrides": {"flow.": 1}}], "dotted path", id="trailing dot"),
]


@pytest.mark.parametrize(("phases", "message"), OVERRIDE_REFUSALS)
def test_override_refusals(phases, message) -> None:
    with pytest.raises(ValueError, match=message):
        _overrides_cfg(phases)


# `hmp calibrate --resume` reopens the session of the case. A phase completed there
# with the same fingerprint is read back, a cut phase is solved again, and `--phase`
# runs one phase on top of what the session holds.


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


def test_resume_reads_completed_phase(tmp_path, fake) -> None:
    cfg_path = _write_resume(tmp_path)
    _completed_steady_session(tmp_path, recorded_marker="v1")

    report = run_staged_calibration(cfg_path, resume=True)

    assert fake.phases_run == ["transient_sy"]
    assert report.reused_from_disk == ("steady_k",)
    assert report.session_dir == tmp_path / "sessions" / "calage"
    assert report.frozen[0].name == "K"
    assert report.frozen[0].value == pytest.approx(K_FROM_DISK)
    assert report.phases[0].report.best_trial == 1


def test_resume_freezes_reused_value(tmp_path, fake) -> None:
    cfg_path = _write_resume(tmp_path)
    _completed_steady_session(tmp_path, recorded_marker="v1")

    run_staged_calibration(cfg_path, resume=True)

    (transient_call,) = fake.calls
    assert transient_call.trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(K_FROM_DISK)


def test_resume_new_fingerprint_re_solves(tmp_path, monkeypatch, fake) -> None:
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
    phases = {p.name: p for p in CalibrationPersistence(tmp_path / "sessions" / "calage").phases()}
    assert phases["steady_k"].restarts == 1, "the re-solved phase counts a restart"


def test_phase_runs_alone(tmp_path, fake) -> None:
    cfg_path = _write_resume(tmp_path)
    _completed_steady_session(tmp_path, recorded_marker="v1")

    report = run_staged_calibration(cfg_path, phase="transient_sy")

    assert fake.phases_run == ["transient_sy"]
    assert [p.name for p in report.phases] == ["transient_sy"]
    assert fake.calls[0].trial_ctx.base_cfg.flow.param.K.field.value == pytest.approx(K_FROM_DISK)


def test_phase_without_dependency_refused(tmp_path, fake) -> None:
    cfg_path = _write_resume(tmp_path)

    with pytest.raises(CalibrationError, match="steady_k"):
        run_staged_calibration(cfg_path, phase="transient_sy")

    assert fake.calls == []


class _PromotionRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, trial_ctx, values, **kwargs):
        del trial_ctx
        self.calls.append({"values": dict(values), **kwargs})
        return kwargs["sim_id"]


PROMOTING = RESUME_DOCUMENT.replace('save_runs = "none"', 'save_runs = "best_n"')


def test_resume_keeps_promoted_run(tmp_path, monkeypatch, fake) -> None:
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


def test_better_trial_leaves_paired_run(tmp_path, monkeypatch, fake) -> None:
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


def test_interrupted_search(tmp_path, monkeypatch, fake) -> None:
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


# What a run in phases hands from one stage to the next: the order of the phases, the
# configuration each runs under, where a frozen value lands, the chain of sessions.


NO_FREEZE = phases_toml(
    {**STEADY_K, "freeze_on_success": False}, {**H_SY, "parameters": ["Sy", "K"]}
)
# The second phase is not written against what the first freezes, so a failure of
# the first can be observed without stopping the chain.
INDEPENDENT = phases_toml(STEADY_K, {**H_SY, "depends_on": None})
# `rel_tol` belongs to the root search. The second phase searches on a grid, so the
# file is refused at load, naming the phase.
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


def test_frozen_value_enters_next_baseline(report, runner) -> None:
    steady, transient = runner.calls
    assert steady.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_CALIBRATED)
    assert transient.baseline.flow.param.Sy.field.value == pytest.approx(SY_TOML)


def test_report_names_frozen_values(report) -> None:
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


def test_no_freeze_leaves_value_free(tmp_path, runner) -> None:
    report = run_staged_calibration(_write_staged(tmp_path, NO_FREEZE))

    transient = runner.calls[1]
    assert "K" in transient.cfg.parameters
    assert "K" in transient.space.names
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert report.phases[0].frozen == ()


@pytest.mark.parametrize("best_cost", [None, FAILED_EVAL_COST], ids=["no_result", "sentinel"])
def test_unconverged_phase_freezes_nothing(tmp_path, monkeypatch, best_cost) -> None:
    # No phase of INDEPENDENT is written against what another one freezes, so
    # the chain survives the failure and what it hands over stays observable.
    fake = FakeRunner(best_cost=best_cost)
    fake.patch(monkeypatch)

    report = run_staged_calibration(_write_staged(tmp_path, INDEPENDENT))

    assert report.frozen == ()
    assert fake.calls[1].baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert "K" not in fake.prepared[1]


def test_missing_result_stops_the_chain(tmp_path, monkeypatch) -> None:
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


PHASE_SELECTION_REFUSALS = [
    pytest.param(TWO_PHASES, "transient_sy", "steady_k", id="dependency did not run"),
    pytest.param(TWO_PHASES, "nowhere", "transient_sy", id="undeclared phase"),
    pytest.param("", None, "run_calibration_cli", id="no phases"),
]


@pytest.mark.parametrize(("phases", "phase", "message"), PHASE_SELECTION_REFUSALS)
def test_phase_selection_refusals(tmp_path, runner, phases, phase, message) -> None:
    with pytest.raises(CalibrationError, match=message):
        run_staged_calibration(_write_staged(tmp_path, phases), phase=phase)

    assert runner.calls == []


def test_unbuildable_phase_refused_at_load(tmp_path, runner) -> None:
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


def test_override_naming_no_field_refused(tmp_path, monkeypatch) -> None:
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
        "_PIPELINE",
        FakePipeline(config=Root(), document={"simulation": {"name": "toy"}}),
    )
    cfg_path = tmp_path / "project.toml"
    cfg_path.write_text('[simulation]\nname = "toy"\n', encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=r"flowx\.flow_regime"):
        trial_module.prepare_trials(
            cfg_path,
            override_paths={"K": "flow.flow_regime"},
            config_overrides={"flowx.flow_regime": "transient"},
        )


def test_refused_preparation_names_the_phase(tmp_path, monkeypatch) -> None:
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


def test_phases_share_one_session(report, runner, tmp_path) -> None:
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


MULTISTART = """
[calibration.uncertainty]
method = "multistart"
restarts = 3
"""

NELDER_PHASES = phases_toml({**STEADY_K, "method": "scipy_nelder_mead", "outputs": ["q"]})


def _write_multistart(tmp_path: Path) -> Path:
    return _write_staged(tmp_path, NELDER_PHASES, MULTISTART)


ROOT_OUTSIDE = "root K = 1 closed OUTSIDE the declared bounds [1e-07, 0.001]"


def _closes_the_first_phase_outside(runner, monkeypatch) -> None:
    search = runner.run_calibration_core

    def outside_on_the_first_phase(cfg, *args, **kwargs):
        report = search(cfg, *args, **kwargs)
        if "K" not in cfg.parameters:
            return report
        extra = {**report.extra, "root_outside_bounds": ROOT_OUTSIDE, "search_status": "partial"}
        return replace(report, extra=extra)

    monkeypatch.setattr(search_module, "run_calibration_core", outside_on_the_first_phase)


def test_root_outside_bounds_closes_partial(tmp_path, runner, monkeypatch) -> None:
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


def test_dependent_of_outside_root_refused(tmp_path, runner, monkeypatch) -> None:
    _closes_the_first_phase_outside(runner, monkeypatch)

    with pytest.raises(CalibrationError, match="not a solved value, so it is not passed on"):
        run_staged_calibration(_write_staged(tmp_path))


def test_report_publishes_restart_spread(tmp_path, runner, caplog) -> None:
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


def test_restarts_on_a_sweep_refused(tmp_path, runner) -> None:
    with pytest.raises(ValueError, match="same answer every time"):
        run_staged_calibration(_write_staged(tmp_path, section=MULTISTART))


def test_each_phase_has_its_own_width(tmp_path, runner) -> None:
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


def test_linearized_width_per_phase(linearized, width) -> None:
    assert len(width) == 2
    assert all(phase.report.parameter_uncertainty for phase in linearized.phases)
    assert read_phase(linearized.session_dir, "steady_k").widths["K"].sigma == 0.1
    assert read_session(linearized.session_dir).widths["Sy"].sigma == 0.1


def test_no_model_evaluator_refused_first(tmp_path, monkeypatch) -> None:
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


def test_single_metric_phase_has_no_width(tmp_path, runner, monkeypatch) -> None:
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


def test_network_phase_has_no_width(tmp_path, runner, monkeypatch) -> None:
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


def test_reused_phase_width_note(tmp_path, runner, width, monkeypatch) -> None:
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
    cfg, _raw = document.load_toml_calibration(path)
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


def test_reused_single_metric_width_note(tmp_path, runner, width, monkeypatch) -> None:
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
                "solver": {"backend": "modflow6"},
            },
            "boussinesq",
            id="the_flow_process_wins_over_a_solver_table",
        ),
        pytest.param(
            {"solver": {"backend": "modflow_nwt"}},
            "modflow_nwt",
            id="the_solver_backend_is_read_without_a_flow_process",
        ),
        pytest.param(
            {"solver": {"backend": "myflow"}},
            "myflow",
            id="a_plugin_backend_gives_its_name",
        ),
        pytest.param({}, "modflow6", id="a_document_that_names_none_runs_the_default"),
        pytest.param(
            {
                "simulation": {
                    "process": ["text", {"kind": "heat"}, {"kind": "flow", "solvers": ["mf6"]}]
                }
            },
            "mf6",
            id="first_solver_of_the_first_flow_process",
        ),
        pytest.param(
            {"simulation": {"process": [{"kind": " FLOW ", "solvers": [" nwt "]}]}},
            "nwt",
            id="blanks_and_case_are_ignored",
        ),
    ],
)
def test_backend_name(document, backend) -> None:
    assert staged_report.backend_name(document) == backend


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
    return staged_report.steady_window_summary(cfg, list(runs), document)


@pytest.mark.parametrize(
    ("phases", "document"),
    [
        ([_steady_phase(regime="transient")], _DOCUMENT),
        (None, _DOCUMENT),
        ([_steady_phase()], {}),
    ],
    ids=["no_steady_phase", "no_phases", "unresolvable_window"],
)
def test_no_window_is_none(phases, document) -> None:
    cfg = SimpleNamespace(phases=phases)
    assert staged_report.steady_window_summary(cfg, [], document) is None


def test_window_from_regime_overrides() -> None:
    window = _window()

    assert window["start"] == "1995-01-01"
    assert window["end"] == "2020-12-31"
    assert window["days"] == 9497


def test_recharge_from_k_over_r() -> None:
    run = _phase_run("steady_conductivity", {"k_over_r": 15110.0, "k_optim_m_s": 2.1034e-4})

    assert _window(runs=[run])["mean_recharge_m_s"] == pytest.approx(2.1034e-4 / 15110.0)


def test_no_recharge_without_k_over_r() -> None:
    assert "mean_recharge_m_s" not in _window(runs=[_phase_run("steady_conductivity", {})])


@pytest.mark.parametrize(
    ("start", "end", "warns"),
    [("2000-01-01", "2000-03-01", True), ("1995-01-01", "2020-12-31", False)],
    ids=["short", "long"],
)
def test_short_window_warns(caplog, start, end, warns) -> None:
    document = {"simulation": {"time": {"start_datetime": start, "end_datetime": end}}}
    with caplog.at_level(logging.WARNING):
        window = _window(document=document)

    assert (window["days"] < 365) is warns
    assert any("under a year" in record.message for record in caplog.records) is warns


# `methods.md` ends on what each stage minimized, read off its report.


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
    text = methods_paragraph_for(cfg, runs, [])
    assert text is not None
    return text


def test_scoring_sentence_per_stage() -> None:
    text = _paragraph()

    assert (
        "Scoring: stage 1 (steady_conductivity) minimised distance_gap; stage 2 "
        "(transient_storage) minimised 1 - nse_log on hydrograph 1828 pair(s), period "
        "ends 2016-01-01 to 2021-01-01, at its best trial (window 2016-01-01 to 2020-12-31)."
    ) in text


# Example 04 writes its protocol out as phases, and the two must run the same search.


EXAMPLE_04 = Path(__file__).resolve().parents[3] / (
    "examples/projects/04_streamflow_intermittence_in_transient"
)


@pytest.fixture(scope="module")
def calibrations():
    protocol = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration.toml").calibration
    by_hand = HydroModPyConfig.from_toml(EXAMPLE_04 / "run_calibration_by_hand.toml").calibration
    return protocol, by_hand


@pytest.mark.fast
def test_protocol_matches_hand_written_stages(calibrations) -> None:
    protocol, by_hand = calibrations

    for ours, theirs in zip(protocol.phases, by_hand.phases, strict=True):
        assert staged_runner._phase_config(protocol, ours).model_dump(
            mode="json"
        ) == staged_runner._phase_config(by_hand, theirs).model_dump(mode="json")


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
def test_unpreparable_phase_refused(monkeypatch, target, message) -> None:
    def refuse(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(staged_runner, target, refuse)
    cfg = _staged_cfg()

    with pytest.raises(ConfigValidationError, match=f"phase 'stage' .*{message}"):
        staged_runner._phase_plans(cfg, list(enumerate(cfg.phases)), {})


def test_refused_search_names_the_phase(monkeypatch) -> None:
    def refuse(self):
        raise ValueError("boom")

    monkeypatch.setattr(CalibrationConfig, "validate_registry", refuse)
    cfg = _staged_cfg()

    with pytest.raises(
        ConfigValidationError, match="declares a search its optimizer refuses: boom"
    ):
        staged_runner._phase_plans(cfg, list(enumerate(cfg.phases)), {})


def test_settled_phase_without_value(monkeypatch) -> None:
    monkeypatch.setattr(staged_runner, "phase_settled", lambda report: True)
    monkeypatch.setattr(staged_runner, "_froze_budget_only", lambda report: False)
    decl = CalibPhaseDecl.model_validate({"name": "stage", "parameters": ["K"]})

    with pytest.raises(CalibrationError, match=r"carries no value for \['K'\]"):
        staged_runner._frozen_by(decl, make_report(best_parameters={"Sy": 0.1}), None)


def test_undeclared_phase_not_replayed() -> None:
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
def test_output_location(output, where) -> None:
    assert staged_report._output_where(output) == where


def test_missing_coordinate() -> None:
    assert staged_report._length_text(None) == "?"


def test_no_protocol_no_paragraph() -> None:
    assert staged_report.methods_paragraph_for(_staged_cfg(), [], []) is None


def test_stage_without_pairs() -> None:
    def stage(name, **extra):
        return SimpleNamespace(name=name, report=SimpleNamespace(extra=extra))

    runs = [
        stage("silent"),
        stage("a", cost_metric="rmse", cost_window="window 2001-2002"),
        stage("b", cost_metric="nse", cost_window="calibration"),
    ]

    assert staged_report._scoring_sentence(runs) == (
        "Scoring: stage 2 (a) minimised rmse over the window 2001-2002, pairs not counted; "
        "stage 3 (b) minimised nse."
    )
    assert staged_report._scoring_sentence(runs[:1]) is None
