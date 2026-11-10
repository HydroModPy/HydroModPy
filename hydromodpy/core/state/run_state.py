"""Mutable runtime state threaded through workflow steps.

Three canonical scopes:

- ``setup``: structural objects prepared once (workspace, domain, flow, ...);
- ``loaded_data``: loaded support data (climatic, oceanic, hydrometry, ...);
- ``execution``: run outputs and registries (planned runs, what each run produced).

Plus the identity of the run being executed: ``sim_id``, the ``run_dir`` the
run writes into, the attempt that writes it, the ``parent_sim_id`` a run is
pinned to, and the ``reserved_sim_id`` minted before the pipeline starts. The
project layer pins the lineage, the workflow layer reads it.

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

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.state.rng import RngManager

if TYPE_CHECKING:
    from hydromodpy.core.workspace import WorkspaceLayout


@dataclass(frozen=True, slots=True, kw_only=True)
class SlotRequest:
    """What a calibration trial asks of the slot its runs solve in.

    The runner of a plan reads it to fill the ``RunSlot`` of each run. ``name``
    replaces ``setup.run_id`` as the run name, so each trial writes its own
    folder. ``stop_before_solve`` builds the model of each run and solves
    nothing. ``shared_forcing_dir`` is the folder a trial keeps its forcing
    files in, the recharge binaries for instance, apart from its model folder.
    It is the folder every trial of the session shares when the forcing is the
    same for all of them, or a folder of the trial's own when the trial samples
    a forcing parameter. ``None`` keeps the forcing files beside the model.

    The folder and the solver binaries are not asked for: they are facts of the
    machine, and the runner reads them on ``setup.workspace``.
    """

    name: str | None = None
    stop_before_solve: bool = False
    shared_forcing_dir: Path | None = None


@dataclass
class SetupContext:
    """Objects prepared during setup and reused by all runs.

    Most field types are ``Any`` because ``core`` cannot import from
    sibling layers (``catchment``, ``mesh``, ``model``). Concrete classes live in
    ``model.flow``, ``model.model``, ``model.domain``,
    ``catchment.preprocess`` and ``mesh.io``.
    """

    workspace: WorkspaceLayout | None = None
    geographic: Any = None
    geographic_features: Any = None
    domain_geographic: Any = None
    domain: Any = None
    # The ``cfg.domain`` section ``domain`` was built from. A Project builds its
    # model phase once and drives several runs through it; a run defined by
    # another configuration - a thickness sweep, a run following an overridden
    # one - must not inherit the previous run's geometry, and this is what says
    # so. Identity, not equality: ``HydroModPyConfig.with_changes`` keeps every
    # section a run does not override.
    domain_config_source: Any = None
    flow: Any = None
    # The frozen Model of the run (model.model.Model), built from ``flow`` by the
    # prepare_solver step and the only thing a flow adapter reads. None until then.
    model: Any = None
    mesh_summary: dict[str, Any] | None = None
    # The planar cell mesh the solvers read (mesh.planar PlanarCellMesh).
    cell_mesh: Any = None
    # What a calibration trial asks of the slot of each run. None outside a trial.
    slot_request: SlotRequest | None = None
    run_id: str = "default"
    # The grid of the periods this run solves: the whole simulation, or one
    # window of a chain (``core.time.window.window_grid``).
    time_grid: Any = None
    # The grid of the whole simulation. The data and the soil reservoir run on it
    # in every window of a chain, so each window sees the forcing of the run in
    # one piece. ``None`` outside a chain, where ``time_grid`` is the whole one.
    whole_time_grid: Any = None
    # The window of the chain this run solves (``core.time.window.ChainWindow``),
    # ``None`` for a run that is not a window.
    chain_window: Any = None
    # The frozen inputs of the run (``data.provenance.lockfile.LockedInputs``), read
    # once by the runner when the request is frozen. ``None`` for an unfrozen run.
    locked_inputs: Any = None
    # The DEM file record of the run (data.records FileRecord), set by the setup
    # step from [[data.dem.sources]]. None for a synthetic domain.
    dem_record: Any = None
    # Delineated SFR reach traces keyed by network id (spatial.SfrReachTrace).
    # Computed once by the data step and re-bound onto every per-run Flow.
    sfr_reach_traces: dict[str, Any] | None = None
    # Soil reservoir outputs of this context (model.forcing.soil_forcing.SoilForcings),
    # None outside soil mode. Assigned on every binder call, never mutated.
    soil_forcings: Any = None
    # Product keys this context asked the store for, ``{kind: key}``. Replaced
    # whole and never mutated in place: a forked trial shares the object by
    # reference, and an edit in one trial would leak into the others. A plain
    # dict, because a parallel calibration pickles the context for its workers.
    products: Mapping[str, str] = field(default_factory=dict)
    # The digests of the soil inputs, computed once by the data step and shared
    # by reference across forks, with what they were computed from: ``(sources,
    # {input: digest})``. A reload replaces the sources, and the digests go.
    soil_product_inputs: tuple[tuple[Any, ...], dict[str, str]] | None = None


@dataclass
class LoadedDataContext:
    """Loaded data-manager objects shared by process runs.

    Field types are ``Any`` because ``core`` cannot import from sibling
    layers (``data``, ``model``). Concrete types live in ``data.contracts``,
    ``data.variables.hydrography``, and ``model.properties.geology_field``.
    """

    dem: Any = None
    geology: Any = None
    oceanic: Any = None
    hydrography: Any = None
    intermittency: Any = None
    hydrometry: Any = None
    piezometry: Any = None
    recharge: Any = None
    runoff: Any = None
    precipitation: Any = None
    etp: Any = None
    temperature: Any = None
    wind: Any = None
    humidity: Any = None
    radiation: Any = None
    soil_moisture: Any = None
    water_quality: Any = None
    lake_geometry: Any = None
    lake_bathymetry: Any = None
    lake_abacus: Any = None
    lake_levels: Any = None
    lake_inflow: Any = None
    lake_outflow: Any = None
    lake_withdrawal: Any = None
    substratum: Any = None
    layer_base: Any = None
    soil_capacity: Any = None
    crossings: Any = None
    # Data-plan types covered by the last completed load; None = never loaded.
    loaded_plan_types: tuple[str, ...] | None = None


@dataclass
class ExecutionRegistry:
    """Execution-oriented metadata and what each run produced.

    ``lightweight`` is set to ``True`` when the pipeline runs inside a
    calibration trial: in that mode steps 06/07 skip Zarr / Parquet /
    provenance writes and the solver output is kept in RAM for scoring
    only. The flag is ``False`` for normal ``hmp run`` and for promoted
    trials.

    ``solver_runs`` maps a run id to the ``SolverRun`` that run produced:
    the solver model it built, the folder its solver wrote and the metrics
    it recorded about itself. Calibration metric extractors read the solver
    binaries (``.hds`` / ``.cbc``) from that folder without touching the
    catalog. A resume past the solver puts back a ``SolverRun`` without a
    solver model, read from the facts of the run.

    ``rng`` is the master :class:`RngManager` for the simulation.
    Stochastic consumers derive their own deterministic ``Generator``
    from ``rng.child_rng(label)``. It is ``None`` when no master seed
    is declared in ``[simulation]``: each consumer then uses
    ``np.random.default_rng()`` with a fresh entropy source.

    ``resumed`` is set to ``True`` by the runner while it rebuilds the
    prefix steps of a resumed run, so the product steps read the keys the
    earlier attempt cited instead of recomputing them.

    Field types are ``Any`` because ``core`` cannot import from sibling
    layers. ``simulation_plan``, ``process_runs_by_id`` values and
    ``solver_runs`` values are ``solver.base.plan`` types.
    """

    simulation_plan: Any = None
    process_runs_by_id: dict[str, Any] = field(default_factory=dict)
    solver_runs: dict[str, Any] = field(default_factory=dict)
    lightweight: bool = False
    resumed: bool = False
    rng: RngManager | None = None


@dataclass
class WorkflowContext:
    """Mutable workflow state split into setup/loaded_data/execution scopes.

    ``execution.solver_runs`` is where the runner records what each run
    produced. The runner reads it to hand a run the runs it declares in
    ``depends_on``. Every other consumer reads what one run produced, and
    receives it through ``RunContext.solver_run``.

    Also carries the identity of the run being executed: ``sim_id``, the
    ``run_dir`` it writes into with the ``attempt`` that writes it, the
    ``parent_sim_id`` a run is pinned to - whether it descends
    from a calibration promotion or from a rerun, which pin it the same way -
    the ``reserved_sim_id`` minted before the pipeline starts, and the
    ``lineage`` and ``calibrated_by`` blocks a promotion hands its run.

    It carries no live handle. The store a run writes to is opened by
    whoever writes, for the span of that write, through
    :func:`hydromodpy.workflow.record.run_store`: a store holds open
    array handles, and a context that held one could not cross a process
    boundary.

    ``cfg`` and ``data_plan`` are typed as ``Any`` because ``core`` cannot
    import from sibling layers. Concrete types are
    ``config.hydromodpy_config.HydroModPyConfig`` and ``data.plan.DataLoadPlan``.
    ``bounds`` carries the :class:`~hydromodpy.core.runtime.bounds.Bounds` of the
    call, set by whoever started the project; left ``None``, a context built
    without one keeps the all-allowing bounds it holds by itself. ``inputs``
    carries the files the runner resolved when it claimed the run, so the setup
    reads them and never resolves a second time.
    """

    cfg: Any
    config_path: Path
    raw_toml: dict[str, Any]
    # What this call may reach and read, said by the ``Environment`` its caller
    # received (the credentials file, the hosts and roots it permits). When no
    # environment was given, the field keeps the all-allowing default its type
    # holds by itself.
    bounds: Any = None
    # The files the run resolved at its claim, before any step: the
    # ``ResolvedInputs`` of the data layer, typed ``Any`` because ``core`` cannot
    # import it. ``None`` until a runner resolves them, and the setup then
    # resolves for itself.
    inputs: Any = None
    data_plan: Any = None
    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)

    sim_id: str | None = None
    parent_sim_id: str | None = None

    # The directory the run writes into, claimed before the first step, and
    # the attempt that writes it. Set by the step that opens the run store.
    run_dir: Path | None = None
    attempt: int = 1

    # The lineage and the promoting session a run is sealed with, typed
    # ``Any`` because ``core`` cannot import ``results``; the concrete types
    # are ``results.lineage.Lineage`` and ``results.checks.CalibratedBy``.
    lineage: Any = None
    calibrated_by: Any = None

    # Run id minted by the caller before the pipeline starts, consumed once by
    # the store-opening step. Calibration promotion reserves it so the row
    # linking the run to its session exists before the run draws its figures.
    reserved_sim_id: str | None = None

    # The per-cell budget this run keeps, decided at planning (or read back
    # from the store on a resume after extraction). The extraction reads it.
    budget_terms: BudgetKeep | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunState:
    """What a solver adapter reads of the workflow runtime, and nothing else.

    A :class:`WorkflowContext` is the state of a whole pipeline: the loaded support
    data, the raw TOML, the data plan, the budget the planner kept. An adapter executes
    one run and reads two scopes of it. Handing it the context made everything else
    reachable, and the field that carried it was typed ``Any``, so nothing said what an
    adapter was allowed to read. This view says it: the three members below are the
    whole surface, and reaching for anything else raises ``AttributeError``.

    ``setup`` is the context's own scope, shared by reference and mutable. The
    view owns it, and it carries no live handle - the catalog of the enclosing
    run reaches an adapter through ``RunContext.store``.

    The view carries no execution registry either. Every read an adapter made
    of it asked for the entry keyed by its own ``run.id``: the model that run
    produced and the directory its solver wrote into. Both now reach a
    consumer through ``RunContext.solver_run``, so reaching for another run's
    product is not forbidden by convention, it raises ``AttributeError``.

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
