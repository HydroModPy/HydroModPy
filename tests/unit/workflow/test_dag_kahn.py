"""DAG Kahn sort tests: cycle detection, ordering, multi-source cohorts."""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import WorkflowDAGCycleError
from hydromodpy.workflow.dag import WorkflowDAG


class _FakeStep:
    """Minimal workflow step used by the DAG tests."""

    def __init__(self, name: str, deps: tuple[str, ...] = ()) -> None:
        self.name = name
        self._deps = deps
        self.tin: ClassVar[type | None] = None
        self.tout: ClassVar[type | None] = None
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


def test_kahn_detects_self_loop() -> None:
    """A step depending on itself is a cycle of length 1."""
    steps = (_FakeStep("a", ("a",)),)
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


def test_kahn_unknown_dependency_raises() -> None:
    """Declaring a non-existent predecessor raises a clear error."""
    steps = (_FakeStep("a", ("ghost",)),)
    with pytest.raises(WorkflowDAGCycleError):
        WorkflowDAG(steps).topological_order()


def test_kahn_duplicate_name_raises() -> None:
    """Two steps with the same ``name`` collapse the DAG and must raise."""
    steps = (_FakeStep("a"), _FakeStep("a"))
    with pytest.raises(WorkflowDAGCycleError):
        WorkflowDAG(steps).topological_order()


def test_standard_steps_dag_has_13_singleton_cohorts() -> None:
    """The canonical 13-step pipeline currently produces singleton cohorts."""
    from hydromodpy.workflow.orchestrator import standard_steps

    dag = WorkflowDAG(standard_steps())
    cohorts = dag.topological_order()
    assert [tuple(step.name for step in cohort) for cohort in cohorts] == [
        ("validate",),
        ("resolve",),
        ("build_geographic",),
        ("load_data",),
        ("build_mesh",),
        ("setup_process",),
        ("prepare_solver",),
        ("run_solver",),
        ("extract",),
        ("derive",),
        ("export",),
        ("display",),
        ("html_report",),
    ]
    assert all(len(cohort) == 1 for cohort in cohorts)
