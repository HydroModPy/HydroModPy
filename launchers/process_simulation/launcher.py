"""HydroModPy launcher driven by an explicit simulation plan.

This module is the user-facing entry point that turns a declarative TOML file
into a concrete modeling run.

The launcher deliberately stays thin:

1. it loads and validates the configuration,
2. it prepares shared runtime context used by process solvers,
3. it asks the simulation layer to resolve the declared process list,
4. it delegates the actual solver execution to ``SimulationRunner``.

That separation matters because three concerns stay isolated:

- ``HydroModPyLauncher`` handles I/O-oriented bootstrap work
  (paths, raw TOML, shared objects),
- ``SimulationPlanner`` handles dependency logic
  (for example: a transport run may require a specific flow solver first),
- ``SimulationRunner`` handles side effects
  (writing models, launching binaries, storing produced models).

In practice, the launcher consumes a TOML structure like::

    [simulation]
    name = "Example 12 launcher baseline"
    description = "Transient flow, particle tracking, and nitrate transport."

    [[simulation.process]]
    id = "flow_main"
    type = "flow"
    solvers = ["modflownwt"]

    [[simulation.process]]
    id = "transport_no3"
    type = "transport"
    solvers = ["mt3dms"]

The launcher itself does not hard-code "run flow then transport". It only:

- prepares the shared state,
- builds a plan from the TOML,
- runs optional launcher-managed postprocess actions after process families,
- executes the resolved plan.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import (
    DataLoadPlan,
    DataManagersPlanner,
    DataManagersRuntimeLoader,
)
from hydromodpy.domain import Domain
from hydromodpy.domain.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)
from hydromodpy.postprocess.runner import PostprocessRunner
from hydromodpy.process.flow.structure_binders import (
    apply_climatic_to_flow_recharge,
    apply_oceanic_to_flow,
)
from hydromodpy.simulation.forcing import build_recharge_chronicle_payload
from hydromodpy.simulation import SimulationPlanner, ensure_flow, ensure_transport
from hydromodpy.simulation.runtime.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.state.run_state import LauncherRunState
from hydromodpy.simulation.settings import Settings
from hydromodpy.simulation.time import (
    apply_explicit_time_window_to_tgrids,
    resolve_simulation_time_window,
    validate_recharge_coverage,
)


class HydroModPyLauncher:
    """High-level orchestration layer between configuration and execution.

    This class is intentionally small. It does not implement solver-specific
    logic itself; instead, it prepares a ``LauncherRunState`` object and then
    hands a resolved ``SimulationPlan`` to ``SimulationRunner``.

    Example
    -------
    The typical usage is:

    >>> from pathlib import Path
    >>> launcher = HydroModPyLauncher(Path("examples/launcher_simulation/config_standard.toml"))
    >>> run_state = launcher.run()

    After ``run()``, ``run_state`` contains both the shared objects created during
    bootstrap (workspace, domain, flow config, transport config) and the models
    produced by executed runs.
    """

    def __init__(self, config_path: str | Path) -> None:
        """Load configuration and raw TOML for one launcher run.

        Parameters
        ----------
        config_path:
            Path to the TOML file that declares both the shared HydroModPy
            sections (workspace, flow, transport, etc.) and the
            ``[simulation]`` block.

        Notes
        -----
        Two views of the same configuration are kept on purpose:

        - ``self.cfg`` is the validated Pydantic representation used by the core
          code,
        - ``raw_toml`` is the untyped dictionary kept for optional
          launcher-managed custom sections (currently ``[recharge_chronicle]``).
        """
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # HYDROMODPY_OUT_PATH allows redirecting outputs without editing the launcher TOML.
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

        apply_explicit_time_window_to_tgrids(self.cfg)

        with self.config_path.open("rb") as fh:
            raw_toml = tomllib.load(fh)

        # Resolve the effective data-manager activation set from:
        # - explicit [data].types declarations,
        # - high-level domain/process/context hints.
        data_plan = DataManagersPlanner().build(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            raw_toml=raw_toml,
            flow_active_bc=self.cfg.flow.active_bc,
        )
        self._log_data_plan(data_plan)
        # Apply resolved types back to cfg so downstream code can keep reading
        # one canonical config tree (`self.cfg.data`).
        self.cfg.data = self.cfg.data.with_resolved_types(data_plan.types)
        self.data_plan = data_plan

        self.run_state = LauncherRunState(
            cfg=self.cfg,
            config_path=self.config_path,
            raw_toml=raw_toml,
        )
        self.run_state.data_plan = data_plan
        self.postprocess_runner = PostprocessRunner(self.cfg.postprocess)

    @staticmethod
    def _log_data_plan(data_plan: DataLoadPlan) -> None:
        """Print concise planner diagnostics when inferred types are present."""
        if not data_plan.inferred_types:
            return
        print(
            "[DataManagersPlanner] inferred data types: "
            + ", ".join(data_plan.inferred_types)
        )
        for type_name in data_plan.inferred_types:
            reasons = data_plan.reasons_for(type_name)
            if reasons:
                print(
                    f"[DataManagersPlanner] {type_name}: "
                    + "; ".join(reasons)
                )

    def run(self) -> LauncherRunState:
        """Execute one full launcher session and return the populated runtime state.

        The execution order is:

        1. validate that the TOML declares at least one simulation process,
        2. build the resolved execution plan,
        3. create the shared structural objects (setup),
        4. load shared forcings (data),
        5. execute planned process runs through ``SimulationRunner``.

        A useful mental model is:

        - ``setup`` and ``loaded_data`` run once per launcher session,
        - planned process runs (flow, transport, etc.) run once per declared
          process/solver pair.

        For example, if the TOML declares:

        - one ``flow`` process with ``["modflownwt", "modflow6"]``
        - one ``transport`` process with ``["mt3dms", "modflow6gwt"]``

        then ``run()`` will still perform setup/loaded_data only once, but it will
        later execute four concrete solver runs in the resolved order.
        """
        if not self.cfg.simulation.has_processes():
            raise ValueError(
                "Launchers require an explicit [simulation] block with at least "
                "one [[simulation.process]] entry."
            )

        run_state = self.run_state
        execution_state = run_state.execution
        plan = self._create_simulation_plan()
        execution_state.simulation_plan = plan
        # Keep a direct lookup table by run id because downstream code often
        # needs concrete run-level lookup, not just the flat list.
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._run_data()
        # The runner owns the fine-grained solver dispatch. The launcher
        # only provides process-family callbacks for managed postprocess.
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=self._on_after_process,
            ),
        ).execute(plan, run_state)

        return run_state

    def _run_setup(self) -> None:
        """Initialise the structural objects shared by all later process runs.

        This method builds the stable "session context" of the simulation:

        - workspace and folders,
        - geographic context and topographic support,
        - domain geometry,
        - process-level context objects (``flow``, ``transport``),
        - generic launcher settings.

        It runs once, even when the simulation plan later contains several
        solver runs. For example, two flow solvers still reuse the same domain
        geometry and the same declared flow configuration.
        """
        run_state = self.run_state
        setup_state = run_state.setup
        cfg = self.cfg

        setup_state.workspace = hmp.Workspace(config=cfg.workspace)
        setup_state.geographic = hmp.Geographic(cfg.geographic, setup_state.workspace)
        setup_state.domain_geographic = setup_state.geographic.get_domain_geographic_context()
        surface_topo = setup_state.domain_geographic.surface_topo

        domain_cfg = cfg.domain
        zone_ids = getattr(domain_cfg, "zone_ids", None)
        if isinstance(zone_ids, list):
            normalized_zone_ids = {str(item).strip().lower() for item in zone_ids}
            if "catchment" not in normalized_zone_ids:
                if hasattr(domain_cfg, "model_copy"):
                    domain_cfg = domain_cfg.model_copy(deep=True)
                    domain_cfg.zone_ids.append("catchment")
                else:
                    zone_ids.append("catchment")

        setup_state.domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=setup_state.domain,
            geographic=setup_state.domain_geographic,
        )

        setup_state.settings = Settings()
        # Use [simulation].name as the default model/folder base name.
        # Canonical runtime location is setup.model_name.
        simulation_name = "_".join(str(cfg.simulation.name).strip().split())
        if simulation_name:
            setup_state.model_name = simulation_name
            # Keep mirroring for compatibility with code paths still reading
            # settings.model_name directly.
            if hasattr(setup_state.settings, "model_name"):
                setup_state.settings.model_name = simulation_name
        # Eagerly create Flow/Transport so data binders can reference them.
        ensure_flow(run_state)
        ensure_transport(run_state)

    def _run_data(self) -> None:
        """Load the external forcings shared by all process runs.

        Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
        data_managers package. Structural bindings are then applied explicitly
        through domain/process binder modules.
        """
        run_state = self.run_state
        loader = DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=self.data_plan,
        )
        loader.load_all(run_state)
        self._apply_recharge_chronicle_from_toml()
        self._apply_structural_updates_from_data()

    def _apply_recharge_chronicle_from_toml(self) -> None:
        """Optionally materialize climatic recharge from [recharge_chronicle]."""
        run_state = self.run_state
        climatic = run_state.loaded_data.climatic
        if climatic is None:
            raise RuntimeError(
                "Launcher internal error: loaded_data.climatic is not initialized."
            )

        sinks_sources = getattr(run_state.setup.flow, "sinks_sources", {})
        recharge_cfg = (
            sinks_sources.get("recharge")
            if isinstance(sinks_sources, dict)
            else None
        )
        default_values = getattr(recharge_cfg, "values", None) if recharge_cfg is not None else None
        sim_state = run_state.setup.flow.flow_regime
        payload = build_recharge_chronicle_payload(
            run_state.raw_toml,
            config_path=self.config_path,
            default_values=default_values,
            default_observed_path=run_state.cfg.workspace.data_path / "_climate_REANALYSIS.csv",
            default_sim_state=sim_state,
        )
        if payload is None:
            return

        window = resolve_simulation_time_window(self.cfg)

        if payload.mode == "observed_csv":
            observed = payload.observed
            if observed is None:
                raise RuntimeError("Observed recharge payload is missing for mode='observed_csv'.")
            climatic.update_recharge_reanalysis(
                path_file=observed.path_file,
                clim_mod=observed.clim_mod,
                clim_sce=observed.clim_sce,
                first_year=observed.first_year,
                last_year=observed.last_year,
                time_step=observed.time_step,
                sim_state=observed.sim_state,
            )
            climatic.update_runoff_reanalysis(
                path_file=observed.path_file,
                clim_mod=observed.clim_mod,
                clim_sce=observed.clim_sce,
                first_year=observed.first_year,
                last_year=observed.last_year,
                time_step=observed.time_step,
                sim_state=observed.sim_state,
            )
            validate_recharge_coverage(
                climatic.recharge,
                window,
            )
            return

        recharge = payload.recharge
        runoff = payload.runoff
        if recharge is None or runoff is None:
            raise RuntimeError(
                f"Synthetic recharge payload is incomplete for mode='{payload.mode}'."
            )
        validate_recharge_coverage(
            recharge,
            window,
        )
        climatic.update_recharge(recharge, sim_state=sim_state)
        climatic.update_runoff(runoff, sim_state=sim_state)

    def _apply_structural_updates_from_data(self) -> None:
        """Bind loaded data objects to runtime structures using explicit updaters."""
        run_state = self.run_state
        setup_state = run_state.setup
        data_state = run_state.loaded_data
        apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
        ensure_flow(run_state)
        apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)
        apply_climatic_to_flow_recharge(flow=setup_state.flow, climatic=data_state.climatic)

    def _create_simulation_plan(self):
        """Resolve the declarative ``[simulation]`` block into concrete runs.

        ``SimulationPlanner`` converts a compact declaration into explicit
        executable units. For example, this input:

        - ``type="flow", solvers=["modflownwt"]``
        - ``type="transport", solvers=["mt3dms"]``

        becomes two concrete runs where the second one explicitly depends on
        the first. That explicit plan is what makes execution deterministic and
        reusable outside the launcher as well.
        """
        planner = SimulationPlanner()
        return planner.build(self.cfg.simulation)

    def _on_after_process(self, process_type: str) -> None:
        """Run launcher-level actions after one process-family block."""
        self.postprocess_runner.after_process(process_type, self.run_state)
