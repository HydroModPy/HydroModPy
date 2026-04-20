# -*- coding: utf-8 -*-
"""
* Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

from collections.abc import Mapping
import flopy
import numpy as np
import os
import rasterio
import sys
from tqdm import tqdm

from hydromodpy.solver.modflow_common.binary_reader import (
    open_cell_budget_file,
    open_head_file,
)

# Map MODFLOW ITMUNI codes to seconds per time unit.
# Used to convert FieldParam SI values (m/s) to solver time units.
_ITMUNI_TO_SECONDS: dict[int, float] = {
    0: 1.0,         # undefined → treat as seconds
    1: 1.0,         # seconds
    2: 60.0,        # minutes
    3: 3600.0,      # hours
    4: 86400.0,     # days
    5: 31557600.0,  # years (365.25 days)
}

from hydromodpy.core.tools import get_logger
from hydromodpy.core.tools.filesystem import create_folder
from hydromodpy.core.tools.raster_io import export_tif
from hydromodpy.solver.modflow_common import (
    ensure_platform_executable,
    SolverGridContext,
    SolverRoutingContext,
    build_solver_routing_context,
    masstransfer,
    write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_common.discretization_spatial import (
    build_spatial_discretization,
    resolve_domain_surfaces,
)
from hydromodpy.solver.modflow_common.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.contracts import Solver
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SolverSGridConfig
from .diagnostics import check_water_flow_connectivity
from .flow_to_modflow_adapter import FlowToModflowAdapter
from .intermittency import export_intermittency
from .nwt_config import (
    ModflowConfig,
    ModflowSpecifParams,
)
from .nwt_options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from .postprocess import (
    NODATA,
    compute_groundwater_flux,
    compute_groundwater_storage,
    compute_outlet_discharge_east_side_m3_s,
    compute_outflow_drain,
    compute_seepage_areas,
    compute_watertable_depth,
    compute_watertable_elevation,
)

logger = get_logger(__name__)
MODFLOW_LENUNI_METERS = 2

# ---------------------------------------------------------------------------
# Helper: run MODFLOW with a tqdm progress bar on stress periods
# ---------------------------------------------------------------------------

import re as _re

_SOLVING_RE = _re.compile(
    r"Solving:\s+Stress period:\s+(\d+)\s+Time step:\s+(\d+)",
    _re.IGNORECASE,
)


def _run_model_with_progress(
    mf_model,
    nper: int,
) -> tuple[bool, list[str]]:
    """Run a MODFLOW model while showing a tqdm progress bar.

    Intercepts solver stdout, parses "Solving: Stress period: N …" lines
    to advance the bar, and suppresses the raw output.  Non-solving lines
    (header, termination message, etc.) are forwarded to the logger.
    """
    import flopy.mbase as _mbase

    pbar = tqdm(
        total=nper,
        desc="[INFO] MODFLOW solving",
        unit="sp",
        disable=nper <= 1,
    )
    _last_sp = 0

    def _progress_print(line: str) -> None:
        nonlocal _last_sp
        m = _SOLVING_RE.search(line)
        if m:
            sp = int(m.group(1))
            if sp > _last_sp:
                pbar.update(sp - _last_sp)
                _last_sp = sp
            return
        # Forward important non-solving lines (header, termination, etc.)
        stripped = line.strip()
        if stripped:
            logger.debug("%s", stripped)

    try:
        success, buff = _mbase.run_model(
            mf_model.exe_name,
            mf_model.namefile,
            model_ws=mf_model.model_ws,
            silent=False,
            report=True,
            custom_print=_progress_print,
        )
    finally:
        pbar.close()

    return success, buff


# %% CLASS


class Modflow(Solver):
    """
    Class Modflow.

    To build, run the hydrologic model and manage/format simulation outputs.
    """

    def __init__(
        self,
        geographic: object,
        modflow_config: ModflowConfig | Mapping[str, object] | None = None,
        # Worflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str = "bin",
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        """
        Initialize method.

        Parameters
        ----------
        geographic : object
            Object geographic build by HydroModPy.
        model_folder : str, optional
            Path where the model will be store. The default is 'HydroModPy_outputs'.
        model_name : str, optional
            Name of the model. The default is 'Default'.
        bin_path : str, optional
            Location folder of the modflow executables. The default is 'bin'.
        modflow_config : ModflowConfig | Mapping | None, optional
            Expert MODFLOW-NWT package parameters loaded from
            `[modflownwt.runtime]`, `[modflownwt.process_specific]`,
            `[modflownwt.sgrid.planar]`, and `[modflownwt.sgrid.vertical]`
            in TOML.
            If None, internal defaults from ModflowConfig are used.
        preprocess_options : ModflowPreprocessOptions | None
            Optional typed options for pre_processing stage.
        """

        # %% Initialization paths

        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            create_folder(self.model_folder)

        self.model_name = model_name

        if (sys.platform == "win32") or (sys.platform == "win64"):
            self.exe = os.path.join(bin_path, "win", "mfnwt.exe")
        if sys.platform == "linux":
            self.exe = os.path.join(bin_path, "linux", "mfnwt")
        if sys.platform == "darwin":
            self.exe = os.path.join(bin_path, "mac", "mfnwt")
        self.exe = str(ensure_platform_executable(self.exe))

        self.full_path = os.path.join(model_folder, model_name)  #'modraw'

        # %% Domain definition

        self.geographic = geographic
        self.flow = None
        self.domain = None
        self.flow_regime: str | None = None

        self.resolution = geographic.dem_res
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        try:
            self.sink = geographic.depressions_data
        except AttributeError:
            pass

        if preprocess_options is None:
            preprocess_options = ModflowPreprocessOptions()
        self.preprocess_options = preprocess_options
        self._apply_preprocess_options(preprocess_options)

        # %% Flopy model parameters driven by expert config
        specif_params = ModflowSpecifParams.from_config(modflow_config)
        if modflow_config is None:
            self.modflow_config = ModflowConfig()
        elif isinstance(modflow_config, ModflowConfig):
            self.modflow_config = modflow_config
        else:
            self.modflow_config = ModflowConfig.model_validate(dict(modflow_config))

        self._params: ModflowSpecifParams = specif_params
        self.sgrid_config: SolverSGridConfig | None = specif_params.sgrid
        self.tgrid_config = specif_params.tgrid
        self.grid_ctx: SolverGridContext | None = None
        self.routing_ctx: SolverRoutingContext | None = None

        # dis_itmuni is mutable: may be updated in _build_temporal_discretization
        self.dis_itmuni = specif_params.runtime.dis_itmuni

    def _select_active_dem(self, box: bool) -> None:
        """Select and normalize the active DEM support for the simulation."""
        if box:
            dem_source = self.geographic.dem_box_buff_data
            self.dem_watershed_path = self.geographic.watershed_box_buff_dem
        else:
            dem_source = self.geographic.dem_data
            self.dem_watershed_path = self.geographic.watershed_buff_dem

        self.box = bool(box)
        dem = np.asarray(dem_source, dtype=float).copy()
        dem[(dem <= NODATA) | (dem >= 9999)] = NODATA
        self.nrow = int(dem.shape[0])
        self.ncol = int(dem.shape[1])

    def _apply_preprocess_options(
        self, options: ModflowPreprocessOptions | None = None
    ) -> None:
        """Apply pre-processing options on model state."""
        if options is None:
            options = self.preprocess_options
        if not isinstance(options, ModflowPreprocessOptions):
            raise TypeError(
                "pre_processing options must be a ModflowPreprocessOptions instance."
            )

        self.preprocess_options = options
        self.sink_fill = bool(options.sink_fill)
        self.time_grid = getattr(options, "time_grid", None)
        self.check_grid = bool(options.check_grid)
        self._select_active_dem(box=bool(options.box))

    # %% PRE-PROCESSING

    def _get_domain_surfaces(self):
        """
        Return explicit domain surfaces used by the MODFLOW spatial grid.
        """
        return resolve_domain_surfaces(
            domain=self.domain,
        )

    def _resolve_flow_regime(self) -> str | None:
        """Return flow regime from flow config when available."""
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
        """Validate mandatory inputs before MODFLOW package assembly."""
        if self.flow is None:
            raise ValueError("pre_processing requires a configured Flow object.")
        if self.domain is None:
            raise ValueError("pre_processing requires a configured Domain object.")

        flow_regime = self._resolve_flow_regime()
        if flow_regime is None:
            raise ValueError(
                "Missing flow.flow_regime configuration: Modflow temporal setup "
                "must be driven by [flow].flow_regime."
            )
        self.flow_regime = flow_regime

        launcher_time_grid = getattr(self.preprocess_options, "time_grid", None)
        if launcher_time_grid is None and self.flow_regime != "steady":
            raise ValueError(
                "Launcher flow preprocessing requires preprocess_options.time_grid "
                "derived from [simulation.time] for transient flow runs. "
                "Solver tgrid fallback is no longer supported."
            )

    def _initialize_solver_packages(self) -> None:
        """Initialize FLOPY MODFLOW and NWT solver packages."""
        r = self._params.runtime
        self.mf = flopy.modflow.Modflow(
            self.model_name,
            exe_name=self.exe,
            version=r.mf_version,
            listunit=r.mf_listunit,
            verbose=r.mf_verbose,
            model_ws=self.full_path,
        )

        self.nwt = flopy.modflow.ModflowNwt(
            self.mf,
            headtol=r.nwt_headtol,
            fluxtol=r.nwt_fluxtol,
            maxiterout=r.nwt_maxiterout,
            thickfact=r.nwt_thickfact,
            linmeth=r.nwt_linmeth,
            iprnwt=r.nwt_iprnwt,
            ibotav=r.nwt_ibotav,
            options=r.nwt_options,
            Continue=r.nwt_continue,
            backflag=r.nwt_backflag,
            stoptol=r.nwt_stoptol,
        )

    def _build_temporal_discretization(self) -> dict[str, object]:
        """Build temporal discretization arrays from tgrid configuration."""
        launcher_time_grid = getattr(self.preprocess_options, "time_grid", None)
        result = build_temporal_discretization_from_time_grid(
            time_grid=launcher_time_grid,
            flow_regime=self.flow_regime,
            firstpersteady=bool(getattr(self.tgrid_config, "firstpersteady", True)),
        )

        self.dis_itmuni = result.itmuni
        self.nper = result.nper
        self.perlen = result.perlen
        self.nstp = result.nstp
        self.steady = result.steady
        self.start_datetime = result.start_datetime

        return result.as_dis_kwargs()

    def _build_spatial_discretization(self):
        """Build structured spatial grid from validated domain surfaces."""
        self.grid_ctx = build_spatial_discretization(
            domain=self.domain,
            sgrid_config=self.sgrid_config,
            # MODFLOW-NWT remains on the structured backend for now even when a
            # runtime Gmsh mesh is available elsewhere in the launcher state.
        )
        if not self.grid_ctx.solver_mesh.is_structured:
            raise ValueError("MODFLOW NWT requires a structured grid")
        self.solver_mesh = self.grid_ctx.solver_mesh
        self.top_elevation = self.solver_mesh.reshape_to_grid(self.solver_mesh.top)
        self.inactive_mask = self.solver_mesh.reshape_to_grid(self.solver_mesh.inactive_mask[0])
        self.nlay = self.solver_mesh.nlay
        self.nrow = self.solver_mesh.nrow
        self.ncol = self.solver_mesh.ncol
        self.bottom_layer = self.solver_mesh.reshape_to_grid(self.solver_mesh.botm[-1])
        self.zbot = self.solver_mesh.botm_grid
        self.cell_area = float(self.grid_ctx.grid.cell_area)
        self.resolution = float(self.grid_ctx.grid.characteristic_length)
        self.dem_watershed_path = self._write_solver_grid_template()
        return self.solver_mesh

    def _write_solver_grid_template(self) -> str:
        """Persist one solver-grid-aligned raster template used by exports."""
        if self.grid_ctx is None:
            raise ValueError("grid_ctx must exist before writing a solver grid template")
        os.makedirs(self.full_path, exist_ok=True)
        template_path = os.path.join(self.full_path, "_solver_grid_template.tif")
        top_flat = np.asarray(self.grid_ctx.top_elevation, dtype=float)
        top_2d = self.solver_mesh.reshape_to_grid(top_flat)
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

    def _build_dis_package(self, solver_mesh, temporal_dis: Mapping[str, object]) -> None:
        """Create FLOPY DIS package from spatial and temporal discretization."""
        dis_kwargs = solver_mesh.to_dis_kwargs()
        verts = np.asarray(solver_mesh.planar_mesh.vertices, dtype=float)
        xmin = float(verts[:, 0].min())
        ymax = float(verts[:, 1].max())
        self.dis = flopy.modflow.ModflowDis(
            self.mf,
            lenuni=MODFLOW_LENUNI_METERS,
            xul=xmin,
            yul=ymax,
            **dis_kwargs,
            itmuni=temporal_dis["itmuni"],
            nper=temporal_dis["nper"],
            perlen=temporal_dis["perlen"],
            nstp=temporal_dis["nstp"],
            steady=temporal_dis["steady"],
            start_datetime=temporal_dis["start_datetime"],
        )

    def _build_flow_modflow_inputs(self, solver_mesh):
        """Adapt Flow+Domain data into solver-ready payloads."""
        adapter = FlowToModflowAdapter(
            flow=self.flow,
            domain=self.domain,
            solver_mesh=solver_mesh,
            nper=int(self.nper),
            grid=None if self.grid_ctx is None else self.grid_ctx.grid,
            simulation_window=None if self.time_grid is None else self.time_grid.window,
            sink_fill=bool(self.sink_fill),
            sink=getattr(self, "sink", None),
            flow_runtime_overrides=getattr(self, "flow_runtime_overrides", None),
        )
        return adapter.build()

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
        """
        Pre-processing to build the hydrologic model.

        Parameters
        ----------
        flow : object
            Flow object for this preprocessing run.
        domain : object
            Domain object for this preprocessing run.
        options : ModflowPreprocessOptions, optional
            Optional typed pre-processing options.

        Returns
        -------
        None.

        """
        self.flow = flow
        self.domain = domain
        self.runtime_mesh_planar = mesh_planar
        self.runtime_mesh_support = mesh_support
        self.flow_runtime_overrides = (
            None
            if flow_runtime_overrides is None
            else dict(flow_runtime_overrides)
        )
        active_options = self.preprocess_options if options is None else options
        self._apply_preprocess_options(active_options)

        self._validate_pre_processing_inputs()
        self._initialize_solver_packages()
        temporal_dis = self._build_temporal_discretization()
        sgrid = self._build_spatial_discretization()
        self._build_dis_package(sgrid, temporal_dis)

        # %% Flow adaptation (process -> solver-ready payloads)
        flow_inputs = self._build_flow_modflow_inputs(sgrid)

        # FieldParam stores hydraulic properties in SI (m/s). MODFLOW
        # interprets values according to itmuni. Convert K (and derived
        # conductances) from SI to solver time units.
        _si_to_solver = _ITMUNI_TO_SECONDS.get(self.dis_itmuni, 1.0)

        # Boundary conditions arrays
        self.drain_array = flow_inputs.drain_array

        if flow_inputs.chd_spd is not None:
            self.chd = flopy.modflow.ModflowChd(
                self.mf, stress_period_data=flow_inputs.chd_spd
            )

        # ---- flopy.modflow.ModflowBas
        # BAS contract reminder:
        # - ibound > 0: active cells (head is solved)
        # - ibound = 0: inactive/no-flow cells
        # - ibound < 0: constant-head cells
        # - strt: startup head field and imposed head on constant-head cells
        self.bas_hnoflo = self._params.runtime.bas_hnoflo
        self.bas = flopy.modflow.ModflowBas(
            self.mf,
            ibound=flow_inputs.ibound,
            strt=flow_inputs.strt,
            hnoflo=self.bas_hnoflo,
        )

        # %% Parametrization

        # Specify the unconfined conditions of the aquifer.
        self.laywet = np.zeros(self.nlay)  # wettable
        self.laytype = np.ones(self.nlay)  # convertible

        self.hk = flow_inputs.hk * _si_to_solver
        self.hk_value = flow_inputs.hk_value * _si_to_solver
        self.sy = flow_inputs.sy
        self.sy_value = flow_inputs.sy_value
        self.ss = flow_inputs.ss
        self.ss_value = flow_inputs.ss_value

        # ---- flopy.modflow.ModflowUpw
        self.upw_hdry = self._params.runtime.upw_hdry
        self.upw = flopy.modflow.ModflowUpw(
            self.mf,
            laytyp=self.laytype,
            laywet=self.laywet,
            hk=self.hk,
            sy=self.sy,
            ss=self.ss,
            vka=self._params.process_specific.vka,
            iphdry=self._params.runtime.upw_iphdry,
            hdry=self.upw_hdry,
            layvka=self._params.runtime.upw_layvka,
            extension="upw",
            unitnumber=None,
            noparcheck=False,
        )

        # %% Source terms

        if flow_inputs.evt_spd is not None:
            self.evt = flopy.modflow.ModflowEvt(
                self.mf,
                evtr=flow_inputs.evt_spd,
                surf=self.top_elevation,
                nevtop=self._params.runtime.evt_nevtop,
                exdp=self._params.process_specific.exdp,
                ievt=self._params.runtime.evt_ievt,
                ipakcb=self._params.runtime.evt_ipakcb,
            )

        # ---- flopy.modflow.ModflowRch
        if flow_inputs.rch_data is not None:
            self.rch = flopy.modflow.ModflowRch(self.mf, rech=flow_inputs.rch_data)
        # Store the RCH schedule as an instance attribute so that post-processing
        # consumers (e.g. Timeseries) can read it without going back to the flow
        # object.  This is the *processed* schedule: first_clim has been applied
        # to period 0 and, when negative_to_evt=True, negative values have already
        # been clipped to 0 (their absolute values were routed to the EVT package
        # above).  Format: dict {kper: rate [L/T]} — one entry per stress period.
        # None when recharge is not in active_sinks_sources.
        self.recharge = flow_inputs.rch_data

        # %% Drain package

        # DRN is applied to all the surface of the model: enables seepage on the top layer
        if flow_inputs.drn_spd is not None:
            # Drainage conductance [L²/T] was derived from hk in SI;
            # convert to solver time units (column index 4 = conductance).
            for _kper_data in flow_inputs.drn_spd.values():
                _kper_data[:, 4] *= _si_to_solver
            self.drn = flopy.modflow.ModflowDrn(
                self.mf,
                stress_period_data=flow_inputs.drn_spd,
            )

        # %% Well package

        if flow_inputs.wel_spd:
            self.wel = flopy.modflow.ModflowWel(
                self.mf, ipakcb=self._params.runtime.wel_ipakcb, stress_period_data=flow_inputs.wel_spd
            )

        # %% Output control

        stress_period_data = {}
        for kper in range(self.nper):
            kstp = int(self.nstp[kper])
            if kstp > 1:
                # Multiple substeps: save every substep for transient accuracy
                for ts in range(kstp):
                    stress_period_data[(kper, ts)] = ["save head", "save budget"]
            else:
                stress_period_data[(kper, 0)] = ["save head", "save budget"]
        # ---- flopy.modflow.ModflowOc
        self.oc = flopy.modflow.ModflowOc(
            self.mf,
            stress_period_data=stress_period_data,
            extension=["oc", "hds", "cbc"],
            unitnumber=None,
            compact=self._params.runtime.oc_compact,
        )
        self.oc.reset_budgetunit(fname=self.model_name + ".cbc")

        # %% Grid connectivity check

        if active_options.check_grid:
            grid_to_check = self.mf.modelgrid.top_botm
            problematic_cells = check_water_flow_connectivity(grid_to_check)
            if not problematic_cells:
                logger.info("MODFLOW grid connectivity check passed")
                self.prob_cells = 0
            else:
                logger.warning(
                    "MODFLOW grid connectivity check found %d problematic cells",
                    len(problematic_cells),
                )
                self.prob_cells = len(problematic_cells)

    # %% PROCESSING

    def processing(
        self,
        options: ModflowRunOptions | None = None,
    ):
        """
        Run the hydrologic model.

        Parameters
        ----------
        options : ModflowRunOptions, optional
            Optional typed run options.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation is done correctly.

        """

        if options is None:
            options = ModflowRunOptions()
        elif not isinstance(options, ModflowRunOptions):
            raise TypeError("processing options must be a ModflowRunOptions instance.")

        if options.link_mt3dms:
            lmt = flopy.modflow.ModflowLmt(
                self.mf,
                output_file_name=self._params.runtime.lmt_output_file_name,
                extension=self._params.runtime.lmt_extension,
                output_file_format=self._params.runtime.lmt_output_format,
                unitnumber=None,
            )

        # Create modflow files
        if options.write_model:
            # Write input files
            self.mf.write_input()

        # Run modflow files
        success_model = False
        if options.run_model:
            if options.verbose:
                success_model, _ = _run_model_with_progress(
                    self.mf, int(self.nper),
                )
            else:
                success_model, _ = self.mf.run_model(silent=True)

        return success_model

    # %% POST-PROCESSING

    def _setup_postprocess_folders(self) -> None:
        """Create the output folder hierarchy for post-processing artefacts."""
        self.save_file = os.path.join(self.full_path, "_postprocess")
        create_folder(self.save_file)

        self.figure_file = os.path.join(self.full_path, "_postprocess", "_figures")
        create_folder(self.figure_file)

        self.temporary_file = os.path.join(self.full_path, "_postprocess", "_temporary")
        create_folder(self.temporary_file)

        self.tifs_file = os.path.join(self.full_path, "_postprocess", "_rasters")
        create_folder(self.tifs_file)

        self.save_fig = os.path.join(self.model_folder, "_figures")
        create_folder(self.save_fig)

    def post_processing(
        self,
        options: ModflowPostprocessOptions | None = None,
    ):
        """
        Create outputs files.

        Parameters
        ----------
        options : ModflowPostprocessOptions, optional
            Optional typed post-processing options.
        """
        if options is None:
            options = ModflowPostprocessOptions()
        elif not isinstance(options, ModflowPostprocessOptions):
            raise TypeError(
                "post_processing options must be a ModflowPostprocessOptions instance."
            )

        self._setup_postprocess_folders()

        # %% Load essential data

        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name)

        # Files have been output in the processing phase and are re-read here.
        if not hasattr(self, "inactive_mask"):
            raise ValueError("inactive_mask must be set before MODFLOW post-processing.")
        inactive_mask = np.asarray(self.inactive_mask, dtype=bool)
        # heads
        self.head_fpu = open_head_file(self.path_file + ".hds", precision="single")
        # fluxes
        self.cbb = open_cell_budget_file(self.path_file + ".cbc", precision="single")

        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkpers = self.head_fpu.get_kstpkper()

        # Params model
        self.nper = self.dis.nper
        self.kper = np.arange(0, self.nper, 1)
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1

        # %% Initialize result dictionaries
        # x[time] = matrix — one 2-D array per stress period
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_outlet_discharge_east_side_m3_s = {}
        self.dict_groundwater_flux = {}
        self.dict_specific_discharge = {}
        self.dict_accumulation_flux = {}
        self.dict_groundwater_storage = {}
        self.dict_persistency_index = {}
        self.dict_intermittency_yearly = {}
        self.dict_intermittency_monthly = {}
        self.dict_intermittency_weekly = {}
        self.dict_intermittency_daily = {}

        logger.debug("Post-processing MODFLOW: %s", self.model_name)

        # %% Loop over stress periods

        for item, time in enumerate(tqdm(
            self.times,
            desc="[INFO] Post-processing",
            unit="sp",
            disable=len(self.times) <= 1,
        )):

            if len(self.times) == 1:
                self.kstpkper = self.kstpkpers[0]
            else:
                self.kstpkper = (self.kstp[item], self.kper[item])

            lead_numb = str(item)
            do_export_tif = options.export_all_tif or (item == 0)

            self.head = self.head_fpu.get_data(totim=time)

            if options.watertable_elevation:
                self.wt_elev = compute_watertable_elevation(self.head, self.nlay)
                self.wt_elev[inactive_mask] = NODATA
                output_path = (
                    self.tifs_file + f"/watertable_elevation_t({lead_numb}).tif"
                )
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.wt_elev, output_path, NODATA
                    )
                self.dict_watertable_elevation[item] = self.wt_elev

            if options.watertable_depth:
                self.wt_depth = compute_watertable_depth(
                    self.wt_elev, self.top_elevation, inactive_mask
                )
                output_path = (
                    self.tifs_file + f"/watertable_depth_t({lead_numb}).tif"
                )
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.wt_depth, output_path, NODATA
                    )
                self.dict_watertable_depth[item] = self.wt_depth

            if options.seepage_areas:
                self.seep_area = compute_seepage_areas(
                    self.wt_elev, self.top_elevation, inactive_mask
                )
                output_path = self.tifs_file + f"/seepage_areas_t({lead_numb}).tif"
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.seep_area, output_path, NODATA
                    )
                self.dict_seepage_areas[item] = self.seep_area

            if options.outflow_drain:
                self.drain = self.cbb.get_data(
                    text="DRAINS", kstpkper=self.kstpkper, totim=time
                )
                self.out_drn = compute_outflow_drain(
                    self.drain,
                    self.drain_array,
                    self.dis.nrow,
                    self.dis.ncol,
                    inactive_mask,
                )
                output_path = self.tifs_file + f"/outflow_drain_t({lead_numb}).tif"
                if options.accumulation_flux or do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.out_drn, output_path, NODATA
                    )
                self.dict_outflow_drain[item] = self.out_drn

            if options.outlet_discharge_east_side_m3_s:
                try:
                    constant_head = self.cbb.get_data(
                        text="CONSTANT HEAD",
                        kstpkper=self.kstpkper,
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
                    nrow=self.dis.nrow,
                    ncol=self.dis.ncol,
                )
                self.dict_outlet_discharge_east_side_m3_s[item] = np.asarray(
                    [outlet_discharge_m3_s],
                    dtype=float,
                )

            if options.groundwater_flux:
                self.flux_top = compute_groundwater_flux(
                    self.cbb, self.kstpkper, time, self.nlay, inactive_mask
                )
                output_path = (
                    self.tifs_file + f"/groundwater_flux_t({lead_numb}).tif"
                )
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.flux_top, output_path, NODATA
                    )
                self.dict_groundwater_flux[item] = self.flux_top

            if options.groundwater_storage:
                self.wt_sto = compute_groundwater_storage(
                    self.wt_elev,
                    self.zbot,
                    self.sy,
                    self.top_elevation,
                    cell_area=float(self.cell_area),
                )
                output_path = (
                    self.tifs_file + f"/groundwater_storage_t({lead_numb}).tif"
                )
                if do_export_tif:
                    export_tif(
                        self.dem_watershed_path, self.wt_sto, output_path, NODATA
                    )
                self.dict_groundwater_storage[item] = self.wt_sto

            if options.accumulation_flux:
                routing_ctx = self._ensure_solver_routing_context()
                accumulated_flow = masstransfer.Masstransfer(
                    self.geographic,
                    f"outflow_drain_t({lead_numb}).tif",
                    f"tracept_t({lead_numb}).shp",
                    f"accumulation_flux_t({lead_numb}).tif",
                    extraction_folder=self.save_file,
                    routing_fill_path=routing_ctx.correc_path,
                    routing_direc_path=routing_ctx.direc_path,
                )
                accumulated_flow.trace_cumulated()
                output_path = (
                    self.tifs_file + f"/accumulation_flux_t({lead_numb}).tif"
                )
                with rasterio.open(output_path) as src:
                    self.dict_accumulation_flux[item] = src.read(1)

        # %% Persistency index

        if options.persistency_index and self.dict_accumulation_flux:
            logger.info("Exporting persistency index maps")
            acc_npy_raw = self.dict_accumulation_flux
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
            self.pi = np.ma.masked_where(days_flux <= 0, days_flux)
            self.dict_persistency_index[0] = self.pi
            pi_export[days_flux <= 0] = NODATA
            pi_export[mask] = NODATA
            output_path = self.tifs_file + "/persistency_index_t(-).tif"
            export_tif(self.dem_watershed_path, pi_export, output_path, NODATA)

        # %% Intermittency (daily / weekly / monthly / yearly)

        _any_intermittency = (
            options.intermittency_daily
            or options.intermittency_weekly
            or options.intermittency_monthly
            or options.intermittency_yearly
        )
        acc_npy_raw = self.dict_accumulation_flux if (_any_intermittency and self.dict_accumulation_flux) else None

        if options.intermittency_daily and acc_npy_raw is not None:
            export_intermittency(
                label="daily",
                window_size=365,
                acc_npy_raw=acc_npy_raw,
                result_dict=self.dict_intermittency_daily,
                tifs_file=self.tifs_file,
                watershed_dem=self.dem_watershed_path,
            )

        if options.intermittency_weekly and acc_npy_raw is not None:
            export_intermittency(
                label="weekly",
                window_size=52,
                acc_npy_raw=acc_npy_raw,
                result_dict=self.dict_intermittency_weekly,
                tifs_file=self.tifs_file,
                watershed_dem=self.dem_watershed_path,
            )

        if options.intermittency_monthly and acc_npy_raw is not None:
            export_intermittency(
                label="monthly",
                window_size=12,
                acc_npy_raw=acc_npy_raw,
                result_dict=self.dict_intermittency_monthly,
                tifs_file=self.tifs_file,
                watershed_dem=self.dem_watershed_path,
            )

        if options.intermittency_yearly and acc_npy_raw is not None:
            export_intermittency(
                label="yearly",
                window_size=1,
                acc_npy_raw=acc_npy_raw,
                result_dict=self.dict_intermittency_yearly,
                tifs_file=self.tifs_file,
                watershed_dem=self.dem_watershed_path,
            )


# %% NOTES
