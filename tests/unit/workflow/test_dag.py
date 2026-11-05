"""WorkflowDAG."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import WorkflowDAGCycleError
from hydromodpy.workflow.dag import WorkflowDAG

# --- test_dag_kahn ---
# DAG Kahn sort tests: cycle detection, ordering, multi-source cohorts.


class _FakeStep:
    """Minimal workflow step used by the DAG tests."""

    def __init__(self, name: str, deps: tuple[str, ...] = ()) -> None:
        self.name = name
        self._deps = deps
        self.config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return self._deps

    def run(self, state):  # pragma: no cover - never executed by these tests
        return state


def test_kahn_linear_order_canonical_pipeline() -> None:
    """A purely linear DAG yields singleton cohorts in declaration order."""
    steps = (
        _FakeStep("a"),
        _FakeStep("b", ("a",)),
        _FakeStep("c", ("b",)),
        _FakeStep("d", ("c",)),
    )
    dag = WorkflowDAG(steps)
    cohorts = dag.topological_order()
    assert [tuple(s.name for s in cohort) for cohort in cohorts] == [
        ("a",),
        ("b",),
        ("c",),
        ("d",),
    ]


def test_kahn_detects_two_step_cycle() -> None:
    """An ``A -> B -> A`` cycle raises :class:`WorkflowDAGCycleError`."""
    steps = (
        _FakeStep("a", ("b",)),
        _FakeStep("b", ("a",)),
    )
    with pytest.raises(WorkflowDAGCycleError):
        WorkflowDAG(steps).topological_order()


def test_kahn_handles_multiple_sources() -> None:
    """Two independent steps form a single 2-element cohort."""
    steps = (
        _FakeStep("a"),
        _FakeStep("b"),
        _FakeStep("c", ("a", "b")),
    )
    dag = WorkflowDAG(steps)
    cohorts = dag.topological_order()
    names = [tuple(sorted(s.name for s in cohort)) for cohort in cohorts]
    assert names == [("a", "b"), ("c",)]


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            (_FakeStep("a", ("a",)),), id="a step depending on itself is a cycle of length 1"
        ),
        pytest.param(
            (_FakeStep("a", ("ghost",)),), id="a non-existent predecessor raises a clear error"
        ),
        pytest.param(
            (_FakeStep("a"), _FakeStep("a")), id="two steps with the same name collapse the DAG"
        ),
    ],
)
def test_kahn_rejects_an_ill_formed_graph(steps) -> None:
    with pytest.raises(WorkflowDAGCycleError):
        WorkflowDAG(steps).topological_order()


def test_standard_steps_dag_has_13_singleton_cohorts() -> None:
    """The canonical 13-step pipeline produces 13 singleton cohorts."""
    from hydromodpy.workflow.steps.sequence import standard_steps

    dag = WorkflowDAG(standard_steps())
    cohorts = dag.topological_order()
    assert len(cohorts) == 13
    assert all(len(cohort) == 1 for cohort in cohorts)
