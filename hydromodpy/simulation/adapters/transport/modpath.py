"""Adapter for the ``transport/modpath`` solver pair."""

from __future__ import annotations

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
            model_folder=state.setup.workspace.simulations_folder,
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
        return RunExecutionResult(primary_model=model_modpath)
