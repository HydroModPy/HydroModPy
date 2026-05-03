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
from hydromodpy.physics.flow.regime import normalize_flow_regime
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
    resolve_ims_complexity,
    resolve_rewet_npf_options,
    resolve_xt3d_npf_options,
    xt3d_activation_mode,
    xt3d_is_enabled,
    xt3d_requested_value,
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


def _windows_extended_length_path(path: str) -> str:
    """Return a Windows long-path spelling while keeping normal paths unchanged."""
    if os.name != "nt":
        return path
    normalized = os.path.normpath(os.path.abspath(path))
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized.lstrip("\\")
    return "\\\\?\\" + normalized


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

    def _xt3d_requested_value(self) -> bool | None:
        """Return the configured XT3D override."""
        return xt3d_requested_value(self)

    def _xt3d_is_enabled(self, solver_mesh=None) -> bool:
        """Return whether XT3D is active for this run."""
        return xt3d_is_enabled(self, solver_mesh)

    def _xt3d_activation_mode(self, solver_mesh=None) -> str:
        """Return the XT3D activation mode."""
        return xt3d_activation_mode(self, solver_mesh)

    def _resolve_xt3d_npf_options(self, solver_mesh=None) -> list[str] | None:
        """Return FloPy NPF XT3D options."""
        return resolve_xt3d_npf_options(self, solver_mesh)

    def _resolve_ims_complexity(self, solver_mesh=None) -> str:
        """Return the resolved IMS complexity."""
        return resolve_ims_complexity(self, solver_mesh)

    def _log_xt3d_resolution(self, solver_mesh=None) -> None:
        """Log the resolved XT3D mode."""
        logger.info(
            "MF6 XT3D resolution: mode=%s enabled=%s structured=%s",
            self._xt3d_activation_mode(solver_mesh),
            self._xt3d_is_enabled(solver_mesh),
            bool(getattr(solver_mesh, "is_structured", True)),
        )

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

        return normalize_flow_regime(flow_regime)

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
        self._log_xt3d_resolution(solver_mesh)

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
            complexity=self._resolve_ims_complexity(solver_mesh),
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
        xt3doptions = self._resolve_xt3d_npf_options(solver_mesh)

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
            xt3doptions=xt3doptions,
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

    @staticmethod
    def _get_budget_records_or_none(cbb: object, *, kstpkper: tuple[int, int], text: str):
        """Return one budget term, or None when the term is absent from the file."""
        try:
            return cbb.get_data(kstpkper=kstpkper, text=text)
        except Exception as exc:
            message = str(exc)
            if "text string is not in the budget file" in message.lower():
                return None
            raise

    @staticmethod
    def _open_budget_file(path: str):
        """Open one MF6 cell-budget file with a small precision fallback chain."""
        for kwargs in ({}, {"precision": "double"}, {"precision": "single"}):
            try:
                return bf.CellBudgetFile(path, **kwargs)
            except TypeError:
                if kwargs:
                    continue
                raise
            except Exception:
                if kwargs == {"precision": "single"}:
                    raise
                continue

    def _build_unstructured_cell_adjacency(self) -> list[set[int]]:
        """Return cell-to-cell adjacency for one unstructured planar mesh."""
        n_cells = int(getattr(self, "ncpl", 0) or getattr(self.solver_mesh, "n_cells", 0))
        adjacency = [set() for _ in range(n_cells)]
        support = getattr(self, "runtime_mesh_support", None)
        if support is not None:
            edge_cell_a = np.asarray(getattr(support, "edge_cell_a", ()), dtype=int).reshape(-1)
            edge_cell_b = np.asarray(getattr(support, "edge_cell_b", ()), dtype=int).reshape(-1)
            for cell_a, cell_b in zip(edge_cell_a.tolist(), edge_cell_b.tolist(), strict=False):
                if int(cell_a) < 0 or int(cell_b) < 0:
                    continue
                if int(cell_a) >= n_cells or int(cell_b) >= n_cells:
                    continue
                adjacency[int(cell_a)].add(int(cell_b))
                adjacency[int(cell_b)].add(int(cell_a))
            if any(neighbors for neighbors in adjacency):
                return adjacency

        planar_mesh = getattr(self.solver_mesh, "planar_mesh", None)
        if planar_mesh is None:
            return adjacency

        edge_owner: dict[tuple[int, int], int] = {}
        cell_offset = 0
        for block in tuple(getattr(planar_mesh, "cell_blocks", ()) or ()):
            connectivity = np.asarray(getattr(block, "connectivity", ()), dtype=int)
            if connectivity.ndim != 2:
                continue
            for local_index, node_ids in enumerate(connectivity.tolist()):
                cell_id = int(cell_offset + local_index)
                if cell_id >= n_cells:
                    break
                nodes = np.asarray(node_ids, dtype=int).reshape(-1)
                if nodes.size < 3:
                    continue
                for node_index in range(int(nodes.size)):
                    node_a = int(nodes[node_index])
                    node_b = int(nodes[(node_index + 1) % int(nodes.size)])
                    edge = tuple(sorted((node_a, node_b)))
                    owner = edge_owner.get(edge)
                    if owner is None:
                        edge_owner[edge] = cell_id
                        continue
                    if int(owner) == cell_id:
                        continue
                    adjacency[cell_id].add(int(owner))
                    adjacency[int(owner)].add(cell_id)
            cell_offset += int(connectivity.shape[0])
        return adjacency

    def _accumulate_unstructured_cell_values(
        self,
        *,
        local_values: np.ndarray,
        reference_values: np.ndarray,
        inactive_mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """Accumulate one per-cell source field along a downhill mesh graph.

        This is a cell-based proxy for raster D8 accumulation used on irregular
        meshes where no solver-aligned routing raster exists. Downstream routing is
        chosen cell-to-cell from the steepest decrease in ``reference_values``.
        """
        local = np.asarray(local_values, dtype=float).reshape(-1)
        reference = np.asarray(reference_values, dtype=float).reshape(-1)
        n_cells = int(getattr(self, "ncpl", 0) or getattr(self.solver_mesh, "n_cells", 0))
        if local.size != n_cells or reference.size != n_cells:
            raise ValueError(
                "Unstructured accumulation requires local_values/reference_values "
                f"with {n_cells} entries."
            )

        if inactive_mask is None:
            mask = np.zeros(n_cells, dtype=bool)
        else:
            mask = np.asarray(inactive_mask, dtype=bool).reshape(-1)
            if mask.size != n_cells:
                raise ValueError(f"inactive_mask must have {n_cells} entries, got {mask.size}.")

        active = (~mask) & np.isfinite(reference)
        if not np.any(active):
            return np.zeros(n_cells, dtype=float)

        adjacency = self._build_unstructured_cell_adjacency()
        centroids = None
        try:
            centroids = np.asarray(self.solver_mesh.cell_centroids(), dtype=float).reshape(
                n_cells, 2
            )
        except Exception:
            centroids = None

        ref_active = reference[active]
        ref_range = (
            float(np.nanmax(ref_active) - np.nanmin(ref_active)) if ref_active.size > 0 else 0.0
        )
        tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))
        downstream = np.full(n_cells, -1, dtype=int)

        for cell_id in np.flatnonzero(active).tolist():
            best_neighbor = -1
            best_score = 0.0
            cell_ref = float(reference[cell_id])
            for neighbor in adjacency[int(cell_id)]:
                if neighbor < 0 or neighbor >= n_cells or not bool(active[neighbor]):
                    continue
                neighbor_ref = float(reference[int(neighbor)])
                drop = cell_ref - neighbor_ref
                if not np.isfinite(drop) or drop <= tolerance:
                    continue
                score = drop
                if centroids is not None:
                    delta_x = float(centroids[cell_id, 0] - centroids[int(neighbor), 0])
                    delta_y = float(centroids[cell_id, 1] - centroids[int(neighbor), 1])
                    distance = max((delta_x * delta_x + delta_y * delta_y) ** 0.5, 1.0e-12)
                    score = drop / distance
                if score > best_score:
                    best_score = float(score)
                    best_neighbor = int(neighbor)
            downstream[int(cell_id)] = int(best_neighbor)

        clean_local = np.where(
            active & np.isfinite(local) & (local > -9999.0),
            np.maximum(local, 0.0),
            0.0,
        )
        accumulated = np.zeros(n_cells, dtype=float)
        order = np.argsort(np.where(active, reference, -np.inf).astype(float, copy=False))[::-1]
        for cell_id in order.tolist():
            if not bool(active[int(cell_id)]):
                continue
            accumulated[int(cell_id)] += float(clean_local[int(cell_id)])
            target = int(downstream[int(cell_id)])
            if target >= 0:
                accumulated[target] += float(accumulated[int(cell_id)])

        accumulated[~active] = np.nan
        return accumulated

    def _native_mesh_exports_enabled(self, options: ModflowPostprocessOptions) -> bool:
        """Return True when one native mesh export format is enabled."""
        return bool(
            getattr(options, "native_mesh_npz", False)
            or getattr(options, "native_mesh_csv", False)
            or getattr(options, "native_mesh_vtu", False)
            or getattr(options, "native_mesh_png", False)
        )

    def _native_cell_series_payload(
        self,
        *,
        datasets: Mapping[str, Mapping[int, np.ndarray]],
    ) -> dict[str, np.ndarray]:
        """Normalize time-indexed cell datasets to stacked (ntime, ncpl) arrays."""
        payload: dict[str, np.ndarray] = {}
        for name, data_by_time in datasets.items():
            if not data_by_time:
                continue
            stacked_rows: list[np.ndarray] = []
            for _, values in sorted(data_by_time.items(), key=lambda item: int(item[0])):
                flat = np.asarray(
                    self.solver_mesh.flatten_from_grid(np.asarray(values)),
                    dtype=float,
                ).reshape(-1)
                if flat.size != int(self.ncpl):
                    continue
                stacked_rows.append(flat)
            if stacked_rows:
                payload[str(name)] = np.vstack(stacked_rows).astype(float, copy=False)
        return payload

    def _export_native_mesh_outputs(
        self,
        *,
        options: ModflowPostprocessOptions,
        times: list[float] | tuple[float, ...],
        datasets: Mapping[str, Mapping[int, np.ndarray]],
        prefix: str,
    ) -> None:
        """Write native mesh exports (NPZ, CSV, VTU) for cell-based outputs."""
        if not self._native_mesh_exports_enabled(options):
            return

        cell_series = self._native_cell_series_payload(datasets=datasets)
        if not cell_series:
            return

        mesh_dir = os.path.join(self.save_file, "_mesh")
        create_folder(mesh_dir)
        time_index = np.arange(len(times), dtype=int)
        times_array = np.asarray(times, dtype=float)
        cell_ids = np.arange(int(self.ncpl), dtype=int)

        if getattr(options, "native_mesh_npz", False):
            for name, values in cell_series.items():
                np.savez_compressed(
                    os.path.join(mesh_dir, f"{prefix}_{name}.npz"),
                    time_index=time_index,
                    times=times_array,
                    cell_ids=cell_ids,
                    values=values,
                )

        if getattr(options, "native_mesh_csv", False):
            for name, values in cell_series.items():
                csv_path = os.path.join(mesh_dir, f"{prefix}_{name}.csv")
                with open(csv_path, "w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["time_index", "time", "cell_id", "value"])
                    for tidx, time_value in enumerate(times_array.tolist()):
                        for cell_id, cell_value in enumerate(values[tidx].tolist()):
                            writer.writerow(
                                [
                                    int(tidx),
                                    float(time_value),
                                    int(cell_id),
                                    float(cell_value),
                                ]
                            )

        if getattr(options, "native_mesh_vtu", False):
            try:
                from hydromodpy.spatial.mesh.io import write_vtu

                for tidx, _time_value in enumerate(times_array.tolist()):
                    cell_fields = {
                        "cell_id": cell_ids.astype(float, copy=False),
                        "top_elevation": np.asarray(self.solver_mesh.top, dtype=float).reshape(-1),
                    }
                    for name, values in cell_series.items():
                        cell_fields[str(name)] = np.asarray(values[tidx], dtype=float).reshape(-1)
                    mesh_with_data = self.solver_mesh.planar_mesh.with_cell_data(**cell_fields)
                    write_vtu(
                        os.path.join(mesh_dir, f"{prefix}_t({int(tidx)}).vtu"),
                        mesh_with_data,
                    )
            except ImportError as exc:
                logger.warning("Skipping native mesh VTU export: %s", exc)

        if getattr(options, "native_mesh_png", False):
            import matplotlib

            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt
            from matplotlib.ticker import ScalarFormatter
            from mpl_toolkits.axes_grid1 import make_axes_locatable

            from hydromodpy.spatial.mesh.plotting import plot_cell_values

            figure_dir = os.path.join(self.save_file, "_figures", "native_mesh")
            create_folder(figure_dir)
            field_styles = {
                "watertable_elevation": ("Hydraulic head", "Head [m]", "viridis"),
                "watertable_depth": ("Water-table depth", "Top - h [m]", "Blues"),
                "seepage_areas": ("Seepage areas", "Seepage [m/day]", "Reds"),
                "outflow_drain": ("Drain discharge", "Discharge [m/day]", "magma"),
                "accumulation_flux": ("Accumulation flux", "Accumulated flow [m/day]", "plasma"),
                "concentration_seepage": ("Seepage concentration", "Concentration [-]", "viridis"),
                "mass_seepage": ("Seepage mass", "Mass [-]", "cividis"),
                "mass_accumulated": ("Accumulated mass", "Accumulated mass [-]", "inferno"),
            }

            for name, values in cell_series.items():
                for tidx, time_value in enumerate(times_array.tolist()):
                    flat = np.asarray(values[tidx], dtype=float).reshape(-1).copy()
                    flat[~np.isfinite(flat)] = np.nan
                    flat[flat <= -9999.0] = np.nan
                    finite = flat[np.isfinite(flat)]
                    if finite.size == 0:
                        continue

                    vmin = float(np.nanmin(finite))
                    vmax = float(np.nanmax(finite))
                    if np.isclose(vmin, vmax):
                        vmax = vmin + 1.0

                    field_title, colorbar_label, cmap = field_styles.get(
                        str(name),
                        (
                            str(name).replace("_", " ").title(),
                            str(name).replace("_", " "),
                            "viridis",
                        ),
                    )
                    fig, ax = plt.subplots(figsize=(7.2, 6.0), dpi=220)
                    mappable = plot_cell_values(
                        ax,
                        self.solver_mesh.planar_mesh,
                        flat,
                        cmap=cmap,
                        show_mesh=True,
                        vmin=vmin,
                        vmax=vmax,
                    )
                    ax.set_title(
                        f"{field_title} | t={float(time_value):.12g} s",
                        fontsize=10.5,
                        loc="left",
                        pad=5.0,
                    )
                    ax.set_xlabel("x (m)", fontsize=9)
                    ax.set_ylabel("y (m)", fontsize=9)
                    ax.ticklabel_format(style="plain", axis="both", useOffset=False)
                    ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

                    divider = make_axes_locatable(ax)
                    cax = divider.append_axes("right", size="3.8%", pad=0.06)
                    cbar = fig.colorbar(mappable, cax=cax)
                    cbar.set_label(colorbar_label, fontsize=8.5, labelpad=6.0)
                    cbar.ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)
                    formatter = ScalarFormatter(useMathText=True)
                    formatter.set_powerlimits((-2, 3))
                    cbar.formatter = formatter
                    cbar.update_ticks()

                    fig.subplots_adjust(left=0.08, right=0.94, bottom=0.11, top=0.9)
                    output_path = os.path.join(
                        figure_dir,
                        f"{prefix}_{name}_t({int(tidx)}).png",
                    )
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    fig.savefig(
                        _windows_extended_length_path(output_path),
                        bbox_inches="tight",
                    )
                    plt.close(fig)

    def _support_edge_segments(self, support: object, edge_indices: np.ndarray) -> list[np.ndarray]:
        """Return XY segments for one sequence of runtime support edge indices."""
        indices = np.asarray(edge_indices, dtype=int).reshape(-1)
        if indices.size == 0:
            return []
        node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
        node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
        edge_node_a = np.asarray(getattr(support, "edge_node_a_index", ()), dtype=int).reshape(-1)
        edge_node_b = np.asarray(getattr(support, "edge_node_b_index", ()), dtype=int).reshape(-1)
        segments: list[np.ndarray] = []
        for edge_index in indices.tolist():
            if edge_index < 0 or edge_index >= edge_node_a.size or edge_index >= edge_node_b.size:
                continue
            node_a = int(edge_node_a[edge_index])
            node_b = int(edge_node_b[edge_index])
            segments.append(
                np.asarray(
                    [
                        [float(node_x_m[node_a]), float(node_y_m[node_a])],
                        [float(node_x_m[node_b]), float(node_y_m[node_b])],
                    ],
                    dtype=float,
                )
            )
        return segments

    def _support_cell_polygons(self, support: object, cell_ids: np.ndarray) -> list[np.ndarray]:
        """Return XY polygons for one sequence of runtime support cell ids."""
        indices = np.asarray(cell_ids, dtype=int).reshape(-1)
        if indices.size == 0:
            return []
        node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
        node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
        cell_node_indices = tuple(getattr(support, "cell_node_indices", ()) or ())
        polygons: list[np.ndarray] = []
        for cell_id in np.unique(indices).tolist():
            if cell_id < 0 or cell_id >= len(cell_node_indices):
                continue
            node_indices = np.asarray(cell_node_indices[int(cell_id)], dtype=int).reshape(-1)
            if node_indices.size < 3:
                continue
            polygons.append(
                np.column_stack(
                    [
                        node_x_m[node_indices],
                        node_y_m[node_indices],
                    ]
                ).astype(float, copy=False)
            )
        return polygons

    def _support_overlay_specs(self) -> list[tuple[str, np.ndarray, str]]:
        """Return active runtime support selections to visualize on one overview figure."""
        if self.flow is None:
            return []

        overlays: list[tuple[str, np.ndarray, str]] = []
        color_by_bc = {
            "west_side": "#d62728",
            "east_side": "#1f77b4",
            "north_side": "#ff7f0e",
            "south_side": "#9467bd",
            "stream": "#17becf",
            "ocean": "#2ca02c",
        }
        boundary_conditions = self._boundary_conditions_mapping()
        for bc_id in ("west_side", "east_side", "north_side", "south_side"):
            if not self._is_bc_active(bc_id):
                continue
            boundary = boundary_conditions.get(bc_id)
            if boundary is None:
                continue
            cell_ids = np.asarray(
                self._boundary_support_cell_ids(boundary=boundary, bc_id=bc_id),
                dtype=int,
            ).reshape(-1)
            if cell_ids.size == 0:
                continue
            support_label = self._boundary_attr(boundary, "support_label", None)
            label = str(bc_id)
            if support_label is not None:
                label = f"{bc_id} [{str(support_label)}]"
            overlays.append((label, cell_ids, color_by_bc[bc_id]))

        if self._is_bc_active("stream"):
            stream_series = self._resolve_stream_boundary_series()
            stream_mask = self._stream_chd_support_mask(stream_series)
            stream_cell_ids = np.flatnonzero(np.asarray(stream_mask, dtype=bool)).astype(
                int, copy=False
            )
            if stream_cell_ids.size > 0:
                stream_boundary = boundary_conditions.get("stream")
                support_label = (
                    None
                    if stream_boundary is None
                    else self._boundary_attr(
                        stream_boundary,
                        "support_label",
                        None,
                    )
                )
                label = "stream"
                if support_label is not None:
                    label = f"stream [{str(support_label)}]"
                overlays.append((label, stream_cell_ids, color_by_bc["stream"]))

        if self._is_bc_active("ocean"):
            ocean_series = self._resolve_ocean_boundary_series()
            ocean_mask = self._ocean_chd_support_mask(ocean_series)
            ocean_cell_ids = np.flatnonzero(np.asarray(ocean_mask, dtype=bool)).astype(
                int, copy=False
            )
            if ocean_cell_ids.size > 0:
                overlays.append(("ocean", ocean_cell_ids, color_by_bc["ocean"]))

        return overlays

    def _well_overlay_specs(self) -> list[dict[str, object]]:
        """Return resolved well locations suitable for diagnostic plotting."""
        if self.flow is None:
            return []
        active = getattr(self.flow, "active_sinks_sources", [])
        if "wells" not in active:
            return []

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        if not isinstance(sinks_sources, Mapping):
            return []
        wells = sinks_sources.get("wells", {})
        if not isinstance(wells, Mapping):
            return []

        support = getattr(self, "runtime_mesh_support", None)
        grid = None if self.grid_ctx is None else self.grid_ctx.grid
        items: list[dict[str, object]] = []
        for well_id, well_cfg in wells.items():
            try:
                _, cell_id = self._resolve_well_disv_cell(
                    well_id=str(well_id),
                    well_cfg=well_cfg,
                    grid=grid,
                )
            except Exception:
                continue

            if support is not None and 0 <= int(cell_id) < int(getattr(support, "n_cells", 0)):
                x_m = float(
                    np.asarray(support.cell_centroid_x_m, dtype=float).reshape(-1)[int(cell_id)]
                )
                y_m = float(
                    np.asarray(support.cell_centroid_y_m, dtype=float).reshape(-1)[int(cell_id)]
                )
            else:
                continue
            items.append(
                {
                    "id": str(well_id),
                    "cell_id": int(cell_id),
                    "x_m": x_m,
                    "y_m": y_m,
                }
            )
        return items

    def _export_runtime_support_overview(self, *, options: ModflowPostprocessOptions) -> None:
        """Write one diagnostic figure showing runtime gmsh supports used by the solver."""
        if not getattr(options, "native_mesh_png", False):
            return
        support = getattr(self, "runtime_mesh_support", None)
        if support is None:
            return

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection, PolyCollection
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        figure_dir = os.path.join(self.save_file, "_figures", "native_mesh")
        create_folder(figure_dir)

        all_edge_indices = np.arange(
            np.asarray(getattr(support, "edge_ids", ()), dtype=int).size, dtype=int
        )
        all_segments = self._support_edge_segments(support, all_edge_indices)
        if not all_segments:
            return

        node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
        node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
        fig, axs = plt.subplots(1, 2, figsize=(14.8, 6.4), dpi=220)
        ax_active, ax_labels = axs

        for ax in (ax_active, ax_labels):
            ax.add_collection(LineCollection(all_segments, colors="0.80", linewidths=0.8, zorder=1))
            ax.set_aspect("equal")
            ax.set_xlim(float(np.min(node_x_m)), float(np.max(node_x_m)))
            ax.set_ylim(float(np.min(node_y_m)), float(np.max(node_y_m)))
            ax.set_xlabel("x (m)", fontsize=9)
            ax.set_ylabel("y (m)", fontsize=9)
            ax.ticklabel_format(style="plain", axis="both", useOffset=False)
            ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

        active_handles: list[object] = []
        for label, cell_ids, color in self._support_overlay_specs():
            polygons = self._support_cell_polygons(support, cell_ids)
            if not polygons:
                continue
            ax_active.add_collection(
                PolyCollection(
                    polygons,
                    facecolors=color,
                    edgecolors=color,
                    linewidths=1.4,
                    alpha=0.22,
                    zorder=2,
                )
            )
            active_handles.append(Patch(facecolor=color, edgecolor=color, alpha=0.22, label=label))

        river_indices = np.asarray(support.river_edge_indices(), dtype=int).reshape(-1)
        river_segments = self._support_edge_segments(support, river_indices)
        if river_segments:
            river_collection = LineCollection(
                river_segments,
                colors="#17becf",
                linewidths=2.0,
                alpha=0.95,
                zorder=3,
            )
            ax_active.add_collection(river_collection)
            ax_labels.add_collection(
                LineCollection(
                    river_segments,
                    colors="#17becf",
                    linewidths=2.0,
                    alpha=0.95,
                    zorder=3,
                )
            )
            active_handles.append(Line2D([0], [0], color="#17becf", lw=2.0, label="river edges"))

        well_items = self._well_overlay_specs()
        if well_items:
            ax_active.scatter(
                [float(item["x_m"]) for item in well_items],
                [float(item["y_m"]) for item in well_items],
                marker="x",
                s=55.0,
                linewidths=1.5,
                color="black",
                zorder=4,
            )
            for item in well_items:
                ax_active.text(
                    float(item["x_m"]),
                    float(item["y_m"]),
                    str(item["id"]),
                    fontsize=7.5,
                    color="black",
                    ha="left",
                    va="bottom",
                    zorder=5,
                )
            active_handles.append(
                Line2D([0], [0], marker="x", color="black", linestyle="None", label="wells")
            )

        label_handles: list[object] = []
        label_values = sorted(
            {
                str(value)
                for value in getattr(support, "boundary_labels_by_edge_id", {}).values()
                if str(value).strip() != ""
            }
        )
        palette = (
            "#d62728",
            "#1f77b4",
            "#ff7f0e",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
        )
        for index, label in enumerate(label_values):
            edge_indices = np.asarray(support.edge_indices_for_label(label), dtype=int).reshape(-1)
            segments = self._support_edge_segments(support, edge_indices)
            if not segments:
                continue
            color = palette[index % len(palette)]
            ax_labels.add_collection(
                LineCollection(
                    segments,
                    colors=color,
                    linewidths=2.4,
                    alpha=0.95,
                    zorder=2,
                )
            )
            x_mid = float(
                np.mean(
                    np.asarray(support.edge_midpoint_x_m, dtype=float).reshape(-1)[edge_indices]
                )
            )
            y_mid = float(
                np.mean(
                    np.asarray(support.edge_midpoint_y_m, dtype=float).reshape(-1)[edge_indices]
                )
            )
            ax_labels.text(
                x_mid,
                y_mid,
                label,
                fontsize=7.5,
                color=color,
                ha="center",
                va="center",
                bbox={"facecolor": "white", "edgecolor": color, "alpha": 0.75, "pad": 1.5},
                zorder=4,
            )
            label_handles.append(Line2D([0], [0], color=color, lw=2.4, label=label))

        ax_active.set_title("Active supports", fontsize=10.5, loc="left", pad=5.0)
        ax_labels.set_title("Support labels", fontsize=10.5, loc="left", pad=5.0)
        if active_handles:
            ax_active.legend(
                handles=active_handles,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.12),
                ncol=min(3, len(active_handles)),
                fontsize=7.5,
                frameon=True,
                framealpha=0.92,
            )
        if label_handles:
            ax_labels.legend(
                handles=label_handles,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.12),
                ncol=min(3, len(label_handles)),
                fontsize=7.5,
                frameon=True,
                framealpha=0.92,
            )
        else:
            ax_labels.text(
                0.5,
                0.5,
                "No labeled runtime supports",
                transform=ax_labels.transAxes,
                ha="center",
                va="center",
                fontsize=9,
                color="0.35",
            )

        fig.suptitle("Runtime support overview", fontsize=11.5, y=0.96)
        fig.subplots_adjust(left=0.055, right=0.985, bottom=0.2, top=0.88, wspace=0.12)
        output_path = os.path.join(figure_dir, "flow_support_overview.png")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fig.savefig(_windows_extended_length_path(output_path), bbox_inches="tight")
        plt.close(fig)

    def _east_side_cell_ids(self) -> set[int]:
        """Return east-boundary cell ids for one DISV topological layer."""
        if getattr(self.solver_mesh, "is_structured", False):
            nrow = int(self.nrow)
            ncol = int(self.ncol)
            return {row * ncol + (ncol - 1) for row in range(nrow)}
        support = getattr(self, "runtime_mesh_support", None)
        if support is None:
            return set()
        return {
            int(cell_id) for cell_id in support.boundary_cell_indices_for_side("east_side").tolist()
        }

    def _compute_chd_outlet_discharge_east_side_m3_s(
        self,
        chd_records,
        *,
        ncpl: int,
        east_side_cell_ids: set[int],
    ) -> float:
        """Return total positive east-side CHD outflow [m3/s] for one stress period."""
        if not chd_records or not east_side_cell_ids:
            return 0.0

        record = chd_records[0]
        if record is None or len(record) == 0:
            return 0.0

        if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
            node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
            q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
            iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
        else:
            iterator = ((int(item[0]), float(item[-1])) for item in record)

        discharge_m3_s = 0.0
        for node, q in iterator:
            if node <= 0:
                continue
            cell_id = (int(node) - 1) % int(ncpl)
            if cell_id not in east_side_cell_ids:
                continue
            discharge_m3_s += max(-float(q), 0.0)
        return float(discharge_m3_s)

    def post_processing(self, options: ModflowPostprocessOptions | None = None):
        if options is None:
            options = ModflowPostprocessOptions()
        elif not isinstance(options, ModflowPostprocessOptions):
            raise TypeError("post_processing options must be ModflowPostprocessOptions")
        self.last_postprocess_options = options

        self.save_file = os.path.join(self.full_path, "_postprocess")
        create_folder(self.save_file)
        self.tifs_file = os.path.join(self.save_file, "_rasters")
        create_folder(self.tifs_file)

        head_path = os.path.join(self.full_path, f"{self.model_name}.hds")
        cbc_path = os.path.join(self.full_path, f"{self.model_name}.cbc")
        head_fpu = bf.HeadFile(head_path)
        cbb = self._open_budget_file(cbc_path)

        times = head_fpu.get_times()
        self.times = times
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_outlet_discharge_east_side_m3_s = {}
        self.dict_accumulation_flux = {}
        dict_watertable_elevation = self.dict_watertable_elevation
        dict_watertable_depth = self.dict_watertable_depth
        dict_seepage_areas = self.dict_seepage_areas
        dict_outflow_drain = self.dict_outflow_drain
        dict_outlet_discharge_east_side_m3_s = self.dict_outlet_discharge_east_side_m3_s
        dict_accumulation_flux = self.dict_accumulation_flux
        can_export_raster = bool(
            getattr(self.solver_mesh, "is_structured", False)
            and getattr(self, "dem_watershed_path", "")
        )

        ncpl = int(self.ncpl)
        dem_mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
        dem_flat = np.asarray(self.dem, dtype=float).reshape(-1)
        east_side_cell_ids = self._east_side_cell_ids()

        for item, time in enumerate(times):
            head = head_fpu.get_data(totim=time)
            wt = pp.get_water_table(head, -9999)
            wt = np.asarray(wt, dtype=float).reshape(-1)  # flatten to (ncpl,)
            wt[np.isnan(wt)] = -9999
            wt[wt <= -1e20] = -9999

            if options.watertable_elevation:
                wt_out = wt.copy()
                wt_out[dem_mask_flat] = -9999
                dict_watertable_elevation[item] = self._to_export_array(wt_out)
                if can_export_raster and (options.export_all_tif or item == 0):
                    export_tif(
                        self.dem_watershed_path,
                        self._to_export_array(wt_out),
                        os.path.join(self.tifs_file, f"watertable_elevation_t({item}).tif"),
                        -9999,
                    )

            if options.watertable_depth:
                wtd = np.where(dem_mask_flat, -9999, np.maximum(dem_flat - wt, 0))
                dict_watertable_depth[item] = self._to_export_array(wtd)
                if can_export_raster and (options.export_all_tif or item == 0):
                    export_tif(
                        self.dem_watershed_path,
                        self._to_export_array(wtd),
                        os.path.join(self.tifs_file, f"watertable_depth_t({item}).tif"),
                        -9999,
                    )

            drn = self._get_budget_records_or_none(
                cbb,
                kstpkper=(0, item),
                text="DRN",
            )
            outflow = np.zeros(ncpl, dtype=float)
            seepage = np.zeros(ncpl, dtype=float)
            if drn is not None and len(drn) > 0:
                rec = drn[0]
                try:
                    if getattr(rec, "dtype", None) is not None and rec.dtype.names is not None:
                        node_field = "node" if "node" in rec.dtype.names else rec.dtype.names[0]
                        q_field = "q" if "q" in rec.dtype.names else rec.dtype.names[-1]
                        iterator = ((int(r[node_field]), float(r[q_field])) for r in rec)
                    else:
                        iterator = ((int(r[0]), float(r[-1])) for r in rec)
                    for node, q in iterator:
                        if node <= 0:
                            continue
                        # DISV node numbering: node = layer * ncpl + cell_id + 1
                        layer = (node - 1) // ncpl
                        cell_id = (node - 1) % ncpl
                        if layer == 0:
                            outflow[cell_id] += max(-q, 0.0)
                            seepage[cell_id] = 1.0 if q < 0 else seepage[cell_id]
                except Exception:
                    pass

            outflow[dem_mask_flat] = -9999
            seepage[dem_mask_flat] = -9999

            outflow_tif_path = os.path.join(self.tifs_file, f"outflow_drain_t({item}).tif")
            if options.outflow_drain:
                dict_outflow_drain[item] = self._to_export_array(outflow)
            if options.outflow_drain or options.accumulation_flux:
                if can_export_raster and (
                    options.accumulation_flux or options.export_all_tif or item == 0
                ):
                    export_tif(
                        self.dem_watershed_path,
                        self._to_export_array(outflow),
                        outflow_tif_path,
                        -9999,
                    )
            if options.seepage_areas:
                dict_seepage_areas[item] = self._to_export_array(seepage)
                if can_export_raster and (options.export_all_tif or item == 0):
                    export_tif(
                        self.dem_watershed_path,
                        self._to_export_array(seepage),
                        os.path.join(self.tifs_file, f"seepage_areas_t({item}).tif"),
                        -9999,
                    )

            if options.outlet_discharge_east_side_m3_s:
                chd = self._get_budget_records_or_none(
                    cbb,
                    kstpkper=(0, item),
                    text="CHD",
                )
                outlet_discharge_m3_s = self._compute_chd_outlet_discharge_east_side_m3_s(
                    chd,
                    ncpl=ncpl,
                    east_side_cell_ids=east_side_cell_ids,
                )
                dict_outlet_discharge_east_side_m3_s[item] = np.asarray(
                    [outlet_discharge_m3_s],
                    dtype=float,
                )

            if options.accumulation_flux and can_export_raster and self.solver_mesh.is_structured:
                routing_ctx = self._ensure_solver_routing_context()
                accumulated_flow = masstransfer.Masstransfer(
                    self.geographic,
                    f"outflow_drain_t({item}).tif",
                    f"tracept_t({item}).shp",
                    f"accumulation_flux_t({item}).tif",
                    extraction_folder=self.save_file,
                    routing_fill_path=routing_ctx.correc_path,
                    routing_direc_path=routing_ctx.direc_path,
                )
                accumulated_flow.trace_cumulated()
                with rasterio.open(
                    os.path.join(self.tifs_file, f"accumulation_flux_t({item}).tif")
                ) as src:
                    dict_accumulation_flux[item] = src.read(1)
            elif options.accumulation_flux and not getattr(
                self.solver_mesh, "is_structured", False
            ):
                accumulated_flow = self._accumulate_unstructured_cell_values(
                    local_values=np.where(outflow <= -9999.0, 0.0, outflow),
                    reference_values=np.where(dem_mask_flat, np.nan, dem_flat),
                    inactive_mask=dem_mask_flat,
                )
                accumulated_flow[dem_mask_flat] = -9999.0
                dict_accumulation_flux[item] = self._to_export_array(accumulated_flow)

        if hasattr(head_fpu, "close"):
            head_fpu.close()
        if options.watertable_elevation:
            np.save(os.path.join(self.save_file, "watertable_elevation"), dict_watertable_elevation)
        if options.watertable_depth:
            np.save(os.path.join(self.save_file, "watertable_depth"), dict_watertable_depth)
        if options.seepage_areas:
            np.save(os.path.join(self.save_file, "seepage_areas"), dict_seepage_areas)
        if options.outflow_drain:
            np.save(os.path.join(self.save_file, "outflow_drain"), dict_outflow_drain)
        if options.outlet_discharge_east_side_m3_s:
            np.save(
                os.path.join(self.save_file, "outlet_discharge_east_side_m3_s"),
                dict_outlet_discharge_east_side_m3_s,
            )
        if options.accumulation_flux:
            np.save(os.path.join(self.save_file, "accumulation_flux"), dict_accumulation_flux)
        self._export_native_mesh_outputs(
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
        self._export_runtime_support_overview(options=options)


class Modflow6Transport:
    """Transport solver based on MODFLOW 6 GWT and `transport.modflow6gwt.parameters`."""

    def __init__(
        self,
        domain: object,
        transport: object,
        model_modflow: object,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modflow6",
        suffix_name: str = "_gwt",
        bin_path: str | None = None,
        **kwargs,
    ):
        self.domain = domain
        self.transport = transport
        self.model_modflow = model_modflow
        self.model_folder = model_folder
        self.model_name = model_name
        self.suffix_name = suffix_name
        self.model_name_mt = model_name + suffix_name
        self.model_name_mt_mf6 = _mf6_safe_name(self.model_name_mt)
        self.full_path = os.path.join(model_folder, model_name)
        self.exe = getattr(model_modflow, "exe", "mf6")

        conc_params = {}
        comp = transport.modflow6gwt
        if isinstance(getattr(comp, "parameters", None), Mapping):
            conc_params = dict(comp.parameters)
        conc_params.update(kwargs)
        conc_params.update(
            build_concentration_runtime_overrides(
                conc_params,
                model_modflow,
            )
        )

        self.spc_name = conc_params.get("spc_name", "NO3")
        self.sconc_init = conc_params.get("sconc_init", 0.0)
        self.sconc_input = conc_params.get("sconc_input", 0.0)
        self.disp_long = float(conc_params.get("disp_long", 0.0))
        self.disp_transh = float(conc_params.get("disp_transh", 0.0))
        self.disp_transv = float(conc_params.get("disp_transv", 0.0))
        self.diffu_coeff = float(conc_params.get("diffu_coeff", 0.0))
        self.react_order = conc_params.get("react_order", None)
        self.rate_decay = conc_params.get("rate_decay", 0.0)
        self.plot_conc = bool(conc_params.get("plot_conc", True))

    def _build_crch(self) -> dict[int, np.ndarray]:
        nper = int(self.model_modflow.nper)
        ncpl = int(self.model_modflow.ncpl)
        if isinstance(self.sconc_input, dict):
            out = {}
            for k in range(nper):
                arr = self.sconc_input.get(k)
                if arr is None:
                    arr = np.zeros(ncpl, dtype=float)
                out[k] = np.asarray(arr, dtype=float).reshape(-1)
            return out
        val = float(self.sconc_input)
        return {k: np.full(ncpl, val, dtype=float) for k in range(nper)}

    def _build_crch_aux(self) -> dict[int, list[np.ndarray]]:
        crch = self._build_crch()
        return {k: [np.asarray(v, dtype=float)] for k, v in crch.items()}

    def pre_processing(self):
        sim = self.model_modflow.sim
        self.gwf = self.model_modflow.gwf
        self.ims = flopy.mf6.ModflowIms(
            sim,
            print_option="SUMMARY",
            complexity="COMPLEX",
            filename=f"{self.model_name_mt_mf6}.ims",
            pname="IMS_GWT",
        )
        self.gwt = flopy.mf6.ModflowGwt(sim, modelname=self.model_name_mt_mf6, save_flows=True)
        sim.register_ims_package(self.ims, [self.gwt.name])
        if hasattr(self.model_modflow, "ims") and self.model_modflow.ims is not None:
            sim.name_file.solutiongroup.set_data(
                [
                    ("ims6", self.model_modflow.ims.filename, self.gwf.name),
                    ("ims6", self.ims.filename, self.gwt.name),
                ],
                key=0,
            )

        disv_kwargs = self.model_modflow.solver_mesh.to_disv_kwargs()
        self.gwtdis = flopy.mf6.ModflowGwtdisv(
            self.gwt,
            nlay=self.model_modflow.nlay,
            **disv_kwargs,
        )
        self.gwtic = flopy.mf6.ModflowGwtic(self.gwt, strt=self.sconc_init)
        self.adv = flopy.mf6.ModflowGwtadv(self.gwt, scheme="upstream")
        self.dsp = flopy.mf6.ModflowGwtdsp(
            self.gwt,
            alh=self.disp_long,
            ath1=self.disp_long * self.disp_transh,
            atv=self.disp_long * self.disp_transv,
            diffc=self.diffu_coeff,
        )

        decay = self.rate_decay if self.react_order in {0, 1} else None
        self.mst = flopy.mf6.ModflowGwtmst(
            self.gwt,
            porosity=self.model_modflow.sy,
            first_order_decay=bool(self.react_order == 1),
            decay=decay,
        )

        if not hasattr(self.model_modflow, "rch") or self.model_modflow.rch is None:
            raise RuntimeError("Modflow6Transport requires an existing GWF recharge package.")
        self.model_modflow.rch.aux.set_data(self._build_crch_aux())
        self.ssm = flopy.mf6.ModflowGwtssm(self.gwt, sources=[("RCHA", "AUX", "CONCENTRATION")])

        self.gwfgwt = flopy.mf6.ModflowGwfgwt(
            sim,
            exgtype="GWF6-GWT6",
            exgmnamea=self.gwf.name,
            exgmnameb=self.gwt.name,
        )
        self.oc = flopy.mf6.ModflowGwtoc(
            self.gwt,
            concentration_filerecord=f"{self.model_name_mt}.ucn",
            budget_filerecord=f"{self.model_name_mt}.cbc",
            saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
        )

    def processing(self, write_model: bool = True, run_model: bool = False, verbose: bool = True):
        if write_model:
            self.model_modflow.sim.write_simulation(silent=not verbose)
        success = False
        if run_model:
            success, _ = self.model_modflow.sim.run_simulation(silent=not verbose)
        return success

    def _resolve_postprocess_options(
        self,
        *,
        export_all_tif: bool,
        options: ModflowPostprocessOptions | None,
    ) -> ModflowPostprocessOptions:
        """Resolve transport post-processing options from explicit or inherited flow settings."""
        if options is not None and not isinstance(options, ModflowPostprocessOptions):
            raise TypeError("transport post_processing options must be ModflowPostprocessOptions")

        resolved = options
        if resolved is None:
            inherited = getattr(self.model_modflow, "last_postprocess_options", None)
            if isinstance(inherited, ModflowPostprocessOptions):
                resolved = inherited
        if resolved is None:
            return ModflowPostprocessOptions(export_all_tif=bool(export_all_tif))
        if bool(getattr(resolved, "export_all_tif", False)) == bool(export_all_tif):
            return resolved
        return replace(resolved, export_all_tif=bool(export_all_tif))

    def post_processing(
        self,
        model_mt3dms: object,
        concentration_seepage: bool = True,
        mass_seepage: bool = True,
        mass_accumulated: bool = False,
        export_all_tif: bool = False,
        options: ModflowPostprocessOptions | None = None,
    ):
        runtime_options = self._resolve_postprocess_options(
            export_all_tif=export_all_tif,
            options=options,
        )
        export_all_tif = bool(runtime_options.export_all_tif)
        self.save_file = os.path.join(self.full_path, "_postprocess")
        create_folder(self.save_file)
        self.tifs_file = os.path.join(self.save_file, "_rasters")
        create_folder(self.tifs_file)

        path_ucn = os.path.join(self.full_path, f"{self.model_name_mt}.ucn")
        conc_reader = None
        try:
            ucnobj = bf.UcnFile(path_ucn)
            conc_reader = ucnobj
            concobj_1c = ucnobj.get_alldata(mflay=None)
        except Exception:
            # MF6-GWT concentration output may use HeadFile structure with double precision.
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
        times = list(getattr(self.model_modflow, "times", []) or [])
        if len(times) != int(self.model_modflow.nper):
            try:
                times = [float(value) for value in conc_reader.get_times()]
            except Exception:
                times = []
        if len(times) != int(self.model_modflow.nper):
            times = [float(i + 1) for i in range(int(self.model_modflow.nper))]

        outflow_drain = getattr(self.model_modflow, "dict_outflow_drain", {})
        dem_mask = np.asarray(
            getattr(self.model_modflow, "dem_mask", self.model_modflow.dem < -9999),
            dtype=bool,
        ).reshape(-1)

        dict_concentration_seepage = {}
        dict_mass_seepage = {}
        dict_mass_accumulated = {}
        can_export_raster = bool(
            getattr(self.model_modflow.solver_mesh, "is_structured", False)
            and getattr(self.model_modflow, "dem_watershed_path", "")
        )

        def _reshape_for_export(arr):
            return self.model_modflow._to_export_array(np.asarray(arr, dtype=float).reshape(-1))

        for i in range(self.model_modflow.nper):
            the_time = str(i + 1)
            seep = outflow_drain.get(i, np.zeros(int(self.model_modflow.ncpl), dtype=float))
            seep = np.asarray(seep, dtype=float).reshape(-1)
            conc_time_idx = min(i, conc_last_idx)
            mass_surf = None

            if concentration_seepage:
                conc_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
                conc_surf[seep <= 0] = -9999
                conc_surf[dem_mask] = -9999
                dict_concentration_seepage[i] = _reshape_for_export(conc_surf)
                if can_export_raster and (export_all_tif or i == 0):
                    export_tif(
                        self.model_modflow.dem_watershed_path,
                        _reshape_for_export(conc_surf),
                        os.path.join(self.tifs_file, f"concentration_seepage_t({the_time}).tif"),
                        -9999,
                    )

            if mass_seepage or mass_accumulated:
                mass_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
                mass_surf[seep <= 0] = np.nan
                mass_surf = mass_surf * seep
                mass_surf[dem_mask] = -9999
                mass_surf = np.where(np.isnan(mass_surf), -9999, mass_surf)
            if mass_seepage and mass_surf is not None:
                dict_mass_seepage[i] = _reshape_for_export(mass_surf)
                if can_export_raster and (export_all_tif or i == 0):
                    export_tif(
                        self.model_modflow.dem_watershed_path,
                        _reshape_for_export(mass_surf),
                        os.path.join(self.tifs_file, f"mass_seepage_t({the_time}).tif"),
                        -9999,
                    )

            if mass_accumulated and can_export_raster:
                routing_ctx = self.model_modflow._ensure_solver_routing_context()
                accumulated_mass = masstransfer.Masstransfer(
                    self.model_modflow.geographic,
                    f"mass_seepage_t({the_time}).tif",
                    f"tracept_conc_t({the_time}).shp",
                    f"mass_accumulated_t({the_time}).tif",
                    extraction_folder=self.save_file,
                    routing_fill_path=routing_ctx.correc_path,
                    routing_direc_path=routing_ctx.direc_path,
                )
                accumulated_mass.trace_cumulated()
                with bf.HeadFile(
                    os.path.join(self.tifs_file, f"mass_accumulated_t({the_time}).tif")
                ) as src:
                    dict_mass_accumulated[i] = src.read(1)
            elif (
                mass_accumulated
                and mass_surf is not None
                and not getattr(self.model_modflow.solver_mesh, "is_structured", False)
            ):
                accumulated_mass = self.model_modflow._accumulate_unstructured_cell_values(
                    local_values=np.where(mass_surf <= -9999.0, 0.0, mass_surf),
                    reference_values=np.where(
                        dem_mask,
                        np.nan,
                        np.asarray(self.model_modflow.dem, dtype=float).reshape(-1),
                    ),
                    inactive_mask=dem_mask,
                )
                accumulated_mass[dem_mask] = -9999.0
                dict_mass_accumulated[i] = _reshape_for_export(accumulated_mass)

        self.dict_concentration_seepage = dict_concentration_seepage
        self.dict_mass_seepage = dict_mass_seepage
        self.dict_mass_accumulated = dict_mass_accumulated
        if concentration_seepage:
            np.save(
                os.path.join(self.save_file, "concentration_seepage"), dict_concentration_seepage
            )
        if mass_seepage:
            np.save(os.path.join(self.save_file, "mass_seepage"), dict_mass_seepage)
        if mass_accumulated:
            np.save(os.path.join(self.save_file, "mass_accumulated"), dict_mass_accumulated)
        self.model_modflow.save_file = self.save_file
        self.model_modflow._export_native_mesh_outputs(
            options=runtime_options,
            times=times,
            datasets={
                "concentration_seepage": dict_concentration_seepage,
                "mass_seepage": dict_mass_seepage,
                "mass_accumulated": dict_mass_accumulated,
            },
            prefix="transport",
        )
