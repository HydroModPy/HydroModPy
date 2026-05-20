"""MODFLOW 6 pre_processing: flopy package wiring and grid template helpers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping

import flopy
import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.modflow6.builders import (
    bind_recharge_from_flow,
    build_drain_stress_period_data,
    build_evt_stress_period_data,
    build_ocean_boundary_chd_spd,
    build_side_boundary_chd_spd,
    build_start_heads,
    build_stream_boundary_chd_spd,
    build_well_stress_period_data,
    empty_recharge_aux,
    finalize_pending_recharge_evt,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
    resolve_drainage_conductance_series,
    resolve_ims_complexity,
    resolve_rewet_npf_options,
    resolve_xt3d_npf_options,
    xt3d_activation_mode,
    xt3d_is_enabled,
    xt3d_requested_value,
)
from hydromodpy.solver.modflow6.property_mapping import (
    fill_missing_flow_properties_from_mesh_support,
    resolve_flow_property_arrays,
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


def log_xt3d_resolution(model, solver_mesh=None) -> None:
    """Log the resolved XT3D mode."""
    logger.info(
        "MF6 XT3D resolution: mode=%s enabled=%s structured=%s",
        xt3d_mode(model, solver_mesh),
        xt3d_is_enabled(model, solver_mesh),
        bool(getattr(solver_mesh, "is_structured", True)),
    )


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
    model.flow = flow
    model.domain = domain
    model.runtime_mesh_planar = mesh_planar
    model.runtime_mesh_support = mesh_support
    model._flow_runtime_overrides = flow_runtime_overrides
    active_options = model.preprocess_options if options is None else options
    apply_preprocess_options(model, active_options)
    validate_pre_processing_inputs(model)
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
        firstpersteady=bool(
            getattr(getattr(model.modflow_config, "tgrid", None), "firstpersteady", True)
        ),
    )
    model.perlen = temporal.perlen
    model.nper = temporal.nper
    model.nstp = temporal.nstp
    model.steady = temporal.steady
    time_units = "seconds"
    finalize_pending_recharge_evt(model)

    model.grid_ctx = build_spatial_discretization(
        domain=model.domain,
        sgrid_config=getattr(model.modflow_config, "sgrid", None),
        runtime_planar_mesh=model.runtime_mesh_planar,
        runtime_mesh_support=model.runtime_mesh_support,
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
    log_xt3d_resolution(model, solver_mesh)

    runtime = model.modflow_config.runtime
    sim_name = model.model_name_mf6
    model.sim = flopy.mf6.MFSimulation(
        sim_name=sim_name, sim_ws=model.full_path, exe_name=model.exe
    )
    model.tdis = flopy.mf6.ModflowTdis(
        model.sim,
        nper=int(model.nper),
        perioddata=[
            (float(model.perlen[i]), int(model.nstp[i]), 1.0) for i in range(int(model.nper))
        ],
        time_units=time_units,
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
    )
    newtonoptions = None
    if bool(getattr(runtime, "mf6_newton", False)):
        newtonoptions = ["NEWTON"]
        if bool(getattr(runtime, "mf6_newton_under_relaxation", True)):
            newtonoptions.append("UNDER_RELAXATION")
    model.gwf = flopy.mf6.ModflowGwf(
        model.sim,
        modelname=model.model_name_mf6,
        save_flows=True,
        print_input=getattr(runtime, "mf_verbose", False),
        print_flows=getattr(runtime, "mf_verbose", False),
        newtonoptions=newtonoptions,
    )
    model.sim.register_ims_package(model.ims, [model.gwf.name])
    idomain = np.where(solver_mesh.inactive_mask, 0, 1).astype(int)

    disv_kwargs = solver_mesh.to_disv_kwargs()
    model.dis = flopy.mf6.ModflowGwfdisv(
        model.gwf,
        nlay=solver_mesh.nlay,
        **disv_kwargs,
        idomain=idomain,
        xorigin=float(solver_mesh.xoffset),
        yorigin=float(solver_mesh.yoffset),
        length_units="METERS",
    )

    strt = build_start_heads(model, solver_mesh)
    model.ic = flopy.mf6.ModflowGwfic(model.gwf, strt=strt)
    ocean_chd_spd, ocean_support_mask = build_ocean_boundary_chd_spd(model)
    stream_chd_spd, stream_support_mask = build_stream_boundary_chd_spd(model)
    model._ocean_support_mask = np.asarray(ocean_support_mask, dtype=bool).copy()
    model._stream_support_mask = np.asarray(stream_support_mask, dtype=bool).copy()
    rewet_record, wetdry = resolve_rewet_npf_options(model, solver_mesh)
    xt3doptions = resolve_xt3d_options(model, solver_mesh)

    model.npf = flopy.mf6.ModflowGwfnpf(
        model.gwf,
        icelltype=np.ones((model.nlay,), dtype=int),
        k=model.hk,
        k33=model.hk
        / max(
            float(
                getattr(
                    getattr(model.modflow_config, "process_specific", object()),
                    "vka",
                    1.0,
                )
            ),
            1e-12,
        ),
        rewet_record=rewet_record,
        xt3doptions=xt3doptions,
        wetdry=wetdry,
        save_specific_discharge=True,
        save_saturation=True,
    )
    model.sto = flopy.mf6.ModflowGwfsto(
        model.gwf,
        sy=model.sy,
        ss=model.ss,
        iconvert=np.ones((model.nlay,), dtype=int),
        steady_state={0: bool(model.steady[0])},
        transient={i: not bool(model.steady[i]) for i in range(int(model.nper))},
    )

    model.rch_spd = recharge_to_spd(model)
    model.rch = flopy.mf6.ModflowGwfrcha(
        model.gwf,
        recharge=model.rch_spd,
        auxiliary=["CONCENTRATION"],
        aux=empty_recharge_aux(model),
        pname="RCHA",
    )
    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=ocean_support_mask,
        stream_support_mask=stream_support_mask,
    )
    if evt_spd is not None:
        maxbound = max((len(period_cells) for period_cells in evt_spd.values()), default=0)
        model.evt = flopy.mf6.ModflowGwfevt(
            model.gwf,
            stress_period_data=evt_spd,
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
    if drainage_cond_series is not None:
        drn_spd = build_drain_stress_period_data(
            model,
            solver_mesh=solver_mesh,
            drainage_cond_series=np.asarray(drainage_cond_series, dtype=float),
            ocean_support_mask=np.asarray(ocean_support_mask, dtype=bool),
            stream_support_mask=np.asarray(stream_support_mask, dtype=bool),
        )
        model.drn = flopy.mf6.ModflowGwfdrn(model.gwf, stress_period_data=drn_spd, save_flows=True)

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
    if any(len(v) > 0 for v in chd_spd.values()):
        model.chd = flopy.mf6.ModflowGwfchd(model.gwf, stress_period_data=chd_spd, save_flows=True)

    wel_spd = build_well_stress_period_data(model, int(model.nper))
    if any(len(v) > 0 for v in wel_spd.values()):
        model.wel = flopy.mf6.ModflowGwfwel(model.gwf, stress_period_data=wel_spd, save_flows=True)

    model.oc = flopy.mf6.ModflowGwfoc(
        model.gwf,
        head_filerecord=f"{model.model_name}.hds",
        budget_filerecord=f"{model.model_name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST")],
    )
    model._runtime_dirty_packages = ()
    model._calibration_runtime_reuse_signature = reuse_signature
