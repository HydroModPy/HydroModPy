"""HydroModPy launcher driven by an explicit simulation plan.

This module is the user-facing entry point that turns a declarative TOML file
into a concrete modeling run.

The launcher deliberately stays thin:

1. it loads and validates the configuration,
2. it prepares shared runtime objects used by all solvers,
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
- wires legacy hooks around process families,
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
from hydromodpy.data_managers.geology.geology_field import GeologyField
from hydromodpy.domain import Domain
from hydromodpy.process import Flow, Transport
from hydromodpy.simulation import SimulationPlanner
from hydromodpy.simulation.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.watershed.settings import Settings
from launchers.hook_registry import HookRegistry
from launchers.run_result import RunResult


class HydroModPyLauncher:
    """High-level orchestration layer between configuration and execution.

    This class is intentionally small. It does not implement solver-specific
    logic itself; instead, it prepares a ``RunResult`` state object and then
    hands a resolved ``SimulationPlan`` to ``SimulationRunner``.

    Example
    -------
    The typical usage is:

    >>> from pathlib import Path
    >>> launcher = HydroModPyLauncher(Path("examples/example12launcher/config.toml"))
    >>> result = launcher.run()

    After ``run()``, ``result`` contains both the shared objects created during
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

        self.result = RunResult(
            cfg=self.cfg,
            config_path=self.config_path,
            raw_toml=raw_toml,
            data_plan=data_plan,
        )
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

    def run(self) -> RunResult:
        """Execute one full launcher session and return the populated runtime state.

        The execution order is:

        1. validate that the TOML declares at least one simulation process,
        2. build the resolved execution plan,
        3. create the shared structural objects (setup),
        4. load shared forcings (data),
        5. execute planned process runs through ``SimulationRunner``.

        A useful mental model is:

        - ``setup`` and ``data`` run once per launcher session,
        - planned process runs (flow, transport, etc.) run once per declared
          process/solver pair.

        For example, if the TOML declares:

        - one ``flow`` process with ``["modflownwt", "modflow6"]``
        - one ``transport`` process with ``["mt3dms", "modflow6gwt"]``

        then ``run()`` will still perform setup/data only once, but it will
        later execute four concrete solver runs in the resolved order.
        """
        if not self.cfg.simulation.has_processes():
            raise ValueError(
                "Launchers require an explicit [simulation] block with at least "
                "one [[simulation.process]] entry."
            )

        plan = self._create_simulation_plan()
        self.result.simulation_plan = plan
        # Keep a direct lookup table by run id because downstream code and
        # hooks often need to reason about concrete runs, not just the flat list.
        self.result.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._run_data()
        # The runner owns the fine-grained solver dispatch. The launcher only
        # adapts legacy hooks to the new "process family" transitions.
        SimulationRunner(
            callbacks=ProcessCallbacks(
                before_process=lambda process_type: self._call_process_hook("before", process_type),
                after_process=lambda process_type: self._call_process_hook("after", process_type),
            )
        ).execute(plan, self.result)

        return self.result

    def _run_setup(self) -> None:
        """Initialise the structural objects shared by all later process runs.

        This method builds the stable "session context" of the simulation:

        - workspace and folders,
        - geographic context and topographic support,
        - domain and optional geology zone,
        - flow and transport process objects,
        - generic launcher settings.

        It runs once, even when the simulation plan later contains several
        solver runs. For example, two flow solvers still reuse the same domain
        geometry and the same declared flow configuration.
        """
        r = self.result
        cfg = self.cfg

        self.hooks.call("on_before_setup", r)

        r.workspace = hmp.Workspace(config=cfg.workspace)
        r.geographic = hmp.Geographic(cfg.geographic, r.workspace)
        surface_topo = r.geographic.get_domain_surface_topo()

        r.domain = Domain(config=cfg.domain, surface_topo=surface_topo)
        if "geology" in cfg.data.types:
            geology = GeologyField.from_watershed_config(
                cfg.data.geology, raster_support=surface_topo.support
            )
            r.domain.set_zone("geology", geology)

        r.flow = Flow(config=cfg.flow)
        r.settings = Settings()
        r.transport = Transport(config=cfg.transport)

        self.hooks.call("on_after_setup", r)

    def _run_data(self) -> None:
        """Load the external forcings shared by all process runs.

        Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
        data_managers package to keep launcher orchestration thin.
        """
        r = self.result
        self.hooks.call("on_before_data", r)
        DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=self.data_plan,
        ).load_all(r)
        self.hooks.call("on_after_data", r)

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
        self.hooks.call(f"on_{moment}_{process_type}", self.result)
