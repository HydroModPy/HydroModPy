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
- store each produced model back into ``state.results.models_by_run_id``.

In one sentence:

- the runner knows the plan and the runtime state;
- the adapters know how to call the concrete solvers.

Keeping this logic separate from the planner avoids mixing dependency
validation with side effects. Keeping it separate from the adapters avoids
mixing generic orchestration with solver-specific API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hydromodpy.simulation.adapters import get_solver_adapter
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.runtime.process_context import ProcessContextFactory
from hydromodpy.simulation.runtime.runtime_contracts import (
    RunContext,
    RunExecutionResult,
    SimulationState,
)


@dataclass(frozen=True)
class ProcessCallbacks:
    """Optional hooks fired when the runner enters or leaves a process family.

    These callbacks are coarse-grained on purpose: they are triggered once per
    contiguous block of runs with the same ``process_type``, not once per
    solver execution.
    """

    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None


class SimulationRunner:
    """Sequentially execute a resolved plan and persist each produced model.

    A useful mental model is:

    1. open a process-family block (``before_process``),
    2. execute every run in that contiguous block,
    3. close the block (``after_process``),
    4. repeat until the plan is exhausted.

    The runner is intentionally stateful: each completed run writes its model
    back into ``state.results.models_by_run_id`` so later runs can consume it.

    Another useful simplification is:

    - ``SimulationRunner`` decides *when* one run is executed;
    - the selected adapter decides *how* that run is executed.
    """

    def __init__(
        self,
        callbacks: ProcessCallbacks | None = None,
        process_context_factory: ProcessContextFactory | None = None,
    ) -> None:
        self.callbacks = callbacks or ProcessCallbacks()
        self.process_context_factory = process_context_factory or ProcessContextFactory()

    def execute(self, plan: SimulationPlan, state: SimulationState) -> None:
        """Execute each planned run in order against ``state``.

        The plan is assumed to be pre-validated by ``SimulationPlanner``.
        This method focuses on process-family transitions, dependency lookup,
        and adapter dispatch.

        In other words:

        - it does not rebuild planning rules;
        - it does not instantiate solver classes directly;
        - it does ensure process-level context exists before process callbacks;
        - it only coordinates the execution flow around those operations.

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
            # Callbacks are grouped by contiguous process-family blocks. This
            # means two consecutive transport solvers share one
            # before/after-transport window instead of retriggering hooks for
            # every solver.
            if run.process_type != current_process_type:
                if current_process_type is not None:
                    self._call_after_process(current_process_type)
                # Materialize shared process objects before hooks fire so
                # before-process callbacks can safely mutate/read them.
                self.process_context_factory.ensure_for_process(state, run.process_type)
                self._call_before_process(run.process_type)
                current_process_type = run.process_type

            self._run_process_run(plan, state, run)

        if current_process_type is not None:
            self._call_after_process(current_process_type)

    def _call_before_process(self, process_type: str) -> None:
        """Invoke the optional before-process callback."""

        if self.callbacks.before_process is not None:
            self.callbacks.before_process(process_type)

    def _call_after_process(self, process_type: str) -> None:
        """Invoke the optional after-process callback."""

        if self.callbacks.after_process is not None:
            self.callbacks.after_process(process_type)

    def _run_process_run(
        self,
        plan: SimulationPlan,
        state: SimulationState,
        run: ProcessRun,
    ) -> None:
        """Execute one resolved process run through its registered adapter.

        All solver-specific behavior lives behind adapters. The runner only:

        - resolves the already-declared upstream models for the run;
        - selects the adapter matching ``(run.process_type, run.solver)``;
        - records the outputs published by that adapter.

        This is the key boundary of the module: from this point on, the runner
        stays generic and the adapter is responsible for the concrete solver
        call sequence.
        """

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

    def _resolve_dependency_models(
        self,
        state: SimulationState,
        run: ProcessRun,
    ) -> tuple[object, ...]:
        """Resolve the concrete upstream models referenced by ``run.depends_on``.

        The runner resolves dependencies generically, in declared order, then
        hands the resulting model tuple to the adapter.

        This keeps dependency lookup centralized in one place, while still
        allowing each adapter to validate the exact dependency shape it expects
        (for example: "I need exactly one upstream flow model").
        """

        models: list[object] = []
        for dependency_id in run.depends_on:
            if dependency_id not in state.results.models_by_run_id:
                raise ValueError(
                    f"Process run '{run.id}' depends on '{dependency_id}', "
                    "but that run has not produced a model yet."
                )
            models.append(state.results.models_by_run_id[dependency_id])
        return tuple(models)

    def _record_run_output(
        self,
        state: SimulationState,
        run: ProcessRun,
        result: RunExecutionResult,
    ) -> None:
        """Persist one completed run output back into the shared runtime state.

        ``results.models_by_run_id`` is the canonical per-run registry used for future
        dependency resolution.
        """

        state.results.models_by_run_id[run.id] = result.primary_model
