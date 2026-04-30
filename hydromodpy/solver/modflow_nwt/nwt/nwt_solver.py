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

from __future__ import annotations

import os
from collections.abc import Mapping

import flopy
import numpy as np

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.contracts import Solver
from hydromodpy.solver.modflow_common import (
    SolverRoutingContext,
    build_solver_routing_context,
    ensure_solver_binary,
    write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_common.options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow_grid import (
    SolverGridContext,
    build_spatial_discretization,
    build_temporal_discretization_from_time_grid,
    resolve_domain_surfaces,
)
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import SolverSGridConfig

from ._post_processing import run_post_processing
from ._pre_processing import assemble_flopy_packages
from ._progress import run_model_with_progress
from .flow_to_modflow_adapter import FlowToModflowAdapter
from .nwt_config import (
    ModflowConfig,
    ModflowSpecifParams,
)
from .postprocess import NODATA

logger = get_logger(__name__)
MODFLOW_LENUNI_METERS = 2


class ModflowNwt(Solver):
    """MODFLOW-NWT solver lifecycle facade.

    Drives pre-processing, processing, and post-processing for the
    MODFLOW-NWT backend. Heavy concern-specific work is delegated to:

    - ``_pre_processing.assemble_flopy_packages`` for FLOPY package wiring,
    - ``_post_processing.run_post_processing`` for output reduction,
    - ``_progress.run_model_with_progress`` and ``scale_rate_payload``
      for runtime helpers.
    """

    def __init__(
        self,
        geographic: object,
        modflow_config: ModflowConfig | Mapping[str, object] | None = None,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str | None = None,
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        """Initialize the solver state and resolve the MODFLOW-NWT binary.

        Parameters
        ----------
        geographic : object
            Geographic context built by HydroModPy.
        model_folder : str, optional
            Path where the model will be stored. Default is ``HydroModPy_outputs``.
        model_name : str, optional
            Model name. Default is ``Default``.
        bin_path : str | None, optional
            Folder that holds the MODFLOW executables. When None the
            HydroModPy-managed cache (``~/.cache/hydromodpy/bin``) is used
            and missing binaries are downloaded on first use.
        modflow_config : ModflowConfig | Mapping | None, optional
            Expert MODFLOW-NWT package parameters. When None internal
            defaults from ``ModflowConfig`` are used.
        preprocess_options : ModflowPreprocessOptions | None
            Optional typed options for the pre-processing stage.
        """
        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            create_folder(self.model_folder)

        self.model_name = model_name
        self.exe = str(ensure_solver_binary("mfnwt", bin_path))
        self.full_path = os.path.join(model_folder, model_name)

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

    def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
        """Apply pre-processing options on model state."""
        if options is None:
            options = self.preprocess_options
        if not isinstance(options, ModflowPreprocessOptions):
            raise TypeError("pre_processing options must be a ModflowPreprocessOptions instance.")

        self.preprocess_options = options
        self.sink_fill = bool(options.sink_fill)
        self.time_grid = getattr(options, "time_grid", None)
        self.check_grid = bool(options.check_grid)
        self._select_active_dem(box=bool(options.box))

    def _get_domain_surfaces(self):
        """Return explicit domain surfaces used by the MODFLOW spatial grid."""
        return resolve_domain_surfaces(
            domain=self.domain,
        )

    def _resolve_flow_regime(self) -> str | None:
        """Return the flow regime from flow config when available."""
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
                "Missing flow.flow_regime configuration: ModflowNwt temporal setup "
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
        """Build the structured spatial grid from validated domain surfaces."""
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
        """Create the FLOPY DIS package from spatial and temporal discretization."""
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
        """Adapt Flow + Domain data into solver-ready payloads."""
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
        """Pre-processing to build the hydrologic model.

        Parameters
        ----------
        flow : object
            Flow object for this preprocessing run.
        domain : object
            Domain object for this preprocessing run.
        options : ModflowPreprocessOptions, optional
            Optional typed pre-processing options.
        """
        self.flow = flow
        self.domain = domain
        self.runtime_mesh_planar = mesh_planar
        self.runtime_mesh_support = mesh_support
        self.flow_runtime_overrides = (
            None if flow_runtime_overrides is None else dict(flow_runtime_overrides)
        )
        active_options = self.preprocess_options if options is None else options
        self._apply_preprocess_options(active_options)

        self._validate_pre_processing_inputs()
        self._initialize_solver_packages()
        temporal_dis = self._build_temporal_discretization()
        sgrid = self._build_spatial_discretization()
        self._build_dis_package(sgrid, temporal_dis)

        flow_inputs = self._build_flow_modflow_inputs(sgrid)
        assemble_flopy_packages(self, flow_inputs, active_options)

    def processing(
        self,
        options: ModflowRunOptions | None = None,
    ):
        """Run the hydrologic model.

        Parameters
        ----------
        options : ModflowRunOptions, optional
            Optional typed run options.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation completed successfully.
        """
        if options is None:
            options = ModflowRunOptions()
        elif not isinstance(options, ModflowRunOptions):
            raise TypeError("processing options must be a ModflowRunOptions instance.")

        if options.link_mt3dms:
            flopy.modflow.ModflowLmt(
                self.mf,
                output_file_name=self._params.runtime.lmt_output_file_name,
                extension=self._params.runtime.lmt_extension,
                output_file_format=self._params.runtime.lmt_output_format,
                unitnumber=None,
            )

        if options.write_model:
            self.mf.write_input()

        success_model = False
        if options.run_model:
            if options.verbose:
                success_model, _ = run_model_with_progress(
                    self.mf,
                    int(self.nper),
                )
            else:
                success_model, _ = self.mf.run_model(silent=True)

        return success_model

    def post_processing(
        self,
        options: ModflowPostprocessOptions | None = None,
    ):
        """Create output files from MODFLOW heads and budget.

        Parameters
        ----------
        options : ModflowPostprocessOptions, optional
            Optional typed post-processing options.
        """
        if options is None:
            options = ModflowPostprocessOptions()
        elif not isinstance(options, ModflowPostprocessOptions):
            raise TypeError("post_processing options must be a ModflowPostprocessOptions instance.")

        run_post_processing(self, options)
