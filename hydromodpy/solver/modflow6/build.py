"""MODFLOW 6 pre_processing: flopy package wiring and grid template helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping

import flopy
import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    bind_recharge_from_flow,
    build_drain_stress_period_data,
    build_drainage_mover_records,
    build_evt_stress_period_data,
    build_exposed_band_runoff_specs,
    build_lak_package_args,
    build_mvr_period_records,
    build_ocean_boundary_chd_spd,
    build_sfr_mover_records,
    build_sfr_package_args,
    build_side_boundary_chd_spd,
    build_start_heads,
    build_stream_boundary_chd_spd,
    build_well_stress_period_data,
    carve_lake_bed,
    collapse_identical_periods,
    empty_recharge_aux,
    externalize_recharge_spd,
    finalize_pending_recharge_evt,
    log_xt3d_resolution,
    mask_recharge_on_lake_cells,
    mover_package_count,
    recharge_to_spd,
    remove_drain_cells,
    resolve_deferred_heterogeneous_recharge,
    resolve_drainage_conductance_series,
    resolve_flow_barrier_hfb_rows,
    resolve_ims_complexity,
    resolve_lake_cells_for_active_lakes,
    resolve_lake_occupied_layers,
    resolve_rewet_npf_options,
    resolve_sfr_networks,
    resolve_xt3d_npf_options,
    sfr_drain_cells_to_drop,
    sto_period_settings,
    watershed_drainage_cell_mask,
    xt3d_activation_mode,
    xt3d_requested_value,
)
from hydromodpy.solver.modflow6.common import attach_time_series
from hydromodpy.solver.modflow6.flopy_header_cache import install_flopy_header_cache
from hydromodpy.solver.modflow6.mesh_conditioning import condition_solver_mesh_top
from hydromodpy.solver.modflow6.property_mapping import (
    fill_missing_flow_properties_from_mesh_support,
    resolve_flow_property_arrays,
    resolve_k33_field,
    resolve_required_flow_properties,
)
from hydromodpy.solver.modflow6.runtime_reuse import (
    can_refresh_runtime_reuse,
    refresh_reused_runtime_property_packages,
    runtime_reuse_signature,
)
from hydromodpy.solver.modflow_common import (
    ModflowPreprocessOptions,
    SolverRoutingContext,
    build_solver_routing_context,
    write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_grid import (
    build_spatial_discretization,
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)

logger = get_logger(__name__)


def mf6_safe_name(name: str, max_len: int = 16) -> str:
    """Return a safe MODFLOW 6 model name, hashed when longer than max_len."""
    text = str(name)
    if len(text) <= max_len:
        return text
    if max_len <= 6:
        return text[:max_len]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    prefix_len = max_len - 7
    return f"{text[:prefix_len]}_{digest}"


def mf6_output_name(model, extension: str = ".cbc") -> str:
    """Return an output file stem that keeps MF6 paths usable on Windows."""
    requested = str(getattr(model, "model_name", "") or "model")
    if os.name != "nt":
        return requested
    candidate = os.path.join(str(model.full_path), f"{requested}{extension}")
    if len(os.path.abspath(candidate)) < 240:
        return requested
    return str(getattr(model, "model_name_mf6", "") or mf6_safe_name(requested))


def _write_lake_obs_meta(model, lake_obs_meta: Mapping[str, object]) -> None:
    """Persist the LAK obs sidecar next to the solver files for the extractor.

    The extractor reads ``{model_output_name}.lak.meta.json`` from the solver
    output directory to re-key the LAK obs CSV by ``(lake_id, totim)`` and isolate
    the under-dam leakage. The sidecar travels with the model files so post-run
    extraction needs no live flopy object.
    """
    meta_path = os.path.join(str(model.full_path), f"{model.model_output_name}.lak.meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(dict(lake_obs_meta), fh, sort_keys=True)


def _write_lake_abacus_meta(model) -> None:
    """Persist the lake abacus comparison sidecar for the extractor.

    Serializes ``model._lake_bed_reconstruction`` (reference + simulated abacus
    arrays per lake) to ``{model_output_name}.lake_abacus.json`` so the post-run
    extractor can land it in the per-sim Zarr for the comparison figure.
    """
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
    if not entries:
        return
    meta_path = os.path.join(str(model.full_path), f"{model.model_output_name}.lake_abacus.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"entries": entries}, fh, sort_keys=True)


def _write_sfr_obs_meta(model, sfr_obs_meta: Mapping[str, object]) -> None:
    """Persist the SFR obs sidecar (``{stem}.sfr.meta.json``) for the extractor."""
    meta_path = os.path.join(str(model.full_path), f"{model.model_output_name}.sfr.meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(dict(sfr_obs_meta), fh, sort_keys=True)


def _shared_recharge_dir(model) -> str | None:
    """Return the shared recharge directory for a calibration trial, else None.

    The calibration ``TrialSandbox`` writes each trial into a
    ``<scratch>/<base>_trialNNNNNN/`` folder shared by all trials. The recharge is
    invariant across trials, so it lives once in a sibling ``_shared_recharge``
    dir and every trial references it (see ``externalize_recharge_spd``). A
    non-trial single run returns None and keeps the per-model binary layout.

    The trial marker is the ``_trialNNNNNN`` PATH COMPONENT (the sandbox folder),
    found by walking ``full_path`` up: ``model_name_mf6`` (the ``full_path`` leaf)
    is truncated to 16 chars by ``mf6_safe_name`` and drops the suffix, and the
    trial folder can sit at either the leaf or its parent depending on the
    workspace layout. The shared dir is a sibling of the trial folder.
    """
    full_path = getattr(model, "full_path", None)
    if not full_path:
        return None
    path = os.path.normpath(str(full_path))
    while path and path not in (os.sep, "."):
        head, tail = os.path.split(path)
        if re.search(r"_trial\d{6}$", tail):
            return os.path.join(head, "_shared_recharge")
        if head == path:
            break
        path = head
    return None


def _watershed_drainage_mask(model, cell_centroids: np.ndarray) -> np.ndarray | None:
    """Cells inside the topographic watershed, to keep DRN routing off the buffer.

    The active domain is the buffered box, so DRN cells in the buffer model the
    neighbouring basins. Their hillslope drainage must leave the model (plain
    DRN), not feed this catchment's streams and lake, so they are excluded from
    the DRN -> MVR routing. Returns ``None`` when the watershed polygon is
    unavailable (keeps every remaining DRN cell routed).
    """
    geographic = getattr(model, "geographic", None)
    shp = getattr(geographic, "watershed_shp", None)
    if not shp or not os.path.exists(str(shp)):
        logger.warning(
            "watershed polygon not found (%s); hillslope DRN routes over the full "
            "buffered domain, over-feeding this catchment's surface water.",
            shp,
        )
        return None
    import geopandas as gpd

    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        return None
    mask = watershed_drainage_cell_mask(gdf.geometry.union_all(), cell_centroids)
    n_in = int(mask.sum())
    logger.info(
        "watershed DRN mask: %d/%d active cells inside the catchment; "
        "buffer DRN drains out instead of feeding the streams.",
        n_in,
        int(mask.size),
    )
    return mask


def _resolve_channel_mask_for_zonal(model) -> np.ndarray | None:
    """Boolean channel-pixel mask aligned to ``surface_topo`` for zonal top sampling.

    Only produced when ``sgrid.top_sampling.mode == 'zonal'`` and its
    ``channel_source`` requests one. Reads the delineated stream raster and
    reprojects it (nearest) onto the model-top DEM grid. Returns ``None`` (channel
    class disabled, every pixel treated as hillslope) when zonal is off, the
    source is 'none', or no stream raster / georeferenced surface is available.
    """
    sgrid_cfg = getattr(model.modflow_config, "sgrid", None)
    top_sampling = getattr(sgrid_cfg, "top_sampling", None)
    if top_sampling is None or top_sampling.mode != "zonal":
        return None
    if top_sampling.channel_source == "none":
        return None

    geographic = getattr(model, "geographic", None)
    path = None
    for name in ("river_stream_link_id_tif", "river_streams_tif"):
        candidate = getattr(geographic, name, None)
        if candidate and os.path.exists(str(candidate)):
            path = str(candidate)
            break
    if path is None:
        logger.warning(
            "Zonal channel_source=%s but no stream raster found; the channel class "
            "is disabled (every DEM pixel treated as hillslope).",
            top_sampling.channel_source,
        )
        return None

    surface = getattr(model.domain, "surface_topo", None)
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
    dst = np.zeros(out_shape, dtype=np.float64)
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
                dst_nodata=0.0,
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


def xt3d_requested(model) -> bool | None:
    """Return the configured XT3D override."""
    return xt3d_requested_value(model)


def xt3d_mode(model, solver_mesh=None) -> str:
    """Return the XT3D activation mode."""
    return xt3d_activation_mode(model, solver_mesh)


def resolve_xt3d_options(model, solver_mesh=None) -> list[str] | None:
    """Return FloPy NPF XT3D options."""
    return resolve_xt3d_npf_options(model, solver_mesh)


def resolve_ims_complexity_for(model, solver_mesh=None) -> str:
    """Return the resolved IMS complexity."""
    return resolve_ims_complexity(model, solver_mesh)


def newton_options(runtime) -> list[str] | None:
    """Return MF6 GWF newtonoptions. Catchment cells are convertible, so Newton
    with under-relaxation is the robust default."""
    if not runtime.mf6_newton:
        return None
    options = ["NEWTON"]
    if runtime.mf6_newton_under_relaxation:
        options.append("UNDER_RELAXATION")
    return options


def guard_newton_rewet(runtime, rewet_record) -> None:
    """Reject NEWTON + REWET: MF6 forbids rewetting under the Newton formulation,
    which uses continuous upstream weighting."""
    if runtime.mf6_newton and rewet_record is not None:
        raise ValueError(
            "[HMPY.E405] mf6_newton and mf6_enable_rewet are mutually exclusive in "
            "MODFLOW 6: the Newton formulation uses continuous upstream weighting and "
            "forbids NPF rewetting. Disable one of them."
        )


def guard_newton_linear_acceleration(runtime) -> None:
    """Reject CG linear acceleration under Newton: the Newton formulation builds
    a non-symmetric Jacobian, which the conjugate-gradient solver (symmetric
    matrices only) cannot solve. BICGSTAB is required."""
    if runtime.mf6_newton and runtime.mf6_linear_acceleration == "CG":
        raise ValueError(
            "[HMPY.E406] mf6_linear_acceleration='CG' is invalid with "
            "mf6_newton=True: the MODFLOW 6 Newton formulation produces a "
            "non-symmetric Jacobian that CG cannot solve. Use BICGSTAB, or leave "
            "mf6_linear_acceleration unset to keep the preset default."
        )


def optional_ims_kwargs(runtime) -> dict[str, object]:
    """Return the optional IMS knobs that are set; None values keep flopy presets."""
    kwargs: dict[str, object] = {}
    if runtime.mf6_inner_rclose is not None:
        # flopy exposes inner_rclose only through the rcloserecord record
        # (inner_rclose + rclose_option). The empty option keeps MF6's default
        # absolute infinity-norm criterion (sln-ims.dfn: no option = infinity).
        kwargs["rcloserecord"] = [(float(runtime.mf6_inner_rclose), "")]
    if runtime.mf6_linear_acceleration is not None:
        kwargs["linear_acceleration"] = runtime.mf6_linear_acceleration
    if runtime.mf6_under_relaxation is not None:
        kwargs["under_relaxation"] = runtime.mf6_under_relaxation
    return kwargs


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

    model.routing_ctx = build_solver_routing_context(
        dem_path=model.dem_watershed_path,
        output_dir=os.path.join(model.full_path, "_solver_routing"),
        dem_correc_type=str(getattr(model.geographic, "dem_correc_type", "breach")),
        crs_project=getattr(model.geographic, "crs_proj", None),
    )
    return model.routing_ctx


def resolve_flow_regime(model) -> str | None:
    """Resolve the flow regime label from the bound flow config."""
    if model.flow is None:
        return None

    flow_regime = None
    flow_cfg = getattr(model.flow, "config", None)
    if flow_cfg is not None:
        flow_regime = getattr(flow_cfg, "flow_regime", None)
    if flow_regime is None:
        flow_regime = getattr(model.flow, "flow_regime", None)
    if flow_regime is None:
        return None

    return normalize_flow_regime(flow_regime)


def validate_pre_processing_inputs(model) -> None:
    """Validate that flow, domain and time grid are configured for pre_processing."""
    if model.flow is None:
        raise ValueError("pre_processing requires a configured Flow object.")
    if model.domain is None:
        raise ValueError("pre_processing requires a configured Domain object.")
    flow_regime = resolve_flow_regime(model)
    if flow_regime is None:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
    model.flow_regime = flow_regime
    if model.time_grid is None and model.flow_regime != "steady":
        raise ValueError(
            "Launcher flow preprocessing requires preprocess_options.time_grid "
            "derived from [simulation.time] for transient flow runs. Solver tgrid fallback is no longer supported."
        )


def select_active_dem(model, box: bool) -> None:
    """Select the DEM raster to use according to the box option."""
    if box:
        model.dem_watershed_path = model.geographic.watershed_box_buff_dem
    else:
        model.dem_watershed_path = model.geographic.watershed_buff_dem


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
    model.recharge = getattr(options, "recharge", None)
    model.first_clim = getattr(options, "first_clim", None)
    model.time_grid = getattr(options, "time_grid", None)
    model.check_grid = bool(options.check_grid)
    select_active_dem(model, box=bool(options.box))


def run_pre_processing(  # noqa: PLR0915
    model,
    flow: object,
    domain: DomainLike,
    options: ModflowPreprocessOptions | None = None,
    *,
    mesh_planar: object | None = None,
    mesh_support: object | None = None,
    flow_runtime_overrides: Mapping[str, object] | None = None,
) -> None:
    """Run MODFLOW 6 pre_processing: assemble flopy packages and discretizations."""
    install_flopy_header_cache()
    model.flow = flow
    model.domain = domain
    model.runtime_mesh_planar = mesh_planar
    model.runtime_mesh_support = mesh_support
    model._flow_runtime_overrides = flow_runtime_overrides
    active_options = model.preprocess_options if options is None else options
    apply_preprocess_options(model, active_options)
    validate_pre_processing_inputs(model)
    # Reject invalid solver-config combinations before any expensive grid build.
    guard_newton_linear_acceleration(model.modflow_config.runtime)
    bind_recharge_from_flow(model)
    model._calibration_raw_output_payload_cache = {}

    model.flow_regime = resolve_flow_regime(model) or "transient"
    reuse_signature = runtime_reuse_signature(
        model,
        flow=flow,
        domain=domain,
        options=active_options,
        mesh_planar=mesh_planar,
        mesh_support=mesh_support,
    )
    if can_refresh_runtime_reuse(
        model,
        flow=flow,
        domain=domain,
        options=active_options,
        mesh_planar=mesh_planar,
        mesh_support=mesh_support,
        flow_runtime_overrides=flow_runtime_overrides,
    ):
        model._runtime_dirty_packages = refresh_reused_runtime_property_packages(
            model,
            flow_runtime_overrides=flow_runtime_overrides,
        )
        model._calibration_runtime_reuse_signature = reuse_signature
        return
    launcher_time_grid = model.time_grid
    temporal = build_temporal_discretization_from_time_grid(
        time_grid=launcher_time_grid,
        flow_regime=model.flow_regime,
        first_period_steady=resolve_first_period_steady(
            flow=getattr(model, "flow", None),
        ),
    )
    model.perlen = temporal.perlen
    model.nper = temporal.nper
    model.nstp = temporal.nstp
    model.steady = temporal.steady
    # MF6 runs in SI seconds: the launcher delivers perlen in seconds, so TDIS
    # declares SECONDS and the output budget factor stays exactly 1.0. The flow
    # extractor converts fluxes back from this declared unit.
    time_units = "seconds"
    finalize_pending_recharge_evt(model)

    model.grid_ctx = build_spatial_discretization(
        domain=model.domain,
        sgrid_config=getattr(model.modflow_config, "sgrid", None),
        runtime_planar_mesh=model.runtime_mesh_planar,
        channel_mask=_resolve_channel_mask_for_zonal(model),
    )
    solver_mesh = model.grid_ctx.solver_mesh
    model.solver_mesh = solver_mesh
    model.top_elevation = solver_mesh.top  # (ncpl,)
    model.inactive_mask = solver_mesh.inactive_mask[0]  # (ncpl,)
    model.nlay = solver_mesh.nlay
    model.ncpl = solver_mesh.n_cells
    if solver_mesh.is_structured:
        model.nrow = solver_mesh.nrow
        model.ncol = solver_mesh.ncol
    model.cell_area = float(model.grid_ctx.grid.cell_area)
    model.resolution = float(model.grid_ctx.grid.characteristic_length)
    model.dem = model.top_elevation  # flat (ncpl,)
    model.dem_mask = model.inactive_mask  # flat (ncpl,)
    model.dem_watershed_path = write_solver_grid_template(model)

    resolve_deferred_heterogeneous_recharge(model)

    flow_params = resolve_flow_property_arrays(
        flow=model.flow,
        domain=model.domain,
        solver_mesh=solver_mesh,
        planar_mesh=model.runtime_mesh_planar,
        required_properties=resolve_required_flow_properties(flow_regime=model.flow_regime),
        optional_fill_values={"Sy": 0.0, "Ss": 0.0},
        runtime_property_overrides=flow_runtime_overrides,
    )
    flow_params = fill_missing_flow_properties_from_mesh_support(
        flow_params,
        mesh_support=model.runtime_mesh_support,
        solver_mesh=solver_mesh,
    )
    model.hk = solver_mesh.flatten_from_grid(flow_params["hk"])
    model.sy = solver_mesh.flatten_from_grid(flow_params["sy"])
    model.ss = solver_mesh.flatten_from_grid(flow_params["ss"])
    kv_field = solver_mesh.flatten_from_grid(flow_params["kv"]) if "kv" in flow_params else None
    model.k33 = resolve_k33_field(
        model.hk,
        kv_field,
        model.modflow_config.process_specific.vka,
        label="flow vertical anisotropy",
    )
    log_xt3d_resolution(model, solver_mesh)

    runtime = model.modflow_config.runtime
    sim_name = model.model_name_mf6
    model.sim = flopy.mf6.MFSimulation(
        sim_name=sim_name, sim_ws=model.full_path, exe_name=model.exe
    )
    # MF6 TDIS START_DATE_TIME is a free-form ISO 8601 string (flopy rejects a
    # datetime object). None means no calendar anchor is written.
    start_date_time = (
        temporal.start_datetime.isoformat() if temporal.start_datetime is not None else None
    )
    model.tdis = flopy.mf6.ModflowTdis(
        model.sim,
        nper=int(model.nper),
        perioddata=[
            (float(model.perlen[i]), int(model.nstp[i]), 1.0) for i in range(int(model.nper))
        ],
        time_units=time_units,
        start_date_time=start_date_time,
    )
    model.ims = flopy.mf6.ModflowIms(
        model.sim,
        print_option="SUMMARY" if runtime.mf_verbose else "NONE",
        complexity=resolve_ims_complexity_for(model, solver_mesh),
        outer_dvclose=float(runtime.mf6_outer_dvclose),
        inner_dvclose=float(runtime.mf6_inner_dvclose),
        outer_maximum=int(runtime.mf6_outer_maximum),
        inner_maximum=int(runtime.mf6_inner_maximum),
        filename=f"{model.model_name_mf6}_gwf.ims",
        pname="IMS_GWF",
        **optional_ims_kwargs(runtime),
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

    # Lake cells are made inactive (idomain=0) before DISV is built so the LAK
    # footprint stays consistent across idomain, dem_mask, RCH, EVT and DRN. LAK
    # supplies the storage and lake-aquifer exchange through its own
    # CONNECTIONDATA (built later from this same lake mask).
    lake_cell_ids_by_lake = resolve_lake_cells_for_active_lakes(model, solver_mesh)
    occupied_layers_by_lake = resolve_lake_occupied_layers(model)
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
        # A carved bed cuts a per-cell number of layers (deep centre vs shallow
        # rim); the carve stashes that map so the mask follows the real basin.
        occupied_layers_by_cell = getattr(model, "_lake_occupied_layers_by_cell", None)
        solver_mesh = apply_lake_idomain_mask(
            solver_mesh,
            lake_cell_ids_by_lake=inactive_lakes,
            occupied_layers_by_lake=occupied_layers_by_lake,
            occupied_layers_by_cell=occupied_layers_by_cell,
        )
        model.solver_mesh = solver_mesh
        model.inactive_mask = solver_mesh.inactive_mask[0]
        model.dem_mask = model.inactive_mask

    # Projecting the DEM onto irregular Voronoi cells reintroduces closed
    # depressions the raster fill removed. Condition the mesh top so every active
    # non-lake cell drains to the boundary. Lakes (marnage cells kept low) and the
    # idomain edge are base levels; only the top is raised, never the bottom.
    sgrid_cfg = getattr(model.modflow_config, "sgrid", None)
    if sgrid_cfg is not None and getattr(sgrid_cfg, "condition_top", False):
        # Every lake cell is a fixed base level: a reservoir bed is a legitimate
        # low, so the fill must drain INTO it, never raise it. Fixed-area lakes are
        # already inactive (skipped); the ones that matter here are the active
        # marnage cells whose carved bed would otherwise flood to its spill level.
        lake_cells = {cid for cells in lake_cell_ids_by_lake.values() for cid in cells}
        solver_mesh, cond_info = condition_solver_mesh_top(
            solver_mesh,
            getattr(model, "runtime_mesh_support", None),
            protected_cells=lake_cells,
            epsilon=float(getattr(sgrid_cfg, "condition_top_epsilon", 1e-3)),
        )
        model.solver_mesh = solver_mesh
        if cond_info["unreached_active"]:
            logger.warning(
                "Mesh top conditioning could not drain %d active cells (no mesh face "
                "graph or isolated basins); their pits remain.",
                cond_info["unreached_active"],
            )
        logger.info(
            "Mesh top conditioned: %d cells raised (max +%.2f m, mean +%.2f m) to "
            "remove closed depressions.",
            cond_info["cells_raised"],
            cond_info["max_raise_m"],
            cond_info["mean_raise_m"],
        )

    idomain = solver_mesh.idomain()

    # SFR reaches resolve on the post-lake-mask mesh so every reach cell is an
    # active aquifer cell. Resolution happens before DRN so the drain rows
    # coincident with a reach can be dropped (baseflow discharges to the stream,
    # not out of the model); the package itself is built after LAK.
    lake_cells_by_number = {
        index: list(cells) for index, cells in enumerate(lake_cell_ids_by_lake.values())
    }
    # SFR resolves against the lake cells so trace reaches are truncated at the
    # shoreline (never left sitting on a LAK cell once the DEM routes a stream
    # through the lake), then the mover builder hands their flow to that lake.
    sfr_networks = resolve_sfr_networks(
        model, solver_mesh=solver_mesh, lake_cells_by_number=lake_cells_by_number
    )
    _geo = getattr(model, "geographic", None)
    _x_out = getattr(_geo, "x_outlet", None)
    _y_out = getattr(_geo, "y_outlet", None)
    sfr_outlet_xy = (
        (float(_x_out), float(_y_out)) if _x_out is not None and _y_out is not None else None
    )
    sfr_mover_records = build_sfr_mover_records(
        sfr_networks,
        lake_cells_by_number=lake_cells_by_number,
        cell_centroids=solver_mesh.cell_centroids(),
        outlet_xy=sfr_outlet_xy,
    )

    # MF6 uses DISV for every grid (structured and unstructured) so one code path
    # covers both. Native DIS is reserved for the NWT backend, which only supports
    # structured grids.
    disv_kwargs = solver_mesh.to_disv_kwargs()
    # DISV vertices already hold absolute model coordinates (UTM/Lambert meters),
    # so the package origin must be 0. Passing solver_mesh.xoffset here would shift
    # the whole grid by one full origin (double offset).
    model.dis = flopy.mf6.ModflowGwfdisv(
        model.gwf,
        nlay=solver_mesh.nlay,
        **disv_kwargs,
        idomain=idomain,
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )

    strt = build_start_heads(model, solver_mesh)
    model.ic = flopy.mf6.ModflowGwfic(model.gwf, strt=strt)
    ocean_chd_spd, ocean_support_mask = build_ocean_boundary_chd_spd(model)
    stream_chd_spd, stream_support_mask = build_stream_boundary_chd_spd(model)
    model._ocean_support_mask = np.asarray(ocean_support_mask, dtype=bool).copy()
    model._stream_support_mask = np.asarray(stream_support_mask, dtype=bool).copy()
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
        rewet_record=rewet_record,
        xt3doptions=xt3doptions,
        wetdry=wetdry,
        save_specific_discharge=True,
        save_saturation=True,
    )
    steady_state_spd, transient_spd = sto_period_settings(
        [bool(model.steady[i]) for i in range(int(model.nper))]
    )
    model.sto = flopy.mf6.ModflowGwfsto(
        model.gwf,
        sy=model.sy,
        ss=model.ss,
        iconvert=np.ones((model.nlay,), dtype=int),
        steady_state=steady_state_spd or None,
        transient=transient_spd or None,
    )

    model.rch_spd = recharge_to_spd(model)
    if model._lake_cell_ids:
        model.rch_spd = mask_recharge_on_lake_cells(
            model.rch_spd, lake_cell_ids=model._lake_cell_ids
        )
    model.rch_spd = collapse_identical_periods(model.rch_spd)
    model.rch = flopy.mf6.ModflowGwfrcha(
        model.gwf,
        recharge=externalize_recharge_spd(
            model.rch_spd,
            basename=model.model_name_mf6,
            shared_dir=_shared_recharge_dir(model),
        ),
        auxiliary=["CONCENTRATION"],
        aux=empty_recharge_aux(model),
        pname="RCHA",
    )
    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=ocean_support_mask,
        stream_support_mask=stream_support_mask,
        lake_cell_ids=model._lake_cell_ids,
    )
    if evt_spd is not None:
        maxbound = max((len(period_cells) for period_cells in evt_spd.values()), default=0)
        model.evt = flopy.mf6.ModflowGwfevt(
            model.gwf,
            stress_period_data=collapse_identical_periods(evt_spd),
            maxbound=maxbound,
            save_flows=True,
        )

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
        if marnage_cells:
            drn_spd = remove_drain_cells(
                drn_spd,
                cells={int(cid) for cells in marnage_cells.values() for cid in cells},
            )
        if sfr_networks:
            drn_spd = remove_drain_cells(drn_spd, cells=sfr_drain_cells_to_drop(sfr_networks))
            # route_drainage: every in-watershed DRN cell hands its discharge to the
            # nearest reach, or to the coupled lake when its shoreline is closer
            # (MVR), so the hillslope drainage converges to the surface water
            # instead of leaving the model. Buffer cells model neighbouring basins
            # and stay plain DRN (they must not feed this catchment). The provider
            # ids index the period-0 rows, hence the static-DRN requirement.
            drn_cell_centroids = solver_mesh.cell_centroids()
            drainage_movers = build_drainage_mover_records(
                sfr_networks,
                drn_spd=drn_spd,
                cell_centroids=drn_cell_centroids,
                lake_cells_by_number={
                    index: list(cells) for index, cells in enumerate(lake_cell_ids_by_lake.values())
                },
                watershed_cell_mask=_watershed_drainage_mask(model, drn_cell_centroids),
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

    side_chd_spd = build_side_boundary_chd_spd(model)
    chd_spd: dict[int, list[list[float]]] = {}
    for kper in range(int(model.nper)):
        period_map: dict[tuple[int, int], list[float]] = {}
        for entry in ocean_chd_spd.get(kper, []):
            period_map[(int(entry[0]), int(entry[1]))] = entry
        for entry in stream_chd_spd.get(kper, []):
            period_map[(int(entry[0]), int(entry[1]))] = entry
        for entry in side_chd_spd.get(kper, []):
            period_map[(int(entry[0]), int(entry[1]))] = entry
        chd_spd[kper] = list(period_map.values())
    chd_spd = collapse_identical_periods(chd_spd)
    if any(len(v) > 0 for v in chd_spd.values()):
        model.chd = flopy.mf6.ModflowGwfchd(model.gwf, stress_period_data=chd_spd, save_flows=True)

    wel_spd = build_well_stress_period_data(model, int(model.nper))
    if any(len(v) > 0 for v in wel_spd.values()):
        model.wel = flopy.mf6.ModflowGwfwel(model.gwf, stress_period_data=wel_spd, save_flows=True)

    model.model_output_name = mf6_output_name(model)

    # LAK (lake / reservoir) package. Built after model.wel and before model.oc.
    # Lake cells were already made inactive above, so the CONNECTIONDATA targets
    # active aquifer neighbours only. Controlled transfers (LAK -> LAK, SFR -> LAK,
    # LAK -> SFR, DRN -> SFR) ride MVR, which is GWF-scoped and MUST be built last.
    all_mover_rows: list[list[object]] = list(drainage_mover_rows)
    n_lakes_built = 0
    if lake_cell_ids_by_lake:
        lak_args = build_lak_package_args(
            model,
            solver_mesh=solver_mesh,
            lake_cell_ids_by_lake=lake_cell_ids_by_lake,
            occupied_layers_by_cell=getattr(model, "_lake_occupied_layers_by_cell", None),
            # DRN movers always target SFR by design (never a direct DRN -> LAK
            # record), so only the SFR movers can feed a lake externally.
            external_mover_to_lake=any(record.receiver == "LAK" for record in sfr_mover_records),
        )
        if lak_args is not None:
            laktab_specs = lak_args.pop("laktab_specs")
            mover_records = lak_args.pop("mover_records", None)
            lak_args.pop("mover_maxpackages", 0)
            obs_continuous = lak_args.pop("obs_continuous", None)
            lake_obs_meta = lak_args.pop("lake_obs_meta", None)
            ts_specs = lak_args.pop("ts_specs", None)
            n_lakes_built = int(lak_args["nlakes"])
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
                _write_lake_obs_meta(model, lake_obs_meta)
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

    # HFB (horizontal flow barrier): thin vertical low-K walls on shared cell faces
    # (lake dam cutoff walls + general flow_barriers). Static (period 0), built
    # after LAK and after NPF (it scales the NPF horizontal conductance) so the
    # under-dam seepage dives below the wall. No MVR coupling.
    hfb_rows = resolve_flow_barrier_hfb_rows(model, solver_mesh)
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
                _write_sfr_obs_meta(model, sfr_obs_meta)
            model.sfr = sfr
            if sfr_mover_records:
                all_mover_rows.extend(build_mvr_period_records(sfr_mover_records))

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
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST")],
    )
    model._runtime_dirty_packages = ()
    model._calibration_runtime_reuse_signature = reuse_signature
