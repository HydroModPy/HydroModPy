"""Immutable runtime objects describing a resolved simulation plan.

This module is the small contract shared by the planner and the runner.
The user-facing TOML remains declarative and compact, while these dataclasses
store the expanded execution schedule the runtime can consume directly.

The main design choice is to keep these objects frozen and explicit:

- one ``ProcessRun`` represents exactly one process/solver pair,
- dependencies are stored as concrete upstream run ids,
- the ``SimulationPlan`` preserves the execution order chosen by the planner.

That makes the schedule easy to inspect in tests, logs, and debugging sessions
without re-reading or re-interpreting the original configuration file.

``RunContext`` and ``RunExecutionResult`` live here so that both the runner
and the adapters share a single import source without circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProcessRun:
    """One concrete execution unit produced by the planner.

    A single declarative ``[[simulation.process]]`` entry can expand to several
    ``ProcessRun`` objects when multiple solvers are listed. ``depends_on``
    stores resolved run identifiers, so the runner can retrieve the exact
    upstream model instance that must already exist.
    """

    id: str
    process_id: str
    process_type: str
    solver: str
    # Dependencies refer to concrete run ids (for example "flow_1::modflownwt").
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SimulationPlan:
    """Resolved execution schedule ready for runtime orchestration.

    ``runs`` is intentionally ordered: the runner executes it sequentially
    without re-sorting or topological reconstruction.
    """

    name: str
    description: str
    # Preserve the exact execution order emitted by the planner.
    runs: tuple[ProcessRun, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Return ``True`` when the planner emitted no executable run."""
        return not self.runs


# ---------------------------------------------------------------------------
# Runtime contracts — shared by runner and adapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunContext:
    """Resolved runtime context passed to one solver adapter.

    By the time an adapter receives this object, the planner has already fixed
    the run order and the runner has already resolved the concrete upstream
    models referenced by ``run.depends_on``.
    """

    plan: SimulationPlan
    run: ProcessRun
    state: Any
    dependency_models: tuple[Any, ...] = ()


@dataclass(frozen=True)
class RunExecutionResult:
    """Payload returned by a solver adapter after one run completes.

    ``primary_model`` is the exact model produced by the run and is always
    stored under ``state.execution.models_by_run_id[run.id]`` by the runner.
    """

    primary_model: Any
