"""Per-timestep post-processing helpers for MODFLOW 6 flow and transport.

Module-level imports `bf`, `pp`, `raster_io`, `masstransfer`, `rasterio` are kept
at the package root: unit tests monkeypatch them through the dotted path
``hydromodpy.solver.modflow6.postprocess.<name>``.
"""

from __future__ import annotations

import os

import flopy.utils.binaryfile as bf
import numpy as np
import rasterio
from flopy.utils import postprocessing as pp

from hydromodpy.core.io import filesystem, raster_io
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common import masstransfer
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

from ..diagnostics import export_runtime_support_overview
from ._budget import (
    compute_chd_outlet_discharge_east_side_m3_s,
    compute_drain_outflow_and_seepage,
    east_side_cell_ids,
    get_budget_records_or_none,
    open_budget_file,
)
from ._models import (
    NODATA,
    BudgetReaderLike,
    FlowPostprocessModel,
    RoutingContextLike,
    SolverMeshLike,
    TransportPostprocessModel,
)
from ._native_mesh import (
    export_native_mesh_outputs,
    native_cell_series_payload,
    native_mesh_exports_enabled,
)
from ._unstructured import (
    accumulate_unstructured_cell_values,
    build_unstructured_cell_adjacency,
)
from ._watertable import compute_watertable_depth, compute_watertable_elevation

logger = get_logger(__name__)


def run_flow_post_processing(
    model: FlowPostprocessModel,
    options: ModflowPostprocessOptions | None = None,
) -> None:
    """Run MODFLOW 6 flow post-processing and persist the selected outputs."""
    if options is None:
        options = ModflowPostprocessOptions()
    elif not isinstance(options, ModflowPostprocessOptions):
        raise TypeError("post_processing options must be ModflowPostprocessOptions")
    model.last_postprocess_options = options

    model.save_file = os.path.join(model.full_path, "_postprocess")
    filesystem.create_folder(model.save_file)
    model.tifs_file = os.path.join(model.save_file, "_rasters")
    filesystem.create_folder(model.tifs_file)

    head_path = os.path.join(model.full_path, f"{model.model_name}.hds")
    cbc_path = os.path.join(model.full_path, f"{model.model_name}.cbc")
    head_fpu = bf.HeadFile(head_path)
    cbb = open_budget_file(cbc_path)

    times = head_fpu.get_times()
    model.times = times
    dict_watertable_elevation: dict[int, np.ndarray] = {}
    dict_watertable_depth: dict[int, np.ndarray] = {}
    dict_seepage_areas: dict[int, np.ndarray] = {}
    dict_outflow_drain: dict[int, np.ndarray] = {}
    dict_outlet_discharge_east_side_m3_s: dict[int, np.ndarray] = {}
    dict_accumulation_flux: dict[int, np.ndarray] = {}
    model.dict_watertable_elevation = dict_watertable_elevation
    model.dict_watertable_depth = dict_watertable_depth
    model.dict_seepage_areas = dict_seepage_areas
    model.dict_outflow_drain = dict_outflow_drain
    model.dict_outlet_discharge_east_side_m3_s = dict_outlet_discharge_east_side_m3_s
    model.dict_accumulation_flux = dict_accumulation_flux
    can_export_raster = bool(
        getattr(model.solver_mesh, "is_structured", False)
        and getattr(model, "dem_watershed_path", "")
    )

    ncpl = int(model.ncpl)
    dem_mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
    dem_flat = np.asarray(model.dem, dtype=float).reshape(-1)
    east_cells = east_side_cell_ids(model)

    for item, time in enumerate(times):
        head = head_fpu.get_data(totim=time)
        wt = compute_watertable_elevation(head)

        if options.watertable_elevation:
            wt_out = wt.copy()
            wt_out[dem_mask_flat] = NODATA
            dict_watertable_elevation[item] = model._to_export_array(wt_out)
            if can_export_raster and (options.export_all_tif or item == 0):
                raster_io.export_tif(
                    model.dem_watershed_path,
                    model._to_export_array(wt_out),
                    os.path.join(model.tifs_file, f"watertable_elevation_t({item}).tif"),
                    NODATA,
                )

        if options.watertable_depth:
            wtd = compute_watertable_depth(
                watertable_elevation=wt,
                dem=dem_flat,
                dem_mask=dem_mask_flat,
            )
            dict_watertable_depth[item] = model._to_export_array(wtd)
            if can_export_raster and (options.export_all_tif or item == 0):
                raster_io.export_tif(
                    model.dem_watershed_path,
                    model._to_export_array(wtd),
                    os.path.join(model.tifs_file, f"watertable_depth_t({item}).tif"),
                    NODATA,
                )

        drn = get_budget_records_or_none(cbb, kstpkper=(0, item), text="DRN")
        outflow, seepage = compute_drain_outflow_and_seepage(drn, ncpl=ncpl)
        outflow[dem_mask_flat] = NODATA
        seepage[dem_mask_flat] = NODATA

        outflow_tif_path = os.path.join(model.tifs_file, f"outflow_drain_t({item}).tif")
        if options.outflow_drain:
            dict_outflow_drain[item] = model._to_export_array(outflow)
        if options.outflow_drain or options.accumulation_flux:
            if can_export_raster and (
                options.accumulation_flux or options.export_all_tif or item == 0
            ):
                raster_io.export_tif(
                    model.dem_watershed_path,
                    model._to_export_array(outflow),
                    outflow_tif_path,
                    NODATA,
                )
        if options.seepage_areas:
            dict_seepage_areas[item] = model._to_export_array(seepage)
            if can_export_raster and (options.export_all_tif or item == 0):
                raster_io.export_tif(
                    model.dem_watershed_path,
                    model._to_export_array(seepage),
                    os.path.join(model.tifs_file, f"seepage_areas_t({item}).tif"),
                    NODATA,
                )

        if options.outlet_discharge_east_side_m3_s:
            chd = get_budget_records_or_none(cbb, kstpkper=(0, item), text="CHD")
            outlet_discharge_m3_s = compute_chd_outlet_discharge_east_side_m3_s(
                chd,
                ncpl=ncpl,
                east_side_cell_ids=east_cells,
            )
            dict_outlet_discharge_east_side_m3_s[item] = np.asarray(
                [outlet_discharge_m3_s],
                dtype=float,
            )

        if options.accumulation_flux and can_export_raster and model.solver_mesh.is_structured:
            routing_ctx = model._ensure_solver_routing_context()
            accumulated_flow = masstransfer.Masstransfer(
                model.geographic,
                f"outflow_drain_t({item}).tif",
                f"tracept_t({item}).shp",
                f"accumulation_flux_t({item}).tif",
                extraction_folder=model.save_file,
                routing_fill_path=routing_ctx.correc_path,
                routing_direc_path=routing_ctx.direc_path,
            )
            accumulated_flow.trace_cumulated()
            with rasterio.open(
                os.path.join(model.tifs_file, f"accumulation_flux_t({item}).tif")
            ) as src:
                dict_accumulation_flux[item] = src.read(1)
        elif options.accumulation_flux and not getattr(model.solver_mesh, "is_structured", False):
            accumulated_flow = accumulate_unstructured_cell_values(
                model,
                local_values=np.where(outflow <= float(NODATA), 0.0, outflow),
                reference_values=np.where(dem_mask_flat, np.nan, dem_flat),
                inactive_mask=dem_mask_flat,
            )
            accumulated_flow[dem_mask_flat] = float(NODATA)
            dict_accumulation_flux[item] = model._to_export_array(accumulated_flow)

    if options.watertable_elevation:
        np.save(os.path.join(model.save_file, "watertable_elevation"), dict_watertable_elevation)
    if options.watertable_depth:
        np.save(os.path.join(model.save_file, "watertable_depth"), dict_watertable_depth)
    if options.seepage_areas:
        np.save(os.path.join(model.save_file, "seepage_areas"), dict_seepage_areas)
    if options.outflow_drain:
        np.save(os.path.join(model.save_file, "outflow_drain"), dict_outflow_drain)
    if options.outlet_discharge_east_side_m3_s:
        np.save(
            os.path.join(model.save_file, "outlet_discharge_east_side_m3_s"),
            dict_outlet_discharge_east_side_m3_s,
        )
    if options.accumulation_flux:
        np.save(os.path.join(model.save_file, "accumulation_flux"), dict_accumulation_flux)
    export_native_mesh_outputs(
        model,
        options=options,
        times=times,
        datasets={
            "watertable_elevation": dict_watertable_elevation,
            "watertable_depth": dict_watertable_depth,
            "seepage_areas": dict_seepage_areas,
            "outflow_drain": dict_outflow_drain,
            "accumulation_flux": dict_accumulation_flux,
        },
        prefix="flow",
    )
    export_runtime_support_overview(model, options=options)


def run_transport_post_processing(
    transport_model: TransportPostprocessModel,
    model_mt3dms: object,
    *,
    concentration_seepage: bool = True,
    mass_seepage: bool = True,
    mass_accumulated: bool = False,
    export_all_tif: bool = False,
    options: ModflowPostprocessOptions | None = None,
) -> None:
    """Run MODFLOW 6 transport post-processing on the paired GWT outputs."""
    del model_mt3dms
    runtime_options = transport_model._resolve_postprocess_options(
        export_all_tif=export_all_tif,
        options=options,
    )
    export_all_tif = bool(runtime_options.export_all_tif)
    transport_model.save_file = os.path.join(transport_model.full_path, "_postprocess")
    filesystem.create_folder(transport_model.save_file)
    transport_model.tifs_file = os.path.join(transport_model.save_file, "_rasters")
    filesystem.create_folder(transport_model.tifs_file)

    path_ucn = os.path.join(transport_model.full_path, f"{transport_model.model_name_mt}.ucn")
    conc_reader = None
    try:
        ucnobj = bf.UcnFile(path_ucn)
        conc_reader = ucnobj
        concobj_1c = ucnobj.get_alldata(mflay=None)
    except Exception:
        try:
            headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="double")
            conc_reader = headobj
            concobj_1c = headobj.get_alldata(mflay=None)
        except Exception:
            headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="single")
            conc_reader = headobj
            concobj_1c = headobj.get_alldata(mflay=None)
    concobj_1c[concobj_1c >= 1e30] = np.nan
    conc_last_idx = max(int(concobj_1c.shape[0]) - 1, 0)
    times = list(getattr(transport_model.model_modflow, "times", []) or [])
    if len(times) != int(transport_model.model_modflow.nper):
        try:
            times = [float(value) for value in conc_reader.get_times()]
        except Exception:
            times = []
    if len(times) != int(transport_model.model_modflow.nper):
        times = [float(i + 1) for i in range(int(transport_model.model_modflow.nper))]

    outflow_drain = getattr(transport_model.model_modflow, "dict_outflow_drain", {})
    dem_mask = np.asarray(
        getattr(
            transport_model.model_modflow,
            "dem_mask",
            transport_model.model_modflow.dem < float(NODATA),
        ),
        dtype=bool,
    ).reshape(-1)

    dict_concentration_seepage: dict[int, np.ndarray] = {}
    dict_mass_seepage: dict[int, np.ndarray] = {}
    dict_mass_accumulated: dict[int, np.ndarray] = {}
    can_export_raster = bool(
        getattr(transport_model.model_modflow.solver_mesh, "is_structured", False)
        and getattr(transport_model.model_modflow, "dem_watershed_path", "")
    )

    def _reshape_for_export(arr):
        return transport_model.model_modflow._to_export_array(
            np.asarray(arr, dtype=float).reshape(-1)
        )

    for i in range(transport_model.model_modflow.nper):
        the_time = str(i + 1)
        seep = outflow_drain.get(i, np.zeros(int(transport_model.model_modflow.ncpl), dtype=float))
        seep = np.asarray(seep, dtype=float).reshape(-1)
        conc_time_idx = min(i, conc_last_idx)
        mass_surf = None

        if concentration_seepage:
            conc_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
            conc_surf[seep <= 0] = float(NODATA)
            conc_surf[dem_mask] = float(NODATA)
            dict_concentration_seepage[i] = _reshape_for_export(conc_surf)
            if can_export_raster and (export_all_tif or i == 0):
                raster_io.export_tif(
                    transport_model.model_modflow.dem_watershed_path,
                    _reshape_for_export(conc_surf),
                    os.path.join(
                        transport_model.tifs_file, f"concentration_seepage_t({the_time}).tif"
                    ),
                    NODATA,
                )

        if mass_seepage or mass_accumulated:
            mass_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
            mass_surf[seep <= 0] = np.nan
            mass_surf = mass_surf * seep
            mass_surf[dem_mask] = float(NODATA)
            mass_surf = np.where(np.isnan(mass_surf), float(NODATA), mass_surf)
        if mass_seepage and mass_surf is not None:
            dict_mass_seepage[i] = _reshape_for_export(mass_surf)
            if can_export_raster and (export_all_tif or i == 0):
                raster_io.export_tif(
                    transport_model.model_modflow.dem_watershed_path,
                    _reshape_for_export(mass_surf),
                    os.path.join(transport_model.tifs_file, f"mass_seepage_t({the_time}).tif"),
                    NODATA,
                )

        if mass_accumulated and can_export_raster:
            routing_ctx = transport_model.model_modflow._ensure_solver_routing_context()
            accumulated_mass = masstransfer.Masstransfer(
                transport_model.model_modflow.geographic,
                f"mass_seepage_t({the_time}).tif",
                f"tracept_conc_t({the_time}).shp",
                f"mass_accumulated_t({the_time}).tif",
                extraction_folder=transport_model.save_file,
                routing_fill_path=routing_ctx.correc_path,
                routing_direc_path=routing_ctx.direc_path,
            )
            accumulated_mass.trace_cumulated()
            with rasterio.open(
                os.path.join(transport_model.tifs_file, f"mass_accumulated_t({the_time}).tif")
            ) as src:
                dict_mass_accumulated[i] = src.read(1)
        elif (
            mass_accumulated
            and mass_surf is not None
            and not getattr(transport_model.model_modflow.solver_mesh, "is_structured", False)
        ):
            accumulated_mass = accumulate_unstructured_cell_values(
                transport_model.model_modflow,
                local_values=np.where(mass_surf <= float(NODATA), 0.0, mass_surf),
                reference_values=np.where(
                    dem_mask,
                    np.nan,
                    np.asarray(transport_model.model_modflow.dem, dtype=float).reshape(-1),
                ),
                inactive_mask=dem_mask,
            )
            accumulated_mass[dem_mask] = float(NODATA)
            dict_mass_accumulated[i] = _reshape_for_export(accumulated_mass)

    if concentration_seepage:
        np.save(
            os.path.join(transport_model.save_file, "concentration_seepage"),
            dict_concentration_seepage,
        )
    if mass_seepage:
        np.save(os.path.join(transport_model.save_file, "mass_seepage"), dict_mass_seepage)
    if mass_accumulated:
        np.save(os.path.join(transport_model.save_file, "mass_accumulated"), dict_mass_accumulated)
    transport_model.model_modflow.save_file = transport_model.save_file
    export_native_mesh_outputs(
        transport_model.model_modflow,
        options=runtime_options,
        times=times,
        datasets={
            "concentration_seepage": dict_concentration_seepage,
            "mass_seepage": dict_mass_seepage,
            "mass_accumulated": dict_mass_accumulated,
        },
        prefix="transport",
    )


__all__ = [
    "BudgetReaderLike",
    "FlowPostprocessModel",
    "RoutingContextLike",
    "SolverMeshLike",
    "TransportPostprocessModel",
    "NODATA",
    "accumulate_unstructured_cell_values",
    "build_unstructured_cell_adjacency",
    "compute_chd_outlet_discharge_east_side_m3_s",
    "compute_drain_outflow_and_seepage",
    "compute_watertable_depth",
    "compute_watertable_elevation",
    "east_side_cell_ids",
    "export_native_mesh_outputs",
    "get_budget_records_or_none",
    "native_cell_series_payload",
    "native_mesh_exports_enabled",
    "open_budget_file",
    "run_flow_post_processing",
    "run_transport_post_processing",
]
