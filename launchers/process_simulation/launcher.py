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
  (paths, raw TOML, hooks, shared objects),
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
- keeps legacy hooks around process families,
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
from hydromodpy.domain.structure_binders import apply_geology_to_domain
from hydromodpy.postprocess.runner import PostprocessRunner
from hydromodpy.process.flow.structure_binders import apply_oceanic_to_flow
from hydromodpy.simulation import ProcessContextFactory, SimulationPlanner
from hydromodpy.simulation.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.watershed.settings import Settings
from launchers.process_simulation.hook_registry import HookRegistry
from launchers.process_simulation.run_state import LauncherRunState


class HydroModPyLauncher:
    """High-level orchestration layer between configuration and execution.

    This class is intentionally small. It does not implement solver-specific
    logic itself; instead, it prepares a ``LauncherRunState`` object and then
    hands a resolved ``SimulationPlan`` to ``SimulationRunner``.

    Example
    -------
    The typical usage is:

    >>> from pathlib import Path
    >>> launcher = HydroModPyLauncher(Path("examples/example12launcher/config.toml"))
    >>> run_state = launcher.run()

    After ``run()``, ``run_state`` contains both the shared objects created during
    bootstrap (workspace, domain, flow config, transport config) and the models
    produced by executed runs.
    """

    def __init__(self, config_path: str | Path) -> None:
        """Load configuration, raw TOML, and user hooks for one launcher run.

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
        - ``raw_toml`` is the untyped dictionary kept for hooks that still read
          example-specific custom sections directly.
        """
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # HYDROMODPY_OUT_PATH allows redirecting outputs without editing config.toml.
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

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
            hook_python_path=self.config_path.parent / "hooks.py",
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
        self.process_context_factory = ProcessContextFactory()
        self.postprocess_runner = PostprocessRunner(self.cfg.postprocess)
        self.hooks = HookRegistry.discover(self.config_path)

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
        # Keep a direct lookup table by run id because downstream code and
        # hooks often need to reason about concrete runs, not just the flat list.
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._run_data()
        # The runner owns the fine-grained solver dispatch. The launcher
        # provides process-family callbacks to run managed postprocess actions
        # and legacy hooks around those transitions.
        SimulationRunner(
            callbacks=ProcessCallbacks(
                before_process=self._on_before_process,
                after_process=self._on_after_process,
            ),
            process_context_factory=self.process_context_factory,
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

        self.hooks.call("on_before_setup", run_state)

        setup_state.workspace = hmp.Workspace(config=cfg.workspace)
        setup_state.geographic = hmp.Geographic(cfg.geographic, setup_state.workspace)
        surface_topo = setup_state.geographic.get_domain_surface_topo()

        setup_state.domain = Domain(config=cfg.domain, surface_topo=surface_topo)

        setup_state.settings = Settings()
        # Keep eager context creation in setup for compatibility with data
        # binders and existing hooks.
        self.process_context_factory.ensure_flow(run_state)
        self.process_context_factory.ensure_transport(run_state)

        self.hooks.call("on_after_setup", run_state)

    def _run_data(self) -> None:
        """Load the external forcings shared by all process runs.

        Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
        data_managers package. Structural bindings are then applied explicitly
        through domain/process binder modules.
        """
        run_state = self.run_state
        self.hooks.call("on_before_data", run_state)
        loader = DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=self.data_plan,
        )
        loader.load_all(run_state)
        self._apply_structural_updates_from_data()
        self.hooks.call("on_after_data", run_state)

    def _apply_structural_updates_from_data(self) -> None:
        """Bind loaded data objects to runtime structures using explicit updaters."""
        run_state = self.run_state
        setup_state = run_state.setup
        data_state = run_state.loaded_data
        apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
        self.process_context_factory.ensure_flow(run_state)
        apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)

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

    def _call_process_hook(self, moment: str, process_type: str) -> None:
        """Bridge the new process-family execution model to legacy hook names.

        Parameters
        ----------
        moment:
            Either ``"before"`` or ``"after"``.
        process_type:
            Process family name such as ``"flow"`` or ``"transport"``.

        Example
        -------
        ``_call_process_hook("before", "flow")`` resolves to the legacy hook
        name ``on_before_flow``.

        This keeps existing ``hooks.py`` files working while the core runtime is
        now organized around a resolved simulation plan instead of hard-coded
        launcher phases.
        """
        self.hooks.call(f"on_{moment}_{process_type}", self.run_state)

    def _on_before_process(self, process_type: str) -> None:
        """Run launcher-level actions before one process-family block."""
        self._call_process_hook("before", process_type)

    def _on_after_process(self, process_type: str) -> None:
        """Run launcher-level actions after one process-family block."""
        self.postprocess_runner.after_process(process_type, self.run_state)
        self._call_process_hook("after", process_type)
