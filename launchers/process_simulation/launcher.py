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
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.toml_loader import load_toml_with_base_config
from hydromodpy.data_managers import (
    DataLoadPlan,
    DataManagersPlanner,
    DataManagersRuntimeLoader,
)
from hydromodpy.domain import Domain
from hydromodpy.domain.spatial_support import (
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
)
from hydromodpy.domain.structure_binders import apply_catchment_zones_to_domain, apply_geology_to_domain
from hydromodpy.postprocess.runner import PostprocessRunner
from hydromodpy.process.flow.structure_binders import (
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.geographic.synthetic import build_synthetic_geographic
from hydromodpy.simulation import SimulationPlanner, ensure_flow, ensure_transport
from hydromodpy.simulation.runtime.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.state.run_state import LauncherRunState
from hydromodpy.simulation.time import (
    apply_explicit_time_window_to_tgrids,
    require_flow_simulation_time_grid,
    resolve_simulation_time_window,
)
from launchers.output_paths import (
    build_repo_output_redirect_notice,
    resolve_launcher_output_root,
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
    >>> launcher = HydroModPyLauncher(Path("examples/launcher_simulation/config_extensive_nwt.toml"))
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

        resolved_out_dir, resolution = resolve_launcher_output_root(
            self.cfg.workspace.out_dir_path,
        )
        self.cfg.workspace.out_dir_path = resolved_out_dir
        if resolution == "repo_redirect":
            print(
                build_repo_output_redirect_notice(
                    entrypoint_name="HydroModPyLauncher",
                    resolved_out_dir=resolved_out_dir,
                )
            )

        apply_explicit_time_window_to_tgrids(self.cfg)
        self.time_grid = require_flow_simulation_time_grid(self.cfg)

        raw_toml = load_toml_with_base_config(self.config_path)

        self.spatial_support_provider_registry = (
            build_default_spatial_support_provider_registry()
        )
        self.requested_spatial_support_ids = self._collect_requested_support_ids_from_flow_config(
            self.cfg.flow
        )
        self.requested_domain_supports = self._resolve_requested_support_configs(
            domain_cfg=self.cfg.domain,
            requested_support_ids=self.requested_spatial_support_ids,
        )

        # Resolve the effective data-manager activation set from:
        # - explicit [data].types declarations,
        # - high-level domain/process/context hints.
        data_plan = DataManagersPlanner().build(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            domain_support_provider_names=self._support_provider_names(
                self.requested_domain_supports
            ),
            requested_spatial_support_ids=self.requested_spatial_support_ids,
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
        self.run_state.setup.time_grid = self.time_grid
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
        self._build_domain_spatial_supports(phase="setup")
        self._run_data()
        self._build_domain_spatial_supports(phase="data")
        # The runner owns the fine-grained solver dispatch. The launcher
        # only provides process-family callbacks for managed postprocess.
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=self._on_after_process,
            ),
        ).execute(plan, run_state)

        return run_state

    def _build_geographic_runtime(self, workspace):
        """Build the geographic runtime selected by the validated TOML config."""
        geographic_cfg = self.cfg.geographic
        uses_synthetic = getattr(geographic_cfg, "uses_synthetic_geographic", None)
        if callable(uses_synthetic) and uses_synthetic():
            return build_synthetic_geographic(
                config=geographic_cfg.synthetic,
                output_dir=Path(workspace.stable_folder) / "geographic",
                workspace=workspace,
            )
        return hmp.Geographic(geographic_cfg, workspace)

    @staticmethod
    def _collect_requested_support_ids_from_flow_config(flow_cfg: object) -> tuple[str, ...]:
        """Return the ordered support ids referenced by heterogeneous flow parameters."""
        raw_param_cfg = getattr(flow_cfg, "param", {})
        if not isinstance(raw_param_cfg, dict):
            return ()

        requested: list[str] = []
        seen: set[str] = set()
        for param_cfg in raw_param_cfg.values():
            if not isinstance(param_cfg, dict):
                continue
            kind = str(param_cfg.get("kind", "")).strip().lower()
            if kind != "heterogeneous":
                continue
            support_id = str(param_cfg.get("field_spatial_id", "")).strip()
            if support_id == "":
                raise ValueError(
                    "Heterogeneous flow parameters require a non-empty field_spatial_id."
                )
            normalized = support_id.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            requested.append(support_id)
        return tuple(requested)

    @staticmethod
    def _support_provider_names(domain_supports: dict[str, object]) -> tuple[str, ...]:
        """Return the ordered provider names declared by resolved support configs."""
        provider_names: list[str] = []
        seen: set[str] = set()
        for support_cfg in domain_supports.values():
            provider_name = str(getattr(support_cfg, "provider", "")).strip().lower()
            if provider_name == "" or provider_name in seen:
                continue
            seen.add(provider_name)
            provider_names.append(provider_name)
        return tuple(provider_names)

    def _resolve_requested_support_configs(
        self,
        *,
        domain_cfg: object,
        requested_support_ids: tuple[str, ...],
    ) -> dict[str, object]:
        """Resolve support configs actually needed by the current flow parameters."""
        if not requested_support_ids:
            return {}

        explicit_supports = getattr(domain_cfg, "supports", {})
        if explicit_supports is None:
            explicit_supports = {}
        if not isinstance(explicit_supports, dict):
            raise TypeError("domain.supports must be a dictionary")

        explicit_by_lower = {
            str(support_id).strip().lower(): support_cfg
            for support_id, support_cfg in explicit_supports.items()
        }

        resolved: dict[str, object] = {}
        for support_id in requested_support_ids:
            support_cfg = explicit_by_lower.get(str(support_id).strip().lower())
            if support_cfg is not None:
                resolved[support_id] = support_cfg
                continue
            raise ValueError(
                f"Missing domain support declaration for '{support_id}'. "
                "Declare [domain.supports.<id>] with an explicit provider."
            )
        return resolved

    @staticmethod
    def _flow_requires_spatial_support(flow: object | None) -> bool:
        """Return True when at least one flow parameter is heterogeneous."""
        if flow is None:
            return False
        parameters = getattr(flow, "parameters", {})
        if not isinstance(parameters, dict):
            return False
        return any(bool(getattr(param, "is_heterogeneous", False)) for param in parameters.values())

    def _augment_runtime_zone_ids(self, domain_cfg: object) -> object:
        """Ensure runtime-only zone ids required by launcher bindings are declared."""
        zone_ids = getattr(domain_cfg, "zone_ids", None)
        if zone_ids is None:
            zone_ids = []
            setattr(domain_cfg, "zone_ids", zone_ids)
        if not isinstance(zone_ids, list):
            zone_ids = list(zone_ids)
            setattr(domain_cfg, "zone_ids", zone_ids)

        normalized_zone_ids = {str(item).strip().lower() for item in zone_ids}
        if "catchment" not in normalized_zone_ids:
            zone_ids.append("catchment")
            normalized_zone_ids.add("catchment")

        for support_id in getattr(self, "requested_spatial_support_ids", ()):
            normalized_support_id = str(support_id).strip().lower()
            if normalized_support_id in normalized_zone_ids:
                continue
            zone_ids.append(str(support_id).strip())
            normalized_zone_ids.add(normalized_support_id)
        return domain_cfg

    def _validate_domain_support_contract(self, *, domain_cfg: object, flow: object | None) -> None:
        """Fail early when heterogeneous flow parameters reference undeclared supports."""
        _ = domain_cfg
        if not self._flow_requires_spatial_support(flow):
            return
        parameters = getattr(flow, "parameters", {})
        if not isinstance(parameters, dict):
            return

        declared_supports = {
            str(support_id).strip().lower()
            for support_id in getattr(self, "requested_domain_supports", {})
            if str(support_id).strip()
        }
        missing_supports: list[str] = []
        seen: set[str] = set()
        for param in parameters.values():
            if not bool(getattr(param, "is_heterogeneous", False)):
                continue
            support_id = str(getattr(param, "field_spatial_id", "")).strip()
            if support_id == "":
                raise ValueError(
                    "Heterogeneous flow parameters require a non-empty field_spatial_id."
                )
            normalized_support_id = support_id.lower()
            if normalized_support_id in declared_supports or normalized_support_id in seen:
                continue
            seen.add(normalized_support_id)
            missing_supports.append(support_id)

        if missing_supports:
            raise ValueError(
                "Heterogeneous flow parameters require explicit "
                "[domain.supports.<id>] declarations for: "
                + ", ".join(missing_supports)
                + "."
            )

    def _build_domain_spatial_supports(self, *, phase: str) -> None:
        """Materialize declared spatial supports for the requested launcher phase."""
        requested_domain_supports = getattr(self, "requested_domain_supports", {})
        if not requested_domain_supports:
            return

        run_state = self.run_state
        setup_state = run_state.setup
        context = SupportBuildContext(
            cfg=self.cfg,
            raw_toml=run_state.raw_toml,
            workspace=setup_state.workspace,
            geographic=setup_state.geographic,
            domain_geographic=setup_state.domain_geographic,
            domain=setup_state.domain,
            flow=setup_state.flow,
            loaded_data=run_state.loaded_data,
            time_grid=setup_state.time_grid,
        )

        for support_id, support_cfg in requested_domain_supports.items():
            existing_zone = None
            domain_get_zone = getattr(setup_state.domain, "get_zone", None)
            if callable(domain_get_zone):
                existing_zone = domain_get_zone(support_id)
            elif str(support_id).strip().lower() in getattr(setup_state.domain, "zones", {}):
                existing_zone = setup_state.domain.zones[str(support_id).strip().lower()]
            if existing_zone is not None and str(
                getattr(existing_zone, "identifier", "")
            ).strip() == str(support_id).strip():
                continue
            provider = self.spatial_support_provider_registry.get(
                getattr(support_cfg, "provider", "")
            )
            if str(provider.build_phase).strip().lower() != str(phase).strip().lower():
                continue
            support_field = provider.build(
                support_id=support_id,
                config=support_cfg,
                context=context,
            )
            setup_state.domain.set_zone(support_id, support_field)

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
        setup_state.geographic = self._build_geographic_runtime(setup_state.workspace)
        setup_state.domain_geographic = setup_state.geographic.get_domain_geographic_context()
        surface_topo = setup_state.domain_geographic.surface_topo

        domain_cfg = cfg.domain
        if hasattr(domain_cfg, "model_copy"):
            domain_cfg = domain_cfg.model_copy(deep=True)
        domain_cfg = self._augment_runtime_zone_ids(domain_cfg)

        setup_state.domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=setup_state.domain,
            geographic=setup_state.domain_geographic,
        )

        # Use [simulation].name as the default model/folder base name.
        # Canonical runtime location is setup.model_name.
        simulation_name = "_".join(str(cfg.simulation.name).strip().split())
        if simulation_name:
            setup_state.model_name = simulation_name
        # Eagerly create Flow/Transport so data binders can reference them.
        ensure_flow(run_state)
        ensure_transport(run_state)
        self._validate_domain_support_contract(
            domain_cfg=domain_cfg, flow=setup_state.flow,
        )

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
        self._apply_structural_updates_from_data()

    def _apply_structural_updates_from_data(self) -> None:
        """Bind loaded data objects to runtime structures using explicit updaters."""
        run_state = self.run_state
        setup_state = run_state.setup
        data_state = run_state.loaded_data
        apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
        ensure_flow(run_state)
        apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)

        resolved_grid = getattr(setup_state, "time_grid", None)
        window = (
            resolved_grid.window
            if resolved_grid is not None
            else resolve_simulation_time_window(self.cfg)
        )
        apply_recharge_load_result_to_flow(
            flow=setup_state.flow,
            recharge_result=data_state.recharge,
            simulation_window=window,
        )

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
