"""HydroModPy launcher with legacy and simulation-plan execution modes."""

from __future__ import annotations

import os
import pickle
import tomllib
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import DataManagers
from hydromodpy.data_managers.geology.geology_field import GeologyField
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.domain import Domain
from hydromodpy.process import Flow, Transport
from hydromodpy.simulation import ProcessRun, SimulationPlan, SimulationPlanner
from hydromodpy.solver import SolverEngine
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
    Mt3dms,
)
from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.watershed.climatic import Climatic
from hydromodpy.watershed.settings import Settings
from launchers.hook_registry import HookRegistry
from launchers.run_result import RunResult


class HydroModPyLauncher:
    """Orchestrates the HydroModPy pipeline driven by a TOML configuration file."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # HYDROMODPY_OUT_PATH allows redirecting outputs without editing config.toml.
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

        with self.config_path.open("rb") as fh:
            raw_toml = tomllib.load(fh)

        self.result = RunResult(cfg=self.cfg, config_path=self.config_path, raw_toml=raw_toml)
        self.hooks = HookRegistry.discover(self.config_path)

    def run(self) -> RunResult:
        """Execute the pipeline and return the populated result object."""
        if self.cfg.simulation.has_processes():
            planner = SimulationPlanner()
            plan = planner.build(self.cfg.simulation)
            self.result.simulation_plan = plan
            self.result.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._run_data()

        if self.result.simulation_plan and not self.result.simulation_plan.is_empty():
            self._run_simulation_plan(self.result.simulation_plan)
        else:
            self._run_legacy_processes()

        return self.result

    def _run_setup(self) -> None:
        """Initialise the shared structural objects used by later phases."""
        r = self.result
        cfg = self.cfg

        self.hooks.call("on_before_setup", r)

        r.workspace = hmp.Workspace(config=cfg.workspace)
        r.geographic = hmp.Geographic(cfg.geographic, r.workspace)
        surface_topo = r.geographic.get_domain_surface_topo()

        r.domain = Domain(config=cfg.domain, surface_topo=surface_topo)
        if "geology" in DataManagers.from_config(cfg.data).types:
            geology = GeologyField.from_watershed_config(
                cfg.data.geology, raster_support=surface_topo.support
            )
            r.domain.set_zone("geology", geology)

        r.flow = Flow(config=cfg.flow)
        r.settings = Settings()
        r.transport = Transport(config=cfg.transport)

        self.hooks.call("on_after_setup", r)

    def _run_data(self) -> None:
        """Load the external forcings shared by all process runs."""
        r = self.result
        cfg = self.cfg
        ws = r.workspace

        self.hooks.call("on_before_data", r)

        r.climatic = Climatic(out_path=ws.catch_folder)

        oceanic = Oceanic()
        oceanic.extract_local_data(
            out_path=ws.catch_folder,
            geographic=r.geographic,
            oceanic_path=cfg.workspace.data_path,
        )
        oceanic.update_MSL(oceanic.fetch_msl_or_default(r.geographic))
        r.oceanic = oceanic

        if "ocean" in r.flow.boundary_conditions:
            r.flow.boundary_conditions["ocean"].value = oceanic.MSL

        self.hooks.call("on_after_data", r)

    def _run_legacy_processes(self) -> None:
        """Execute the historical fixed phase order."""
        flow_solver = self._legacy_flow_solver_name()

        self.hooks.call("on_before_flow", self.result)
        flow_model = self._run_flow_solver(flow_solver)
        self.hooks.call("on_after_flow", self.result)

        self.hooks.call("on_before_particles", self.result)
        if flow_solver == "modflownwt":
            self._run_particles_solver("modpath", flow_model)
        self.hooks.call("on_after_particles", self.result)

        self.hooks.call("on_before_transport", self.result)
        transport_solver = "mt3dms" if flow_solver == "modflownwt" else "modflow6gwt"
        self._run_transport_solver(transport_solver, flow_model)
        self.hooks.call("on_after_transport", self.result)

    def _run_simulation_plan(self, plan: SimulationPlan) -> None:
        """Execute the resolved process runs in declared order."""
        current_process_type: str | None = None

        for run in plan.runs:
            if run.process_type != current_process_type:
                if current_process_type is not None:
                    self._call_process_hook("after", current_process_type)
                self._call_process_hook("before", run.process_type)
                current_process_type = run.process_type

            self._run_process_run(run)

        if current_process_type is not None:
            self._call_process_hook("after", current_process_type)

    def _call_process_hook(self, moment: str, process_type: str) -> None:
        """Call the legacy hook naming scheme for the given process type."""
        self.hooks.call(f"on_{moment}_{process_type}", self.result)

    def _run_process_run(self, run: ProcessRun) -> None:
        """Dispatch one resolved process run to the matching implementation."""
        if run.process_type == "flow":
            self._run_flow_solver(run.solver, run=run)
            return

        if run.process_type == "particles":
            flow_model = self._resolve_required_flow_model(run)
            self._run_particles_solver(run.solver, flow_model, run=run)
            return

        if run.process_type == "transport":
            flow_model = self._resolve_required_flow_model(run)
            self._run_transport_solver(run.solver, flow_model, run=run)
            return

        raise ValueError(f"Unsupported simulation process type '{run.process_type}'.")

    def _resolve_required_flow_model(self, run: ProcessRun):
        """Return the flow model required by a downstream process run."""
        if len(run.depends_on) != 1:
            raise ValueError(
                f"Process run '{run.id}' expected exactly one flow dependency, "
                f"got {len(run.depends_on)}."
            )

        dependency_id = run.depends_on[0]
        if dependency_id not in self.result.models_by_run_id:
            raise ValueError(
                f"Process run '{run.id}' depends on '{dependency_id}', "
                "but that run has not produced a model yet."
            )

        return self.result.models_by_run_id[dependency_id]

    def _legacy_flow_solver_name(self) -> str:
        """Return the legacy flow solver name from the global solver config."""
        if self.cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
            return "modflownwt"
        return "modflow6"

    def _build_preprocess_options(self) -> ModflowPreprocessOptions:
        """Create the common flow pre-processing options."""
        settings = self.result.settings
        return ModflowPreprocessOptions(
            box=settings.box,
            sink_fill=settings.sink_fill,
            check_grid=settings.check_grid,
            plot_cross=settings.plot_cross,
            cross_ylim=tuple(settings.cross_ylim) if settings.cross_ylim else None,
        )

    def _flow_model_name(self, run: ProcessRun | None) -> str:
        """Return a stable model name for the flow solver run."""
        base_name = self.result.settings.model_name
        if run is None or self._has_single_process_run("flow"):
            return base_name
        return f"{base_name}_{self._run_label(run)}"

    def _transport_suffix(self, run: ProcessRun | None) -> str:
        """Return a stable transport suffix for the solver run."""
        if run is None or self._has_single_process_run("transport"):
            return "_mt_s1"
        return f"_mt_{self._run_label(run)}"

    def _has_single_process_run(self, process_type: str) -> bool:
        """Return True when the simulation plan contains exactly one run of one type."""
        plan = self.result.simulation_plan
        if plan is None:
            return False
        return sum(1 for run in plan.runs if run.process_type == process_type) == 1

    def _run_label(self, run: ProcessRun) -> str:
        """Return a short, stable label for one planned process run."""
        plan = self.result.simulation_plan
        if plan is None:
            return run.process_id

        same_type_runs = [planned for planned in plan.runs if planned.process_type == run.process_type]
        for index, planned in enumerate(same_type_runs, start=1):
            if planned.id == run.id:
                prefix = {
                    "flow": "f",
                    "particles": "p",
                    "transport": "t",
                }.get(run.process_type, "r")
                return f"{prefix}{index}"

        # Fallback for defensive robustness if the plan changed unexpectedly.
        return run.process_id

    def _run_flow_solver(self, solver_name: str, run: ProcessRun | None = None):
        """Build, run, and record one flow solver instance."""
        r = self.result
        ws = r.workspace
        preprocess_options = self._build_preprocess_options()
        model_name = self._flow_model_name(run)

        if solver_name == "modflownwt":
            model_modflow = Modflow(
                r.geographic,
                model_folder=ws.simulations_folder,
                model_name=model_name,
                bin_path=ws.bin_path,
                modflow_config=self.cfg.modflownwt,
                preprocess_options=preprocess_options,
            )
        elif solver_name == "modflow6":
            model_modflow = Modflow6(
                r.geographic,
                model_folder=ws.simulations_folder,
                model_name=model_name,
                bin_path=ws.bin_path,
                modflow_config=self.cfg.modflow6,
                preprocess_options=preprocess_options,
            )
        else:
            raise ValueError(f"Unsupported flow solver '{solver_name}'.")

        model_modflow.pre_processing(
            flow=r.flow,
            domain=r.domain,
            options=preprocess_options,
        )

        pickle_path = (
            Path(ws.simulations_folder)
            / model_name
            / f"results_{model_name}.pkl"
        )
        pickle_path.parent.mkdir(parents=True, exist_ok=True)
        with pickle_path.open("wb") as fh:
            pickle.dump(
                {
                    "list_model_name": [model_name],
                    "list_model_modflow": [model_modflow],
                },
                fh,
            )

        success = model_modflow.processing(
            options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
        )
        if success:
            model_modflow.post_processing(
                options=ModflowPostprocessOptions(
                    watertable_elevation=True,
                    watertable_depth=True,
                    seepage_areas=True,
                    outflow_drain=True,
                    accumulation_flux=True,
                    intermittency_monthly=True,
                )
            )

        r.model_modflow = model_modflow
        if run is not None:
            r.models_by_run_id[run.id] = model_modflow

        return model_modflow

    def _run_particles_solver(
        self,
        solver_name: str,
        flow_model,
        run: ProcessRun | None = None,
    ):
        """Build, run, and record one particle-tracking solver instance."""
        if solver_name != "modpath":
            raise ValueError(f"Unsupported particles solver '{solver_name}'.")

        r = self.result
        ws = r.workspace
        model_modpath = Modpath(
            r.domain,
            r.transport,
            flow_model,
            model_folder=ws.simulations_folder,
            model_name=flow_model.model_name,
            bin_path=ws.bin_path,
        )
        model_modpath.pre_processing()
        model_modpath.processing(write_model=True, run_model=True)
        model_modpath.post_processing(
            model_modpath,
            ending_point=True,
            starting_point=True,
            pathlines_shp=True,
            particles_shp=True,
            random_id=None,
        )
        model_modpath.filt_processing(
            model_modpath,
            norm_flux=True,
            filt_time=True,
            filt_seep=True,
            filt_inout=True,
            calc_rtd=False,
            random_id=None,
        )

        r.model_modpath = model_modpath
        if run is not None:
            r.models_by_run_id[run.id] = model_modpath

        return model_modpath

    def _run_transport_solver(
        self,
        solver_name: str,
        flow_model,
        run: ProcessRun | None = None,
    ):
        """Build, run, and record one transport solver instance."""
        r = self.result
        ws = r.workspace
        suffix_name = self._transport_suffix(run)

        if solver_name == "mt3dms":
            model_transport = Mt3dms(
                r.domain,
                r.transport,
                flow_model,
                model_folder=ws.simulations_folder,
                model_name=flow_model.model_name,
                suffix_name=suffix_name,
                bin_path=ws.bin_path,
            )
        elif solver_name == "modflow6gwt":
            model_transport = Modflow6Transport(
                r.domain,
                r.transport,
                flow_model,
                model_folder=ws.simulations_folder,
                model_name=flow_model.model_name,
                suffix_name=suffix_name,
            )
        else:
            raise ValueError(f"Unsupported transport solver '{solver_name}'.")

        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)

        r.model_transport = model_transport
        if run is not None:
            r.models_by_run_id[run.id] = model_transport

        return model_transport
