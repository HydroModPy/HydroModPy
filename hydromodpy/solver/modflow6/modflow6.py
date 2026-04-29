"""MODFLOW 6 flow and transport solvers aligned with HydroModPy workflow APIs."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass

import flopy
import numpy as np

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.solver import Solver
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
    resolve_rewet_npf_options,
)
from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    _coerce_modflow6_config,
)
from hydromodpy.solver.modflow6.postprocess import (
    run_flow_post_processing,
)
from hydromodpy.solver.modflow6.property_mapping import (
    resolve_flow_property_arrays,
    resolve_required_flow_properties,
)
from hydromodpy.solver.modflow6.runtime_reuse import (
    can_refresh_runtime_reuse,
    refresh_reused_runtime_property_packages,
    runtime_reuse_signature,
)
from hydromodpy.solver.modflow_common import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    SolverRoutingContext,
    build_solver_routing_context,
    ensure_platform_executable,
    ensure_solver_binary,
    write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_grid import (
    SolverGridContext,
    build_spatial_discretization,
    build_temporal_discretization_from_time_grid,
)

logger = get_logger(__name__)


def _mf6_safe_name(name: str, max_len: int = 16) -> str:
    text = str(name)
    if len(text) <= max_len:
        return text
    if max_len <= 6:
        return text[:max_len]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    prefix_len = max_len - 7
    return f"{text[:prefix_len]}_{digest}"


@dataclass(frozen=True)
class Modflow6RuntimeParams:
    """Minimal runtime parameters for MODFLOW 6 simulation."""

    engine: str = "mf6"
    executable_name: str = "mf6"
    print_flows: bool = False
    print_input: bool = False
    save_flows: bool = True
    ims_complexity: str = "COMPLEX"


class Modflow6(Solver):
    """Flow solver based on MODFLOW 6 (GWF)."""

    def __init__(
        self,
        geographic: object,
        modflow_config: Modflow6Config | Mapping[str, object] | None = None,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str | None = None,
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            create_folder(self.model_folder)

        self.model_name = model_name
        self.model_name_mf6 = _mf6_safe_name(model_name)
        self.geographic = geographic
        self.flow = None
        self.domain = None
        self.flow_regime: str | None = None
        self.prob_cells = 0

        self.full_path = os.path.join(model_folder, model_name)
        self.dem_watershed_path = None
        self.grid_ctx: SolverGridContext | None = None
        self.routing_ctx: SolverRoutingContext | None = None

        self.modflow_config = _coerce_modflow6_config(modflow_config)
        runtime = self.modflow_config.runtime
        exe_name = getattr(runtime, "mf6_executable_name", None) or getattr(
            runtime, "executable_name", None
        )
        if exe_name and os.path.isabs(exe_name):
            self.exe = str(ensure_platform_executable(exe_name))
        elif not exe_name or exe_name in ("mf6", "mf6.exe"):
            self.exe = str(ensure_solver_binary("mf6", bin_path))
        else:
            self.exe = str(ensure_platform_executable(os.path.join(bin_path, exe_name)))

        self.resolution = geographic.dem_res
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        self.sink = getattr(geographic, "depressions_data", None)

        self.preprocess_options = preprocess_options or ModflowPreprocessOptions()
        self._apply_preprocess_options(self.preprocess_options)
        self._evt_rate_payload: dict[int, object] | None = None
        self._pending_negative_to_evt = False
        self._heterogeneous_recharge_source = None
        self._heterogeneous_negative_to_evt = False
        self._heterogeneous_interpolation_method = "nearest"

    def _select_active_dem(self, box: bool) -> None:
        if box:
            self.dem_watershed_path = self.geographic.watershed_box_buff_dem
        else:
            self.dem_watershed_path = self.geographic.watershed_buff_dem

    def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
        if options is None:
            options = self.preprocess_options
        if not isinstance(options, ModflowPreprocessOptions):
            raise TypeError("pre_processing options must be a ModflowPreprocessOptions instance.")

        self.preprocess_options = options
        self.sink_fill = bool(options.sink_fill)
        self.recharge = getattr(options, "recharge", None)
        self.first_clim = getattr(options, "first_clim", None)
        self.time_grid = getattr(options, "time_grid", None)
        self.check_grid = bool(options.check_grid)
        self._select_active_dem(box=bool(options.box))

    def _to_export_array(self, flat_array: np.ndarray) -> np.ndarray:
        """Reshape flat (ncpl,) to (nrow, ncol) for raster export (structured only)."""
        return self.solver_mesh.reshape_to_grid(flat_array)

    def _write_solver_grid_template(self) -> str:
        if self.grid_ctx is None:
            raise ValueError("grid_ctx must exist before writing a solver grid template")
        if not self.solver_mesh.is_structured:
            # No raster template for unstructured grids.
            return ""
        os.makedirs(self.full_path, exist_ok=True)
        template_path = os.path.join(self.full_path, "_solver_grid_template.tif")
        top_2d = self.solver_mesh.reshape_to_grid(self.solver_mesh.top)
        write_grid_array_to_raster(
            grid=self.grid_ctx.grid,
            data=top_2d,
            output_path=template_path,
            nodata=float(self.grid_ctx.grid.nodata),
        )
        self.grid_ctx.template_raster_path = template_path
        return template_path

    def _ensure_solver_routing_context(self) -> SolverRoutingContext:
        """Build hydrologic routing rasters aligned with the solver grid."""
        if self.routing_ctx is not None:
            return self.routing_ctx
        if self.grid_ctx is None:
            raise ValueError("grid_ctx must exist before building solver routing products")

        self.routing_ctx = build_solver_routing_context(
            dem_path=self.dem_watershed_path,
            output_dir=os.path.join(self.full_path, "_solver_routing"),
            dem_correc_type=str(getattr(self.geographic, "dem_correc_type", "breach")),
            crs_project=getattr(self.geographic, "crs_proj", None),
        )
        return self.routing_ctx

    def _resolve_flow_regime(self) -> str | None:
        if self.flow is None:
            return None

        flow_regime = None
        flow_cfg = getattr(self.flow, "config", None)
        if flow_cfg is not None:
            flow_regime = getattr(flow_cfg, "flow_regime", None)
        if flow_regime is None:
            flow_regime = getattr(self.flow, "flow_regime", None)
        if flow_regime is None:
            return None

        flow_regime_text = str(flow_regime).strip().lower()
        if flow_regime_text not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
        return flow_regime_text

    def _validate_pre_processing_inputs(self) -> None:
        if self.flow is None:
            raise ValueError("pre_processing requires a configured Flow object.")
        if self.domain is None:
            raise ValueError("pre_processing requires a configured Domain object.")
        flow_regime = self._resolve_flow_regime()
        if flow_regime is None:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
        self.flow_regime = flow_regime
        if self.time_grid is None and self.flow_regime != "steady":
            raise ValueError(
                "Launcher flow preprocessing requires preprocess_options.time_grid "
                "derived from [simulation.time] for transient flow runs. Solver tgrid fallback is no longer supported."
            )

    def pre_processing(
        self,
        flow: object,
        domain: object,
        options: ModflowPreprocessOptions | None = None,
        *,
        mesh_planar: object | None = None,
        mesh_support: object | None = None,
        flow_runtime_overrides: Mapping[str, object] | None = None,
    ):
        self.flow = flow
        self.domain = domain
        self.runtime_mesh_planar = mesh_planar
        self.runtime_mesh_support = mesh_support
        active_options = self.preprocess_options if options is None else options
        self._apply_preprocess_options(active_options)
        self._validate_pre_processing_inputs()
        bind_recharge_from_flow(self)
        self._calibration_raw_output_payload_cache = {}

        self.flow_regime = self._resolve_flow_regime() or "transient"
        reuse_signature = runtime_reuse_signature(
            self,
            flow=flow,
            domain=domain,
            options=active_options,
            mesh_planar=mesh_planar,
            mesh_support=mesh_support,
        )
        if can_refresh_runtime_reuse(
            self,
            flow=flow,
            domain=domain,
            options=active_options,
            mesh_planar=mesh_planar,
            mesh_support=mesh_support,
            flow_runtime_overrides=flow_runtime_overrides,
        ):
            self._runtime_dirty_packages = refresh_reused_runtime_property_packages(
                self,
                flow_runtime_overrides=flow_runtime_overrides,
            )
            self._calibration_runtime_reuse_signature = reuse_signature
            return
        launcher_time_grid = self.time_grid
        temporal = build_temporal_discretization_from_time_grid(
            time_grid=launcher_time_grid,
            flow_regime=self.flow_regime,
            firstpersteady=bool(
                getattr(getattr(self.modflow_config, "tgrid", None), "firstpersteady", True)
            ),
        )
        self.perlen = temporal.perlen
        self.nper = temporal.nper
        self.nstp = temporal.nstp
        self.steady = temporal.steady
        time_units = "seconds"
        finalize_pending_recharge_evt(self)

        self.grid_ctx = build_spatial_discretization(
            domain=self.domain,
            sgrid_config=getattr(self.modflow_config, "sgrid", None),
            runtime_planar_mesh=self.runtime_mesh_planar,
            runtime_mesh_support=self.runtime_mesh_support,
        )
        solver_mesh = self.grid_ctx.solver_mesh
        self.solver_mesh = solver_mesh
        self.top_elevation = solver_mesh.top  # (ncpl,)
        self.inactive_mask = solver_mesh.inactive_mask[0]  # (ncpl,)
        self.nlay = solver_mesh.nlay
        self.ncpl = solver_mesh.n_cells
        if solver_mesh.is_structured:
            self.nrow = solver_mesh.nrow
            self.ncol = solver_mesh.ncol
        self.cell_area = float(self.grid_ctx.grid.cell_area)
        self.resolution = float(self.grid_ctx.grid.characteristic_length)
        self.dem = self.top_elevation  # flat (ncpl,)
        self.dem_mask = self.inactive_mask  # flat (ncpl,)
        self.dem_watershed_path = self._write_solver_grid_template()

        # Deferred heterogeneous recharge: discretize now that solver_mesh is built.
        resolve_deferred_heterogeneous_recharge(self)

        flow_params = resolve_flow_property_arrays(
            flow=self.flow,
            domain=self.domain,
            solver_mesh=solver_mesh,
            planar_mesh=self.runtime_mesh_planar,
            required_properties=resolve_required_flow_properties(flow_regime=self.flow_regime),
            optional_fill_values={"Sy": 0.0, "Ss": 0.0},
            runtime_property_overrides=flow_runtime_overrides,
        )
        # Flatten property arrays to (nlay, ncpl).
        self.hk = solver_mesh.flatten_from_grid(flow_params["hk"])
        self.sy = solver_mesh.flatten_from_grid(flow_params["sy"])
        self.ss = solver_mesh.flatten_from_grid(flow_params["ss"])

        runtime = self.modflow_config.runtime
        sim_name = self.model_name_mf6
        self.sim = flopy.mf6.MFSimulation(
            sim_name=sim_name, sim_ws=self.full_path, exe_name=self.exe
        )
        # TGrid/TMesh fields consumed here:
        # - perlen (stress-period length),
        # - nstp (time-step count),
        # - itmuni (time_units metadata).
        # Current implementation keeps MF6 TDIS tsmult fixed to 1.0.
        self.tdis = flopy.mf6.ModflowTdis(
            self.sim,
            nper=int(self.nper),
            perioddata=[
                (float(self.perlen[i]), int(self.nstp[i]), 1.0) for i in range(int(self.nper))
            ],
            time_units=time_units,
        )
        self.ims = flopy.mf6.ModflowIms(
            self.sim,
            print_option="SUMMARY" if runtime.mf_verbose else "NONE",
            complexity=runtime.mf6_ims_complexity,
            outer_dvclose=float(runtime.mf6_outer_dvclose),
            inner_dvclose=float(runtime.mf6_inner_dvclose),
            outer_maximum=int(runtime.mf6_outer_maximum),
            inner_maximum=int(runtime.mf6_inner_maximum),
            filename=f"{self.model_name_mf6}_gwf.ims",
            pname="IMS_GWF",
        )
        self.gwf = flopy.mf6.ModflowGwf(
            self.sim,
            modelname=self.model_name_mf6,
            save_flows=True,
            print_input=getattr(runtime, "mf_verbose", False),
            print_flows=getattr(runtime, "mf_verbose", False),
        )
        self.sim.register_ims_package(self.ims, [self.gwf.name])
        # Build idomain as flat (nlay, ncpl) - DISV convention.
        idomain = np.where(solver_mesh.inactive_mask, 0, 1).astype(int)  # (nlay, ncpl)

        disv_kwargs = solver_mesh.to_disv_kwargs()
        self.dis = flopy.mf6.ModflowGwfdisv(
            self.gwf,
            nlay=solver_mesh.nlay,
            **disv_kwargs,
            idomain=idomain,
            xorigin=float(solver_mesh.xoffset),
            yorigin=float(solver_mesh.yoffset),
            length_units="METERS",
        )

        strt = build_start_heads(self, solver_mesh)
        self.ic = flopy.mf6.ModflowGwfic(self.gwf, strt=strt)
        ocean_chd_spd, ocean_support_mask = build_ocean_boundary_chd_spd(self)
        stream_chd_spd, stream_support_mask = build_stream_boundary_chd_spd(self)
        self._ocean_support_mask = np.asarray(ocean_support_mask, dtype=bool).copy()
        self._stream_support_mask = np.asarray(stream_support_mask, dtype=bool).copy()
        rewet_record, wetdry = resolve_rewet_npf_options(self, solver_mesh)

        self.npf = flopy.mf6.ModflowGwfnpf(
            self.gwf,
            icelltype=np.ones((self.nlay,), dtype=int),
            k=self.hk,
            k33=self.hk
            / max(
                float(
                    getattr(getattr(self.modflow_config, "process_specific", object()), "vka", 1.0)
                ),
                1e-12,
            ),
            rewet_record=rewet_record,
            wetdry=wetdry,
            save_specific_discharge=True,
            save_saturation=True,
        )
        self.sto = flopy.mf6.ModflowGwfsto(
            self.gwf,
            sy=self.sy,
            ss=self.ss,
            iconvert=np.ones((self.nlay,), dtype=int),
            steady_state={0: bool(self.steady[0])},
            transient={i: not bool(self.steady[i]) for i in range(int(self.nper))},
        )

        self.rch_spd = recharge_to_spd(self)
        self.rch = flopy.mf6.ModflowGwfrcha(
            self.gwf,
            recharge=self.rch_spd,
            auxiliary=["CONCENTRATION"],
            aux=empty_recharge_aux(self),
            pname="RCHA",
        )
        evt_spd = build_evt_stress_period_data(
            self,
            solver_mesh,
            ocean_support_mask=ocean_support_mask,
            stream_support_mask=stream_support_mask,
        )
        if evt_spd is not None:
            maxbound = max((len(period_cells) for period_cells in evt_spd.values()), default=0)
            self.evt = flopy.mf6.ModflowGwfevt(
                self.gwf,
                stress_period_data=evt_spd,
                maxbound=maxbound,
                save_flows=True,
            )

        drainage_cond_series = resolve_drainage_conductance_series(self)
        self._drainage_cond_series = (
            None
            if drainage_cond_series is None
            else np.asarray(drainage_cond_series, dtype=float).copy()
        )
        self._drainage_uses_hk = bool(
            drainage_cond_series is not None
            and np.any(np.asarray(drainage_cond_series, dtype=float) <= 0.0)
        )
        if drainage_cond_series is not None:
            drn_spd = build_drain_stress_period_data(
                self,
                solver_mesh=solver_mesh,
                drainage_cond_series=np.asarray(drainage_cond_series, dtype=float),
                ocean_support_mask=np.asarray(ocean_support_mask, dtype=bool),
                stream_support_mask=np.asarray(stream_support_mask, dtype=bool),
            )
            self.drn = flopy.mf6.ModflowGwfdrn(
                self.gwf, stress_period_data=drn_spd, save_flows=True
            )

        side_chd_spd = build_side_boundary_chd_spd(self)
        chd_spd = {}
        for kper in range(int(self.nper)):
            period_map: dict[tuple[int, int], list[float]] = {}
            for entry in ocean_chd_spd.get(kper, []):
                period_map[(int(entry[0]), int(entry[1]))] = entry
            for entry in stream_chd_spd.get(kper, []):
                period_map[(int(entry[0]), int(entry[1]))] = entry
            for entry in side_chd_spd.get(kper, []):
                period_map[(int(entry[0]), int(entry[1]))] = entry
            chd_spd[kper] = list(period_map.values())
        if any(len(v) > 0 for v in chd_spd.values()):
            self.chd = flopy.mf6.ModflowGwfchd(
                self.gwf, stress_period_data=chd_spd, save_flows=True
            )

        wel_spd = build_well_stress_period_data(self, int(self.nper))
        if any(len(v) > 0 for v in wel_spd.values()):
            self.wel = flopy.mf6.ModflowGwfwel(
                self.gwf, stress_period_data=wel_spd, save_flows=True
            )

        self.oc = flopy.mf6.ModflowGwfoc(
            self.gwf,
            head_filerecord=f"{self.model_name}.hds",
            budget_filerecord=f"{self.model_name}.cbc",
            saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
            printrecord=[("HEAD", "LAST")],
        )
        self._runtime_dirty_packages = ()
        self._calibration_runtime_reuse_signature = reuse_signature

    def processing(self, options: ModflowRunOptions | None = None):
        if options is None:
            options = ModflowRunOptions()
        elif not isinstance(options, ModflowRunOptions):
            raise TypeError("processing options must be ModflowRunOptions")

        if options.write_model:
            dirty_packages = tuple(getattr(self, "_runtime_dirty_packages", ()) or ())
            if dirty_packages:
                for package_name in dirty_packages:
                    package = getattr(self, str(package_name), None)
                    if package is None:
                        continue
                    package.write()
                self._runtime_dirty_packages = ()
            else:
                self.sim.write_simulation(silent=not options.verbose)

        success_model = False
        if options.run_model:
            success_model, _ = self.sim.run_simulation(silent=not options.verbose)
        return success_model

    def post_processing(self, options: ModflowPostprocessOptions | None = None) -> None:
        run_flow_post_processing(self, options)
