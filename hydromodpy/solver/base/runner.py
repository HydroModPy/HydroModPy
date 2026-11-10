"""Execute a resolved ``SimulationPlan`` against a prepared runtime state.

The runner is the orchestration layer that sits between planning and concrete
solver APIs.

By the time this module runs, the planner has already converted the declarative
``[simulation]`` block into a flat ordered list of concrete ``ProcessRun``
objects. The runner therefore does not decide *what* should run or *in which
order*. Its job is narrower:

- walk through the runs in the order provided by the planner,
- fill the ``RunSlot`` of each run (``slot_for``), the one rule for the run
  folder and the run name, and the names a later run reads of it (``hand_off``),
- hand each run the upstream runs referenced by ``depends_on``,
- read the stop flag of the run folder before each run, so a stop asked while a
  run solves ends the plan at the next boundary,
- call the adapter through ``solve_one``: ``validate``, then ``build`` or
  ``rerun``, then ``run`` unless the slot stops before the solve,
- record each ``SolverRun`` in ``state.execution.solver_runs``,
- refuse a transport run that follows a flow run whose steady start did not
  converge, and a transport whose dependencies are not the one flow its
  backend follows.

In one sentence:

- the runner knows the plan and the runtime state;
- the adapters know how to call the concrete solvers.

Keeping this logic separate from the planner avoids mixing dependency
validation with side effects. Keeping it separate from the adapters avoids
mixing generic orchestration with solver-specific API calls.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.exceptions import (
    ConfigError,
    PipelineError,
    SolverDivergedError,
    SolverError,
    SolverInputError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import raise_if_stop_requested
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.solver.base.plan import (
    ProcessRun,
    RunSlot,
    SimulationPlan,
    SolverRun,
)
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.base.rerun import chooses_rerun

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# The slot of a run, and one solve through the adapter contract
# ---------------------------------------------------------------------------

_LABEL_PREFIXES: dict[str, str] = {"flow": "f"}


def run_name(plan: SimulationPlan, run: ProcessRun, base: str) -> str:
    """Return the name of ``run``: ``base``, suffixed when its family has several runs.

    A plan with one flow keeps ``base`` unchanged. With several, each flow takes
    a positional label in its family, ``_f1``, ``_f2``, so each solver writes
    into its own folder. A transport does not come here: it solves in the slot
    of the flow it follows, under the name of that flow.
    """
    family = [planned for planned in plan.runs if planned.process_type == run.process_type]
    if len(family) == 1:
        return base
    for index, planned in enumerate(family, start=1):
        if planned.id == run.id:
            return f"{base}_{_LABEL_PREFIXES.get(run.process_type, 'r')}{index}"
    raise SolverInputError(
        f"Process run '{run.id}' is not present in the provided simulation plan.",
        run_id=run.id,
    )


def hand_off_of(plan: SimulationPlan, run: ProcessRun) -> frozenset[str]:
    """Return the products a later run of the plan reads of ``run``.

    The union of the ``reads`` of every run whose ``depends_on`` names ``run``.
    The runner writes it on the ``RunSlot``, so an adapter reads what it may
    hand over without reading the plan: NWT poses its flow-transport link when
    a transport that follows reads ``face_flow``.
    """
    names: set[str] = set()
    for later in plan.runs:
        if run.id not in later.depends_on:
            continue
        names |= set(solvers.get(later.process_type, later.solver).reads)
    return frozenset(names)


def slot_for(
    plan: SimulationPlan,
    run: ProcessRun,
    setup: Any,
    upstream: tuple[SolverRun, ...] = (),
    run_dir: Path | None = None,
) -> RunSlot:
    """Return the slot ``run`` solves in, from the setup of the pipeline.

    The folder is ``setup.workspace.solver_scratch_folder`` and the binaries
    ``setup.workspace.bin_path``. A setup without a workspace solves in the
    working directory with the managed binaries. The name is the one a trial
    asks for in ``setup.slot_request``, else ``setup.run_id``, else
    ``default``, suffixed by :func:`run_name`. ``stop_before_solve`` and
    ``shared_forcing_dir`` come from the trial request, and are off outside a
    trial. Every slot carries ``hand_off``, what the runs that depend on this
    one read of it. ``stop_flag`` is the stop flag of ``run_dir``, the folder
    the run writes its results in, ``.hmp/stop.json``, and ``None`` without a
    folder, as a calibration trial has none.

    A transport solves in the slot of the one flow run it follows, ``upstream``
    the runner resolved: the folders and the name of the flow, so it reads and
    extends the files that flow wrote, and its own ``stop_before_solve``.
    """
    stop_flag = None if run_dir is None else stop_flag_for(run_dir)
    if run.process_type == "transport":
        if len(upstream) != 1:
            raise SolverInputError(
                f"Process run '{run.id}' expected exactly one flow dependency, "
                f"got {len(upstream)}.",
                run_id=run.id,
            )
        provided = upstream[0].slot
        return RunSlot(
            folder=provided.folder,
            name=provided.name,
            stop_before_solve=bool(
                getattr(getattr(setup, "slot_request", None), "stop_before_solve", False)
            ),
            bin_dir=provided.bin_dir,
            shared_forcing_dir=provided.shared_forcing_dir,
            hand_off=hand_off_of(plan, run),
            stop_flag=stop_flag,
        )
    request = getattr(setup, "slot_request", None)
    workspace = getattr(setup, "workspace", None)
    folder = Path(workspace.solver_scratch_folder) if workspace is not None else Path.cwd()
    bin_path = getattr(workspace, "bin_path", None)
    asked = str(getattr(request, "name", None) or "").strip()
    base = asked or str(getattr(setup, "run_id", "") or "").strip() or "default"
    return RunSlot(
        folder=folder,
        name=run_name(plan, run, base),
        stop_before_solve=bool(getattr(request, "stop_before_solve", False)),
        bin_dir=Path(bin_path) if bin_path else None,
        shared_forcing_dir=getattr(request, "shared_forcing_dir", None),
        hand_off=hand_off_of(plan, run),
        stop_flag=stop_flag,
    )


def options_for(adapter: object, run: ProcessRun, cfg: Any) -> BaseModel | None:
    """Return the validated options of the backend of ``run``, or ``None``.

    A flow backend reads its table ``[solver.<name>]`` through
    ``cfg.solver.options_of``, a transport its table ``[transport.<name>]``
    through ``cfg.transport.options_of``. A backend that declares no settings
    class, and a process kind with no table of its own, receive ``None``.
    """
    if getattr(type(adapter), "options", None) is None:
        return None
    if run.process_type == "flow":
        return cfg.solver.options_of(run.solver)
    if run.process_type == "transport":
        return cfg.transport.options_of(run.solver)
    return None


def solve_one(
    adapter: Any,
    model: Any,
    options: BaseModel | None,
    slot: RunSlot,
    upstream: tuple[SolverRun, ...] = (),
    *,
    previous: SolverRun | None = None,
) -> SolverRun:
    """Solve one run through the adapter contract and return its ``SolverRun``.

    A flow passes no upstream, a transport exactly one, the run of the flow it
    follows. ``validate`` first, then ``rerun`` of ``previous`` when
    :func:`~hydromodpy.solver.base.rerun.chooses_rerun` says so and the backend
    accepts, else ``build`` into ``slot`` with ``upstream``. ``run`` follows
    unless ``slot.stop_before_solve``, which returns the built run unsolved. A
    :class:`~hydromodpy.core.exceptions.SolverError` names the run by
    ``slot.name``; the runner fills its ``run_id``.
    """
    adapter.validate(model, options, slot)
    solver_run = None
    if chooses_rerun(adapter, previous, model):
        solver_run = adapter.rerun(previous, model, slot)
    if solver_run is None:
        solver_run = adapter.build(model, options, slot, upstream)
    if slot.stop_before_solve:
        return solver_run
    return adapter.run(solver_run)


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
    execution completes, receiving the run and its ``SolverRun``. This is the
    hook point for Catalog ingestion.
    """

    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None
    after_run: Callable[[ProcessRun, SolverRun, Any], None] | None = None


class SimulationRunner:
    """Sequentially execute a resolved plan and record what each run produced.

    A useful mental model is:

    1. open a process-family block (``before_process``),
    2. execute every run in that contiguous block,
    3. close the block (``after_process``),
    4. repeat until the plan is exhausted.

    The runner is intentionally stateful: each completed run writes its
    ``SolverRun`` into ``state.execution.solver_runs`` so later runs can consume it.

    Another useful simplification is:

    - ``SimulationRunner`` decides *when* one run is executed;
    - the selected adapter decides *how* that run is executed.
    """

    def __init__(
        self,
        callbacks: ProcessCallbacks | None = None,
    ) -> None:
        self.callbacks = callbacks or ProcessCallbacks()
        self._unconverged_starts: set[str] = set()

    def execute(
        self,
        plan: SimulationPlan,
        state: Any,
        *,
        callbacks: ProcessCallbacks | None = None,
        previous: Mapping[str, SolverRun] | None = None,
    ) -> tuple[tuple[ProcessRun, SolverRun], ...]:
        """Execute each planned run in order against ``state``.

        The plan is assumed to be pre-validated by ``SimulationPlanner``.
        This method focuses on process-family transitions, dependency lookup,
        and adapter dispatch.

        ``previous`` maps a run id to a solved ``SolverRun`` of the same run.
        A run found there is rerun from it when its backend can
        (:func:`solve_one`), and built otherwise. ``rerun`` consumes that run.

        Example
        -------
        If ``plan.runs`` is:

        - ``flow_main::modflow_nwt``
        - ``transport_main::modpath``
        - ``transport_main::mt3dms``

        then the callback and execution order is:

        1. ``before_process("flow")``
        2. run ``flow_main::modflow_nwt``
        3. ``after_process("flow")``
        4. ``before_process("transport")``
        5. run ``transport_main::modpath``
        6. run ``transport_main::mt3dms``
        7. ``after_process("transport")``
        """

        previous_callbacks = self.callbacks
        self._unconverged_starts = set()
        if callbacks is not None:
            self.callbacks = callbacks
        executed_results: list[tuple[ProcessRun, SolverRun]] = []
        try:
            current_process_type: str | None = None
            process_open = False

            try:
                for run in plan.runs:
                    if run.process_type != current_process_type:
                        if process_open and current_process_type is not None:
                            process_open = False
                            self._call_after_process(current_process_type)
                        self._call_before_process(run.process_type)
                        current_process_type = run.process_type
                        process_open = True

                    result = self._run_process_run(
                        plan,
                        state,
                        run,
                        previous=(previous or {}).get(run.id),
                    )
                    executed_results.append((run, result))
            except BaseException:
                if process_open and current_process_type is not None:
                    process_open = False
                    try:
                        self._call_after_process(current_process_type)
                    except Exception:
                        logger.warning(
                            "after_process callback failed while unwinding process %s",
                            current_process_type,
                            exc_info=True,
                        )
                raise

            if process_open and current_process_type is not None:
                process_open = False
                self._call_after_process(current_process_type)
            return tuple(executed_results)
        finally:
            self.callbacks = previous_callbacks

    def _call_before_process(self, process_type: str) -> None:
        if self.callbacks.before_process is not None:
            self.callbacks.before_process(process_type)

    def _call_after_process(self, process_type: str) -> None:
        if self.callbacks.after_process is not None:
            self.callbacks.after_process(process_type)

    def _call_after_run(
        self,
        run: ProcessRun,
        result: SolverRun,
        state: Any,
    ) -> None:
        if self.callbacks.after_run is not None:
            self.callbacks.after_run(run, result, state)

    def _run_process_run(
        self,
        plan: SimulationPlan,
        state: Any,
        run: ProcessRun,
        *,
        previous: SolverRun | None = None,
    ) -> SolverRun:
        """Execute one resolved process run through its registered adapter.

        The stop flag of the run folder is read first, so a stop asked during
        the run before this one ends the plan here and no other run starts.
        """

        run_dir = getattr(state, "run_dir", None)
        raise_if_stop_requested(None if run_dir is None else stop_flag_for(run_dir))
        if run.process_type != "mesh":
            model = getattr(state.setup, "model", None)
            if run.process_type == "flow" and model is None:
                raise ConfigError(
                    f"Flow run '{run.id}' needs the Model of the run (setup.model), and the "
                    "prepare_solver step has not built one."
                )
            upstream = self._resolve_upstream(state, run)
            if run.process_type == "transport":
                self._refuse_a_start_that_did_not_converge(state, run)
                self._refuse_a_dependency_outside_its_family(plan, run)
            slot = slot_for(plan, run, state.setup, upstream=upstream, run_dir=run_dir)
        else:
            upstream = ()
            slot = slot_for(plan, run, state.setup, run_dir=run_dir)
            result = self._run_mesh_process(state, run, slot)
            self._record_run_output(state, run, result)
            self._call_after_run(run, result, state)
            return result

        adapter = solvers.create(run.process_type, run.solver)
        options = options_for(adapter, run, getattr(state, "cfg", None))
        try:
            result = solve_one(adapter, model, options, slot, upstream, previous=previous)
        except SolverError as exc:
            if exc.run_id is None:
                exc.run_id = run.id
            raise
        self._record_run_output(state, run, result)
        self._call_after_run(run, result, state)
        return result

    def _refuse_a_dependency_outside_its_family(
        self, plan: SimulationPlan, run: ProcessRun
    ) -> None:
        """Refuse a transport whose dependencies are not the one flow its backend follows.

        A transport follows one flow of one family, named by its ``requires``.
        The planner binds each dependency to the most recent run of that
        family; a plan built outside the planner, or a transport with other
        dependencies, is refused here, before anything is built.
        """
        expected = solvers.get(run.process_type, run.solver).requires
        if len(run.depends_on) != 1 or len(expected) != 1:
            raise SolverInputError(
                f"Process run '{run.id}' expected exactly one flow dependency, "
                f"got {len(run.depends_on)}.",
                run_id=run.id,
            )
        planned = {planned_run.id: planned_run for planned_run in plan.runs}
        kind, name = expected[0]
        dependency = planned[run.depends_on[0]]
        if dependency.process_type != kind or dependency.solver != name:
            raise SolverInputError(
                f"Transport run '{run.id}' follows the ({kind}, {name}) flow its backend "
                f"requires, and the run it depends on solves "
                f"{dependency.process_type}/{dependency.solver}.",
                run_id=run.id,
            )

    def _refuse_a_start_that_did_not_converge(self, state: Any, run: ProcessRun) -> None:
        """Refuse a transport run whose flow started from a permanent solve that did not converge.

        The heads of that solve are a field the flow was not solved to, and a
        transport run follows them. The convergence is known only once the flow
        has run, so the refusal cannot be made when the file is read. A run read
        back from a sealed document is replayed as it ran: the refusal becomes a
        warning there.
        """
        behind = [dep for dep in run.depends_on if dep in self._unconverged_starts]
        if not behind:
            return
        message = (
            f"Transport run '{run.id}' follows flow run '{behind[0]}', whose steady "
            "start did not converge, so the flow field it would carry is not a "
            "solved one. Tighten the closure of the auxiliary steady solve in the "
            "options of the flow solver, or start the flow from another state."
        )
        if getattr(getattr(state, "cfg", None), "read_as_sealed", False):
            logger.warning(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)
            return
        raise SolverDivergedError(message, run_id=run.id)

    def _run_mesh_process(self, state: Any, run: ProcessRun, slot: RunSlot) -> SolverRun:
        """Record the mesh artifacts already materialized by the mesh phase.

        A mesh run produces no model. What it has to say about what it built is
        execution metadata, and it travels as such in ``metrics``.
        """
        backend = run.backend or run.solver
        if backend != "catchment":
            raise ConfigError(f"Unsupported mesh process backend: {backend!r}", run_id=run.id)
        mesh_summary = getattr(getattr(state, "setup", None), "mesh_summary", None)
        return SolverRun(
            slot=slot,
            metrics={
                "backend": backend,
                "summary": dict(mesh_summary) if isinstance(mesh_summary, dict) else mesh_summary,
            },
        )

    def _resolve_upstream(self, state: Any, run: ProcessRun) -> tuple[SolverRun, ...]:
        """Return the ``SolverRun`` of each run ``run.depends_on`` names, in that order."""

        upstream: list[SolverRun] = []
        for dependency_id in run.depends_on:
            # A run that produced no solver model has nothing to hand over, like
            # a run that has not executed; both are refused for that reason.
            produced = state.execution.solver_runs.get(dependency_id)
            if produced is None or produced.solver_model is None:
                raise PipelineError(
                    f"Process run '{run.id}' depends on '{dependency_id}', "
                    "but that run has produced no model.",
                    run_id=run.id,
                )
            upstream.append(produced)
        return tuple(upstream)

    def _record_run_output(
        self,
        state: Any,
        run: ProcessRun,
        result: SolverRun,
    ) -> None:
        """Record what one run produced in the shared runtime state.

        ``execution.solver_runs`` is what this runner hands to a later run that
        declares a dependency, and what ``RunContext.of`` hands to every
        consumer after the solve. RAM-only metric extractors (calibration
        trials) find the raw solver binaries in its ``output_dir`` without going
        through the catalog.
        """

        state.execution.solver_runs[run.id] = result
        if result.initial_state_converged is False:
            self._unconverged_starts.add(run.id)
