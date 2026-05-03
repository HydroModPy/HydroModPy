"""Adapter for the ``transport/modpath`` solver pair."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.simulation.adapters.transport_helpers import required_flow_model
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow_nwt.modpath import Modpath


class ModpathTransportAdapter:
    """Adapter for ``transport/modpath`` runs."""

    process_type = "transport"
    solver_name = "modpath"
    requires: tuple[tuple[str, str], ...] = (("flow", "modflownwt"),)

    def validate(self, ctx: RunContext) -> None:
        """No precondition checks for Modpath transport runs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Remove the scratch directory written by this run, if any."""
        solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)
        if solver_output_dir is not None:
            cleanup_solver_files(solver_output_dir)

    def extract_calibration_series(
        self,
        ctx: RunContext,
        store: Any,
        *,
        variable: str,
        station_cells: Mapping[str, tuple[int, int, int]] | None = None,
        time_index: pd.DatetimeIndex | None = None,
    ) -> pd.Series:
        """Fail explicitly because particle calibration is not implemented."""
        del ctx, store, station_cells, time_index
        raise NotImplementedError(
            f"MODPATH calibration extraction is not implemented for {variable!r}."
        )

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Instantiate and execute one Modpath particle-tracking run."""

        state = ctx.state
        flow_model = required_flow_model(ctx)
        _restore_seepage_clip_raster(ctx, flow_model)
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
            raise SolverDivergedError(
                f"[HMPY.E401] Transport solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
                f"See {getattr(model_modpath, 'full_path', '<unknown>')} for diagnostics.",
                run_id=ctx.run.id,
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


def _configured_zone_partic(transport: Any) -> str | None:
    modpath = getattr(transport, "modpath", None)
    parameters = getattr(modpath, "parameters", None)
    if isinstance(parameters, Mapping):
        value = parameters.get("zone_partic")
    else:
        value = getattr(parameters, "zone_partic", None)
    return None if value is None else str(value)


def _restore_seepage_clip_raster(ctx: RunContext, flow_model: Any) -> None:
    """Write the MODPATH seepage raster from the store when requested."""
    if _configured_zone_partic(ctx.state.setup.transport) != "seepage_clip":
        return

    store = getattr(ctx.state, "store", None)
    sim_id = getattr(ctx.state, "sim_id", None)
    base_raster = getattr(flow_model, "dem_watershed_path", None)
    full_path = getattr(flow_model, "full_path", None)
    if store is None or sim_id is None or base_raster is None or full_path is None:
        return

    base_path = Path(base_raster)
    if not base_path.is_file():
        return

    seepage_tif = Path(full_path) / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    if seepage_tif.is_file():
        return

    seepage = np.asarray(store.query_field(str(sim_id), "seepage_mask", 0), dtype=float).ravel()
    with rasterio.open(base_path) as src:
        seepage_array = seepage.reshape(src.height, src.width)
    seepage_tif.parent.mkdir(parents=True, exist_ok=True)
    export_tif(str(base_path), seepage_array, str(seepage_tif), -9999.0)
