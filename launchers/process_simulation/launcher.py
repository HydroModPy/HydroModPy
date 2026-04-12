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

from collections.abc import Mapping
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import hydromodpy as hmp
from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.analysis.capability_gallery import publish_run_to_capability_gallery
from hydromodpy.spatial.domain import Domain
from hydromodpy.spatial.domain.spatial_support import (
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
)
from hydromodpy.spatial.geographic.core.derived_features import (
    coerce_geographic_derived_features,
)
from hydromodpy.spatial.geographic.structure_binders import apply_catchment_zones_to_domain, apply_geology_to_domain
from hydromodpy.analysis.postprocess.runner import PostprocessRunner
from hydromodpy.process.flow.structure_binders import (
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.spatial.geographic.synthetic import build_synthetic_geographic
from hydromodpy.simulation import SimulationPlanner, ensure_flow, ensure_transport
from hydromodpy.simulation.execution.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.core.state.run_state import LauncherRunState
from hydromodpy.core.time import (
    apply_explicit_time_window_to_tgrids,
    require_flow_simulation_time_grid,
    resolve_simulation_time_window,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    build_gmsh_support_metadata,
    load_planar_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from hydromodpy.core.units import convert_payload_to_m_per_s
from launchers.mesh_catchment.config import parse_mesh_catchment_batch_config_data
from launchers.mesh_catchment.runtime import (
    get_optional_mesh_section,
    prepare_geographic_config_for_meshing,
    run_single_mesh_catchment_workflow_with_runtime_artifacts,
)

if TYPE_CHECKING:
    from hydromodpy.data import DataLoadPlan
    from launchers.mesh_catchment.config import MeshCatchmentConfigSchema


def _build_data_plan(*args, **kwargs):
    """Import planner lazily to keep launcher imports lightweight in tests."""
    from hydromodpy.data import DataManagersPlanner

    return DataManagersPlanner().build(*args, **kwargs)


def _build_data_runtime_loader(*args, **kwargs):
    """Import runtime loader lazily to avoid importing the full data stack at module import."""
    from hydromodpy.data import DataManagersRuntimeLoader

    return DataManagersRuntimeLoader(*args, **kwargs)


class HydroModPyLauncher:
    """High-level orchestration layer between configuration and execution.

    This class is intentionally small. It does not implement solver-specific
    logic itself; instead, it prepares a ``LauncherRunState`` object and then
    hands a resolved ``SimulationPlan`` to ``SimulationRunner``.

    Example
    -------
    The typical usage is:

    >>> from pathlib import Path
    >>> launcher = HydroModPyLauncher(Path("examples/projects/01_canut/run_steady_nwt.toml"))
    >>> run_state = launcher.run()

    After ``run()``, ``run_state`` contains both the shared objects created during
    bootstrap (workspace, domain, flow config, transport config) and the models
    produced by executed runs.
    """

    model_calibration_runtime_direct = True
    model_calibration_runtime_reusable = True

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

        apply_explicit_time_window_to_tgrids(self.cfg)
        self.time_grid = require_flow_simulation_time_grid(self.cfg)

        raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = self._resolve_optional_mesh_section(raw_toml)
        self.external_mesh_input = self._resolve_optional_mesh_input(raw_toml)
        self.mesh_constraints_mode = None
        if self.mesh_section_data is not None and self.external_mesh_input is not None:
            raise ValueError(
                "Embedded [mesh_catchment] and external [mesh_input] are mutually "
                "exclusive in process_simulation. Use only one mesh source."
            )
        if self.mesh_section_data is not None:
            self.mesh_constraints_mode = self.mesh_section_data.constraints_mode
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode=self.mesh_constraints_mode,
            )
        elif (
            self.external_mesh_input is not None
            and "stream"
            in {
                str(bc_id).strip().lower()
                for bc_id in getattr(self.cfg.flow, "active_bc", ())
            }
        ):
            self.cfg.geographic = prepare_geographic_config_for_meshing(
                self.cfg.geographic,
                constraints_mode="rivers_only",
                section_name="mesh_input",
            )

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
        data_plan = _build_data_plan(
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
        self._prepared_runtime_plan = None
        self._prepared_runtime_ready = False

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

    def _resolve_optional_mesh_section(
        self,
        raw_toml: Mapping[str, object],
    ) -> MeshCatchmentConfigSchema | None:
        section = get_optional_mesh_section(raw_toml)
        batch_section = raw_toml.get("mesh_catchment_batch")
        if batch_section is None:
            return section
        batch_cfg = parse_mesh_catchment_batch_config_data(batch_section)
        if batch_cfg.enabled:
            raise ValueError(
                "Embedded [mesh_catchment_batch] is not supported in process_simulation. "
                "Use the dedicated mesh-catchment launcher for batch runs."
            )
        return section

    def _resolve_optional_mesh_input(
        self,
        raw_toml: Mapping[str, object],
    ) -> dict[str, str] | None:
        """Resolve one optional external mesh-input block from raw launcher TOML."""
        section = raw_toml.get("mesh_input")
        if section is None:
            return None
        if not isinstance(section, Mapping):
            raise ValueError("[mesh_input] configuration must be a mapping when provided.")

        def _resolve_optional_path(raw_value: object) -> str:
            text = str(raw_value or "").strip()
            if text == "":
                return ""
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = (self.config_path.parent / path).resolve()
            return str(path)

        mesh_path = _resolve_optional_path(section.get("mesh_path"))
        bundle_dir = _resolve_optional_path(section.get("bundle_dir"))
        if mesh_path == "" and bundle_dir == "":
            raise ValueError(
                "[mesh_input] requires at least one of 'mesh_path' or 'bundle_dir'."
            )
        return {
            "mesh_path": mesh_path,
            "bundle_dir": bundle_dir,
        }

    def prepare_runtime(self):
        """Prepare the shared runtime once and cache the resolved execution plan."""
        if self._prepared_runtime_ready and self._prepared_runtime_plan is not None:
            return self._prepared_runtime_plan
        if not self.cfg.simulation.has_processes():
            raise ValueError(
                "Launchers require an explicit [simulation] block with at least "
                "one [[simulation.process]] entry."
            )

        run_state = self.run_state
        execution_state = run_state.execution
        plan = self._create_simulation_plan()
        self._validate_runtime_mesh_solver_compatibility(plan)
        execution_state.simulation_plan = plan
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._build_domain_spatial_supports(phase="setup")
        self._run_data()
        self._build_domain_spatial_supports(phase="data")
        self._run_mesh_phase()
        self._run_mesh_input_phase()

        self._prepared_runtime_plan = plan
        self._prepared_runtime_ready = True
        return plan

    def run_prepared(self) -> LauncherRunState:
        """Execute the cached runtime state after resetting only execution outputs."""
        plan = self.prepare_runtime()
        run_state = self.run_state
        execution_state = run_state.execution
        execution_state.simulation_plan = plan
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}
        execution_state.models_by_run_id = {}

        wall_start = time.monotonic()
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=self._on_after_process,
            ),
        ).execute(plan, run_state)
        wall_seconds = time.monotonic() - wall_start
        self._save_run_artifacts(run_state, wall_seconds)
        return run_state

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
        return self.run_prepared()

    def _validate_runtime_mesh_solver_compatibility(self, plan) -> None:
        """Reject unsupported flow solvers when the launcher injects a Gmsh mesh.

        `process_simulation` keeps a single launcher entry point for all flow
        backends. Runtime Gmsh meshes therefore remain a launcher-level option
        (`[mesh_catchment]` or `[mesh_input]`), not a separate launcher family.

        Today, only Boussinesq and MODFLOW 6 consume that runtime mesh contract.
        MODFLOW-NWT still relies on its structured `sgrid` backend and should
        fail early with a clear message instead of silently ignoring the mesh.
        """
        if self.mesh_section_data is None and self.external_mesh_input is None:
            return

        uses_modflow_nwt = any(
            getattr(run, "process_type", None) == "flow"
            and str(getattr(run, "solver", "")).strip().lower() == "modflownwt"
            for run in getattr(plan, "runs", ())
        )
        if not uses_modflow_nwt:
            return

        mesh_source = "[mesh_input]" if self.external_mesh_input is not None else "[mesh_catchment]"
        raise ValueError(
            f"{mesh_source} provides a runtime Gmsh mesh in process_simulation, "
            "but flow solver 'modflownwt' still supports only the structured "
            "sgrid backend. Use 'modflow6' (or 'boussinesq') with the same "
            f"{mesh_source} block, or remove {mesh_source} and configure "
            "[modflownwt.sgrid.planar] instead."
        )

    def _save_run_artifacts(self, run_state: LauncherRunState, wall_seconds: float) -> None:
        """Save config snapshot and metrics into the run output folder."""
        run_id = run_state.setup.run_id
        run_folder = run_state.setup.workspace.simulations_folder / run_id
        run_folder.mkdir(parents=True, exist_ok=True)

        # Config snapshot
        snapshot_path = run_folder / "_config_snapshot.toml"
        try:
            import tomli_w
            snapshot_path.write_bytes(tomli_w.dumps(run_state.raw_toml).encode())
        except Exception:
            pass

        # Metrics
        metrics_path = run_folder / "_metrics.json"
        solvers_used = [
            r.solver for r in (run_state.execution.simulation_plan.runs if run_state.execution.simulation_plan else ())
        ]
        metrics = {
            "wall_time_seconds": round(wall_seconds, 2),
            "solvers": solvers_used,
            "success": True,
        }
        mesh_summary = run_state.setup.mesh_summary
        if isinstance(mesh_summary, dict):
            metrics["mesh_constraints_mode"] = mesh_summary.get("constraints_mode")
            metrics["mesh_output_mesh"] = mesh_summary.get("output_mesh")
            metrics["mesh_output_summary_json"] = mesh_summary.get(
                "output_summary_json"
            )
            metrics["mesh_output_figure"] = mesh_summary.get("output_figure")
            metrics["mesh_output_exchange_bundle_dir"] = mesh_summary.get(
                "output_exchange_bundle_dir"
            )
        try:
            metrics_path.write_text(json.dumps(metrics, indent=2))
        except Exception:
            pass

        gallery_cfg = getattr(run_state.cfg, "capability_gallery", None)
        if gallery_cfg is not None and getattr(gallery_cfg, "enabled", False):
            manifest = publish_run_to_capability_gallery(
                run_id=str(run_id),
                run_folder=run_folder,
                config=gallery_cfg,
                solvers=tuple(str(solver) for solver in solvers_used),
            )
            if manifest is not None:
                metrics["capability_gallery_manifest"] = manifest
                try:
                    metrics_path.write_text(json.dumps(metrics, indent=2))
                except Exception:
                    pass

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
            geographic_features=setup_state.geographic_features,
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
        setup_state.geographic_features = coerce_geographic_derived_features(
            geographic=setup_state.geographic,
        )
        if setup_state.geographic_features is None:
            raise ValueError(
                "Could not resolve geographic derived features from the runtime geographic object."
            )
        setup_state.domain_geographic = (
            setup_state.geographic_features.to_domain_geographic_context()
        )
        surface_topo = setup_state.geographic_features.surface_topo

        domain_cfg = cfg.domain
        if hasattr(domain_cfg, "model_copy"):
            domain_cfg = domain_cfg.model_copy(deep=True)
        domain_cfg = self._augment_runtime_zone_ids(domain_cfg)

        setup_state.domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=setup_state.domain,
            geographic=setup_state.domain_geographic,
        )

        # Set run_id from the simulation config.
        setup_state.run_id = cfg.simulation.run_id or "default"

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
        loader = _build_data_runtime_loader(
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

    def _run_mesh_phase(self) -> None:
        """Run the optional catchment meshing phase embedded in simulation TOML."""
        if self.mesh_section_data is None or self.mesh_constraints_mode is None:
            return
        run_state = self.run_state
        setup_state = run_state.setup
        mesh_runtime = run_single_mesh_catchment_workflow_with_runtime_artifacts(
            config_path=self.config_path,
            section_data=self.mesh_section_data,
            workspace_cfg=self.cfg.workspace,
            geographic_cfg=self.cfg.geographic,
            domain_cfg=self.cfg.domain,
            constraints_mode=self.mesh_constraints_mode,
            workspace=setup_state.workspace,
            geographic_features=setup_state.geographic_features,
            domain_geographic=setup_state.domain_geographic,
        )
        setup_state.mesh_summary = mesh_runtime.summary
        setup_state.mesh_planar = mesh_runtime.mesh_planar
        self._load_mesh_artifacts_from_summary(strict=False, preserve_preloaded=True)

    def _run_mesh_input_phase(self) -> None:
        """Load one pre-existing external mesh declared in `[mesh_input]`."""
        if self.external_mesh_input is None:
            return

        mesh_summary: dict[str, str] = {
            "mesh_source": "external_input",
        }
        mesh_path = str(self.external_mesh_input.get("mesh_path", "")).strip()
        bundle_dir = str(self.external_mesh_input.get("bundle_dir", "")).strip()
        if mesh_path != "":
            mesh_summary["output_mesh"] = mesh_path
        if bundle_dir != "":
            mesh_summary["output_exchange_bundle_dir"] = bundle_dir

        self.run_state.setup.mesh_summary = mesh_summary
        self._load_mesh_artifacts_from_summary(strict=True)

    def _load_mesh_artifacts_from_summary(
        self,
        *,
        strict: bool,
        preserve_preloaded: bool = False,
    ) -> None:
        """Populate runtime mesh objects from `setup.mesh_summary` when available."""
        setup_state = self.run_state.setup
        if not preserve_preloaded:
            setup_state.mesh_bundle = None
            setup_state.mesh_planar = None
            setup_state.mesh_support = None

        mesh_summary = setup_state.mesh_summary
        if not isinstance(mesh_summary, Mapping):
            if strict:
                raise ValueError("Mesh loading requires setup.mesh_summary to be a mapping.")
            return

        bundle_dir = str(mesh_summary.get("output_exchange_bundle_dir", "")).strip()
        if bundle_dir != "" and setup_state.mesh_bundle is None:
            setup_state.mesh_bundle = load_catchment_mesh_bundle(bundle_dir)
        if setup_state.mesh_bundle is not None and setup_state.mesh_support is None:
            setup_state.mesh_support = build_gmsh_support_metadata(setup_state.mesh_bundle)
            if isinstance(mesh_summary, dict):
                mesh_summary.setdefault(
                    "output_mesh",
                    str(setup_state.mesh_bundle.mesh_path),
                )

        mesh_path = str(mesh_summary.get("output_mesh", "")).strip()
        if mesh_path == "":
            if strict and setup_state.mesh_bundle is None and setup_state.mesh_planar is None:
                raise ValueError(
                    "Mesh loading requires one 'output_mesh' path or "
                    "'output_exchange_bundle_dir' in setup.mesh_summary."
                )
            return

        mesh_path_obj = Path(mesh_path).expanduser()
        if not strict and not mesh_path_obj.exists():
            return
        if setup_state.mesh_planar is None:
            setup_state.mesh_planar = load_planar_mesh(mesh_path_obj)

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
