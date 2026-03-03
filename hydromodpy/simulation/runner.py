"""Execute a resolved ``SimulationPlan`` against a prepared runtime state.

The runner receives a flat, already-validated plan from
``hydromodpy.simulation.planner``. Its responsibility is operational rather
than declarative:

- select the concrete solver implementation for each planned run,
- recover the exact upstream model referenced by ``depends_on``,
- apply deterministic model names and suffixes,
- record produced models back into ``state.models_by_run_id`` for later runs.

Keeping this logic separate from the planner avoids mixing dependency
validation with side effects, file-system writes, and solver API calls.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
    Mt3dms,
)
from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport


class SimulationState(Protocol):
    """Minimal mutable state required by ``SimulationRunner``.

    The runner intentionally depends on a protocol instead of a concrete class:
    launcher code can provide any state object that exposes these attributes,
    while tests can substitute lightweight doubles.
    """

    cfg: Any
    workspace: Any
    settings: Any
    geographic: Any
    flow: Any
    domain: Any
    transport: Any
    model_modflow: Any
    model_modpath: Any
    model_transport: Any
    models_by_run_id: dict[str, Any]


@dataclass(frozen=True)
class ProcessCallbacks:
    """Optional hooks fired when the runner enters or leaves a process family.

    These callbacks are coarse-grained on purpose: they are triggered once per
    contiguous block of runs with the same ``process_type``, not once per solver
    execution.
    """

    before_process: Callable[[str], None] | None = None
    after_process: Callable[[str], None] | None = None


class SimulationRunner:
    """Sequentially execute a resolved plan and persist each produced model."""

    def __init__(self, callbacks: ProcessCallbacks | None = None) -> None:
        self.callbacks = callbacks or ProcessCallbacks()

    def execute(self, plan: SimulationPlan, state: SimulationState) -> None:
        """Execute each planned run in order against ``state``.

        The plan is assumed to be pre-validated by ``SimulationPlanner``.
        This method therefore focuses on process-family transitions and runtime
        dispatch, not on rebuilding dependencies.
        """
        current_process_type: str | None = None

        for run in plan.runs:
            # Group callbacks by contiguous process-family blocks so repeated
            # solver runs inside the same family do not retrigger setup/teardown.
            if run.process_type != current_process_type:
                if current_process_type is not None:
                    self._call_after_process(current_process_type)
                self._call_before_process(run.process_type)
                current_process_type = run.process_type

            self._run_process_run(plan, state, run)

        if current_process_type is not None:
            self._call_after_process(current_process_type)

    def _call_before_process(self, process_type: str) -> None:
        """Invoke the optional before-process callback."""
        if self.callbacks.before_process is not None:
            self.callbacks.before_process(process_type)

    def _call_after_process(self, process_type: str) -> None:
        """Invoke the optional after-process callback."""
        if self.callbacks.after_process is not None:
            self.callbacks.after_process(process_type)

    def _run_process_run(
        self,
        plan: SimulationPlan,
        state: SimulationState,
        run: ProcessRun,
    ) -> None:
        """Dispatch one resolved process run to the matching implementation."""
        if run.process_type == "flow":
            self._run_flow_solver(plan, state, run)
            return

        if run.process_type == "transport":
            # Transport runs consume the concrete flow model selected by the
            # planner through ``depends_on``.
            flow_model = self._resolve_required_flow_model(state, run)
            self._run_transport_solver(plan, state, run, flow_model)
            return

        raise ValueError(f"Unsupported simulation process type '{run.process_type}'.")

    def _resolve_required_flow_model(self, state: SimulationState, run: ProcessRun):
        """Return the flow model produced by the declared dependency of *run*."""
        if len(run.depends_on) != 1:
            raise ValueError(
                f"Process run '{run.id}' expected exactly one flow dependency, "
                f"got {len(run.depends_on)}."
            )

        # Dependencies point to the exact upstream run id, not to a generic
        # "latest flow model", which keeps multi-run plans deterministic.
        dependency_id = run.depends_on[0]
        if dependency_id not in state.models_by_run_id:
            raise ValueError(
                f"Process run '{run.id}' depends on '{dependency_id}', "
                "but that run has not produced a model yet."
            )

        return state.models_by_run_id[dependency_id]

    def _build_preprocess_options(self, state: SimulationState) -> ModflowPreprocessOptions:
        """Build the common flow pre-processing options from the prepared settings."""
        settings = state.settings
        # Centralize the mapping from launcher settings to solver options so
        # both flow backends receive the same pre-processing contract.
        return ModflowPreprocessOptions(
            box=settings.box,
            sink_fill=settings.sink_fill,
            check_grid=settings.check_grid,
            plot_cross=settings.plot_cross,
            cross_ylim=tuple(settings.cross_ylim) if settings.cross_ylim else None,
        )

    def _flow_model_name(
        self,
        plan: SimulationPlan,
        state: SimulationState,
        run: ProcessRun,
    ) -> str:
        """Return the stable model name used for one flow run."""
        base_name = state.settings.model_name
        # Keep the base model name when only one flow run is planned.
        if self._has_single_process_run(plan, "flow"):
            return base_name
        return f"{base_name}_{self._run_label(plan, run)}"

    def _transport_suffix(self, plan: SimulationPlan, run: ProcessRun) -> str:
        """Return the stable suffix used by concentration transport runs."""
        concentration_runs = self._concentration_transport_runs(plan)
        for index, planned in enumerate(concentration_runs, start=1):
            if planned.id == run.id:
                return f"_mt_s{index}"
        raise ValueError(
            f"Transport run '{run.id}' is not part of the concentration transport sequence."
        )

    def _concentration_transport_runs(self, plan: SimulationPlan) -> list[ProcessRun]:
        """Return transport runs that write concentration outputs."""
        return [
            run
            for run in plan.runs
            if run.process_type == "transport" and run.solver in {"mt3dms", "modflow6gwt"}
        ]

    def _has_single_process_run(self, plan: SimulationPlan, process_type: str) -> bool:
        """Return True when *plan* contains exactly one run of *process_type*."""
        return sum(1 for run in plan.runs if run.process_type == process_type) == 1

    def _run_label(self, plan: SimulationPlan, run: ProcessRun) -> str:
        """Return a short stable label for one planned run."""
        # Labels are positional within the process family, not global across
        # the whole plan, which keeps names compact and readable.
        same_type_runs = [planned for planned in plan.runs if planned.process_type == run.process_type]
        for index, planned in enumerate(same_type_runs, start=1):
            if planned.id == run.id:
                prefix = {
                    "flow": "f",
                    "transport": "t",
                }.get(run.process_type, "r")
                return f"{prefix}{index}"

        raise ValueError(
            f"Process run '{run.id}' is not present in the provided simulation plan."
        )

    def _run_flow_solver(
        self,
        plan: SimulationPlan,
        state: SimulationState,
        run: ProcessRun,
    ):
        """Build, run, and record one flow solver instance."""
        ws = state.workspace
        preprocess_options = self._build_preprocess_options(state)
        model_name = self._flow_model_name(plan, state, run)

        # Instantiate the concrete flow backend selected by the resolved plan.
        if run.solver == "modflownwt":
            model_modflow = Modflow(
                state.geographic,
                model_folder=ws.simulations_folder,
                model_name=model_name,
                bin_path=ws.bin_path,
                modflow_config=state.cfg.modflownwt,
                preprocess_options=preprocess_options,
            )
        elif run.solver == "modflow6":
            model_modflow = Modflow6(
                state.geographic,
                model_folder=ws.simulations_folder,
                model_name=model_name,
                bin_path=ws.bin_path,
                modflow_config=state.cfg.modflow6,
                preprocess_options=preprocess_options,
            )
        else:
            raise ValueError(f"Unsupported flow solver '{run.solver}'.")

        model_modflow.pre_processing(
            flow=state.flow,
            domain=state.domain,
            options=preprocess_options,
        )

        pickle_path = Path(ws.simulations_folder) / model_name / f"results_{model_name}.pkl"
        pickle_path.parent.mkdir(parents=True, exist_ok=True)
        # Persist the pre-run model payload using the project-standard pickle
        # shape expected by downstream post-processing utilities.
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
            # Post-processing reads solver outputs, so it only makes sense after
            # a successful numerical run.
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

        state.model_modflow = model_modflow
        state.models_by_run_id[run.id] = model_modflow
        return model_modflow

    def _run_modpath_solver(
        self,
        state: SimulationState,
        run: ProcessRun,
        flow_model,
    ):
        """Build, run, and record one Modpath transport solver instance."""
        ws = state.workspace
        # Modpath reuses the flow model folder and name because it consumes the
        # already-written flow files produced by the dependency.
        model_modpath = Modpath(
            state.domain,
            state.transport,
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

        state.model_modpath = model_modpath
        state.models_by_run_id[run.id] = model_modpath
        return model_modpath

    def _run_transport_solver(
        self,
        plan: SimulationPlan,
        state: SimulationState,
        run: ProcessRun,
        flow_model,
    ):
        """Build, run, and record one transport solver instance."""
        if run.solver == "modpath":
            # Particle tracking lives in the transport family at the plan level,
            # but uses its own dedicated runtime path.
            return self._run_modpath_solver(state, run, flow_model)

        ws = state.workspace
        # Concentration solvers receive stable suffixes so multiple transport
        # runs do not overwrite one another's outputs.
        suffix_name = self._transport_suffix(plan, run)

        if run.solver == "mt3dms":
            model_transport = Mt3dms(
                state.domain,
                state.transport,
                flow_model,
                model_folder=ws.simulations_folder,
                model_name=flow_model.model_name,
                suffix_name=suffix_name,
                bin_path=ws.bin_path,
            )
        elif run.solver == "modflow6gwt":
            model_transport = Modflow6Transport(
                state.domain,
                state.transport,
                flow_model,
                model_folder=ws.simulations_folder,
                model_name=flow_model.model_name,
                suffix_name=suffix_name,
            )
        else:
            raise ValueError(f"Unsupported transport solver '{run.solver}'.")

        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)

        state.model_transport = model_transport
        state.models_by_run_id[run.id] = model_transport
        return model_transport
