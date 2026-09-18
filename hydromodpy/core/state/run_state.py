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
- ``state.execution.<...>`` for run outputs and execution registries
  (workflow scope only: a solver adapter reads neither).

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

    ``execution.models_by_run_id`` is where the runner records the model each
    run produced, and the runner is its only reader: it resolves the upstream
    models a run declares in ``depends_on``. Every other consumer reads what
    one run produced, and receives it through ``RunContext``.

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


@dataclass(frozen=True, slots=True, kw_only=True)
class RunState:
    """What a solver adapter reads of the workflow runtime, and nothing else.

    A :class:`WorkflowContext` is the state of a whole pipeline: the loaded
    support data, the raw TOML, the data plan, the post-processing runner, the
    flags the planner forced. An adapter executes one run and reads two scopes
    of it. Handing it the context made everything else reachable, and the field
    that carried it was typed ``Any``, so nothing said what an adapter was
    allowed to read. This view says it: the three members below are the whole
    surface, and reaching for anything else raises ``AttributeError``.

    ``setup`` is the context's own scope, shared by reference and mutable. The
    view owns it, and it carries no live handle - the catalog of the enclosing
    run reaches an adapter through ``RunContext.store``.

    The view carries no execution registry either. Every read an adapter made
    of it asked for the entry keyed by its own ``run.id``: the model that run
    produced and the directory its solver wrote into. Both now reach the
    adapter through ``RunContext.model`` and ``RunContext.output_dir``, so
    reaching for another run's product is not forbidden by convention, it
    raises ``AttributeError``.

    ``cfg`` is typed ``Any`` because ``core`` cannot import from sibling
    layers; the concrete type is ``config.hydromodpy_config.HydroModPyConfig``.
    """

    setup: SetupContext = field(default_factory=SetupContext)
    cfg: Any = None
    sim_id: str | None = None

    @classmethod
    def of(cls, ctx: WorkflowContext) -> RunState:
        """Return the view of ``ctx`` a solver adapter is allowed to read."""
        return cls(
            setup=ctx.setup,
            cfg=ctx.cfg,
            sim_id=ctx.sim_id,
        )
