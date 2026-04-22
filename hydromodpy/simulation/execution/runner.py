"""Execute a resolved ``SimulationPlan`` against a prepared runtime state.

The runner is the orchestration layer that sits between planning and concrete
solver APIs.

By the time this module runs, the planner has already converted the declarative
``[simulation]`` block into a flat ordered list of concrete ``ProcessRun``
objects. The runner therefore does not decide *what* should run or *in which
order*. Its job is narrower:

- walk through the runs in the order provided by the planner,
- ensure each process-family block has its required runtime objects,
- open and close process-family blocks via optional callbacks,
- resolve the exact upstream models referenced by ``depends_on``,
- delegate solver-specific execution to the matching adapter,
- store each produced model back into ``state.execution.models_by_run_id``.

In one sentence:

- the runner knows the plan and the runtime state;
- the adapters know how to call the concrete solvers.

Keeping this logic separate from the planner avoids mixing dependency
validation with side effects. Keeping it separate from the adapters avoids
mixing generic orchestration with solver-specific API calls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hydromodpy.physics.flow import Flow
from hydromodpy.physics.transport import Transport
from hydromodpy.simulation.adapters import get_solver_adapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    RunExecutionResult,
    SimulationPlan,
)

# ---------------------------------------------------------------------------
# Process-context helpers (free functions, no factory class)
# ---------------------------------------------------------------------------

_REQUIRED_COMPONENTS_BY_PROCESS: dict[str, tuple[str, ...]] = {
    "flow": ("flow",),
    "transport": ("flow", "transport"),
}


def ensure_flow(state: Any) -> None:
    """Create ``state.setup.flow`` from ``state.cfg.flow`` when missing."""
    if state.setup.flow is None:
        state.setup.flow = Flow(config=state.cfg.flow)


def ensure_transport(state: Any) -> None:
    """Create ``state.setup.transport`` from ``state.cfg.transport`` when missing."""
    if state.setup.transport is None:
        state.setup.transport = Transport(config=state.cfg.transport)


_COMPONENT_ENSURERS: dict[str, Callable[[Any], None]] = {
    "flow": ensure_flow,
    "transport": ensure_transport,
}


def ensure_process_context(state: Any, process_type: str) -> None:
    """Ensure all process objects required by ``process_type`` exist.

    Process types not listed in ``_REQUIRED_COMPONENTS_BY_PROCESS`` are
    silently accepted — they simply have no components to materialize.
    """
    components = _REQUIRED_COMPONENTS_BY_PROCESS.get(process_type, ())
    for component_name in components:
        ensurer = _COMPONENT_ENSURERS.get(component_name)
        if ensurer is None:
            raise ValueError(f"Unsupported process component '{component_name}'.")
        ensurer(state)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessCallbacks:
    """Optional callbacks fired when the runner enters or leaves a process family.

    These callbacks are coarse-grained on purpose: they are triggered once per
    contiguous block of runs with the same ``process_type``, not once per
    solver execution.

    ``after_run`` is finer-grained: it fires after each individual solver
    execution completes, receiving the run and its result. This is the hook
    point for SimulationCatalog ingestion.
    """

    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None
    after_run: Callable[[ProcessRun, RunExecutionResult, Any], None] | None = None


class SimulationRunner:
    """Sequentially execute a resolved plan and persist each produced model.

    A useful mental model is:

    1. open a process-family block (``before_process``),
    2. execute every run in that contiguous block,
    3. close the block (``after_process``),
    4. repeat until the plan is exhausted.

    The runner is intentionally stateful: each completed run writes its model
    back into ``state.execution.models_by_run_id`` so later runs can consume it.

    Another useful simplification is:

    - ``SimulationRunner`` decides *when* one run is executed;
    - the selected adapter decides *how* that run is executed.
    """

    def __init__(
        self,
        callbacks: ProcessCallbacks | None = None,
    ) -> None:
        self.callbacks = callbacks or ProcessCallbacks()

    def execute(self, plan: SimulationPlan, state: Any) -> None:
        """Execute each planned run in order against ``state``.

        The plan is assumed to be pre-validated by ``SimulationPlanner``.
        This method focuses on process-family transitions, dependency lookup,
        and adapter dispatch.

        Example
        -------
        If ``plan.runs`` is:

        - ``flow_main::modflownwt``
        - ``transport_main::modpath``
        - ``transport_main::mt3dms``

        then the callback and execution order is:

        1. ``before_process("flow")``
        2. run ``flow_main::modflownwt``
        3. ``after_process("flow")``
        4. ``before_process("transport")``
        5. run ``transport_main::modpath``
        6. run ``transport_main::mt3dms``
        7. ``after_process("transport")``
        """

        current_process_type: str | None = None

        for run in plan.runs:
            if run.process_type != current_process_type:
                if current_process_type is not None:
                    self._call_after_process(current_process_type)
                ensure_process_context(state, run.process_type)
                self._call_before_process(run.process_type)
                current_process_type = run.process_type

            self._run_process_run(plan, state, run)

        if current_process_type is not None:
            self._call_after_process(current_process_type)

    def _call_before_process(self, process_type: str) -> None:
        if self.callbacks.before_process is not None:
            self.callbacks.before_process(process_type)

    def _call_after_process(self, process_type: str) -> None:
        if self.callbacks.after_process is not None:
            self.callbacks.after_process(process_type)

    def _call_after_run(
        self,
        run: ProcessRun,
        result: RunExecutionResult,
        state: Any,
    ) -> None:
        if self.callbacks.after_run is not None:
            self.callbacks.after_run(run, result, state)

    def _run_process_run(
        self,
        plan: SimulationPlan,
        state: Any,
        run: ProcessRun,
    ) -> None:
        """Execute one resolved process run through its registered adapter."""

        dependency_models = self._resolve_dependency_models(state, run)
        adapter = get_solver_adapter(run.process_type, run.solver)
        result = adapter.execute(
            RunContext(
                plan=plan,
                run=run,
                state=state,
                dependency_models=dependency_models,
            )
        )
        self._record_run_output(state, run, result)
        self._call_after_run(run, result, state)

    def _resolve_dependency_models(
        self,
        state: Any,
        run: ProcessRun,
    ) -> tuple[object, ...]:
        """Resolve the concrete upstream models referenced by ``run.depends_on``."""

        models: list[object] = []
        for dependency_id in run.depends_on:
            if dependency_id not in state.execution.models_by_run_id:
                raise ValueError(
                    f"Process run '{run.id}' depends on '{dependency_id}', "
                    "but that run has not produced a model yet."
                )
            models.append(state.execution.models_by_run_id[dependency_id])
        return tuple(models)

    def _record_run_output(
        self,
        state: Any,
        run: ProcessRun,
        result: RunExecutionResult,
    ) -> None:
        """Persist one completed run output back into the shared runtime state.

        ``execution.models_by_run_id`` is the canonical per-run registry used for future
        dependency resolution.
        """

        state.execution.models_by_run_id[run.id] = result.primary_model
