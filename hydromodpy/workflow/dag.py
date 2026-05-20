"""Workflow DAG built from declared step dependencies.

The :class:`WorkflowDAG` collects an ordered set of workflow steps and
computes parallelisable cohorts using Kahn's topological sort. Each step
exposes ``depends_on() -> tuple[str, ...]`` referencing the names of
predecessor steps. Cycles raise :class:`WorkflowDAGCycleError`.

A cohort is a tuple of steps that can be executed concurrently because
all their predecessors live in earlier cohorts. The default
``standard_steps()`` declaration produces 11 cohorts (only
``build_geographic`` and ``load_data`` form a 2-step cohort today).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from hydromodpy.core.contracts.workflow_step import step_depends_on, step_name
from hydromodpy.core.exceptions import WorkflowDAGCycleError


@dataclass(frozen=True, slots=True)
class StepEdge:
    """Directed dependency edge ``src -> dst`` in the workflow DAG."""

    src: str
    dst: str


class WorkflowDAG:
    """Workflow DAG over named steps with parallel cohort detection."""

    def __init__(self, steps: Sequence[Any]) -> None:
        self._steps: tuple[Any, ...] = tuple(steps)
        self._by_name: dict[str, Any] = {}
        for s in self._steps:
            name = step_name(s)
            if not name:
                raise WorkflowDAGCycleError(f"step {s!r} has an empty name")
            if name in self._by_name:
                raise WorkflowDAGCycleError(f"duplicate workflow step name: {name!r}")
            self._by_name[name] = s
        self._edges: tuple[StepEdge, ...] = self._build_edges()

    @property
    def steps(self) -> tuple[Any, ...]:
        """Original step sequence used to build the DAG."""
        return self._steps

    @property
    def names(self) -> tuple[str, ...]:
        """Tuple of declared step names, preserving the original order."""
        return tuple(self._by_name)

    @property
    def edges(self) -> tuple[StepEdge, ...]:
        """All declared dependency edges."""
        return self._edges

    def get(self, name: str) -> Any:
        """Return the step registered under ``name``."""
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown workflow step: {name!r}") from exc

    def topological_order(self) -> tuple[tuple[Any, ...], ...]:
        """Return successive parallel cohorts via Kahn's algorithm.

        Each cohort is a tuple of steps whose predecessors all live in
        earlier cohorts. Within a cohort step order matches the original
        declaration so deterministic iteration is preserved.
        """
        in_degree: dict[str, int] = dict.fromkeys(self._by_name, 0)
        forward: dict[str, list[str]] = {name: [] for name in self._by_name}
        for edge in self._edges:
            in_degree[edge.dst] += 1
            forward[edge.src].append(edge.dst)

        order = list(self._by_name)
        ready = [name for name in order if in_degree[name] == 0]
        cohorts: list[tuple[Any, ...]] = []
        seen = 0
        while ready:
            cohort = tuple(self._by_name[name] for name in ready)
            cohorts.append(cohort)
            seen += len(cohort)
            next_ready: list[str] = []
            for name in ready:
                for child in forward[name]:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_ready.append(child)
            next_ready.sort(key=order.index)
            ready = next_ready

        if seen != len(self._by_name):
            unresolved = sorted(name for name, deg in in_degree.items() if deg > 0)
            raise WorkflowDAGCycleError(
                "workflow DAG has a cycle among steps: " + ", ".join(unresolved)
            )
        return tuple(cohorts)

    def linear_order(self) -> tuple[Any, ...]:
        """Flatten the cohorts into a deterministic sequential order."""
        return tuple(step for cohort in self.topological_order() for step in cohort)

    def _build_edges(self) -> tuple[StepEdge, ...]:
        edges: list[StepEdge] = []
        seen: set[tuple[str, str]] = set()
        for step in self._steps:
            dst = step_name(step)
            for src in step_depends_on(step):
                if src not in self._by_name:
                    raise WorkflowDAGCycleError(f"step {dst!r} declares unknown dependency {src!r}")
                key = (src, dst)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(StepEdge(src=src, dst=dst))
        return tuple(edges)


def topological_cohorts(steps: Iterable[Any]) -> tuple[tuple[Any, ...], ...]:
    """Shortcut returning Kahn cohorts for an iterable of workflow steps."""
    return WorkflowDAG(tuple(steps)).topological_order()


__all__ = (
    "StepEdge",
    "WorkflowDAG",
    "topological_cohorts",
)
