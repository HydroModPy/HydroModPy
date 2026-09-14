"""Rebuild-prefix reuse: steps whose products are already in memory are skipped."""

from __future__ import annotations

from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline


class _PrefixStep:
    """Prefix step recording run() calls, optionally reporting prebuilt state."""

    name = "prefix"

    def __init__(self, prebuilt: bool) -> None:
        self.prebuilt = prebuilt
        self.run_calls = 0

    def is_prebuilt(self, state: PipelineState) -> bool:
        return self.prebuilt

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _LegacyPrefixStep:
    """Prefix step without the is_prebuilt hook."""

    name = "prefix"

    def __init__(self) -> None:
        self.run_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.run_calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Terminal:
    name = "terminal"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def test_prebuilt_prefix_step_is_not_rerun() -> None:
    prefix = _PrefixStep(prebuilt=True)
    pipeline = Pipeline([prefix, _Terminal()])
    final = pipeline.run(PipelineState(run_id="r1"), resume_from=1)
    assert prefix.run_calls == 0
    assert final.step_name == "terminal"


def test_unbuilt_prefix_step_is_rerun() -> None:
    prefix = _PrefixStep(prebuilt=False)
    pipeline = Pipeline([prefix, _Terminal()])
    final = pipeline.run(PipelineState(run_id="r2"), resume_from=1)
    assert prefix.run_calls == 1
    assert final.step_name == "terminal"


def test_prefix_step_without_hook_is_rerun() -> None:
    prefix = _LegacyPrefixStep()
    pipeline = Pipeline([prefix, _Terminal()])
    final = pipeline.run(PipelineState(run_id="r3"), resume_from=1)
    assert prefix.run_calls == 1
    assert final.step_name == "terminal"


def test_prebuilt_hook_is_ignored_in_execute_suffix() -> None:
    prefix = _PrefixStep(prebuilt=True)
    pipeline = Pipeline([prefix, _Terminal()])
    final = pipeline.run(PipelineState(run_id="r4"), resume_from=0)
    assert prefix.run_calls == 1
    assert final.step_name == "terminal"
