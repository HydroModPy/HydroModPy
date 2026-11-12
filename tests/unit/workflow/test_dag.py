"""Ordering of workflow steps into cohorts of steps that can run side by side.

A step lists the names it depends on. Each cohort holds the steps whose
dependencies all sit in earlier cohorts (Kahn sort).
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import WorkflowDAGCycleError
from hydromodpy.workflow.dag import WorkflowDAG
from hydromodpy.workflow.steps.sequence import standard_steps


class FakeStep:
    def __init__(self, name: str, deps: tuple[str, ...] = ()) -> None:
        self.name = name
        self._deps = deps
        self.config_sections: ClassVar[tuple[str, ...]] = ()

    def depends_on(self) -> tuple[str, ...]:
        return self._deps

    def run(self, state):  # pragma: no cover - the DAG never runs a step
        return state


def test_two_independent_steps_form_one_cohort() -> None:
    dag = WorkflowDAG((FakeStep("a"), FakeStep("b"), FakeStep("c", ("a", "b"))))
    names = [tuple(sorted(s.name for s in cohort)) for cohort in dag.topological_order()]
    assert names == [("a", "b"), ("c",)]


def test_the_renders_follow_the_seal() -> None:
    # The tail of the pipeline is derive, export, seal, display: figures render the seal.
    cohorts = WorkflowDAG(standard_steps()).topological_order()
    order = [cohort[0].name for cohort in cohorts]
    assert order[-4:] == ["derive", "export", "seal", "display"]


REFUSED = [
    pytest.param((FakeStep("a", ("b",)), FakeStep("b", ("a",))), id="cycle of two steps"),
    pytest.param((FakeStep("a", ("a",)),), id="step depending on itself"),
    pytest.param((FakeStep("a", ("ghost",)),), id="unknown predecessor"),
    pytest.param((FakeStep("a"), FakeStep("a")), id="two steps with one name"),
]


@pytest.mark.parametrize("steps", REFUSED)
def test_refusals(steps) -> None:
    with pytest.raises(WorkflowDAGCycleError):
        WorkflowDAG(steps).topological_order()
