"""Adapter for the ``transport/modpath`` solver pair."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.simulation.adapters.transport.common import required_flow_model
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import Modpath


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs."""

    process_type = "transport"
    solver_name = "modpath"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Modpath particle-tracking run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        model_modpath = Modpath(
            state.setup.domain,
            state.setup.transport,
            flow_model,
            model_folder=state.setup.workspace.solver_scratch_folder,
            model_name=flow_model.model_name,
            bin_path=state.setup.workspace.bin_path,
        )
        model_modpath.pre_processing()
        success = model_modpath.processing(write_model=True, run_model=True)
        if not success:
            raise RuntimeError(
                f"Transport solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
                f"See {getattr(model_modpath, 'full_path', '<unknown>')} for diagnostics."
            )
        # Legacy post_processing / filt_processing skipped:
        # ModpathOutputAdapter.extract() reads pathlines/endpoints into
        # the SimulationCatalog (Zarr).  Shapefile generation is no longer needed.
        return RunExecutionResult(
            primary_model=model_modpath,
            solver_output_dir=Path(model_modpath.full_path)
            if hasattr(model_modpath, "full_path")
            else None,
        )
