"""Shared runtime contracts used across simulation orchestration layers.

This module defines the small typing contracts that connect planning and
execution:

- ``SimulationPlan`` says which runs must execute, and in which order;
- the runtime state stores the real mutable objects used during that execution;
- solver adapters consume one resolved run context and return one execution
  result.

The key design goal is decoupling. The launcher may own a rich concrete state
object such as ``RunResult``, but the runner and adapters only depend on the
minimal shapes defined here. That keeps the orchestration layers loosely
coupled while still making data flow explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from hydromodpy.simulation.plan import ProcessRun, SimulationPlan


class SimulationState(Protocol):
    """Minimal mutable state consumed directly during plan execution.

    ``SimulationRunner`` and the solver adapters only rely on this protocol,
    not on a concrete implementation such as ``RunResult``. The canonical model
    registry is ``models_by_run_id``; concrete states may still expose extra
    compatibility attributes, but generic orchestration does not require them.
    """

    cfg: Any
    workspace: Any
    settings: Any
    geographic: Any
    flow: Any
    domain: Any
    transport: Any
    models_by_run_id: dict[str, Any]


@dataclass(frozen=True)
class RunContext:
    """Resolved runtime context passed to one solver adapter.

    By the time an adapter receives this object, the planner has already fixed
    the run order and the runner has already resolved the concrete upstream
    models referenced by ``run.depends_on``.
    """

    plan: SimulationPlan
    run: ProcessRun
    state: SimulationState
    dependency_models: tuple[Any, ...] = ()


@dataclass(frozen=True)
class RunExecutionResult:
    """Payload returned by a solver adapter after one run completes.

    ``primary_model`` is the exact model produced by the run and is always
    stored under ``state.models_by_run_id[run.id]`` by the runner.
    """

    primary_model: Any
