"""Unit tests for :mod:`hydromodpy.calibration.runners.trial`.

Phase 1 introduces the lightweight trial primitive that the
calibration loop forks from. The surface tested here is intentionally
narrow:

- :class:`TrialContext.fork` deep-copies the config, injects values
  through the declared dotted paths, shares the expensive setup
  objects by reference, and resets ``setup.flow`` / ``setup.transport``
  so the downstream steps rebuild them from the trial's config.
- :func:`run_trial_light` never creates disk artefacts in the CWD and
  returns a ``TrialResult`` even when the default metric extractor
  is used (Phase 2 swaps the extractor in).

The tests exercise the primitive through toy steps rather than the
real MODFLOW pipeline so they run under a second.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest

from hydromodpy.calibration.runners.trial import (
    TrialContext,
    TrialResult,
    _set_by_path,
    run_trial_light,
)
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.internals.step import Step  # noqa: F401

# ---------------------------------------------------------------------------
# Tiny cfg/ctx doubles that look enough like the real thing for the tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeParam:
    value: float = 1.0


@dataclass
class _FakeFlow:
    K: _FakeParam = field(default_factory=_FakeParam)
    Sy: _FakeParam = field(default_factory=_FakeParam)


@dataclass
class _FakeSimulation:
    name: str = "toy"


@dataclass
class _FakeCfg:
    flow: _FakeFlow = field(default_factory=_FakeFlow)
    simulation: _FakeSimulation = field(default_factory=_FakeSimulation)

    def model_copy(self, *, deep: bool = False) -> _FakeCfg:
        import copy as _copy

        return _copy.deepcopy(self) if deep else _copy.copy(self)


@dataclass
class _FakeSetup:
    workspace: Any = None
    geographic: Any = None
    mesh_planar: Any = None
    domain: Any = None
    flow: Any = None
    transport: Any = None
    flow_runtime_overrides: Any = None
    run_id: str = "default"
    time_grid: Any = None


@dataclass
class _FakeLoadedData:
    hydrometry: Any = None


@dataclass
class _FakeCtx:
    cfg: _FakeCfg
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: _FakeSetup = field(default_factory=_FakeSetup)
    loaded_data: _FakeLoadedData = field(default_factory=_FakeLoadedData)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    store: Any = None
    sim_id: Any = None


# ---------------------------------------------------------------------------
# Toy pipeline steps that record their invocations without touching disk
# ---------------------------------------------------------------------------


class _CallCounterStep:
    def __init__(self, name: str, sections: tuple[str, ...]) -> None:
        self.name = name
        self.config_sections: ClassVar[tuple[str, ...]] = sections  # type: ignore[misc]
        self.config_sections = sections  # runtime attr for dependency matcher
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
        )


def _make_trial_context(tmp_path: Path, *, earliest: int) -> tuple[TrialContext, list]:
    """Build a TrialContext populated with stub steps + ctx.

    Returns the ``TrialContext`` and the list of toy steps so individual
    tests can inspect call counts.
    """
    steps = [
        _CallCounterStep("s0", ("workspace", "simulation")),
        _CallCounterStep("s1", ("workspace", "simulation")),
        _CallCounterStep("s2", ("data",)),
        _CallCounterStep("s3", ("geographic", "data.dem")),
        _CallCounterStep("s4", ("domain.supports",)),
        _CallCounterStep("s5", ("domain.depth_model", "flow.ic", "simulation")),
        _CallCounterStep("s6", ("flow", "transport", "solver")),
        _CallCounterStep("s7", ("flow", "transport", "solver")),
        _CallCounterStep("s8", ()),
    ]
    cfg = _FakeCfg()
    ctx = _FakeCtx(cfg=cfg, config_path=tmp_path / "project.toml", raw_toml={})

    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=tuple(steps),
        override_paths={"K": "flow.K.value"},
        workspace=tmp_path,
        cfg_path=tmp_path / "project.toml",
        raw_toml={},
    )
    return trial_ctx, steps


# ---------------------------------------------------------------------------
# Fork isolation
# ---------------------------------------------------------------------------


class TestFork:
    def test_value_is_injected_via_dotted_path(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        forked = trial_ctx.fork({"K": 2.5})
        assert forked.ctx.cfg.flow.K.value == 2.5

    def test_fork_does_not_mutate_base_cfg(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        assert trial_ctx.base_cfg.flow.K.value == 1.0
        forked = trial_ctx.fork({"K": 7.0})
        assert forked.ctx.cfg.flow.K.value == 7.0
        # Base must stay at its initial value so subsequent forks start
        # from the same baseline.
        assert trial_ctx.base_cfg.flow.K.value == 1.0
        assert trial_ctx.ctx.cfg.flow.K.value == 1.0

    def test_fork_produces_independent_setup_but_shares_big_refs(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        trial_ctx.ctx.setup.geographic = object()
        trial_ctx.ctx.setup.mesh_planar = object()
        trial_ctx.ctx.setup.flow = "should_be_reset"

        forked = trial_ctx.fork({"K": 3.0})

        # setup instance is new (so mutation inside the trial does not
        # leak back to base), but geographic / mesh_planar are shared
        # references because those are expensive to rebuild.
        assert forked.ctx.setup is not trial_ctx.ctx.setup
        assert forked.ctx.setup.geographic is trial_ctx.ctx.setup.geographic
        assert forked.ctx.setup.mesh_planar is trial_ctx.ctx.setup.mesh_planar
        # flow is reset so step 05 / SimulationRunner will rebuild it from
        # the trial's cfg.flow.
        assert forked.ctx.setup.flow is None
        assert forked.ctx.setup.transport is None
        assert forked.ctx.setup.flow_runtime_overrides is None

    def test_fork_is_lightweight(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        forked = trial_ctx.fork({"K": 0.01})
        assert forked.ctx.execution.lightweight is True
        # Fresh execution registry: no residual plan / models carried
        # over from another trial or from the base.
        assert forked.ctx.execution.models_by_run_id == {}
        assert forked.ctx.store is None

    def test_loaded_data_is_shared_by_reference(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        hydro = object()
        trial_ctx.ctx.loaded_data.hydrometry = hydro
        forked = trial_ctx.fork({"K": 0.01})
        assert forked.ctx.loaded_data is trial_ctx.ctx.loaded_data
        assert forked.ctx.loaded_data.hydrometry is hydro


# ---------------------------------------------------------------------------
# run_trial_light - scheduling + no-disk-I/O
# ---------------------------------------------------------------------------


class TestRunTrialLight:
    def test_runs_only_downstream_slice(self, tmp_path: Path) -> None:
        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)
        # First trial
        result = run_trial_light(
            trial_ctx,
            {"K": 1.0},
            metric_fn=lambda ctx, *, objective, variable: (0.0, {}),
        )
        assert isinstance(result, TrialResult)
        assert result.status == "completed"
        # steps[0..5] must NOT have been called (they are the shared prep)
        for step in steps[:6]:
            assert step.calls == 0, f"step {step.name} re-ran unexpectedly"
        # steps[6..8] must have run exactly once
        for step in steps[6:9]:
            assert step.calls == 1, f"step {step.name} did not run"

    def test_trial_writes_no_files(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        before = _snapshot_files(tmp_path)
        run_trial_light(trial_ctx, {"K": 0.1})
        after = _snapshot_files(tmp_path)
        assert before == after, "run_trial_light created disk artefacts"

    def test_crash_is_captured_as_status(self, tmp_path: Path) -> None:
        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)

        def boom(_state):
            raise RuntimeError("solver crashed")

        steps[7].run = boom  # type: ignore[assignment]

        result = run_trial_light(trial_ctx, {"K": 0.1})
        assert result.status == "crashed"
        assert result.primary_metric != result.primary_metric  # NaN
        assert "solver crashed" in (result.error or "")

    def test_default_metric_returns_failed_result(self, tmp_path: Path) -> None:
        """The stub metric extractor fails the trial with a non-finite objective.

        The real extractor is swapped in by the calibration CLI in Phase 2.
        """
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        result = run_trial_light(trial_ctx, {"K": 1.0})
        assert result.status == "failed"
        assert result.primary_metric != result.primary_metric  # NaN
        assert result.metrics == {}
        assert result.error == "metric_fn returned a non-finite objective"

    def test_custom_metric_fn_is_used_when_supplied(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)

        def _metric(ctx, *, objective, variable):
            return 0.42, {"nse@outlet": 0.58}

        result = run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=_metric)
        assert result.primary_metric == pytest.approx(0.42)
        assert result.metrics == {"nse@outlet": 0.58}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSetByPath:
    def test_sets_nested_leaf(self) -> None:
        cfg = _FakeCfg()
        _set_by_path(cfg, "flow.K.value", 5.5)
        assert cfg.flow.K.value == 5.5

    def test_deep_copy_isolates_mutation(self) -> None:
        base = _FakeCfg()
        forked = base.model_copy(deep=True)
        _set_by_path(forked, "flow.K.value", 9.0)
        assert forked.flow.K.value == 9.0
        assert base.flow.K.value == 1.0


def _snapshot_files(root: Path) -> set[str]:
    """Recursively list every file under ``root`` relative to ``root``."""
    out: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            out.add(str(Path(dirpath, name).relative_to(root)))
    return out
