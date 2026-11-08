"""MODFLOW 6 pre_processing: flopy package wiring and grid template helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import flopy
import numpy as np

from hydromodpy.catchment.drainage.descent import Descent, DescentBasin
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units import to_modflow6_time_units
from hydromodpy.model.model import Model
from hydromodpy.model.properties.property_table import (
    require_positive_conductivity,
    require_positive_storage,
    resolve_required_flow_properties,
)
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    assemble_constant_head_stress_period_data,
    build_drain_stress_period_data,
    build_ocean_boundary_chd_spd,
    build_side_boundary_chd_spd,
    build_stream_boundary_chd_spd,
    collapse_identical_periods,
    is_bc_active,
    refuse_constant_heads_below_bottom,
    resolve_drainage_conductance_series,
)
from hydromodpy.solver.modflow6.builders.flow_barrier import (
    check_cutoff_wall_seal,
    resolve_flow_barrier_hfb_rows,
)
from hydromodpy.solver.modflow6.builders.initial_conditions import (
    build_start_heads,
    resolve_rewet_npf_options,
)
from hydromodpy.solver.modflow6.builders.lake import (
    build_exposed_band_runoff_specs,
    build_lak_package_args,
)
from hydromodpy.solver.modflow6.builders.lake_cells import (
    apply_lake_idomain_mask,
    carve_lake_bed,
    resolve_lake_cells_for_active_lakes,
    resolve_lake_occupied_layers,
)
from hydromodpy.solver.modflow6.builders.lake_outflow import (
    own_lake_upstream_ifnos,
    resolve_downstream_spillway_reaches,
    resolve_spillway_seed_cells,
)
from hydromodpy.solver.modflow6.builders.mvr import build_mvr_period_records, mover_package_count
from hydromodpy.solver.modflow6.builders.period_forcing import sto_period_settings
from hydromodpy.solver.modflow6.builders.recharge import (
    areal_layer_index,
    bind_recharge_from_flow,
    bind_soil_etp_from_flow,
    build_evt_array_stress_period_data,
    build_evt_stress_period_data,
    build_soil_evta_payload,
    empty_recharge_aux,
    evt_list_spd_to_array_payload,
    evt_routing_is_layer0_only,
    externalize_recharge_spd,
    finalize_pending_recharge_evt,
    mask_recharge_on_lake_cells,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow6.builders.sfr import (
    build_drainage_mover_records,
    build_sfr_mover_records,
    build_sfr_package_args,
    mover_rows_reach_lake,
    remove_drain_cells,
    resolve_sfr_networks,
    sfr_drain_cells_to_drop,
    sfr_networks_lie_on_the_river_network,
    sfr_networks_walk_the_descent,
    sfr_routes_drainage,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    build_ats_perioddata,
    guard_newton_linear_acceleration,
    guard_newton_rewet,
    log_xt3d_resolution,
    newton_options,
    optional_ims_kwargs,
    output_control_records,
    resolve_ims_complexity,
    resolve_xt3d_npf_options,
    xt3d_activation_mode,
)
from hydromodpy.solver.modflow6.builders.wells import build_well_stress_period_data
from hydromodpy.solver.modflow6.support.computational_top import (
    disv_grid_kwargs,
    set_simulation_float_precision,
    well_flow_reduce_fraction,
    write_ground_sidecar,
)
from hydromodpy.solver.modflow6.support.flopy_header_cache import install_flopy_header_cache
from hydromodpy.solver.modflow6.support.flopy_structure_warmup import warm_flopy_structure
from hydromodpy.solver.modflow6.support.names import mf6_output_name
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    k_tensor_npf_kwargs,
    resolve_flow_property_arrays,
    resolve_k33_field,
)
from hydromodpy.solver.modflow6.support.time_series import attach_time_series
from hydromodpy.solver.modflow_common import (
    ModflowPreprocessOptions,
    SolverRoutingContext,
    build_solver_routing_context,
    write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_common.catchment_basin import run_basin
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar
from hydromodpy.solver.modflow_common.flow_adapter_helpers import require_cell_mesh
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
    resolve_dam_foot_cells,
)
from hydromodpy.solver.modflow_common.sink_mask import resolve_sink_mask
from hydromodpy.solver.modflow_grid import (
    build_spatial_discretization,
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)
from hydromodpy.solver.modflow_grid.active_connectivity import warn_on_disconnected_active_cells

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)


def _write_sidecar(model, suffix: str, payload: Mapping[str, object]) -> None:
    """Write ``{model_output_name}{suffix}`` next to the solver files, for the extractor.

    The sidecars travel with the model files, so the post-run extraction needs no
    live flopy object. ``.lak.meta.json`` re-keys the LAK obs CSV by ``(lake_id,
    totim)`` and isolates the under-dam leakage, ``.sfr.meta.json`` does the same
    for SFR, and ``.lake_abacus.json`` carries the bed-reconstruction comparison.
    """
    meta_path = os.path.join(str(model.full_path), f"{model.model_output_name}{suffix}")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(dict(payload), fh, sort_keys=True)


def _write_lake_abacus_meta(model) -> None:
    """Write the reference and simulated abacus of each reconstructed lake bed."""
    reconstruction = getattr(model, "_lake_bed_reconstruction", None)
    entries = [
        {
            "lake_id": str(lid),
            "stage": rec["abacus_stage"],
            "real_volume": rec.get("abacus_volume"),
            "real_sarea": rec["abacus_sarea"],
            "sim_volume": rec["sim_volume"],
            "sim_sarea": rec["sim_sarea"],
        }
        for lid, rec in (reconstruction or {}).items()
        if rec.get("abacus_stage") is not None
        and rec.get("sim_volume") is not None
        and rec.get("abacus_volume") is not None
    ]
    if entries:
        _write_sidecar(model, ".lake_abacus.json", {"entries": entries})


def _shared_forcing_dir(model) -> str | None:
    """Return the folder a calibration trial keeps its forcing binaries in, else None.

    The folder is ``shared_forcing_dir`` of the slot the run builds in. The
    calibration sandbox of a trial names it: one ``_shared_recharge`` folder for
    every trial of a session, because the recharge is the same for all of them,
    or a folder of the trial itself when the phase samples a recharge parameter.
    The recharge and the residual ETP of the soil are then written there once
    and every trial references them (see ``externalize_recharge_spd``). A run
    without that folder keeps the binaries beside its model files.

    The returned path is OS-native: it is only ever handed to the local filesystem
    and to the ``OPEN/CLOSE`` line of the same run's MF6 input, inside a scratch
    tree the sandbox deletes on exit. Unlike the catalog's relative paths, it is
    never read back on another platform, so it must not be posix-normalized.
    """
    slot = getattr(model, "slot", None)
    folder = None if slot is None else slot.shared_forcing_dir
    return None if folder is None else os.fspath(folder)


def _run_descent(
    model, solver_mesh, lake_cell_ids_by_lake, constant_head: np.ndarray
) -> Descent | None:
    """The descent D of this build.

    :func:`_build_descent_and_dam_feet` leaves it beside the model for the
    extractor, once the dam foot of each lake is known.

    Every run builds it: the SFR rectification and drainage routing walk it,
    the per-cell discharge accumulates on it, and the run stores it for its
    figures and accumulated fluxes. ``constant_head`` holds the CHD cells
    (ocean, river, side), the same supports on both backends: they seed the
    flood and the walks stop there. D follows the generated network A on the
    cells A crosses whenever the run has A, with or without SFR. A network
    delineated from A this run makes its rasters mandatory.

    An auxiliary model (steady initialization, spin-up cycle) is never
    extracted: it builds D only when one of its SFR networks walks it, and
    leaves no sidecar.
    """
    if getattr(model, "auxiliary", False) and not sfr_networks_walk_the_descent(model):
        return None
    geometry = model.inputs.geometry
    raster = geometry.raster
    return build_solver_mesh_descent(
        solver_mesh,
        lake_cells_by_lake=lake_cell_ids_by_lake,
        base_level_mask=constant_head,
        channel_exits=channel_exits_for_build(
            None if raster is None else raster.channel,
            geometry.channel_exits,
            required=is_bc_active(model, "sfr") and sfr_networks_lie_on_the_river_network(model),
        ),
        geographic=geometry.catchment,
    )


def _keep_dam_feet_and_leave_descent(
    model,
    descent: Descent | None,
    spillway_seed_by_lake: Mapping[str, int],
    *,
    basin: DescentBasin | None,
) -> None:
    """Keep the dam foot of each lake on the model and leave D and its basin beside it.

    The stream below a dam starts at the dam, so the heads rule of the network
    criterion takes the foot as a head of its own: a calibration reads
    ``model.dam_foot_cells`` (``{lake id: cell}``), and the run stores the same
    cells with D through the sidecar for the redraw. The model keeps the basin
    of D for the discharge observable. An auxiliary model is never extracted:
    it keeps no foot and no basin, and leaves no sidecar. ``basin`` is None only
    when ``descent`` is.
    """
    model.dam_foot_cells = {}
    model.descent_basin = None
    if descent is None or getattr(model, "auxiliary", False):
        return
    model.descent_basin = basin
    model.dam_foot_cells = resolve_dam_foot_cells(descent, spillway_seed_by_lake)
    write_descent_sidecar(
        descent,
        model.full_path,
        model.model_output_name,
        dam_foot_cells=model.dam_foot_cells,
        basin=basin,
    )


def _build_descent_and_dam_feet(
    model,
    solver_mesh,
    lake_cell_ids_by_lake: Mapping[str, Sequence[int]],
    constant_head: np.ndarray,
    outlet_xy: tuple[float, float] | None,
) -> tuple[Descent | None, DescentBasin | None, dict[str, int]]:
    """Build D and its basin, resolve the spillway seeds, keep the dam feet, leave D beside.

    The spillway seeds are the dam-toe cells of the lakes whose spillway routes
    to the downstream reach, so the SFR channel reaches the foot of the dam
    (mover.to_downstream_reach). They are resolved on the mesh, not a fixed
    cell number, so they survive remeshing. They are also the dam feet: the
    stream below a dam starts there, so the heads rule of the network criterion
    takes each as a head of its own.

    The basin of D at the catchment outlet is computed here, once per build,
    while D still holds its adjacency (:func:`run_basin`): the drainage routing,
    the discharge observable and the stored run read it. Returns
    ``(D, basin of D, {lake id: seed cell})``, D and its basin None when the
    model builds no D.
    """
    descent = _run_descent(model, solver_mesh, lake_cell_ids_by_lake, constant_head)
    basin = (
        None
        if descent is None
        else run_basin(model.inputs.geometry.catchment, solver_mesh, descent)
    )
    spillway_seed_by_lake: dict[str, int] = {}
    if lake_cell_ids_by_lake:
        spillway_seed_by_lake = resolve_spillway_seed_cells(
            model,
            lake_cells_by_id=lake_cell_ids_by_lake,
            cell_adjacency=solver_mesh.face_adjacency(),
            cell_centroids=solver_mesh.cell_centers(),
            idomain=solver_mesh.idomain,
            mesh_top=solver_mesh.top,
            outlet_xy=outlet_xy,
        )
    _keep_dam_feet_and_leave_descent(model, descent, spillway_seed_by_lake, basin=basin)
    return descent, basin, spillway_seed_by_lake


def _resolve_spillway_receivers(
    sfr_networks: Mapping[str, Any],
    spillway_seed_by_lake: Mapping[str, int],
    *,
    lake_ids: Sequence[str],
    cell_centroids: np.ndarray,
) -> dict[str, int]:
    """Map each dam-toe seed to the reach on it, ``{lake id: reach ifno}``.

    ``lake_ids`` is the lake order of the build, the order the SFR reaches are
    numbered against: a reach's ``terminal_lake`` is the 1-based position of
    its lake there. The reaches that end in a lake, with everything upstream
    of them, are never the receiver of that lake's spillway, or the lake would
    feed itself (a LAK -> SFR -> LAK loop).
    """
    if not sfr_networks or not spillway_seed_by_lake:
        return {}
    reach_cell_to_ifno = {
        int(reach.cellid[1]): int(reach.ifno)
        for network in sfr_networks.values()
        for reach in network.reaches
        if reach.cellid is not None
    }
    return resolve_downstream_spillway_reaches(
        spillway_seed_by_lake,
        reach_cell_to_ifno=reach_cell_to_ifno,
        cell_centroids=cell_centroids,
        own_lake_terminal_ifnos=own_lake_upstream_ifnos(sfr_networks, lake_ids=lake_ids),
    )


def _constant_head_cells(
    n_cells: int, *support_masks: np.ndarray, side_chd_spd: Mapping[int, Sequence[Sequence]]
) -> np.ndarray:
    """Planar cells holding a CHD in any period: the support masks and the side rows."""
    cells = np.zeros(int(n_cells), dtype=bool)
    for mask in support_masks:
        cells |= np.asarray(mask, dtype=bool).reshape(-1)
    for rows in side_chd_spd.values():
        for row in rows:
            cells[int(row[1])] = True
    return cells


def _drainage_basin_mask(basin: DescentBasin | None) -> np.ndarray:
    """The DRN cells routed to the streams: the basin of D the build computed.

    A run with neither outlet nor watershed polygon routes the largest basin of
    the descent, which is an anomaly for a catchment model: a warning.
    """
    if basin is None:
        raise ValueError("drainage routing walks the descent D, and this build has none.")
    if not basin.is_catchment:
        logger.warning(
            "Drainage routing: no outlet and no watershed polygon for this run. The "
            "hillslope DRN of the largest basin of the descent is routed to the streams."
        )
    return basin.mask


def _resolve_channel_mask_for_zonal(model) -> np.ndarray | None:
    """Boolean channel-pixel mask aligned to ``surface_topo`` for zonal top sampling.

    Only produced when ``sgrid.top_sampling.mode == 'zonal'`` and its
    ``channel_source`` requests one. Reads the channel tree A over the whole model
    domain, the full-extent raster the model carries in
    ``geometry.raster.channel.link``, and reprojects it (nearest) onto the model-top
    DEM grid. The rasters clipped to the watershed miss the buffer the grid keeps
    active, so they are the fallback only. Returns ``None`` (channel class disabled, every
    pixel treated as hillslope) when zonal is off, the source is 'none', or no
    stream raster / georeferenced surface is available.
    """
    sgrid_cfg = getattr(model.modflow_config, "sgrid", None)
    top_sampling = getattr(sgrid_cfg, "top_sampling", None)
    if top_sampling is None or top_sampling.mode != "zonal":
        return None
    if top_sampling.channel_source == "none":
        return None

    raster = model.inputs.geometry.raster
    channel = None if raster is None else raster.channel
    path = None
    if channel is not None and channel.link is not None and os.path.exists(channel.link):
        path = channel.link
        logger.info("Zonal channel mask reads the full-extent channel tree: %s.", path)
    if path is None and channel is not None:
        for candidate in channel.clipped:
            if os.path.exists(candidate):
                path = candidate
                logger.info(
                    "Zonal channel mask reads the stream raster clipped to the watershed "
                    "(no full-extent raster in the corrected-flow folder): %s.",
                    path,
                )
                break
    if path is None:
        logger.warning(
            "Zonal channel_source=%s but no stream raster found; the channel class "
            "is disabled (every DEM pixel treated as hillslope).",
            top_sampling.channel_source,
        )
        return None

    surface = getattr(model.inputs.geometry.domain, "surface_topo", None)
    support = getattr(surface, "support", None)
    fields = ("xmin", "xmax", "ymin", "ymax", "nrows", "ncols")
    if support is None or any(getattr(support, name, None) is None for name in fields):
        logger.warning("Zonal channel mask needs a georeferenced surface; channel class disabled.")
        return None

    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    out_shape = (int(support.nrows), int(support.ncols))
    dst_transform = from_bounds(
        float(support.xmin),
        float(support.ymin),
        float(support.xmax),
        float(support.ymax),
        int(support.ncols),
        int(support.nrows),
    )
    # The fill value must not be 0: GDAL moves a valid source pixel equal to the
    # destination nodata to the next float (5e-324), so with 0 every background
    # pixel of the stream raster turned "positive" and the channel class covered
    # the whole catchment (measured on the Flume: 146 384 pixels for 4 197).
    dst = np.full(out_shape, -1.0, dtype=np.float64)
    with rasterio.open(path) as src:
        src_nodata = src.nodata
        src_crs = src.crs
        dst_crs = support.crs if support.crs is not None else src_crs
        # WhiteboxTools strips the delineated stream raster CRS to an engineering
        # LOCAL_CS tag, but it is delineated from the same projected DEM domain, so
        # it is already co-registered with the model top. Asking PROJ to transform
        # an engineering CRS to the projected DEM CRS raises, so treat a missing or
        # non-standard tag as the model coordinate space (a pure nearest resample).
        if src_crs is None or not (src_crs.is_projected or src_crs.is_geographic):
            src_crs = dst_crs
        try:
            reproject(
                source=src.read(1).astype(np.float64),
                destination=dst,
                src_transform=src.transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                src_nodata=src_nodata,
                dst_nodata=-1.0,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never abort the build
            logger.warning(
                "Zonal channel mask reprojection failed (%s); channel class disabled.", exc
            )
            return None
    # Channel pixels carry a positive link id / stream flag; 0 is background. A
    # nearest reproject can still copy the source nodata value into the target
    # (it is not always filled with dst_nodata), so require a strictly positive
    # value and drop a positive nodata sentinel explicitly.
    mask = np.isfinite(dst) & (dst > 0.0)
    if src_nodata is not None and float(src_nodata) > 0.0:
        mask &= dst != float(src_nodata)
    if top_sampling.channel_buffer_px > 0:
        from scipy import ndimage

        mask = ndimage.binary_dilation(mask, iterations=int(top_sampling.channel_buffer_px))
    logger.info(
        "Zonal channel mask: %d/%d channel pixels from %s.", int(mask.sum()), mask.size, path
    )
    return mask


def xt3d_mode(model, solver_mesh=None) -> str:
    """Return the XT3D activation mode."""
    return xt3d_activation_mode(model, solver_mesh)


def resolve_xt3d_options(model, solver_mesh=None) -> list[str] | None:
    """Return FloPy NPF XT3D options."""
    return resolve_xt3d_npf_options(model, solver_mesh)


def write_solver_grid_template(model) -> str:
    """Write a solver-grid template raster for structured grids."""
    if model.grid_ctx is None:
        raise ValueError("grid_ctx must exist before writing a solver grid template")
    if not model.solver_mesh.is_structured:
        return ""
    os.makedirs(model.full_path, exist_ok=True)
    template_path = os.path.join(model.full_path, "_solver_grid_template.tif")
    top_2d = model.solver_mesh.reshape_to_grid(model.solver_mesh.top)
    write_grid_array_to_raster(
        grid=model.grid_ctx.grid,
        data=top_2d,
        output_path=template_path,
        nodata=float(model.grid_ctx.grid.nodata),
    )
    model.grid_ctx.template_raster_path = template_path
    return template_path


def ensure_solver_routing_context(model) -> SolverRoutingContext:
    """Build hydrologic routing rasters aligned with the solver grid."""
    if model.routing_ctx is not None:
        return model.routing_ctx
    if model.grid_ctx is None:
        raise ValueError("grid_ctx must exist before building solver routing products")

    from hydromodpy.catchment.preprocess.capped_breach_config import capped_breach_of

    raster = _require_raster(model)
    model.routing_ctx = build_solver_routing_context(
        dem_path=model.dem_watershed_path,
        output_dir=os.path.join(model.full_path, "_solver_routing"),
        dem_correc_type=str(raster.dem_correc_type),
        crs_project=raster.crs_proj,
        engine_id=raster.terrain_engine,
        capped_breach=capped_breach_of(raster),
    )
    return model.routing_ctx


def _require_raster(model):
    """The DEM grid of the model, or a refusal that says the run has none."""
    raster = model.inputs.geometry.raster
    if raster is None:
        raise ValueError(
            "MODFLOW 6 reads the DEM grid of the run (Model.geometry.raster), and this model has none."
        )
    return raster


FLOW_PROPERTY_SIDECAR_SUFFIX = ".flow_properties.npz"
"""Name of the file the builder leaves beside the model for the extractor."""

_TENSOR_SIDECAR_NAMES = {
    "k22": "hydraulic_conductivity_k22",
    "angle1": "conductivity_tensor_angle1",
    "angle2": "conductivity_tensor_angle2",
    "angle3": "conductivity_tensor_angle3",
}
"""Stored name of each NPF tensor array, as the field registry declares it."""


def _save_flow_property_sidecar(model) -> None:
    """Leave the resolved K, K33, Sy and Ss arrays beside the MODFLOW 6 model.

    K22 and the three angles join them when the flow sets them. The extractor
    reads the model folder, not the builder, and MODFLOW never writes its own
    input back out. Without this file a run keeps no trace of the conductivity
    field it was actually given, so nothing can draw it. Arrays are
    (nlay, n_cells) in SI units, the clock MF6 runs on, and angles in degrees.
    The model folder may not exist yet (the runtime-mesh path builds the
    arrays before flopy creates it), so it is created here.
    """
    arrays = {
        "hydraulic_conductivity": model.hk,
        "hydraulic_conductivity_k33": model.k33,
        "specific_yield": model.sy,
        "specific_storage": model.ss,
    }
    for name, values in k_tensor_npf_kwargs(model).items():
        arrays[_TENSOR_SIDECAR_NAMES[name]] = values
    try:
        os.makedirs(model.full_path, exist_ok=True)
        np.savez(
            os.path.join(
                model.full_path,
                f"{model.model_output_name}{FLOW_PROPERTY_SIDECAR_SUFFIX}",
            ),
            **{
                name: np.atleast_2d(np.asarray(values, dtype="float64"))
                for name, values in arrays.items()
            },
        )
    except OSError:
        logger.debug("Could not write flow property sidecar", exc_info=True)


def validate_pre_processing_inputs(model) -> None:
    """Validate that the model, its domain and its time grid are set."""
    inputs = model.inputs
    if inputs is None:
        raise ValueError("pre_processing requires a Model object.")
    if inputs.geometry.domain is None:
        raise ValueError("pre_processing requires a configured Domain object.")
    if inputs.time.grid is None and inputs.time.regime != "steady":
        raise ValueError(
            "Launcher flow preprocessing requires preprocess_options.time_grid "
            "derived from [simulation.time] for transient flow runs."
        )


def select_active_dem(model, box: bool) -> None:
    """Select the DEM raster to use according to the box option."""
    raster = _require_raster(model)
    if box:
        model.dem_watershed_path = raster.watershed_box_buff_dem
    else:
        model.dem_watershed_path = raster.watershed_buff_dem


def apply_preprocess_options(
    model,
    options: ModflowPreprocessOptions | None = None,
) -> None:
    """Apply preprocess options on the model (mutating)."""
    if options is None:
        options = model.preprocess_options
    if not isinstance(options, ModflowPreprocessOptions):
        raise TypeError("pre_processing options must be a ModflowPreprocessOptions instance.")

    model.preprocess_options = options
    model.sink_fill = bool(options.sink_fill)
    model.drain_band_depth_m = float(options.drain_band_depth_m)
    model.drain_bed_thickness_m = float(options.drain_bed_thickness_m)
    model.drain_conductance_floor_m2_s = float(options.drain_conductance_floor_m2_s)
    model.recharge = getattr(options, "recharge", None)
    model.first_clim = getattr(options, "first_clim", None)
    model.check_grid = bool(options.check_grid)


def _build_storage_package(model, solver_mesh: SolverMesh) -> None:
    """Build STO on ``solver_mesh``, the grid DISV writes, lake footprint included.

    Every layer is convertible. A storage a transient period reads is checked
    on the active cells of that grid only, since the solver reads none on an
    inactive cell (``require_positive_storage``).
    """
    steady_flags = [bool(model.steady[i]) for i in range(int(model.nper))]
    steady_state_spd, transient_spd = sto_period_settings(steady_flags)
    iconvert = np.ones((model.nlay,), dtype=int)
    require_positive_storage(
        model.sy,
        model.ss,
        active_mask=solver_mesh.idomain > 0,
        iconvert=iconvert,
        steady=steady_flags,
        profiles=model.inputs.properties.profiles,
    )
    model.sto = flopy.mf6.ModflowGwfsto(
        model.gwf,
        sy=model.sy,
        ss=model.ss,
        iconvert=iconvert,
        steady_state=steady_state_spd or None,
        transient=transient_spd or None,
    )


def _settle_inputs(model, inputs: Model, options, slot: RunSlot | None):
    """Bind the inputs and the slot of the run and check them before any build."""
    # Concurrent calibration trials build one MFSimulation each; the flopy DFN
    # singleton must be fully loaded before any of them constructs a package.
    warm_flopy_structure()
    install_flopy_header_cache()
    model.inputs = inputs
    model.slot = slot
    active_options = model.preprocess_options if options is None else options
    apply_preprocess_options(model, active_options)
    validate_pre_processing_inputs(model)
    select_active_dem(model, box=bool(active_options.box))
    # Reject invalid solver-config combinations before any expensive grid build.
    guard_newton_linear_acceleration(model.modflow_config.runtime)
    bind_recharge_from_flow(model)
    bind_soil_etp_from_flow(model)
    model._calibration_raw_output_payload_cache = {}

    # Settle the output stem before anything names a file after it. On Windows a
    # long solver path collapses it to a hashed name, and a sidecar written under
    # the pre-collapse name is a file its reader never finds.
    model.model_output_name = mf6_output_name(model)


def _discretize_time(model):
    """Stress periods and their TDIS time unit."""
    inputs = model.inputs
    temporal = build_temporal_discretization_from_time_grid(
        time_grid=inputs.time.grid,
        flow_regime=inputs.time.regime,
        first_period_steady=resolve_first_period_steady(model=inputs),
    )
    model.perlen = temporal.perlen
    model.nper = temporal.nper
    model.nstp = temporal.nstp
    model.steady = temporal.steady
    # TDIS declares the unit the temporal builder actually produced, not a
    # literal. The launcher delivers perlen in SI seconds, so the output budget
    # factor stays exactly 1.0; the flow extractor reads this token back and
    # converts fluxes from it, so the two sides can no longer disagree.
    time_units = to_modflow6_time_units(temporal.time_units)
    return temporal, time_units


def _discretize_space(model):
    """The solver mesh, and the forcing that waited for its size."""
    geometry = model.inputs.geometry
    cell_mesh = require_cell_mesh(model.inputs)
    model.grid_ctx = build_spatial_discretization(
        domain=geometry.domain,
        vertical_config=geometry.domain.config.layers,
        sgrid_config=getattr(model.modflow_config, "sgrid", None),
        cell_mesh=cell_mesh,
        channel_mask=_resolve_channel_mask_for_zonal(model),
    )
    solver_mesh = model.grid_ctx.solver_mesh
    model.solver_mesh = solver_mesh
    model.top_elevation = solver_mesh.top  # (ncpl,)
    # (ncpl,) columns no surface process reaches; the lake footprint joins below.
    model.inactive_mask = solver_mesh.closed_surface()
    model.nlay = solver_mesh.nlay
    model.ncpl = solver_mesh.n_cells
    finalize_pending_recharge_evt(model)  # reads nper and ncpl
    model.dem = model.top_elevation  # flat (ncpl,)
    model.dem_mask = model.inactive_mask  # flat (ncpl,)
    model.dem_watershed_path = write_solver_grid_template(model)

    resolve_deferred_heterogeneous_recharge(model)
    resolve_deferred_soil_etp(model)
    return solver_mesh


FLOW_PROPERTY_FIELDS: tuple[str, ...] = (
    "hk",
    "k33",
    "k22",
    "angle1",
    "angle2",
    "angle3",
    "sy",
    "ss",
)
"""The per-cell arrays the build maps from the properties of a ``Model``, as solver attributes."""


def flow_property_fields(
    model, inputs: Model, solver_mesh: SolverMesh
) -> dict[str, np.ndarray | None]:
    """Map the properties of ``inputs`` onto the cells of ``solver_mesh``, checked positive.

    K, K33 and the rest of the K tensor, Sy and Ss, keyed as the solver keeps
    them (``FLOW_PROPERTY_FIELDS``). K22 and the angles are ``None`` when the flow
    does not set them. ``model`` gives the vertical anisotropy of the options.
    The build and ``rerun`` map with this one function, so a rerun writes the
    arrays a build of the same ``Model`` would write.
    """
    flow_params = resolve_flow_property_arrays(
        profiles=inputs.properties.profiles,
        domain=inputs.geometry.domain,
        solver_mesh=solver_mesh,
        required_properties=resolve_required_flow_properties(flow_regime=inputs.time.regime),
        optional_fill_values={"Sy": 0.0, "Ss": 0.0},
        runtime_property_overrides=inputs.properties.overrides,
    )
    hk = solver_mesh.flatten_from_grid(flow_params["hk"])
    require_positive_conductivity(
        hk,
        active_mask=solver_mesh.idomain > 0,
        profiles=inputs.properties.profiles,
    )
    kv_field = solver_mesh.flatten_from_grid(flow_params["kv"]) if "kv" in flow_params else None
    fields: dict[str, np.ndarray | None] = {
        "hk": hk,
        "k33": resolve_k33_field(
            hk,
            kv_field,
            model.modflow_config.process_specific.vka,
            label="flow vertical anisotropy",
        ),
        "sy": solver_mesh.flatten_from_grid(flow_params["sy"]),
        "ss": solver_mesh.flatten_from_grid(flow_params["ss"]),
    }
    # K22 and the angles exist only when the flow sets them. They are read
    # before the first XT3D decision, which a tilted or off-axis tensor turns on.
    for name in K_TENSOR_NPF_NAMES:
        values = flow_params.get(name)
        fields[name] = None if values is None else solver_mesh.flatten_from_grid(values)
    if fields["k22"] is not None:
        require_positive_conductivity(
            fields["k22"],
            active_mask=solver_mesh.idomain > 0,
            profiles=inputs.properties.profiles,
            property_label="K22",
        )
    return fields


def _map_hydraulic_properties(model, solver_mesh: SolverMesh):
    """K, K33, the rest of the K tensor, Sy and Ss on the cells, checked positive.

    The mesh they are mapped on is kept as ``_property_mesh``: the lake masking
    and the bed carving that follow give the solver another mesh, and a rerun
    maps a new K on this one, as the build did.
    """
    for name, values in flow_property_fields(model, model.inputs, solver_mesh).items():
        setattr(model, name, values)
    model._property_mesh = solver_mesh
    log_xt3d_resolution(model, solver_mesh)
    _save_flow_property_sidecar(model)


def _build_simulation(model, solver_mesh: SolverMesh, temporal, time_units: str):
    """The simulation, its TDIS (and ATS), IMS and the GWF model."""
    runtime = model.modflow_config.runtime
    sim_name = model.model_name_mf6
    model.sim = flopy.mf6.MFSimulation(
        sim_name=sim_name, sim_ws=model.full_path, exe_name=model.exe
    )
    set_simulation_float_precision(model.sim)
    # MF6 TDIS START_DATE_TIME is a free-form ISO 8601 string (flopy rejects a
    # datetime object). None means no calendar anchor is written.
    start_date_time = (
        temporal.start_datetime.isoformat() if temporal.start_datetime is not None else None
    )
    model.tdis = flopy.mf6.ModflowTdis(
        model.sim,
        nper=int(model.nper),
        # TSMULT stays 1.0. Within one stress period the forcing is constant, so
        # the backward-Euler state at the period end depends only on the set of
        # step sizes and not on their order, and equal steps minimize its error.
        # simulation.time.substeps_per_period is the knob that buys accuracy here.
        perioddata=[
            (float(model.perlen[i]), int(model.nstp[i]), 1.0) for i in range(int(model.nper))
        ],
        time_units=time_units,
        start_date_time=start_date_time,
    )
    if runtime.mf6_ats:
        ats_perioddata = build_ats_perioddata(
            perlen=model.perlen,
            nstp=model.nstp,
            steady=model.steady,
            dtmin_s=float(runtime.mf6_ats_dtmin_s),
        )
        if ats_perioddata:
            flopy.mf6.ModflowUtlats(
                model.tdis,
                maxats=len(ats_perioddata),
                perioddata=ats_perioddata,
            )
    model.ims = flopy.mf6.ModflowIms(
        model.sim,
        print_option=str(runtime.ims_print_option),
        complexity=resolve_ims_complexity(model, solver_mesh),
        outer_dvclose=float(runtime.mf6_outer_dvclose),
        inner_dvclose=float(runtime.mf6_inner_dvclose),
        outer_maximum=int(runtime.mf6_outer_maximum),
        inner_maximum=int(runtime.mf6_inner_maximum),
        filename=f"{model.model_name_mf6}_gwf.ims",
        pname="IMS_GWF",
        # The flow cleanup removes the whole solver folder unless
        # keep_solver_files is set, so this record survives only then.
        **optional_ims_kwargs(
            runtime, csv_outer_output=f"{model.model_name_mf6}_gwf.ims.outer.csv"
        ),
    )
    newtonoptions = newton_options(runtime)
    model.gwf = flopy.mf6.ModflowGwf(
        model.sim,
        modelname=model.model_name_mf6,
        save_flows=True,
        print_input=getattr(runtime, "mf_verbose", False),
        print_flows=getattr(runtime, "mf_verbose", False),
        newtonoptions=newtonoptions,
    )
    model.sim.register_ims_package(model.ims, [model.gwf.name])
    return runtime


def _mask_lakes(model, solver_mesh: SolverMesh):
    """Make the lake footprint inactive, carve the beds, and settle the sinks."""
    # Lake cells are made inactive (idomain=0) before DISV is built so the LAK
    # footprint stays consistent across idomain, dem_mask, RCH, EVT and DRN. LAK
    # supplies the storage and lake-aquifer exchange through its own
    # CONNECTIONDATA (built later from this same lake mask).
    lake_cell_ids_by_lake = resolve_lake_cells_for_active_lakes(model, solver_mesh)
    occupied_layers_by_lake = resolve_lake_occupied_layers(model)
    # The open-water footprint of the run: every lake cell, marnage included.
    # It answers "is this cell open water", not "is this lake modeled as
    # active", so it is deliberately wider than the inactive-only list below.
    model.open_water_cell_ids = sorted(
        {int(cid) for cells in lake_cell_ids_by_lake.values() for cid in cells}
    )
    model._lake_cell_ids = []
    if lake_cell_ids_by_lake:
        # Carve the real lake bed from bathymetry (opt-in per lake) before the
        # idomain mask, so the carved top/botm flow into DISV, start heads and the
        # LAK connectiondata. Lakes without bed_reconstruction pass through.
        solver_mesh = carve_lake_bed(
            model,
            solver_mesh,
            lake_cell_ids_by_lake=lake_cell_ids_by_lake,
            occupied_layers_by_lake=occupied_layers_by_lake,
        )
        # Active-littoral (marnage) lakes keep their cells ACTIVE so MF6 toggles
        # RCH/ET per cell (IWETLAKE); only fixed-area reservoirs deactivate their
        # footprint and drop RCH/ET. Mask + RCH/ET masking exclude marnage cells.
        marnage_ids = getattr(model, "_marnage_lake_ids", set())
        inactive_lakes = {
            lid: cells for lid, cells in lake_cell_ids_by_lake.items() if lid not in marnage_ids
        }
        model._lake_cell_ids = sorted({cid for cells in inactive_lakes.values() for cid in cells})
        # A carved bed cuts a per-cell number of layers (deep center vs shallow
        # rim); the carve stashes that map so the mask follows the real basin.
        occupied_layers_by_cell = getattr(model, "_lake_occupied_layers_by_cell", None)
        solver_mesh = apply_lake_idomain_mask(
            solver_mesh,
            lake_cell_ids_by_lake=inactive_lakes,
            occupied_layers_by_lake=occupied_layers_by_lake,
            occupied_layers_by_cell=occupied_layers_by_cell,
        )
        model.solver_mesh = solver_mesh
        model.inactive_mask = solver_mesh.closed_surface(model._lake_cell_ids)
        model.dem_mask = model.inactive_mask

    # The grid is final once the lake footprint is inactive, so the groups of active
    # cells are counted here: a lake can cut a stack that was whole before it.
    warn_on_disconnected_active_cells(solver_mesh, lake_cell_ids_by_lake.values())

    # Measured here and not on the raw grid: the lake mask moves the surface the
    # drains sit on.
    model.sink = resolve_sink_mask(
        solver_mesh,
        sink_fill=bool(model.sink_fill),
        model_name=model.model_name,
        covered_cells=model._lake_cell_ids,
    )
    return solver_mesh, lake_cell_ids_by_lake


def _resolve_constant_heads(model, solver_mesh: SolverMesh):
    """The ocean, stream and side constant heads, with their supports."""
    # The CHD supports are built here, before SFR, because the descent D below
    # seeds on them. They read the DEM, the post-lake-mask activity and the mesh
    # support, none of which changes further down.
    ocean_chd_spd, ocean_support_mask = build_ocean_boundary_chd_spd(model)
    stream_chd_spd, stream_support_mask = build_stream_boundary_chd_spd(model)
    side_chd_spd = build_side_boundary_chd_spd(model)
    refuse_constant_heads_below_bottom(
        model,
        botm=solver_mesh.botm,
        idomain=solver_mesh.idomain,
        ocean_spd=ocean_chd_spd,
        stream_spd=stream_chd_spd,
        side_spd=side_chd_spd,
        structured_shape=solver_mesh.structured_shape if solver_mesh.is_structured else None,
    )
    model._ocean_support_mask = np.asarray(ocean_support_mask, dtype=bool).copy()
    model._stream_support_mask = np.asarray(stream_support_mask, dtype=bool).copy()
    return (ocean_chd_spd, ocean_support_mask), (stream_chd_spd, stream_support_mask), side_chd_spd


def _resolve_streams(model, solver_mesh: SolverMesh, lake_cell_ids_by_lake, side_chd_spd):
    """The descent D, the SFR networks, their movers and the spillway receivers."""
    # SFR resolves against the lake cells so trace reaches are truncated at the
    # shoreline (never left sitting on a LAK cell once the DEM routes a stream
    # through the lake), then the mover builder hands their flow to that lake.
    catchment = model.inputs.geometry.catchment
    _x_out = getattr(catchment, "x_outlet", None)
    _y_out = getattr(catchment, "y_outlet", None)
    sfr_outlet_xy = (
        (float(_x_out), float(_y_out)) if _x_out is not None and _y_out is not None else None
    )

    # The descent D: a copy of the top the solver sees, filled on the graph it
    # descends, so every cell holds a path to the domain rim or a CHD cell. The
    # reach rectification, the drainage routing and the per-cell discharge all
    # walk it; the copy never reaches the solver, which keeps reading this top.
    # The dam-toe seeds of the lake spillways extend the SFR channel to the foot
    # of the dam, fed to the rectification below, so the overflow enters an SFR
    # reach at the dam foot instead of a gap of hillslope DRN cells. The same
    # cells are kept on the model and stored with D as the dam feet.
    descent, basin, spillway_seed_by_lake = _build_descent_and_dam_feet(
        model,
        solver_mesh,
        lake_cell_ids_by_lake,
        _constant_head_cells(
            int(solver_mesh.n_cells),
            model._ocean_support_mask,
            model._stream_support_mask,
            side_chd_spd=side_chd_spd,
        ),
        sfr_outlet_xy,
    )

    # SFR reaches resolve on the post-lake-mask mesh so every reach cell is an
    # active aquifer cell. Resolution happens before DRN so the drain rows
    # coincident with a reach can be dropped (baseflow discharges to the stream,
    # not out of the model); the package itself is built after LAK.
    lake_cells_by_number = {
        index: list(cells) for index, cells in enumerate(lake_cell_ids_by_lake.values())
    }

    sfr_networks = resolve_sfr_networks(
        model,
        solver_mesh=solver_mesh,
        lake_cells_by_number=lake_cells_by_number,
        spillway_seeds=set(spillway_seed_by_lake.values()),
        descent=descent,
    )
    sfr_mover_records = build_sfr_mover_records(
        sfr_networks,
        lake_cells_by_number=lake_cells_by_number,
        cell_centroids=solver_mesh.cell_centers(),
        outlet_xy=sfr_outlet_xy,
    )

    # Map each dam-toe seed to the reach that now sits on it (the spillway receiver).
    downstream_reach_by_lake = _resolve_spillway_receivers(
        sfr_networks,
        spillway_seed_by_lake,
        lake_ids=list(lake_cell_ids_by_lake),
        cell_centroids=solver_mesh.cell_centers(),
    )
    return (
        descent,
        basin,
        lake_cells_by_number,
        sfr_networks,
        sfr_mover_records,
        downstream_reach_by_lake,
    )


def _build_grid_packages(model, solver_mesh: SolverMesh, runtime):
    """DISV, IC, NPF and STO."""
    # MF6 uses DISV for every grid (structured and unstructured) so one code path
    # covers both. Native DIS is reserved for the NWT backend, which only supports
    # structured grids. The DISV carries the computational top; every package
    # below reads the ground of the solver mesh, and so does the run store
    # through the ground file.
    model.dis = flopy.mf6.ModflowGwfdisv(model.gwf, **disv_grid_kwargs(model))
    if not getattr(model, "auxiliary", False):
        write_ground_sidecar(model)

    strt = build_start_heads(model, solver_mesh)
    model.ic = flopy.mf6.ModflowGwfic(model.gwf, strt=strt)
    rewet_record, wetdry = resolve_rewet_npf_options(model, solver_mesh)
    guard_newton_rewet(runtime, rewet_record)
    xt3doptions = resolve_xt3d_options(model, solver_mesh)

    model.npf = flopy.mf6.ModflowGwfnpf(
        model.gwf,
        icelltype=np.ones((model.nlay,), dtype=int),
        k=model.hk,
        # Vertical conductivity: a per-cell Kv field or the uniform kh/vka ratio.
        # Vertical anisotropy is grid-aligned, so it needs no XT3D.
        k33=model.k33,
        # K22 and the angles only when the flow sets them. A tilted tensor, or a
        # K22 off the grid axes, turns XT3D on unless mf6_enable_xt3d is written.
        **k_tensor_npf_kwargs(model),
        rewet_record=rewet_record,
        xt3doptions=xt3doptions,
        wetdry=wetdry,
        save_specific_discharge=bool(model.modflow_config.runtime.save_specific_discharge),
        save_saturation=bool(model.modflow_config.runtime.save_saturation),
    )
    _build_storage_package(model, solver_mesh)


def _build_recharge_and_evt(
    model,
    solver_mesh: SolverMesh,
    ocean_support_mask,
    stream_support_mask,
):
    """RCH, and EVT from the soil residual ETP or the routed negative recharge."""
    # LOCAL, never an attribute of the model. On the shared calibration path
    # `externalize_recharge_spd` hands FloPy filenames without the arrays, so
    # the only thing keeping the stack alive afterwards was `model.rch_spd`,
    # which nothing in the package ever read. Measured on the Nancon at 25 m:
    # 1826 periods x 243 552 cells x 8 bytes = 3.31 GB retained per model, for
    # the whole solve, times the number of concurrent trials.
    rch_spd = recharge_to_spd(model)
    if model._lake_cell_ids:
        rch_spd = mask_recharge_on_lake_cells(rch_spd, lake_cell_ids=model._lake_cell_ids)
    rch_spd = collapse_identical_periods(rch_spd)
    recharge_payload = externalize_recharge_spd(
        rch_spd,
        basename=model.model_name_mf6,
        shared_dir=_shared_forcing_dir(model),
    )
    del rch_spd
    # A stack with a pass-through cell names the top active layer of each column.
    areal_layer = areal_layer_index(solver_mesh)
    model.rch = flopy.mf6.ModflowGwfrcha(
        model.gwf,
        recharge=recharge_payload,
        auxiliary=["CONCENTRATION"],
        aux=empty_recharge_aux(model),
        pname="RCHA",
        **({} if areal_layer is None else {"irch": areal_layer}),
    )
    soil_evta = build_soil_evta_payload(
        model,
        solver_mesh,
        ocean_support_mask=ocean_support_mask,
        stream_support_mask=stream_support_mask,
        lake_cell_ids=model._lake_cell_ids,
        drain_active=is_bc_active(model, "drainage"),
        shared_dir=_shared_forcing_dir(model),
    )
    # Prefer the vectorized EVTA build: it is byte-for-byte equivalent to
    # build_evt_stress_period_data -> collapse_identical_periods ->
    # evt_list_spd_to_array_payload whenever every kept EVT cell's first active
    # layer is 0 (evt_routing_is_layer0_only, cheap and period-invariant), and
    # it never materializes the list builder's O(ncells x nper) Python records
    # (63M lists / ~12 GB on a real daily chronicle). Otherwise keep the list
    # path, which also handles the rare cell whose top layer is inactive.
    evt_array = None
    if evt_routing_is_layer0_only(
        model,
        solver_mesh,
        ocean_support_mask=ocean_support_mask,
        stream_support_mask=stream_support_mask,
        lake_cell_ids=model._lake_cell_ids,
    ):
        evt_array = build_evt_array_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=ocean_support_mask,
            stream_support_mask=stream_support_mask,
            lake_cell_ids=model._lake_cell_ids,
        )
        # evt_spd is the single source of truth for the soil/routed-EVT collision
        # guard below, whichever path ran; the list payload itself is only needed
        # when the vectorized path did not run.
        evt_spd = True if evt_array is not None else None
    else:
        evt_spd = build_evt_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=ocean_support_mask,
            stream_support_mask=stream_support_mask,
            lake_cell_ids=model._lake_cell_ids,
        )
    if soil_evta is not None:
        if evt_spd is not None:
            raise RuntimeError(
                "the soil residual ETP and the routed negative recharge both ask for "
                "the EVT package; soil mode refuses [data.recharge], so this state is "
                "a bug."
            )
        soil_rate, soil_surface, soil_depth = soil_evta
        model.evt = flopy.mf6.ModflowGwfevta(
            model.gwf,
            surface=soil_surface,
            depth=soil_depth,
            rate=soil_rate,
            save_flows=True,
            pname="EVTA",
            **({} if areal_layer is None else {"ievt": areal_layer}),
        )
    elif evt_array is not None:
        rate_by_period, evt_surface, evt_depth = evt_array
        model.evt = flopy.mf6.ModflowGwfevta(
            model.gwf,
            surface=evt_surface,
            depth=evt_depth,
            rate=rate_by_period,
            save_flows=True,
            pname="EVTA",
        )
    elif evt_spd is not None:
        evt_spd = collapse_identical_periods(evt_spd)
        # Prefer the array package (EVTA): a compact READARRAY per changed period is far
        # cheaper to write than O(ncells) list records on chronicles. It is exactly
        # equivalent while every EVT record sits on layer 0 (the builder skips lake
        # cells, the usual inactive-top source); otherwise fall back to the list.
        evt_array = evt_list_spd_to_array_payload(
            evt_spd, top_flat=solver_mesh.top, ncpl=int(model.ncpl)
        )
        if evt_array is not None:
            rate_by_period, evt_surface, evt_depth = evt_array
            model.evt = flopy.mf6.ModflowGwfevta(
                model.gwf,
                surface=evt_surface,
                depth=evt_depth,
                rate=rate_by_period,
                save_flows=True,
                pname="EVTA",
            )
        else:
            maxbound = max((len(period_cells) for period_cells in evt_spd.values()), default=0)
            model.evt = flopy.mf6.ModflowGwfevt(
                model.gwf,
                stress_period_data=evt_spd,
                maxbound=maxbound,
                save_flows=True,
            )


def _build_drains(
    model,
    solver_mesh: SolverMesh,
    ocean_support_mask,
    stream_support_mask,
    sfr_networks,
    descent,
    basin,
    lake_cells_by_number,
):
    """DRN, and the movers that route the hillslope drainage to the streams."""
    drainage_cond_series = resolve_drainage_conductance_series(model)
    model._drainage_cond_series = (
        None
        if drainage_cond_series is None
        else np.asarray(drainage_cond_series, dtype=float).copy()
    )
    model._drainage_uses_hk = bool(
        drainage_cond_series is not None
        and np.any(np.asarray(drainage_cond_series, dtype=float) <= 0.0)
    )
    drainage_mover_rows: list[list[object]] = []
    # The cells whose drain row is dropped, kept so that a rerun drops the same.
    model._drain_dropped_cells = frozenset()
    if drainage_cond_series is not None:
        drn_spd = build_drain_stress_period_data(
            model,
            solver_mesh=solver_mesh,
            drainage_cond_series=np.asarray(drainage_cond_series, dtype=float),
            ocean_support_mask=np.asarray(ocean_support_mask, dtype=bool),
            stream_support_mask=np.asarray(stream_support_mask, dtype=bool),
        )
        # Marnage lakebed cells stay active (they carry the LAK connection), but they
        # are not hillslope: a route_drainage DRN on them would drain the lake's own
        # leakage straight back to the streams (LAK -> aquifer -> DRN-to-MVR -> SFR ->
        # lake), an artificial recirculation that inflates the lake-aquifer exchange.
        # Drop their DRN rows so the under-lake aquifer equilibrates with the stage.
        marnage_cells = getattr(model, "_marnage_lake_cells", None)
        dropped: set[int] = set()
        if marnage_cells:
            dropped |= {int(cid) for cells in marnage_cells.values() for cid in cells}
        if sfr_networks:
            dropped |= {int(cid) for cid in sfr_drain_cells_to_drop(sfr_networks)}
        drn_spd = remove_drain_cells(drn_spd, cells=dropped)
        model._drain_dropped_cells = frozenset(dropped)
        if sfr_networks:
            # route_drainage: every DRN cell of the basin of D follows the receivers
            # of D to the FIRST reach or lake it reaches, so the hillslope drainage
            # joins the water body it physically drains to. Cells outside that basin
            # drain to a neighboring one and stay plain DRN. The provider ids index
            # the period-0 rows, hence the static-DRN requirement.
            drainage_movers = []
            if sfr_routes_drainage(sfr_networks):
                drainage_movers = build_drainage_mover_records(
                    sfr_networks,
                    drn_spd=drn_spd,
                    receiver=descent.stopping_receiver,
                    basin_cell_mask=_drainage_basin_mask(basin),
                    face_adjacency=solver_mesh.face_adjacency(),
                    mesh_top=np.asarray(solver_mesh.top, dtype=float).reshape(-1),
                    lake_cells_by_number=lake_cells_by_number,
                )
            if drainage_movers:
                drainage_mover_rows = build_mvr_period_records(drainage_movers)
        model.drn = flopy.mf6.ModflowGwfdrn(
            model.gwf,
            pname="DRN",
            stress_period_data=drn_spd,
            save_flows=True,
            mover=bool(drainage_mover_rows),
        )

    # The SFR walks are done: the model keeps D without its adjacency sets, all
    # the per-cell discharge needs. An auxiliary model keeps none.
    model.descent = (
        None
        if descent is None or getattr(model, "auxiliary", False)
        else descent.without_adjacency()
    )
    return drainage_mover_rows


def _build_constant_heads_and_wells(
    model,
    ocean_chd_spd,
    ocean_support_mask,
    stream_chd_spd,
    stream_support_mask,
    side_chd_spd,
    runtime,
):
    """CHD and WEL."""
    chd_spd = assemble_constant_head_stress_period_data(
        model,
        ocean=(ocean_chd_spd, ocean_support_mask),
        stream=(stream_chd_spd, stream_support_mask),
        side=side_chd_spd,
    )
    if any(len(v) > 0 for v in chd_spd.values()):
        model.chd = flopy.mf6.ModflowGwfchd(model.gwf, stress_period_data=chd_spd, save_flows=True)

    wel_spd = build_well_stress_period_data(model, int(model.nper))
    if any(len(v) > 0 for v in wel_spd.values()):
        wel_kwargs: dict[str, object] = {"stress_period_data": wel_spd, "save_flows": True}
        if runtime.mf6_newton:
            # Under the Newton formulation a well that dewaters its cell makes
            # the head oscillate across the confined/unconfined threshold and the
            # solve diverges. AUTO_FLOW_REDUCE tapers the extraction as the
            # saturated thickness drops below 10% of the cell (physically
            # correct: you cannot pump water that is not there), which removes
            # the oscillation. No effect on cells that stay saturated. The 10 %
            # are of the aquifer, not of a cell raised to the computational top.
            wel_kwargs["auto_flow_reduce"] = well_flow_reduce_fraction(
                model, wel_spd, of_aquifer=0.1
            )
        model.wel = flopy.mf6.ModflowGwfwel(model.gwf, **wel_kwargs)


def _build_lakes(
    model,
    solver_mesh: SolverMesh,
    lake_cell_ids_by_lake,
    sfr_mover_records,
    drainage_mover_rows,
    downstream_reach_by_lake,
):
    """LAK, its tables, observations and sidecars; returns the mover rows so far."""
    # LAK (lake / reservoir) package. Built after model.wel and before model.oc.
    # Lake cells were already made inactive above, so the CONNECTIONDATA targets
    # active aquifer neighbors only. Controlled transfers (LAK -> LAK, SFR -> LAK,
    # LAK -> SFR, DRN -> SFR) ride MVR, which is GWF-scoped and MUST be built last.
    all_mover_rows: list[list[object]] = list(drainage_mover_rows)
    n_lakes_built = 0
    lake_connections: list[list[object]] = []
    if lake_cell_ids_by_lake:
        lak_args = build_lak_package_args(
            model,
            solver_mesh=solver_mesh,
            lake_cell_ids_by_lake=lake_cell_ids_by_lake,
            occupied_layers_by_cell=getattr(model, "_lake_occupied_layers_by_cell", None),
            # A lake is fed by a mover from SFR, or from DRN when the descent of a
            # drain cell meets the lake before any reach. LAK must announce MOVER
            # for either, or MODFLOW 6 stops at the first DRN-to-LAK record.
            external_mover_to_lake=any(record.receiver == "LAK" for record in sfr_mover_records)
            or mover_rows_reach_lake(drainage_mover_rows),
            downstream_reach_by_lake=downstream_reach_by_lake,
        )
        if lak_args is not None:
            laktab_specs = lak_args.pop("laktab_specs")
            mover_records = lak_args.pop("mover_records", None)
            lak_args.pop("mover_maxpackages", 0)
            obs_continuous = lak_args.pop("obs_continuous", None)
            lake_obs_meta = lak_args.pop("lake_obs_meta", None)
            ts_specs = lak_args.pop("ts_specs", None)
            n_lakes_built = int(lak_args["nlakes"])
            lake_connections = lak_args["connectiondata"]
            lak = flopy.mf6.ModflowGwflak(model.gwf, pname="LAK", **lak_args)
            # Non-constant forcings routed to an external TS6 file: attach right
            # after construction so the series names are registered before write.
            if ts_specs:
                attach_time_series(lak, ts_specs, filename=f"{model.model_output_name}.lak.ts")
            for spec in laktab_specs:
                flopy.mf6.ModflowUtllaktab(
                    model.gwf,
                    nrow=len(spec["table"]),
                    ncol=3,
                    table=spec["table"],
                    filename=spec["filename"],
                    parent_file=lak,
                )
            # OBS6 for the per-lake output series, plus a JSON sidecar the
            # extractor reads to re-key the obs CSV by (lake_id, totim).
            if obs_continuous:
                lak.obs.initialize(
                    filename=f"{model.model_output_name}.lak.obs",
                    digits=10,
                    print_input=False,
                    continuous=obs_continuous,
                )
            if lake_obs_meta is not None:
                _write_sidecar(model, ".lak.meta.json", lake_obs_meta)
            # Persist the bed-reconstruction abacus comparison for the QC figure.
            _write_lake_abacus_meta(model)
            model.lak = lak
            if mover_records:
                all_mover_rows.extend(mover_records)
            # Active-littoral lakes with exposed_band_runoff need the in-process BMI
            # runner: build the per-lake coupling specs now (lake order == LAK ifno).
            # Their presence flips the runner to 'api' and attaches the callback.
            band_specs = build_exposed_band_runoff_specs(model)
            if band_specs:
                model._exposed_band_runoff_specs = band_specs
    return all_mover_rows, n_lakes_built, lake_connections


def _build_flow_barriers(
    model,
    solver_mesh: SolverMesh,
    lake_cell_ids_by_lake,
    lake_connections,
):
    """HFB on the cutoff walls and the flow barriers."""
    # HFB (horizontal flow barrier): thin vertical low-K walls on shared cell faces
    # (lake dam cutoff walls + general flow_barriers). Static (period 0), built
    # after LAK and after NPF (it scales the NPF horizontal conductance) so the
    # under-dam seepage dives below the wall. No MVR coupling.
    hfb_rows = resolve_flow_barrier_hfb_rows(model, solver_mesh, lake_cell_ids_by_lake)
    check_cutoff_wall_seal(model, solver_mesh, lake_cell_ids_by_lake, lake_connections, hfb_rows)
    if hfb_rows:
        n_faces = len({(row[0][1], row[1][1]) for row in hfb_rows})
        logger.info(
            "HFB cutoff wall: %d barrier rows over %d shared faces.", len(hfb_rows), n_faces
        )
        model.hfb = flopy.mf6.ModflowGwfhfb(
            model.gwf,
            pname="HFB",
            maxhfb=len(hfb_rows),
            stress_period_data={0: hfb_rows},
        )


def _build_sfr(
    model,
    solver_mesh: SolverMesh,
    sfr_networks,
    sfr_mover_records,
    all_mover_rows,
    n_lakes_built,
):
    """SFR, its observations and sidecar; adds its movers to ``all_mover_rows``."""
    # SFR (streamflow routing) package. Built after LAK so the SFR -> LAK mover
    # seam can reference an existing lake, and before OC / MVR.
    if sfr_networks:
        if sfr_mover_records and getattr(model, "lak", None) is None:
            raise ValueError(
                "flow.sinks_sources.sfr declares outflow_to_lake but no lake is "
                "active; enable the lake boundary or drop the coupling."
            )
        for record in sfr_mover_records:
            if record.receiver == "LAK" and record.receiver_id >= n_lakes_built:
                raise ValueError(
                    f"flow.sinks_sources.sfr outflow_to_lake={record.receiver_id + 1} "
                    f"has no matching lake ({n_lakes_built} lakes declared)."
                )
        # A LAK -> SFR spillway or a DRN -> SFR drainage routing makes SFR an MVR
        # receiver: the package advertises MOVER and the per-reach to/from-mvr
        # series are observed even with no SFR-owned mover record.
        sfr_args = build_sfr_package_args(
            model,
            networks=sfr_networks,
            external_mover=any(str(row[2]) == "SFR" for row in all_mover_rows),
            has_mover_records=bool(sfr_mover_records),
            solver_mesh=solver_mesh,
        )
        if sfr_args is not None:
            sfr_obs_continuous = sfr_args.pop("obs_continuous", None)
            sfr_obs_meta = sfr_args.pop("sfr_obs_meta", None)
            sfr_ts_specs = sfr_args.pop("ts_specs", None)
            sfr = flopy.mf6.ModflowGwfsfr(model.gwf, pname="SFR", **sfr_args)
            if sfr_ts_specs:
                attach_time_series(sfr, sfr_ts_specs, filename=f"{model.model_output_name}.sfr.ts")
            if sfr_obs_continuous:
                sfr.obs.initialize(
                    filename=f"{model.model_output_name}.sfr.obs",
                    digits=10,
                    print_input=False,
                    continuous=sfr_obs_continuous,
                )
            if sfr_obs_meta is not None:
                _write_sidecar(model, ".sfr.meta.json", sfr_obs_meta)
            model.sfr = sfr
            if sfr_mover_records:
                all_mover_rows.extend(build_mvr_period_records(sfr_mover_records))


def _build_mover_and_output(model, all_mover_rows):
    """MVR, built last, then OC."""
    # MVR last: it routes provider features to receiver features by package name,
    # so every package it references must already exist. The packages list is
    # derived from the record rows so LAK-only, SFR-only and mixed models all
    # produce a consistent block.
    if all_mover_rows:
        mvr_packages = sorted(
            {(str(row[0]),) for row in all_mover_rows} | {(str(row[2]),) for row in all_mover_rows}
        )
        model.mvr = flopy.mf6.ModflowGwfmvr(
            model.gwf,
            pname="MVR",
            maxmvr=len(all_mover_rows),
            maxpackages=mover_package_count(all_mover_rows),
            packages=mvr_packages,
            perioddata={0: all_mover_rows},
        )

    model.oc = flopy.mf6.ModflowGwfoc(
        model.gwf,
        head_filerecord=f"{model.model_output_name}.hds",
        budget_filerecord=f"{model.model_output_name}.cbc",
        **output_control_records(print_head=model.modflow_config.runtime.print_head),
    )


def run_pre_processing(
    model,
    inputs: Model,
    options: ModflowPreprocessOptions | None = None,
    *,
    slot: RunSlot | None = None,
) -> None:
    """Run MODFLOW 6 pre_processing: assemble flopy packages and discretizations.

    ``slot`` is where the run solves. The build reads its shared forcing
    folder, and keeps it on the model for an auxiliary solve and for ``rerun``.
    A build without a slot keeps every file beside the model.

    The steps run in the order MODFLOW 6 and FloPy need: the grid is final once
    the lakes are masked, SFR resolves before DRN so a drain under a reach is
    dropped, LAK comes before SFR so the SFR to LAK movers find a lake, and MVR
    comes last because it names packages that must exist.
    """
    _settle_inputs(model, inputs, options, slot)
    temporal, time_units = _discretize_time(model)
    solver_mesh = _discretize_space(model)
    _map_hydraulic_properties(model, solver_mesh)
    runtime = _build_simulation(model, solver_mesh, temporal, time_units)
    solver_mesh, lake_cell_ids_by_lake = _mask_lakes(model, solver_mesh)
    ocean, stream, side_chd_spd = _resolve_constant_heads(model, solver_mesh)
    (
        descent,
        basin,
        lake_cells_by_number,
        sfr_networks,
        sfr_mover_records,
        downstream_reach_by_lake,
    ) = _resolve_streams(model, solver_mesh, lake_cell_ids_by_lake, side_chd_spd)
    _build_grid_packages(model, solver_mesh, runtime)
    _build_recharge_and_evt(model, solver_mesh, ocean[1], stream[1])
    drainage_mover_rows = _build_drains(
        model, solver_mesh, ocean[1], stream[1], sfr_networks, descent, basin, lake_cells_by_number
    )
    _build_constant_heads_and_wells(model, *ocean, *stream, side_chd_spd, runtime)
    all_mover_rows, n_lakes_built, lake_connections = _build_lakes(
        model,
        solver_mesh,
        lake_cell_ids_by_lake,
        sfr_mover_records,
        drainage_mover_rows,
        downstream_reach_by_lake,
    )
    _build_flow_barriers(model, solver_mesh, lake_cell_ids_by_lake, lake_connections)
    _build_sfr(model, solver_mesh, sfr_networks, sfr_mover_records, all_mover_rows, n_lakes_built)
    _build_mover_and_output(model, all_mover_rows)
