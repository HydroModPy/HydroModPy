"""A promoted run closes its attempt: completed once sealed, failed when it raises.

A promotion is not launched under ``project.attempt.run_attempt``: the
pipeline claims the reserved directory and seals it, and nothing else used to
close the attempt. The promoted run then kept ``outcome.json = running``,
``ended_at = null`` and its ``.hmp/`` beside a completed manifest. The
pipeline is stubbed down to a claim, a seal and the facts the session hands it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.trial import TrialContext, promote_prepared_trial
from hydromodpy.core.exceptions import StepError
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.core.state.paths import INTERNAL_DIRNAME
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_reserved_directory
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.run_facts import PromotionFacts
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline

pytestmark = pytest.mark.unit


@dataclass
class _Cfg:
    K: float = 1.0
    simulation: Any = field(default_factory=lambda: SimpleNamespace(name="toy", results=None))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return copy.deepcopy(self)


@dataclass
class _Setup:
    workspace: Any = None
    geographic: Any = None
    flow: Any = None
    transport: Any = None
    flow_runtime_overrides: Any = None
    run_id: str = "toy"
    time_grid: Any = None


@dataclass
class _Ctx:
    cfg: _Cfg
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: _Setup = field(default_factory=_Setup)
    loaded_data: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: Any = None
    reserved_sim_id: Any = None


class _Step:
    def __init__(self, name: str, action) -> None:
        self.name = name
        self._action = action

    def run(self, state: PipelineState) -> PipelineState:
        self._action(state)
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Provider:
    def make_pipeline(self, steps, *, run_dir=None):
        return Pipeline(steps, run_dir=run_dir)

    def make_state(self, run_id, data):
        return PipelineState(run_id=run_id, data=dict(data))

    def with_solver_launcher(self, steps, launcher):
        del launcher
        return tuple(steps)


def _claim(state: PipelineState) -> None:
    ctx = state.get("ctx")
    run_dir = state.get("run_dir")
    claim_reserved_directory(
        run_dir, case_id=run_dir.name, project="project", sim_id=ctx.reserved_sim_id
    )
    (run_dir / INTERNAL_DIRNAME / "checkpoints").mkdir(parents=True, exist_ok=True)
    ctx.sim_id = ctx.reserved_sim_id


def _seal(state: PipelineState) -> None:
    (state.get("run_dir") / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")


def _trial_ctx(tmp_path: Path, steps) -> TrialContext:
    cfg = _Cfg()
    ctx = _Ctx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=tuple(steps),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )
    trial_ctx.kept_solves = None
    return trial_ctx


@pytest.fixture(autouse=True)
def _provider(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "get_trial_pipeline_provider", _Provider)


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "calage"
    run_dir.mkdir(parents=True)
    return run_dir


def test_a_sealed_promotion_is_completed_and_keeps_no_attempt_state(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)
    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _seal)])

    promote_prepared_trial(trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir)

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.ended_at is not None
    assert not (run_dir / INTERNAL_DIRNAME).exists()


def test_a_promotion_that_raises_is_failed_and_says_why(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)

    def _boom(state: PipelineState) -> None:
        raise RuntimeError("the solver did not converge")

    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _boom)])

    with pytest.raises(StepError, match="did not converge"):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error is not None and "did not converge" in outcome.error.message
    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()


def test_an_interrupted_promotion_is_aborted(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)

    def _interrupt(state: PipelineState) -> None:
        raise KeyboardInterrupt

    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _interrupt)])

    with pytest.raises(KeyboardInterrupt):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "aborted"


def test_the_facts_of_the_session_travel_in_the_state_of_the_run(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)
    seen: list[Any] = []
    trial_ctx = _trial_ctx(
        tmp_path,
        [
            _Step(
                "prepare_solver", lambda state: (seen.append(state.get("promotion")), _claim(state))
            ),
            _Step("export", _seal),
        ],
    )
    promotion = PromotionFacts(objective_name="nse", objective_value=0.4, converged=True)

    promote_prepared_trial(
        trial_ctx,
        {"K": 2.0},
        name="calage",
        sim_id="a" * 32,
        run_dir=run_dir,
        promotion=promotion,
    )

    assert seen == [promotion]
    assert json.loads((run_dir / "outcome.json").read_text())["status"] == "completed"
