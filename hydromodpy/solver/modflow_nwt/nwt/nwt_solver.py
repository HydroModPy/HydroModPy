# Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
# which is available at https://www.apache.org/licenses/LICENSE-2.0.
#
# SPDX-License-Identifier: EPL-2.0 OR Apache-2.0

"""The MODFLOW-NWT flow model: pre-processing and processing."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping

import flopy
import numpy as np

from hydromodpy.catchment.drainage.descent import Descent, DescentBasin
from hydromodpy.catchment.preprocess.capped_breach_config import capped_breach_of
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger
from hydromodpy.model.initial.state import SteadyStart
from hydromodpy.model.model import Model
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.catchment_basin import run_basin
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar
from hydromodpy.solver.modflow_common.flow_directions import (
    build_solver_mesh_descent,
    channel_exits_for_build,
)
from hydromodpy.solver.modflow_common.flow_run import require_cell_mesh
from hydromodpy.solver.modflow_common.options import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow_common.progress import run_model_with_progress
from hydromodpy.solver.modflow_common.raster_export import write_grid_array_to_raster
from hydromodpy.solver.modflow_common.routing_context import (
    SolverRoutingContext,
    build_solver_routing_context,
)
from hydromodpy.solver.modflow_common.sink_mask import resolve_sink_mask
from hydromodpy.solver.modflow_grid.active_connectivity import warn_on_disconnected_active_cells
from hydromodpy.solver.modflow_grid.discretization_spatial import (
    SolverGridContext,
    build_spatial_discretization,
    resolve_domain_surfaces,
)
from hydromodpy.solver.modflow_grid.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig

from ._pre_processing import assemble_flopy_packages
from .flow_to_modflow_adapter import FlowModflowInputs, FlowToModflowAdapter
from .nwt_config import (
    ModflowConfig,
    ModflowSpecifParams,
)
from .steady_initial_conditions import (
    apply_nwt_steady_state_initial_heads,
    run_nwt_steady_state_initialization,
)

logger = get_logger(__name__)
MODFLOW_LENUNI_METERS = 2
# Raster nodata value of the DEM cells outside the domain.
NODATA = -9999


class ModflowNwt:
    """MODFLOW-NWT solver lifecycle facade.

    Drives pre-processing and processing for the MODFLOW-NWT backend.
    ``pre_processing`` receives the frozen ``Model`` of the run and keeps it in
    ``inputs``. The solver reads it and never changes it.
    Heavy concern-specific work is delegated to:

    - ``_pre_processing.assemble_flopy_packages`` for FLOPY package wiring,
    - ``modflow_common.progress.run_model_with_progress`` and
      ``_pre_processing.scale_rate_payload`` for runtime helpers.
    """

    def __init__(
        self,
        modflow_config: ModflowConfig | Mapping[str, object] | None = None,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str | os.PathLike[str] | None = None,
        preprocess_options: ModflowPreprocessOptions | None = None,
    ):
        """Initialize the solver state and resolve the MODFLOW-NWT binary.

        Parameters
        ----------
        model_folder : str, optional
            Path where the model will be stored. Default is ``HydroModPy_outputs``.
        model_name : str, optional
            Model name. Default is ``Default``.
        bin_path : str | PathLike | None, optional
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

        # The Model of the run, set by pre_processing and never written to.
        self.inputs: Model | None = None
        self.flow_regime: str | None = None
        self.last_flow_solve_time_seconds: float | None = None
        # Set by the flow adapter from ``slot.hand_off``: when a transport
        # that follows the flow reads ``face_flow``, the LMT package is
        # built with the run.
        self.link_mt3dms = False
        # The input files ``processing`` wrote, relative to ``full_path``.
        self.input_files: tuple[str, ...] = ()

        # The DEM grid, read off ``inputs.geometry.raster`` by pre_processing.
        self.resolution: float | None = None
        self.xul: float | None = None
        self.yul: float | None = None
        self.sink: np.ndarray | None = None

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
        self.grid_ctx: SolverGridContext | None = None
        self.routing_ctx: SolverRoutingContext | None = None
        self.descent: Descent | None = None
        # The basin of D at the catchment outlet, set with D.
        self.descent_basin: DescentBasin | None = None
        # No lake package: the dam foot of the criterion stays empty.
        self.dam_foot_cells: dict[str, int] = {}
        # Set by the steady initialization: a model never extracted builds no D.
        self.auxiliary = False

        # dis_itmuni is mutable: may be updated in _build_temporal_discretization
        self.dis_itmuni = specif_params.runtime.dis.itmuni

    def _select_active_dem(self, box: bool) -> None:
        """Select and normalize the active DEM support for the simulation."""
        raster = self.inputs.geometry.raster
        if box:
            dem_source = raster.dem_box_buff_data
            self.dem_watershed_path = raster.watershed_box_buff_dem
        else:
            dem_source = raster.dem_data
            self.dem_watershed_path = raster.watershed_buff_dem

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
        self.drain_band_depth_m = float(options.drain_band_depth_m)
        self.drain_bed_thickness_m = float(options.drain_bed_thickness_m)
        self.drain_conductance_floor_m2_s = float(options.drain_conductance_floor_m2_s)
        self.time_grid = getattr(options, "time_grid", None)
        self.check_grid = bool(options.check_grid)

    def _get_domain_surfaces(self):
        """Return explicit domain surfaces used by the MODFLOW spatial grid."""
        return resolve_domain_surfaces(
            domain=self.inputs.geometry.domain,
        )

    def _read_the_dem_grid(self) -> None:
        """Read the pixel size and the origin of the DEM grid, and pick the active DEM."""
        raster = self.inputs.geometry.raster
        self.resolution = raster.dem_res
        self.xul = raster.xmin
        self.yul = raster.ymax
        self._select_active_dem(box=bool(self.preprocess_options.box))

    def _validate_pre_processing_inputs(self) -> None:
        """Validate mandatory inputs before MODFLOW package assembly."""
        if self.inputs is None:
            raise ValueError("pre_processing requires a Model.")
        geometry = self.inputs.geometry
        if geometry.domain is None:
            raise ValueError("pre_processing requires a configured Domain object.")
        require_cell_mesh(self.inputs)
        if geometry.raster is None:
            raise ValueError(
                "MODFLOW-NWT builds its grid on the DEM of the run, and Model.geometry.raster "
                "is missing."
            )
        self.flow_regime = self.inputs.time.regime

        launcher_time_grid = getattr(self.preprocess_options, "time_grid", None)
        if launcher_time_grid is None and self.flow_regime != "steady":
            raise ValueError(
                "Launcher flow preprocessing requires preprocess_options.time_grid "
                "derived from [simulation.time] for transient flow runs."
            )

    def _initialize_solver_packages(self) -> None:
        """Initialize FLOPY MODFLOW and NWT solver packages."""
        r = self._params.runtime
        self.mf = flopy.modflow.Modflow(
            self.model_name,
            exe_name=self.exe,
            version=r.nwt.version,
            listunit=r.nwt.listunit,
            verbose=r.nwt.verbose,
            model_ws=self.full_path,
        )

        self.nwt = flopy.modflow.ModflowNwt(
            self.mf,
            headtol=r.nwt.headtol,
            fluxtol=r.nwt.fluxtol,
            maxiterout=r.nwt.maxiterout,
            thickfact=r.nwt.thickfact,
            linmeth=r.nwt.linmeth,
            iprnwt=r.nwt.iprnwt,
            ibotav=r.nwt.ibotav,
            options=r.nwt.options,
            Continue=r.nwt.continue_run,
            backflag=r.nwt.backflag,
            stoptol=r.nwt.stoptol,
        )

    def _build_temporal_discretization(self) -> dict[str, object]:
        """Build temporal discretization arrays from the launcher time grid."""
        launcher_time_grid = getattr(self.preprocess_options, "time_grid", None)
        result = build_temporal_discretization_from_time_grid(
            time_grid=launcher_time_grid,
            flow_regime=self.flow_regime,
            first_period_steady=resolve_first_period_steady(model=self.inputs),
        )

        self.dis_itmuni = result.itmuni
        self.nper = result.nper
        self.perlen = result.perlen
        self.nstp = result.nstp
        self.steady = result.steady
        self.start_datetime = result.start_datetime

        return result.as_dis_kwargs()

    def _build_spatial_discretization(self):
        """Build the structured spatial grid from validated domain surfaces.

        A grid with a vertical pass-through cell is refused: NWT has none.
        """
        geometry = self.inputs.geometry
        if geometry.cells.structured_shape is None:
            raise ValueError("MODFLOW NWT requires a structured grid")
        self.grid_ctx = build_spatial_discretization(
            domain=geometry.domain,
            vertical_config=geometry.domain.config.layers,
            sgrid_config=self.sgrid_config,
            cell_mesh=geometry.cells,
        )
        self.solver_mesh = self.grid_ctx.solver_mesh
        if (self.solver_mesh.idomain < 0).any():
            raise ConfigError(
                "The layering holds vertical pass-through cells (idomain -1), which "
                "MODFLOW-NWT does not have. Write [domain.layers] pinch_out = "
                "'keep_min_thickness', or run MODFLOW 6."
            )
        warn_on_disconnected_active_cells(self.solver_mesh)
        self.top_elevation = self.solver_mesh.reshape_to_grid(self.solver_mesh.top)
        self.inactive_mask = self.solver_mesh.reshape_to_grid(self.solver_mesh.closed_surface())
        self.nlay = self.solver_mesh.nlay
        self.nrow = self.solver_mesh.nrow
        self.ncol = self.solver_mesh.ncol
        self.bottom_layer = self.solver_mesh.reshape_to_grid(self.solver_mesh.botm[-1])
        self.zbot = self.solver_mesh.botm_grid
        self.cell_area = float(self.grid_ctx.grid.cell_area)
        self.resolution = float(self.grid_ctx.grid.characteristic_length)
        self.dem_watershed_path = self._write_solver_grid_template()
        self.sink = resolve_sink_mask(
            self.solver_mesh,
            sink_fill=self.sink_fill,
            model_name=self.model_name,
        )
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

        raster = self.inputs.geometry.raster
        self.routing_ctx = build_solver_routing_context(
            dem_path=self.dem_watershed_path,
            output_dir=os.path.join(self.full_path, "_solver_routing"),
            dem_correc_type=raster.dem_correc_type,
            crs_project=raster.crs_proj,
            engine_id=raster.terrain_engine,
            capped_breach=capped_breach_of(raster),
        )
        return self.routing_ctx

    def _build_descent(self, solver_mesh, flow_inputs: FlowModflowInputs) -> Descent | None:
        """Build the descent D of this run and leave it beside the model.

        The seeds are the domain rim and every constant-head cell the adapter
        writes, the same supports MODFLOW 6 seeds on: ``ibound == -1`` (a
        static ocean or side boundary) and the CHD package rows (a transient
        ocean or side boundary, which keep ``ibound`` at 1). NWT writes no
        stream CHD, so it has none to seed. The routable columns are those
        ``ibound`` keeps active. NWT builds no lake, so none is traversed. D
        follows the generated network A whenever the run has A.

        The basin of D at the catchment outlet is computed once, before D drops
        its adjacency, and kept with it. NWT has no SFR walk, so the model keeps
        D without its adjacency, and an auxiliary model (the steady
        initialization) builds none.
        """
        geometry = self.inputs.geometry
        if self.auxiliary:
            self.descent = None
            self.descent_basin = None
            return None
        ibound_cells = solver_mesh.flatten_from_grid(np.asarray(flow_inputs.ibound))
        constant_head = (ibound_cells == -1).any(axis=0)
        if flow_inputs.chd_spd:
            chd_grid = np.zeros((int(solver_mesh.nrow), int(solver_mesh.ncol)), dtype=bool)
            for rows in flow_inputs.chd_spd.values():
                for row in rows:
                    chd_grid[int(row[1]), int(row[2])] = True
            constant_head |= np.asarray(solver_mesh.flatten_from_grid(chd_grid), dtype=bool)
        descent = build_solver_mesh_descent(
            solver_mesh,
            lake_cells_by_lake={},
            base_level_mask=constant_head,
            channel_exits=channel_exits_for_build(geometry.raster.channel, geometry.channel_exits),
            active_column=(ibound_cells != 0).any(axis=0),
            geographic=geometry.catchment,
        )
        self.descent_basin = run_basin(geometry.catchment, solver_mesh, descent)
        write_descent_sidecar(descent, self.full_path, self.model_name, basin=self.descent_basin)
        self.descent = descent.without_adjacency()
        return self.descent

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
        """Adapt the Model into solver-ready payloads."""
        adapter = FlowToModflowAdapter(
            model=self.inputs,
            solver_mesh=solver_mesh,
            nper=int(self.nper),
            grid=None if self.grid_ctx is None else self.grid_ctx.grid,
            simulation_window=None if self.time_grid is None else self.time_grid.window,
            steady=getattr(self, "steady", None),
            period_lengths=getattr(self, "perlen", None),
            record_lengths=getattr(self.time_grid, "record_lengths_seconds", None),
            sink_fill=bool(self.sink_fill),
            sink=self.sink,
            drain_band_depth_m=float(self.drain_band_depth_m),
            drain_bed_thickness_m=float(self.drain_bed_thickness_m),
            drain_conductance_floor_m2_s=float(self.drain_conductance_floor_m2_s),
        )
        return adapter.build()

    def pre_processing(
        self,
        model: Model,
        options: ModflowPreprocessOptions | None = None,
        *,
        slot: RunSlot | None = None,
    ):
        """Pre-processing to build the hydrologic model.

        Parameters
        ----------
        model : Model
            The frozen model of the run. Its regular cell mesh is the one the
            grid is extruded from, and MODFLOW-NWT refuses any other kind. Its
            raster geometry is the DEM the grid and the routing are built on.
        options : ModflowPreprocessOptions, optional
            Optional typed pre-processing options.
        slot : RunSlot, optional
            The slot of the run, which ``build_flow_model`` hands to both
            MODFLOW backends. MODFLOW-NWT already holds its folder, its name
            and its binary from the constructor and reads nothing more of it.
            A per-cell property override is ``Model.with_properties``.
        """
        del slot
        self.inputs = model
        active_options = self.preprocess_options if options is None else options
        self._apply_preprocess_options(active_options)

        self._validate_pre_processing_inputs()
        self._read_the_dem_grid()
        self._initialize_solver_packages()
        temporal_dis = self._build_temporal_discretization()
        sgrid = self._build_spatial_discretization()
        self._build_dis_package(sgrid, temporal_dis)

        flow_inputs = self._build_flow_modflow_inputs(sgrid)
        self._build_descent(sgrid, flow_inputs)
        assemble_flopy_packages(self, flow_inputs, active_options)

    def _written_input_files(self) -> tuple[str, ...]:
        """Return the name file and the package files ``write_input`` wrote, in order."""
        names = [self.mf.namefile]
        for package in self.mf.packagelist:
            names.extend(package.file_name)
        written = (
            name
            for name in dict.fromkeys(names)
            if os.path.isfile(os.path.join(self.mf.model_ws, name))
        )
        return tuple(written)

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
                output_file_name=self._params.runtime.lmt.output_file_name,
                extension=self._params.runtime.lmt.extension,
                output_file_format=self._params.runtime.lmt.output_format,
                unitnumber=None,
            )

        steady_initial_heads_applied = False
        if (
            options.run_model
            and self.flow_regime == "transient"
            and isinstance(self.inputs.initial, SteadyStart)
        ):
            steady_heads = run_nwt_steady_state_initialization(self)
            apply_nwt_steady_state_initial_heads(self, steady_heads)
            steady_initial_heads_applied = True

        if options.write_model:
            self.mf.write_input()
            self.input_files = self._written_input_files()
        elif steady_initial_heads_applied:
            self.bas.write_file()

        success_model = False
        self.last_flow_solve_time_seconds = None
        if options.run_model:
            solve_start = time.perf_counter()
            try:
                success_model, _ = run_model_with_progress(
                    self.mf.exe_name,
                    self.mf.namefile,
                    self.mf.model_ws,
                    int(self.nper),
                )
            finally:
                self.last_flow_solve_time_seconds = time.perf_counter() - solve_start

        return success_model
