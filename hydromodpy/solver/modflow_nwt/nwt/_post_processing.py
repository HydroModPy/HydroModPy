"""Post-processing pipeline for MODFLOW-NWT outputs.

Reads heads / budget files, derives the standard maps (water table,
seepage areas, drain outflow, persistency, intermittency) and
exports them as TIFFs. Operates in place on the solver instance.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np
import rasterio
from tqdm import tqdm

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common import masstransfer
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions
from hydromodpy.solver.modflow_nwt.common.binary_reader import (
    open_cell_budget_file,
    open_head_file,
)

from .intermittency import export_intermittency
from .postprocess import (
    NODATA,
    compute_groundwater_flux,
    compute_groundwater_storage,
    compute_outflow_drain,
    compute_outlet_discharge_east_side_m3_s,
    compute_seepage_areas,
    compute_watertable_depth,
    compute_watertable_elevation,
)

if TYPE_CHECKING:
    from .nwt_solver import ModflowNwt

logger = get_logger(__name__)


def setup_postprocess_folders(solver: ModflowNwt) -> None:
    """Create the output folder hierarchy for post-processing artefacts."""
    solver.save_file = os.path.join(solver.full_path, "_postprocess")
    create_folder(solver.save_file)

    solver.figure_file = os.path.join(solver.full_path, "_postprocess", "_figures")
    create_folder(solver.figure_file)

    solver.temporary_file = os.path.join(solver.full_path, "_postprocess", "_temporary")
    create_folder(solver.temporary_file)

    solver.tifs_file = os.path.join(solver.full_path, "_postprocess", "_rasters")
    create_folder(solver.tifs_file)

    solver.save_fig = os.path.join(solver.model_folder, "_figures")
    create_folder(solver.save_fig)


def _initialize_result_dictionaries(solver: ModflowNwt) -> None:
    """Reset the per-stress-period output dictionaries."""
    solver.dict_watertable_elevation = {}
    solver.dict_watertable_depth = {}
    solver.dict_seepage_areas = {}
    solver.dict_outflow_drain = {}
    solver.dict_outlet_discharge_east_side_m3_s = {}
    solver.dict_groundwater_flux = {}
    solver.dict_specific_discharge = {}
    solver.dict_accumulation_flux = {}
    solver.dict_groundwater_storage = {}
    solver.dict_persistency_index = {}
    solver.dict_intermittency_yearly = {}
    solver.dict_intermittency_monthly = {}
    solver.dict_intermittency_weekly = {}
    solver.dict_intermittency_daily = {}


def _process_one_period(
    solver: ModflowNwt,
    options: ModflowPostprocessOptions,
    *,
    item: int,
    time: float,
    inactive_mask: np.ndarray,
) -> None:
    """Compute and export the products requested for one stress period."""
    if len(solver.times) == 1:
        solver.kstpkper = solver.kstpkpers[0]
    else:
        solver.kstpkper = (solver.kstp[item], solver.kper[item])

    lead_numb = str(item)
    do_export_tif = options.export_all_tif or (item == 0)

    solver.head = solver.head_fpu.get_data(totim=time)

    if options.watertable_elevation:
        solver.wt_elev = compute_watertable_elevation(solver.head, solver.nlay)
        solver.wt_elev[inactive_mask] = NODATA
        output_path = solver.tifs_file + f"/watertable_elevation_t({lead_numb}).tif"
        if do_export_tif:
            export_tif(solver.dem_watershed_path, solver.wt_elev, output_path, NODATA)
        solver.dict_watertable_elevation[item] = solver.wt_elev

    if options.watertable_depth:
        solver.wt_depth = compute_watertable_depth(
            solver.wt_elev, solver.top_elevation, inactive_mask
        )
        output_path = solver.tifs_file + f"/watertable_depth_t({lead_numb}).tif"
        if do_export_tif:
            export_tif(solver.dem_watershed_path, solver.wt_depth, output_path, NODATA)
        solver.dict_watertable_depth[item] = solver.wt_depth

    if options.seepage_areas:
        solver.seep_area = compute_seepage_areas(
            solver.wt_elev, solver.top_elevation, inactive_mask
        )
        output_path = solver.tifs_file + f"/seepage_areas_t({lead_numb}).tif"
        if do_export_tif:
            export_tif(solver.dem_watershed_path, solver.seep_area, output_path, NODATA)
        solver.dict_seepage_areas[item] = solver.seep_area

    if options.outflow_drain:
        solver.drain = solver.cbb.get_data(text="DRAINS", kstpkper=solver.kstpkper, totim=time)
        solver.out_drn = compute_outflow_drain(
            solver.drain,
            solver.drain_array,
            solver.dis.nrow,
            solver.dis.ncol,
            inactive_mask,
        )
        output_path = solver.tifs_file + f"/outflow_drain_t({lead_numb}).tif"
        if options.accumulation_flux or do_export_tif:
            export_tif(solver.dem_watershed_path, solver.out_drn, output_path, NODATA)
        solver.dict_outflow_drain[item] = solver.out_drn

    if options.outlet_discharge_east_side_m3_s:
        try:
            constant_head = solver.cbb.get_data(
                text="CONSTANT HEAD",
                kstpkper=solver.kstpkper,
                totim=time,
            )
        except Exception as exc:
            message = str(exc).lower()
            if "text string is not in the budget file" in message:
                constant_head = None
            else:
                raise
        outlet_discharge_m3_s = compute_outlet_discharge_east_side_m3_s(
            constant_head,
            nrow=solver.dis.nrow,
            ncol=solver.dis.ncol,
        )
        solver.dict_outlet_discharge_east_side_m3_s[item] = np.asarray(
            [outlet_discharge_m3_s],
            dtype=float,
        )

    if options.groundwater_flux:
        solver.flux_top = compute_groundwater_flux(
            solver.cbb, solver.kstpkper, time, solver.nlay, inactive_mask
        )
        output_path = solver.tifs_file + f"/groundwater_flux_t({lead_numb}).tif"
        if do_export_tif:
            export_tif(solver.dem_watershed_path, solver.flux_top, output_path, NODATA)
        solver.dict_groundwater_flux[item] = solver.flux_top

    if options.groundwater_storage:
        solver.wt_sto = compute_groundwater_storage(
            solver.wt_elev,
            solver.zbot,
            solver.sy,
            solver.top_elevation,
            cell_area=float(solver.cell_area),
        )
        output_path = solver.tifs_file + f"/groundwater_storage_t({lead_numb}).tif"
        if do_export_tif:
            export_tif(solver.dem_watershed_path, solver.wt_sto, output_path, NODATA)
        solver.dict_groundwater_storage[item] = solver.wt_sto

    if options.accumulation_flux:
        routing_ctx = solver._ensure_solver_routing_context()
        accumulated_flow = masstransfer.Masstransfer(
            solver.geographic,
            f"outflow_drain_t({lead_numb}).tif",
            f"tracept_t({lead_numb}).shp",
            f"accumulation_flux_t({lead_numb}).tif",
            extraction_folder=solver.save_file,
            routing_fill_path=routing_ctx.correc_path,
            routing_direc_path=routing_ctx.direc_path,
        )
        accumulated_flow.trace_cumulated()
        output_path = solver.tifs_file + f"/accumulation_flux_t({lead_numb}).tif"
        with rasterio.open(output_path) as src:
            solver.dict_accumulation_flux[item] = src.read(1)


def _export_persistency_index(solver: ModflowNwt, inactive_mask: np.ndarray) -> None:
    """Compute and export the persistency index map across all stress periods."""
    if not solver.dict_accumulation_flux:
        return
    logger.info("Exporting persistency index maps")
    acc_npy_raw = solver.dict_accumulation_flux
    acc_npy = list(acc_npy_raw.items())[:]
    mask = inactive_mask
    for key in range(len(acc_npy)):
        acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=mask)
    zero = acc_npy_raw[0] * 0
    for i in range(len(acc_npy)):
        tempo = acc_npy[i].copy()
        tempo[tempo > 0] = 1
        zero = zero + tempo
    days_flux = zero.copy() / len(acc_npy)
    pi_export = days_flux.copy()
    solver.pi = np.ma.masked_where(days_flux <= 0, days_flux)
    solver.dict_persistency_index[0] = solver.pi
    pi_export[days_flux <= 0] = NODATA
    pi_export[mask] = NODATA
    output_path = solver.tifs_file + "/persistency_index_t(-).tif"
    export_tif(solver.dem_watershed_path, pi_export, output_path, NODATA)


def _export_intermittencies(
    solver: ModflowNwt,
    options: ModflowPostprocessOptions,
) -> None:
    """Export the four intermittency rasters when requested by the options."""
    any_intermittency = (
        options.intermittency_daily
        or options.intermittency_weekly
        or options.intermittency_monthly
        or options.intermittency_yearly
    )
    acc_npy_raw = (
        solver.dict_accumulation_flux
        if (any_intermittency and solver.dict_accumulation_flux)
        else None
    )
    if acc_npy_raw is None:
        return

    if options.intermittency_daily:
        export_intermittency(
            label="daily",
            window_size=365,
            acc_npy_raw=acc_npy_raw,
            result_dict=solver.dict_intermittency_daily,
            tifs_file=solver.tifs_file,
            watershed_dem=solver.dem_watershed_path,
        )
    if options.intermittency_weekly:
        export_intermittency(
            label="weekly",
            window_size=52,
            acc_npy_raw=acc_npy_raw,
            result_dict=solver.dict_intermittency_weekly,
            tifs_file=solver.tifs_file,
            watershed_dem=solver.dem_watershed_path,
        )
    if options.intermittency_monthly:
        export_intermittency(
            label="monthly",
            window_size=12,
            acc_npy_raw=acc_npy_raw,
            result_dict=solver.dict_intermittency_monthly,
            tifs_file=solver.tifs_file,
            watershed_dem=solver.dem_watershed_path,
        )
    if options.intermittency_yearly:
        export_intermittency(
            label="yearly",
            window_size=1,
            acc_npy_raw=acc_npy_raw,
            result_dict=solver.dict_intermittency_yearly,
            tifs_file=solver.tifs_file,
            watershed_dem=solver.dem_watershed_path,
        )


def run_post_processing(
    solver: ModflowNwt,
    options: ModflowPostprocessOptions,
) -> None:
    """Run the full MODFLOW-NWT post-processing pipeline on ``solver``."""
    setup_postprocess_folders(solver)

    solver.path_file = os.path.join(solver.full_path, solver.model_name)

    if not hasattr(solver, "inactive_mask"):
        raise ValueError("inactive_mask must be set before MODFLOW post-processing.")
    inactive_mask = np.asarray(solver.inactive_mask, dtype=bool)

    solver.head_fpu = open_head_file(solver.path_file + ".hds", precision="single")
    solver.cbb = open_cell_budget_file(solver.path_file + ".cbc", precision="single")

    solver.times = solver.head_fpu.get_times()
    solver.kstpkpers = solver.head_fpu.get_kstpkper()

    solver.nper = solver.dis.nper
    solver.kper = np.arange(0, solver.nper, 1)
    if len(solver.kper) > 1:
        solver.kstp = solver.nstp[solver.kper] - 1

    _initialize_result_dictionaries(solver)

    logger.debug("Post-processing MODFLOW: %s", solver.model_name)

    for item, time in enumerate(
        tqdm(
            solver.times,
            desc="[INFO] Post-processing",
            unit="sp",
            disable=len(solver.times) <= 1,
        )
    ):
        _process_one_period(
            solver,
            options,
            item=item,
            time=time,
            inactive_mask=inactive_mask,
        )

    if options.persistency_index:
        _export_persistency_index(solver, inactive_mask)

    _export_intermittencies(solver, options)


__all__ = ["run_post_processing", "setup_postprocess_folders"]
