"""Mutable runtime state threaded through workflow steps.

Three canonical scopes:

- ``setup``: structural objects prepared once (workspace, domain, flow, ...);
- ``loaded_data``: loaded support data (climatic, oceanic, hydrometry, ...);
- ``execution``: run outputs and registries (planned runs, produced models).

Plus the identity of the run being executed (``sim_id``,
``postprocess_runner``) used by the workflow layer.

Canonical access is explicit:

- ``state.setup.<...>`` for structural runtime context,
- ``state.loaded_data.<...>`` for loaded datasets,
- ``state.execution.<...>`` for run outputs and execution registries.

:class:`RunState` is the reduced view of that context a solver adapter is
handed. The workflow context is the state of a whole pipeline; an adapter
executes one run inside it and must not be able to reach the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.core.state.setup import SetupContext


@dataclass
class WorkflowContext:
    """Mutable workflow state split into setup/loaded_data/execution scopes.

    ``models_by_run_id`` is the source of truth for produced solver models.
    Concrete solver instances are resolved explicitly from that registry.

    Also carries the identity of the run being executed: ``sim_id`` and
    ``postprocess_runner``.

    It carries no live handle. The catalog a run writes to is opened by
    whoever writes, for the span of that write, through
    :func:`hydromodpy.workflow.run_catalog.run_catalog`: a DuckDB connection
    and its lock are a resource, and a context that held one could not cross
    a process boundary.

    ``cfg`` and ``data_plan`` are typed as ``Any`` because ``core`` cannot
    import from sibling layers. Concrete types are
    ``config.hydromodpy_config.HydroModPyConfig`` and ``data.plan.DataLoadPlan``.
    """

    cfg: Any
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)

    sim_id: str | None = None
    parent_sim_id: str | None = None

    # Run id minted by the caller before the pipeline starts, consumed once by
    # the store-opening step. Calibration promotion reserves it so the row
    # linking the run to its session exists before the run draws its figures.
    reserved_sim_id: str | None = None
    postprocess_runner: Any = field(default=None, repr=False)
    effective_results_config: Any = field(default=None, repr=False)

    # Dotted results-config paths the planning reconciliation turned on by
    # itself (never a user choice). Finalization reads them to tell a computed
    # intermediate apart from a requested output.
    forced_results_flags: tuple[str, ...] = ()

    def get_model(self, run_id: str) -> Any:
        """Return the exact model produced by a concrete process run."""
        return self.execution.models_by_run_id[run_id]

    def get_run_for_solver(self, solver_name: str) -> Any:
        """Return the unique planned run matching ``solver_name``, if any."""
        matches = [
            run for run in self.execution.process_runs_by_id.values() if run.solver == solver_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Expected at most one run for solver '{solver_name}', got {len(matches)}."
            )
        return matches[0] if matches else None

    def get_model_for_solver(self, solver_name: str) -> Any:
        """Return the produced model for ``solver_name``, if that run completed."""
        run = self.get_run_for_solver(solver_name)
        if run is None:
            return None
        return self.execution.models_by_run_id.get(run.id)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunState:
    """What a solver adapter reads of the workflow runtime, and nothing else.

    A :class:`WorkflowContext` is the state of a whole pipeline: the loaded
    support data, the raw TOML, the data plan, the post-processing runner, the
    flags the planner forced. An adapter executes one run and reads three
    scopes of it. Handing it the context made everything else reachable, and
    the field that carried it was typed ``Any``, so nothing said what an
    adapter was allowed to read. This view says it: the four members below are
    the whole surface, and reaching for anything else raises ``AttributeError``.

    ``setup`` and ``execution`` are the context's own scopes, shared by
    reference and mutable: the runner records a produced model in
    ``execution`` while adapters hold this view. The view owns neither, and it
    carries no live handle - the catalog of the enclosing run reaches an
    adapter through ``RunContext.store``.

    ``cfg`` is typed ``Any`` because ``core`` cannot import from sibling
    layers; the concrete type is ``config.hydromodpy_config.HydroModPyConfig``.
    """

    setup: SetupContext = field(default_factory=SetupContext)
    cfg: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: str | None = None

    @classmethod
    def of(cls, ctx: WorkflowContext) -> RunState:
        """Return the view of ``ctx`` a solver adapter is allowed to read."""
        return cls(
            setup=ctx.setup,
            cfg=ctx.cfg,
            execution=ctx.execution,
            sim_id=ctx.sim_id,
        )
