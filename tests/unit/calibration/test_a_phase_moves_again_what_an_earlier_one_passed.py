"""A phase that lists a parameter an earlier phase calibrated moves it again.

The rule, in declaration order: a phase moves the parameters it lists. Every
other parameter holds the last value an earlier converged phase passed on,
otherwise the value of the model file. A phase that lists a parameter already
passed on moves it again, starting from that value when its engine accepts a
start point.

No solver runs. The preparation is a toy configuration and a closed-form
metric scores each trial, so the real engine, and the first point it asks
for, is what is under test.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.calibration.runners.staged_runner import phase_summaries, run_staged_calibration
from hydromodpy.calibration.runners.trial import TrialContext

K_TOML = 1e-5
SY_TOML = 0.1
# Grid points of the first two phases: K on log10 [-9, -3], Sy on [0.001, 0.3],
# five points each. The metric's optimum sits on the K grid and near the Sy one.
K_BEST = 10**-4.5
SY_BEST = 0.1
SY_ON_THE_GRID = 0.001 + 0.25 * (0.3 - 0.001)

BASE = """
[calibration]
method = "grid"
max_iter = 5
seed = 7
use_cache = false

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
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
name = "k_first"
method = "grid"
max_iter = 5
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "sy_second"
method = "grid"
max_iter = 5
parameters = ["Sy"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "both_again"
method = "{method}"
max_iter = 4
parameters = ["K", "Sy"]
objective_blocks = ["q_block"]
"""

# K is frozen twice: by k_first, then by k_again, which moves it again.
TWICE = """
[calibration]
method = "grid"
max_iter = 5

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
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
name = "k_first"
method = "grid"
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "k_again"
method = "scipy_nelder_mead"
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "sy_last"
method = "grid"
parameters = ["Sy"]
objective_blocks = ["q_block"]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return path


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
        from hydromodpy.core.state.execution import ExecutionRegistry

        self.phase += 1
        setup = SimpleNamespace(
            workspace=SimpleNamespace(root=cfg_path.parent, project_root=cfg_path.parent),
            flow=None,
            transport=None,
            flow_runtime_overrides=None,
        )
        ctx = SimpleNamespace(
            setup=setup,
            loaded_data=SimpleNamespace(),
            data_plan=None,
            execution=ExecutionRegistry(),
            store=None,
        )
        return TrialContext(
            base_cfg=_Model(),
            ctx=ctx,
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


@pytest.fixture
def toy(monkeypatch) -> ToyPipeline:
    pipeline = ToyPipeline()
    monkeypatch.setattr(staged_runner, "prepare_trials", pipeline.prepare_trials)
    return pipeline


def test_under_nelder_mead_the_first_trial_is_the_passed_value(tmp_path, toy) -> None:
    path = _write(tmp_path, BASE.format(method="scipy_nelder_mead"))

    report = run_staged_calibration(path, metric_fn=toy.metric)

    k_first, sy_second, both = report.phases
    k_passed = k_first.report.best_parameters["K"]
    sy_passed = sy_second.report.best_parameters["Sy"]
    assert k_passed == pytest.approx(K_BEST)
    assert sy_passed == pytest.approx(SY_ON_THE_GRID)
    # sy_second holds K at the value k_first passed on.
    held = [k for index, k, _ in toy.trials if index == 1]
    assert held == pytest.approx([K_BEST] * 5)
    # Before the rule, both_again started at the prior centre (K = 1e-6,
    # Sy = 0.1505), with the passed values written under every trial.
    assert toy.first_trial_of(2) == (pytest.approx(k_passed), pytest.approx(sy_passed))
    assert [(item.name, item.phase) for item in both.reopened] == [
        ("K", "k_first"),
        ("Sy", "sy_second"),
    ]
    assert both.to_dict()["reopened"][0]["phase"] == "k_first"
    assert "reopened" not in k_first.to_dict()


def test_the_rows_say_which_phase_a_parameter_is_reopened_from(tmp_path) -> None:
    cfg, _raw = load_toml_calibration(_write(tmp_path, BASE.format(method="scipy_nelder_mead")))

    rows = phase_summaries(cfg)

    assert "reopens" not in rows[0]
    assert "reopens" not in rows[1]
    assert rows[2]["reopens"] == [
        {"parameter": "K", "from_phase": "k_first"},
        {"parameter": "Sy", "from_phase": "sy_second"},
    ]
    assert rows[2]["starts_from_passed_values"] is True


def test_under_grid_list_phases_says_the_engine_takes_no_start_point(tmp_path, capsys) -> None:
    from hydromodpy.cli.commands import calibrate as calibrate_cmd

    path = _write(tmp_path, BASE.format(method="grid"))
    cfg, _raw = load_toml_calibration(path)

    assert phase_summaries(cfg)[2]["starts_from_passed_values"] is False
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split("\t") == ["0", "k_first", "grid", ""]
    assert lines[2].endswith(
        "\tre-opens K<-k_first, Sy<-sy_second, grid takes no start point and keeps its own"
    )


def test_under_grid_the_engine_keeps_its_own_start(tmp_path, toy) -> None:
    report = run_staged_calibration(
        _write(tmp_path, BASE.format(method="grid")), metric_fn=toy.metric
    )

    # The grid's first point is its lower corner, not a passed value.
    k, sy = toy.first_trial_of(2)
    assert k == pytest.approx(1e-9)
    assert sy == pytest.approx(0.001)
    assert [item.name for item in report.phases[2].reopened] == ["K", "Sy"]


# -- two phases freezing the same parameter ----------------------------------


class PerPhaseRunner:
    """Stands in for the calibration loop; each phase returns its own values."""

    VALUES = {
        "k_first": {"K": 2e-5},
        "k_again": {"K": 4e-5},
        "sy_last": {"Sy": 0.07},
    }

    def __init__(self) -> None:
        self.calls: list[SimpleNamespace] = []

    def run_calibration_core(
        self, cfg, trial_ctx, *, workspace, space, chain=None, start_at=None, **_
    ):
        self.calls.append(
            SimpleNamespace(name=chain.phase_name, baseline=trial_ctx.base_cfg, start_at=start_at)
        )
        return CalibrationReport(
            session_id=chain.session_id,
            method=cfg.method,
            n_iterations=1,
            best_objective=0.1,
            best_sim_id=None,
            duration_s=0.0,
            save_runs=cfg.save_runs,
            promoted=0,
            best_parameters=dict(self.VALUES[chain.phase_name]),
            workspace=workspace,
        )


def test_two_phases_freezing_the_same_parameter_run_and_the_latest_wins(
    tmp_path, toy, monkeypatch
) -> None:
    runner = PerPhaseRunner()
    monkeypatch.setattr(staged_runner, "run_calibration_core", runner.run_calibration_core)

    report = run_staged_calibration(_write(tmp_path, TWICE))

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
ALIASED = """
[calibration]
method = "grid"
max_iter = 5

[calibration.parameters.K1]
bounds = [1e-9, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.K2]
bounds = [1e-9, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

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
name = "phase_a"
method = "grid"
parameters = ["K1"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "phase_b"
method = "grid"
parameters = ["K2"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "phase_c"
method = "scipy_nelder_mead"
parameters = ["K1"]
objective_blocks = ["q_block"]
"""


def test_a_name_aimed_at_a_path_frozen_under_another_name_starts_from_the_latest(
    tmp_path, toy, monkeypatch
) -> None:
    runner = PerPhaseRunner()
    runner.VALUES = {
        "phase_a": {"K1": 1e-5},
        "phase_b": {"K2": 4e-5},
        "phase_c": {"K1": 3e-5},
    }
    monkeypatch.setattr(staged_runner, "run_calibration_core", runner.run_calibration_core)
    path = _write(tmp_path, ALIASED)

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
