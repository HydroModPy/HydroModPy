"""Pipeline runs parallel cohorts by default.

Drives a small DAG with two independent steps inside the same Kahn
cohort to confirm that the runner's default (``parallel=True``) walks
the cohort via :class:`ThreadPoolCohortExecutor` without raising and
preserves the merged state.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline


class _SourceStep:
    """Independent source step writing a unique key into ``state.data``."""

    def __init__(self, name: str, key: str, value: int) -> None:
        self.name = name
        self._key = key
        self._value = value
        self.tin: ClassVar[type | None] = None
        self.tout: ClassVar[type | None] = None

    def depends_on(self) -> tuple[str, ...]:
        return ()

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            **{self._key: self._value},
        )


class _SinkStep:
    """Joining step that depends on two upstream sources."""

    name = "sink"
    tin: ClassVar[type | None] = None
    tout: ClassVar[type | None] = None

    def __init__(self, upstream: tuple[str, str]) -> None:
        self._upstream = upstream

    def depends_on(self) -> tuple[str, ...]:
        return self._upstream

    def run(self, state: PipelineState) -> PipelineState:
        a = state.data.get("a", 0)
        b = state.data.get("b", 0)
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            sum=a + b,
        )


def test_pipeline_runs_parallel_cohort_by_default() -> None:
    """Two independent sources form one cohort that runs without errors."""
    src_a = _SourceStep("src_a", "a", 3)
    src_b = _SourceStep("src_b", "b", 4)
    sink = _SinkStep(upstream=("src_a", "src_b"))
    pipeline = Pipeline([src_a, src_b, sink])

    cohorts = pipeline.cohorts()
    cohort_names = [tuple(sorted(s.name for s in cohort)) for cohort in cohorts]
    assert cohort_names == [("src_a", "src_b"), ("sink",)]

    state = PipelineState(run_id="r", data={})
    final = pipeline.run(state)

    assert final.data.get("sum") == 7
    assert pipeline._parallel is True


def test_pipeline_no_parallel_falls_back_to_sequential() -> None:
    """``parallel=False`` selects the sequential executor."""
    src_a = _SourceStep("src_a", "a", 1)
    src_b = _SourceStep("src_b", "b", 2)
    sink = _SinkStep(upstream=("src_a", "src_b"))
    pipeline = Pipeline([src_a, src_b, sink])

    state = PipelineState(run_id="r", data={})
    final = pipeline.run(state, parallel=False)

    assert final.data.get("sum") == 3
    assert pipeline._parallel is False


def test_pipeline_parallel_cohort_runs_in_threads() -> None:
    """Independent steps in the same cohort observe distinct threads."""
    seen_threads: list[int] = []
    lock = threading.Lock()

    class _ProbeStep:
        def __init__(self, name: str, key: str) -> None:
            self.name = name
            self._key = key
            self.tin = None
            self.tout = None

        def depends_on(self) -> tuple[str, ...]:
            return ()

        def run(self, state: PipelineState) -> PipelineState:
            # Hold the thread briefly so cohort siblings overlap.
            evt.wait(timeout=1.0)
            with lock:
                seen_threads.append(threading.get_ident())
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                **{self._key: 1},
            )

    evt = threading.Event()

    class _ReleaseStep:
        name = "release"
        tin = None
        tout = None

        def depends_on(self) -> tuple[str, ...]:
            return ()

        def run(self, state: PipelineState) -> PipelineState:
            evt.set()
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                released=True,
            )

    pipeline = Pipeline([_ProbeStep("p1", "x"), _ProbeStep("p2", "y"), _ReleaseStep()])
    state = PipelineState(run_id="r", data={})
    pipeline.run(state, parallel=True)

    # Two probe steps should have run in different threads.
    assert len(set(seen_threads)) == 2
