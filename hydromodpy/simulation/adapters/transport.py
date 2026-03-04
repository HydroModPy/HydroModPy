"""Adapters for transport-family simulation runs."""

from __future__ import annotations

from hydromodpy.simulation.adapters.base import transport_output_suffix
from hydromodpy.simulation.runtime import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import Modpath, Mt3dms
from hydromodpy.solver.modflow6 import Modflow6Transport


def _required_flow_model(ctx: RunContext):
    """Return the single flow dependency required by current transport adapters."""

    if len(ctx.dependency_models) != 1:
        raise ValueError(
            f"Process run '{ctx.run.id}' expected exactly one flow dependency, "
            f"got {len(ctx.dependency_models)}."
        )
    return ctx.dependency_models[0]


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs."""

    process_type = "transport"
    solver_name = "modpath"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Modpath particle-tracking run."""

        state = ctx.state
        flow_model = _required_flow_model(ctx)
        model_modpath = Modpath(
            state.domain,
            state.transport,
            flow_model,
            model_folder=state.workspace.simulations_folder,
            model_name=flow_model.model_name,
            bin_path=state.workspace.bin_path,
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
        return RunExecutionResult(primary_model=model_modpath)


class Mt3dmsTransportAdapter:
    """Adapter for ``transport/mt3dms`` runs."""

    process_type = "transport"
    solver_name = "mt3dms"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MT3DMS concentration transport run."""

        state = ctx.state
        flow_model = _required_flow_model(ctx)
        model_transport = Mt3dms(
            state.domain,
            state.transport,
            flow_model,
            model_folder=state.workspace.simulations_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
            bin_path=state.workspace.bin_path,
        )
        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)
        return RunExecutionResult(primary_model=model_transport)


class Modflow6GwtTransportAdapter:
    """Adapter for ``transport/modflow6gwt`` runs."""

    process_type = "transport"
    solver_name = "modflow6gwt"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one MODFLOW 6 GWT concentration run."""

        state = ctx.state
        flow_model = _required_flow_model(ctx)
        model_transport = Modflow6Transport(
            state.domain,
            state.transport,
            flow_model,
            model_folder=state.workspace.simulations_folder,
            model_name=flow_model.model_name,
            suffix_name=transport_output_suffix(ctx.plan, ctx.run),
        )
        model_transport.pre_processing()
        model_transport.processing(write_model=True, run_model=True, verbose=True)
        model_transport.post_processing(model_transport)
        return RunExecutionResult(primary_model=model_transport)
