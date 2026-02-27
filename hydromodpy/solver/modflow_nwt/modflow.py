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

# %% LIBRAIRIES

# Python
from collections.abc import Mapping
import flopy
import numpy as np
import os
import datetime
import pandas as pd
import sys
import rasterio
from pathlib import Path
import matplotlib.pyplot as plt
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

# Root
repo_root = Path(__file__).resolve().parents[3]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
from hydromodpy.modeling import masstransfer
from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface
from hydromodpy.solver import Solver
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.solver.utils.temporal.tmesh_generation import (
    TMeshConfig,
    TMesh_Generation,
)
from hydromodpy.solver.modflow_nwt.modflow_utils import (
    build_flow_domain_property_snapshot,
)
from hydromodpy.solver.modflow_nwt.modflow_config import (
    ModflowConfig,
    ModflowSpecifParams,
)

logger = get_logger(__name__)

import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable

# %% CLASS


class Modflow(Solver):
    """
    Class Modflow.

    To build, run the hydrologic model and manage/format simulation outputs.
    """

    def __init__(
        self,
        geographic: object,
        flow: object = None,
        domain: object = None,
        # Worflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str = "bin",
        box: bool = True,
        sink_fill: bool = False,
        sim_state: str = "steady",
        plot_cross: bool = True,
        cross_ylim: list = [],
        check_grid: bool = True,
        # Climatic settings
        recharge=0.001,
        runoff=None,
        first_clim: str = "mean",
        dis_perlen: bool = False,
        # Hydraulic settings
        nlay: int = 1,
        lay_decay: float = 1.0,
        bottom: float = None,
        thick: float = 100.0,
        modflow_config: ModflowConfig | Mapping[str, object] | None = None,
        # Well settings
        well_coords: list = [],
        well_fluxes: list = [],
        # Boundary settings
        cond_drain: float = None,
        bc_left: float = None,
        bc_right: float = None):
        """
        Initialize method.

        Parameters
        ----------
        geographic : object
            Object geographic build by HydroModPy.
        flow : object, optional
            Flow-process object carrying K/Sy/Ss parameters.
            Required by pre_processing() for property mapping on SGrid.
        domain : object, optional
            Domain object carrying zones (including geology support).
            Required by pre_processing() for property mapping on SGrid.
        model_folder : str, optional
            Path where the model will be store. The default is 'HydroModPy_outputs'.
        model_name : str, optional
            Name of the model. The default is 'Default'.
        bin_path : str, optional
            Location folder of the modflow executables. The default is 'bin'.
        box : bool, optional
            True if you want run the model on the square area of the watershed. The default is True.
        sink_fill : bool, optional
            If True, package drain is desactivate on pit. The watertable can create lake on pit. The default is False.
        sim_state : str, optional
            'steady' or 'transient'. simulation state. The default is 'steady'.
        plot_cross : bool, optional
            If True, display a cross section of the model. The default is True.
        check_grid : bool, optional
            If True, check if the water connectivity is respected with the meshgrid. The default is True.
        recharge : float or list, optional
            Recharge [L/T] as input of the model. The default is 0.001.
        runoff : float or list, optional
            Runoff [L/T] as an independent variable that can be added in post-processing to the model. The default is 0.0001.
        first_clim : str, optional
            If 'mean': the first recharge value is the mean of the chronicle.
            If 'first': the first recharge value is the first value of the timeseries.
            If a 'float' : the first recharge is the fixed value.
            The default is 'mean'.
        nlay : int, optional
            Number of layer. The default is 1.
        lay_decay : float, optional
            Modification of layer thickness for exponentially decreasing whit depth. The default is 1.
        bottom : float, optional
            At this elevation, fix a flat no flow boundary at the bottom of the model. The default is None.
        thick : float, optional
            Constant aquifer thickness of the the tickness of the model (if bottom is None). The default is 100.
        modflow_config : ModflowConfig | Mapping | None, optional
            Expert MODFLOW-NWT package parameters loaded from
            `[modflow.runtime]`, `[modflow.process_specific]`,
            `[modflow.sgrid]`, and `[modflow.tgrid]` in TOML.
            If None, internal defaults from ModflowConfig are used.
        wells_coord : list
            Inform the outlet coordinates of wells [lay,row,col].
            Example for 2 wells: [ [1,20,30], [1,15,15] ]
        wells_fluxes : list
            Inform the fluxes [L3/T] for each stress-periods, for different wells.
            Example for 2 wells and 5 stress-periods: [ [-100,0,-100,0,-100], [-100,0,-100,0,-100] ]
        cond_drain : float, optional
            Fix the conductance value of the drai (DRN) package. The default is None.
        bc_left : float, optional
            Fix head on the left border of the domain. The default is None.
        bc_right : float, optional
            Fix head on the right border of the domain. The default is None.
        """

        # %% Initialization paths

        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            toolbox.create(self.model_folder)

        self.model_name = model_name

        if (sys.platform == "win32") or (sys.platform == "win64"):
            self.exe = os.path.join(bin_path, "win", "mfnwt.exe")
        if sys.platform == "linux":
            self.exe = os.path.join(bin_path, "linux", "mfnwt")
        if sys.platform == "darwin":
            self.exe = os.path.join(bin_path, "mac", "mfnwt")

        self.full_path = os.path.join(model_folder, model_name)  #'modraw'

        # %% Domain definition

        # General
        self.geographic = geographic
        self.flow = flow
        self.domain = domain

        #######################################################################
        # self.geographic.watershed_dem = 'C:/Users/rabherve/Simulations/Lasset/Lasset_25m/results_stable/geographic/watershed_dem.tif'
        # self.geographic.watershed_box_buff_dem = 'C:/Users/rabherve/Simulations/Lasset/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif'
        #######################################################################

        self.resolution = geographic.dem_res
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        self.sink_fill = sink_fill
        try:
            self.sink = geographic.depressions_data
        except:
            pass

        # Enlarges the modeled domain
        self.box = box
        if box == True:
            self.dem = geographic.dem_box_buff_data
            self.dem_watershed_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_watershed_path = geographic.watershed_buff_dem
        
        self.dem[self.dem <= -9999] = -9999
        self.dem[self.dem >= 9999] = -9999

        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]

        # %% Boundary conditions
        self.bc_left = bc_left
        self.bc_right = bc_right

        # commented on 2026-02-27: lines do not seem relevant
        # try:
        #     if self.flow.boundary_conditions["ocean"].value == None:
        #         self.dem[(self.dem < 0) & (self.dem > -200)] = 0
        # except:
        #     pass

        # %% Input and discretization termes

        self.recharge = recharge
        self.runoff = runoff

        self.sim_state = sim_state
        self.first_clim = first_clim
        self.dis_perlen = dis_perlen

        # %% Model parameters

        self.bottom = bottom
        self.thick = thick

        self.nlay = nlay
        self.lay_decay = lay_decay

        self.cond_drain = cond_drain

        # %% Specific case implementation

        # %% Plot things

        self.plot_cross = plot_cross
        self.cross_ylim = cross_ylim
        self.check_grid = check_grid

        # %% Well settings

        self.well_coords = well_coords
        self.well_fluxes = well_fluxes

        # %% Flopy model parameters driven by expert config
        specif_params = ModflowSpecifParams.from_config(modflow_config)
        if modflow_config is None:
            self.modflow_config = ModflowConfig()
        elif isinstance(modflow_config, ModflowConfig):
            self.modflow_config = modflow_config
        else:
            self.modflow_config = ModflowConfig.model_validate(dict(modflow_config))

        runtime_params = specif_params.runtime
        process_specific_params = specif_params.process_specific
        self.sgrid_config: VerticalGridConfig | None = specif_params.sgrid
        self.tgrid_config = specif_params.tgrid
        self.tgrid = None

        self.mf_version = runtime_params.mf_version
        self.mf_listunit = runtime_params.mf_listunit
        self.mf_verbose = runtime_params.mf_verbose

        self.nwt_headtol = runtime_params.nwt_headtol
        self.nwt_fluxtol = runtime_params.nwt_fluxtol
        self.nwt_maxiterout = runtime_params.nwt_maxiterout
        self.nwt_thickfact = runtime_params.nwt_thickfact
        self.nwt_linmeth = runtime_params.nwt_linmeth
        self.nwt_iprnwt = runtime_params.nwt_iprnwt
        self.nwt_ibotav = runtime_params.nwt_ibotav
        self.nwt_options = runtime_params.nwt_options
        self.nwt_continue = runtime_params.nwt_continue
        self.nwt_backflag = runtime_params.nwt_backflag
        self.nwt_stoptol = runtime_params.nwt_stoptol

        self.dis_itmuni = runtime_params.dis_itmuni
        self.bas_hnoflo = runtime_params.bas_hnoflo

        self.upw_iphdry = runtime_params.upw_iphdry
        self.upw_hdry = runtime_params.upw_hdry
        self.upw_layvka = runtime_params.upw_layvka

        self.evt_nevtop = runtime_params.evt_nevtop
        self.evt_ievt = runtime_params.evt_ievt
        self.evt_ipakcb = runtime_params.evt_ipakcb

        self.oc_compact = runtime_params.oc_compact
        self.wel_ipakcb = runtime_params.wel_ipakcb

        self.lmt_output_file_name = runtime_params.lmt_output_file_name
        self.lmt_extension = runtime_params.lmt_extension
        self.lmt_output_format = runtime_params.lmt_output_format

        self.vka = process_specific_params.vka
        self.exdp = process_specific_params.exdp

        # Optional early synchronization from typed [modflow.sgrid].
        if self.sgrid_config is not None:
            if self.sgrid_config.nlay is not None:
                self.nlay = int(self.sgrid_config.nlay)
            if (
                self.sgrid_config.genmtd_lay == "decay"
                and self.sgrid_config.lay_decay is not None
            ):
                self.lay_decay = float(self.sgrid_config.lay_decay)
            elif self.sgrid_config.genmtd_lay == "constant":
                self.lay_decay = 1.0

        # Optional synchronization from typed [modflow.tgrid].
        if self.tgrid_config is not None:
            if str(sim_state) != str(self.tgrid_config.sim_state):
                logger.info(
                    "Overriding sim_state=%s with modflow.tgrid.sim_state=%s",
                    sim_state,
                    self.tgrid_config.sim_state,
                )
            self.sim_state = str(self.tgrid_config.sim_state)

    # %% PRE-PROCESSING

    def _get_domain_surfaces(self):
        """
        Return explicit domain surfaces when they match the active MODFLOW DEM.
        """
        if self.domain is None:
            return None

        surface_topo = getattr(self.domain, "surface_topo", None)
        substratum = getattr(self.domain, "substratum", None)
        if surface_topo is None or substratum is None:
            return None
        if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
            raise TypeError("Domain surfaces must be Surface instances.")

        top = np.asarray(surface_topo.as_array(), dtype=float)
        bot = np.asarray(substratum.as_array(), dtype=float)
        if top.shape != bot.shape:
            raise ValueError(
                f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}."
            )
        if top.shape != self.dem.shape:
            return None

        surface_topo.assert_same_geographic_domain(substratum)
        return surface_topo, substratum

    def _build_runtime_support(self, shape: tuple[int, int]) -> RasterSupport:
        """
        Build one RasterSupport for the active runtime DEM support.
        """
        nrows, ncols = int(shape[0]), int(shape[1])
        georef = {}
        if hasattr(self.geographic, "build_georeferencing"):
            georef = dict(self.geographic.build_georeferencing())
        support = RasterSupport.from_georeferencing(
            georef,
            shape=(nrows, ncols),
            nodata=-9999.0,
        )

        xmin = (
            float(support.xmin)
            if support.xmin is not None
            else float(getattr(self, "xmin", 0.0))
        )
        ymax = (
            float(support.ymax)
            if support.ymax is not None
            else float(getattr(self, "ymax", float(nrows)))
        )
        dx = (
            float(support.dx)
            if support.dx is not None
            else float(getattr(self, "resolution", 1.0))
        )
        dy = (
            float(support.dy)
            if support.dy is not None
            else float(getattr(self, "resolution", 1.0))
        )
        xmax = (
            float(support.xmax)
            if support.xmax is not None
            else xmin + (dx * ncols)
        )
        ymin = (
            float(support.ymin)
            if support.ymin is not None
            else ymax - (dy * nrows)
        )
        crs = support.crs if support.crs is not None else getattr(self.geographic, "crs_proj", None)
        return RasterSupport(
            crs=crs,
            dx=dx,
            dy=dy,
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            nrows=nrows,
            ncols=ncols,
            nodata=-9999.0,
        )

    def _build_solver_surfaces(self) -> tuple[Surface, Surface]:
        """
        Build top and bottom surfaces for StructuredGrid vertical discretization.
        """
        domain_surfaces = self._get_domain_surfaces()
        if domain_surfaces is not None:
            return domain_surfaces

        top = np.asarray(self.dem, dtype=float)
        support = self._build_runtime_support(top.shape)
        top_surface = Surface(name="surface_topo", values=top, support=support)

        if self.bottom is None:
            bottom_values = np.asarray(top, dtype=float) - float(self.thick)
        elif isinstance(self.bottom, (int, float)):
            bottom_values = np.full_like(top, float(self.bottom), dtype=float)
        else:
            bottom_values = np.asarray(self.bottom, dtype=float)
            if bottom_values.shape != top.shape:
                raise ValueError(
                    f"Bottom array shape mismatch: {bottom_values.shape} != {top.shape}."
                )

        bottom_values[top <= -9999.0] = -9999.0
        bottom_surface = Surface(
            name="substratum",
            values=bottom_values,
            support=support,
        )
        top_surface.assert_same_geographic_domain(bottom_surface)
        return top_surface, bottom_surface

    def _build_vertical_grid_config(self) -> VerticalGridConfig:
        """
        Build vertical-grid settings, preferring typed [modflow.sgrid] when provided.
        """
        if self.sgrid_config is not None:
            return self.sgrid_config

        payload: dict[str, object] = {
            "lenuni": "m",
            "nodata": -9999.0,
            "nlay": int(self.nlay),
        }
        if float(self.lay_decay) > 1.0:
            payload["genmtd_lay"] = "decay"
            payload["lay_decay"] = float(self.lay_decay)
        else:
            payload["genmtd_lay"] = "constant"

        genmtd_lay = payload.get("genmtd_lay")
        if genmtd_lay != "decay":
            payload.pop("lay_decay", None)
        if genmtd_lay != "list":
            payload.pop("lay_proportions", None)
        else:
            payload.pop("nlay", None)

        return VerticalGridConfig.from_mapping(payload)

    def _build_temporal_grid_config(self):
        """
        Build temporal-grid settings, preferring typed [modflow.tgrid] when provided.
        """
        if self.tgrid_config is None:
            return None
        tmesh_config = TMeshConfig(**self.tgrid_config.to_builder_kwargs())
        builder = TMesh_Generation(config=tmesh_config)
        return builder.run()

    def _sync_runtime_time_from_tgrid(self, tgrid) -> None:
        """
        Align runtime temporal arrays with the effective TGrid/ModelTime payload.
        """
        perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
        nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
        tsmult = np.asarray(getattr(tgrid, "tsmult", []), dtype=float)
        steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
        if perlen.size == 0:
            raise ValueError("modflow.tgrid produced an empty perlen vector.")
        if nstp.size != perlen.size:
            raise ValueError(
                "modflow.tgrid produced inconsistent nstp/perlen sizes "
                f"({nstp.size} != {perlen.size})."
            )
        if tsmult.size != perlen.size:
            raise ValueError(
                "modflow.tgrid produced inconsistent tsmult/perlen sizes "
                f"({tsmult.size} != {perlen.size})."
            )
        if steady.size != perlen.size:
            raise ValueError(
                "modflow.tgrid produced inconsistent steady/perlen sizes "
                f"({steady.size} != {perlen.size})."
            )
        self.dis_itmuni = getattr(tgrid, "time_units", self.dis_itmuni)
        self.nper = int(perlen.size)
        self.perlen = perlen
        self.nstp = nstp
        self.tsmult = tsmult
        self.steady = steady
        self.start_datetime = getattr(tgrid, "start_datetime", None)

    def _log_tgrid_self_comparison(self, tgrid) -> None:
        """
        Log one explicit comparison between tgrid values and synchronized self values.
        """
        unit_code = {
            "undefined": 0,
            "seconds": 1,
            "minutes": 2,
            "hours": 3,
            "days": 4,
            "years": 5,
        }

        def _normalize_unit(value):
            if value is None:
                return None
            if isinstance(value, (int, np.integer)):
                ivalue = int(value)
                for key, code in unit_code.items():
                    if code == ivalue:
                        return key
                return str(ivalue)
            text = str(value).strip().lower()
            aliases = {
                "0": "undefined",
                "1": "seconds",
                "2": "minutes",
                "3": "hours",
                "4": "days",
                "5": "years",
                "u": "undefined",
                "s": "seconds",
                "sec": "seconds",
                "second": "seconds",
                "seconds": "seconds",
                "m": "minutes",
                "min": "minutes",
                "minute": "minutes",
                "minutes": "minutes",
                "h": "hours",
                "hr": "hours",
                "hour": "hours",
                "hours": "hours",
                "d": "days",
                "day": "days",
                "days": "days",
                "y": "years",
                "yr": "years",
                "year": "years",
                "years": "years",
            }
            return aliases.get(text, text)

        def _preview(values):
            arr = np.asarray(values).reshape(-1)
            if arr.size <= 6:
                return arr.tolist()
            return arr[:3].tolist() + ["..."] + arr[-2:].tolist()

        tgrid_time_units = getattr(tgrid, "time_units", None)
        tgrid_nper = int(getattr(tgrid, "nper", 0))
        tgrid_perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
        tgrid_nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
        tgrid_tsmult = np.asarray(getattr(tgrid, "tsmult", []), dtype=float)
        tgrid_steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
        tgrid_start_datetime = getattr(tgrid, "start_datetime", None)

        self_perlen = np.asarray(self.perlen, dtype=float).reshape(-1)
        self_nstp = np.asarray(self.nstp, dtype=int).reshape(-1)
        self_tsmult = np.asarray(getattr(self, "tsmult", []), dtype=float).reshape(-1)
        self_steady = np.asarray(self.steady, dtype=bool).reshape(-1)

        tgrid_unit_name = _normalize_unit(tgrid_time_units)
        self_unit_name = _normalize_unit(self.dis_itmuni)
        tgrid_unit_code = unit_code.get(tgrid_unit_name, None)
        self_unit_code = unit_code.get(self_unit_name, None)
        itmuni_match = tgrid_unit_name == self_unit_name
        nper_match = int(tgrid_nper) == int(self.nper)
        perlen_match = (
            tgrid_perlen.shape == self_perlen.shape
            and np.allclose(tgrid_perlen, self_perlen, equal_nan=True)
        )
        nstp_match = np.array_equal(tgrid_nstp, self_nstp)
        tsmult_match = (
            tgrid_tsmult.shape == self_tsmult.shape
            and np.allclose(tgrid_tsmult, self_tsmult, equal_nan=True)
        )
        steady_match = np.array_equal(tgrid_steady, self_steady)
        start_datetime_match = str(tgrid_start_datetime) == str(self.start_datetime)

        logger.info(
            "[Temporal compare] units | tgrid=%s(code=%s) | self=%s(code=%s) | match=%s",
            tgrid_unit_name,
            tgrid_unit_code,
            self_unit_name,
            self_unit_code,
            itmuni_match,
        )
        logger.info(
            "[Temporal compare] itmuni raw | tgrid=%s | self=%s | match=%s",
            tgrid_time_units,
            self.dis_itmuni,
            itmuni_match,
        )
        logger.info(
            "[Temporal compare] nper | tgrid=%s | self=%s | match=%s",
            tgrid_nper,
            self.nper,
            nper_match,
        )
        logger.info(
            "[Temporal compare] perlen | tgrid=%s | self=%s | match=%s",
            _preview(tgrid_perlen),
            _preview(self_perlen),
            perlen_match,
        )
        logger.info(
            "[Temporal compare] nstp | tgrid=%s | self=%s | match=%s",
            _preview(tgrid_nstp),
            _preview(self_nstp),
            nstp_match,
        )
        logger.info(
            "[Temporal compare] tsmult | tgrid=%s | self=%s | match=%s",
            _preview(tgrid_tsmult),
            _preview(self_tsmult),
            tsmult_match,
        )
        logger.info(
            "[Temporal compare] steady | tgrid=%s | self=%s | match=%s",
            _preview(tgrid_steady),
            _preview(self_steady),
            steady_match,
        )
        logger.info(
            "[Temporal compare] start_datetime | tgrid=%s | self=%s | match=%s",
            tgrid_start_datetime,
            self.start_datetime,
            start_datetime_match,
        )

    def _sync_runtime_grid_from_sgrid(self, sgrid) -> None:
        """
        Align runtime DEM/grid attributes with the effective SGrid geometry.

        This keeps all downstream arrays (BAS/DRN/CHD/post-processing) on the
        exact same support as the discretization actually passed to FloPy.
        """
        sgrid_top = np.asarray(sgrid.top, dtype=float)
        # Keep historical DEM values when the support is already identical.
        # This avoids tiny numerical drifts while still fixing shape conflicts.
        if np.asarray(self.dem).shape != sgrid_top.shape:
            self.dem = sgrid_top
        self.nlay = int(sgrid.nlay)
        self.nrow = int(sgrid.nrow)
        self.ncol = int(sgrid.ncol)
        self.zbot = np.asarray(sgrid.botm, dtype=float)
        self.bottom_layer = np.asarray(self.zbot[-1], dtype=float)

    def pre_processing(self):
        """
        Pre-processing to build the hydrologic model.

        Returns
        -------
        None.

        """
        # %% Initialization

        # Flopy initialization of Modflow model
        # ---- flopy.modflow.Modflow
        self.mf = flopy.modflow.Modflow(
            self.model_name,
            exe_name=self.exe,
            version=self.mf_version,
            listunit=self.mf_listunit,
            verbose=self.mf_verbose,
            model_ws=self.full_path,
        )

        # Uses Nwt for Modflow 2005, necessary for unconfined aquifers (improved interactions between surface and aquifer)
        # Sets up numerical parameters
        # ---- flopy.modflow.ModflowNwt
        self.nwt = flopy.modflow.ModflowNwt(
            self.mf,
            headtol=self.nwt_headtol,
            fluxtol=self.nwt_fluxtol,
            maxiterout=self.nwt_maxiterout,
            thickfact=self.nwt_thickfact,
            linmeth=self.nwt_linmeth,
            iprnwt=self.nwt_iprnwt,
            ibotav=self.nwt_ibotav,
            options=self.nwt_options,
            Continue=self.nwt_continue,
            backflag=self.nwt_backflag,
            stoptol=self.nwt_stoptol,
        )

        # %% Discretization

        ### Temporal: time step is driven by recharge
        if self.tgrid_config is None:
            # Steady state
            if self.sim_state == "steady":
                self.nper = 1  # Number of forcing periods (recharge)
                self.perlen = 1  # Length of period
                self.nstp = [1]  # Steps in a given period (not used here)
                self.steady = True  # Steady state
                self.start_datetime = None

            # Transient state
            if self.sim_state == "transient":
                if isinstance(self.recharge, (dict)) == True:
                    self.start_datetime = 0
                else:
                    self.start_datetime = self.recharge.index[0]  # First date of recharge
                self.steady = np.zeros(
                    len(self.recharge), dtype=bool
                )  # Vector of booleans (transient state at each time step)
                self.steady[0] =True  # Steady state for the first time step (initialization of head values by a steady state)
                self.nstp = np.ones(len(self.recharge))  # One step per time step
                self.nper = len(self.recharge)
                # Definition of period duration (forcing is constant on a period)
                #       As many periods as recharge values
                #       Extracts from climatic data the time steps (self.perlen)
                if self.dis_perlen == True:
                    if isinstance(self.recharge, pd.core.series.Series):
                        if isinstance(self.recharge.index[0], datetime.datetime):
                            self.perlen = (
                                self.recharge.index.to_series()
                                .diff()
                                .dt.total_seconds()
                                .values
                                / 86400
                            )  # values converted into float days
                        else:
                            self.perlen = self.recharge.index.to_series().diff().values
                if isinstance(self.dis_perlen, list) == True:
                    self.perlen = self.dis_perlen
                if self.dis_perlen == False:
                    self.perlen = np.ones(len(self.recharge))
                if isinstance(self.recharge, (dict)) == True:
                    self.perlen = np.ones(len(self.recharge))
                # First timestep is steady state:
                self.perlen[0] = 1
            self.tsmult = np.ones(int(self.nper), dtype=float)

        ### Sptial: model domain definition and discretization

        # Prefer explicit Domain surfaces when available
        if (
            self.domain is not None
            and getattr(self.domain, "surface_topo", None) is not None
            and getattr(self.domain, "substratum", None) is not None
        ):
            top_surface = self.domain.surface_topo
            bottom_surface = self.domain.substratum
            top_surface.assert_same_geographic_domain(bottom_surface)
        else:
            top_surface, bottom_surface = self._build_solver_surfaces()

        self.dem = np.asarray(top_surface.as_array(), dtype=float)
        self.nrow, self.ncol = self.dem.shape

        vertical_cfg = (
            self.modflow_config.sgrid
            if self.modflow_config.sgrid is not None
            else self._build_vertical_grid_config()
        )
        sgrid = StructuredGridBuilder().build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_cfg,
        )
        if self.tgrid_config is not None:
            tmesh_config = TMeshConfig(**self.modflow_config.tgrid.to_builder_kwargs())
            tmesh_generator = TMesh_Generation(config=tmesh_config)
            tgrid = tmesh_generator.run()
            self.tgrid = tgrid
            self._sync_runtime_time_from_tgrid(tgrid)
            self._log_tgrid_self_comparison(tgrid)
        self._sync_runtime_grid_from_sgrid(sgrid)
        
        # Imposes discretization to modflow model through
        # ---- flopy.modflow.ModflowDis
        self.dis = flopy.modflow.ModflowDis(
            self.mf,
            # Spatial grid parameters
            lenuni=sgrid.lenuni,
            nlay=sgrid.nlay,
            nrow=sgrid.nrow,
            ncol=sgrid.ncol,
            delr=sgrid.delr,
            delc=sgrid.delc,
            top=sgrid.top,
            botm=sgrid.botm,
            xul=sgrid.xoffset,
            yul=sgrid.extent[3],
            # Temporal grid parameters
            itmuni=tgrid.time_units,
            nper=tgrid.nper,
            perlen=tgrid.perlen,
            nstp=tgrid.nstp,
            steady=tgrid.steady_state,
            start_datetime=tgrid.start_datetime)

        # self.dis = flopy.modflow.ModflowDis(self.mf,
        #                                     itmuni=0, # itmuni = 0 ==> undefined
        #                                     lenuni=2, # itmuni_values = {'days': 4, 'hours': 3, 'minutes': 2, 'seconds': 1, 'undefined': 0, 'years': 5}
        #                                     nlay=self.nlay,
        #                                     nrow=self.nrow,
        #                                     ncol=self.ncol,
        #                                     delr=self.resolution,
        #                                     delc=self.resolution,
        #                                     top=self.dem,
        #                                     botm=self.zbot,
        #                                     xul=self.xul,
        #                                     yul=self.yul,
        #                                     nper=self.nper,
        #                                     perlen=self.perlen,
        #                                     nstp=self.nstp,
        #                                     steady=self.steady,
        #                                     start_datetime=self.start_datetime)

        # %% Boundary conditions

        ### Initialze the top boundary condition of DRN package
        self.drain_array = np.ones((self.nrow, self.ncol))

        ### Constant head boundary conditions of no flow (sides of domain)

        self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
        # iboundData=1: Should compute head in cells
        # iboundData=0: Nothing is calculated in cells
        # iboundData=-1: Values imposed at the value of strtData

        # Free surface level is set to the surface (altitude of DEM)
        self.strtData = np.ones((self.nlay, self.nrow, self.ncol)) * self.dem

        # Fixed head on the left (better for square domain)
        if isinstance(self.bc_left, (int, float)) == True:
            self.iboundData[:, :, 0] = -1
            self.strtData[:, :, 0] = self.bc_left

        # Fixed head on the right (better for square domain)
        if isinstance(self.bc_right, (int, float)) == True:
            self.iboundData[:, :, -1] = -1
            self.strtData[:, :, -1] = self.bc_right

        for i in range(self.nlay):
            self.iboundData[i][self.dem < -1000] = 0  # 0 is for NO FLOW

        if "ocean" in self.flow.boundary_conditions.keys():

            # No flow boundary conditions
            for i in range(self.nlay):
                if isinstance(self.flow.boundary_conditions["ocean"].value, (int, float)) == True:
                    self.iboundData[i][self.dem <= self.flow.boundary_conditions["ocean"].value] = -1
                    self.strtData[self.iboundData == -1] = self.flow.boundary_conditions["ocean"].value
                

            ### Constant head boundary conditions of no f : specific for sea level
            if isinstance(self.flow.boundary_conditions["ocean"].value, (int, float, pd.Series, list)) == True:
                package = np.zeros((self.nper, self.nrow, self.ncol))
                if isinstance(self.flow.boundary_conditions["ocean"].value, (int, float)) == False:
                    self.chData = {}
                    for kper in range(0, self.nper):
                        chdKper = []
                        for i in range(0, self.nrow):
                            for j in range(0, self.ncol):
                                if self.dem[i, j] < np.max(self.flow.boundary_conditions["ocean"].value):
                                    if (
                                        self.iboundData[0, i, j] != 0
                                    ):  # no-flow cells cannot be converted to specified head cells
                                        self.drain_array[i, j] = 0
                                        package[kper, i, j] = 1
                                        chdKper.append(
                                            [
                                                0,
                                                i,
                                                j,
                                                self.flow.boundary_conditions["ocean"].value[kper],
                                                self.flow.boundary_conditions["ocean"].value[kper],
                                            ]
                                        )
                                self.chData[kper] = chdKper
                    # ---- flopy.modflow.ModflowChd
                    self.chd = flopy.modflow.ModflowChd(
                        self.mf, stress_period_data=self.chData
                    )

        # ---- flopy.modflow.ModflowBas
        self.bas = flopy.modflow.ModflowBas(
            self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=self.bas_hnoflo)

        # %% Parametrization

        # Specify the unconfined conditions of the aquifer
        self.laywet = np.zeros(self.nlay)  # wettable
        self.laytype = np.ones(self.nlay)  # convertible

        # Necessary to give hydraulic conductivity: 3D matrix of hydraulic conductivities
        # Homogeneous or heterogeneous hydraulic conductivity is always built
        # from Flow/Domain mapping on the generated SGrid.

        # Compact mapping table for Flow -> MODFLOW properties.
        #
        # Tuple format:
        #   (accepted_flow_keys, target_3d_attr, target_surface_attr, human_label)
        mapping_specs = [
            (("K", "k"), "hk", "hk_value", "Hydraulic conductivity"),
            (("Sy", "SY", "sy", "S", "s"), "sy", "sy_value", "Specific yield"),
            (("Ss", "SS", "ss"), "ss", "ss_value", "Specific storage"),
        ]
        has_flow_domain_inputs = (
            self.flow is not None
            and hasattr(self.flow, "parameters")
            and self.domain is not None
            and hasattr(self.domain, "zones")
        )
        if not has_flow_domain_inputs:
            raise ValueError(
                "Flow/Domain inputs are required to build hk/sy/ss on SGrid. "
                "Expected flow.parameters and domain.zones."
            )

        flow_params = build_flow_domain_property_snapshot(
            model=self,
            sgrid=sgrid,
            mapping_specs=mapping_specs,
            strict=True,
        )
        for _, target_3d_attr, target_surface_attr, label in mapping_specs:
            values_3d = flow_params.get(target_3d_attr)
            values_2d = flow_params.get(target_surface_attr)
            if values_3d is None or values_2d is None:
                raise ValueError(
                    f"Missing mapped values for {label} "
                    f"('{target_3d_attr}' / '{target_surface_attr}')."
                )
            setattr(self, target_3d_attr, np.asarray(values_3d, dtype=float))
            setattr(self, target_surface_attr, np.asarray(values_2d, dtype=float))

        # ---- flopy.modflow.ModflowUpw
        self.upw = flopy.modflow.ModflowUpw(
            self.mf,
            laytyp=self.laytype,
            laywet=self.laywet,
            hk=self.hk,
            sy=self.sy,
            ss=self.ss,
            vka=self.vka,
            iphdry=self.upw_iphdry,
            hdry=self.upw_hdry,
            layvka=self.upw_layvka,
            extension="upw",
            unitnumber=None,
            noparcheck=False,
        )

        # %% Source terms

        # Activated only when recharge values are negative (king of pumping)
        if isinstance(self.recharge, (dict)) == False:
            if (
                isinstance(self.recharge, float) == False
                and (self.recharge < 0).any().any() == True
            ):
                self.evt = self.recharge.copy()
                # All positive values are set to 0 (no negative values)
                self.evt[self.evt >= 0] = 0
                # All negative values are set to positive values
                self.evt = abs(self.evt)
                self.evtData = {}
                # Loop over all time steps to make a dictionnary from a scalar or a dictionnary
                for kper in range(0, self.nper):
                    if isinstance(self.evt, (int, float)):
                        # Steady state:
                        self.evtData[kper] = self.evt
                    else:
                        # Transient state:
                        if kper == 0:
                            self.evtData[kper] = 0
                        else:
                            self.evtData[kper] = self.evt[kper]
                # ---- flopy.modflow.ModflowEvt
                self.evt = flopy.modflow.ModflowEvt(
                    self.mf,
                    evtr=self.evtData,
                    surf=self.dem,
                    nevtop=self.evt_nevtop,
                    exdp=self.exdp,
                    ievt=self.evt_ievt,
                    ipakcb=self.evt_ipakcb,
                )
                # Finally sets all negative of self.recharge to zero values for simulation
                if not isinstance(self.recharge, (int, float)):
                    self.recharge[self.recharge < 0] = 0

        # Recharge of the aquifer on the top of the water table
        self.rchData = {}
        for kper in range(0, self.nper):
            if isinstance(self.recharge, (dict)) == True:
                if self.sim_state == "steady":
                    self.rchData = sum(self.recharge.values()) / len(self.recharge)
                if self.sim_state == "transient":
                    self.rchData = self.recharge
            else:
                if isinstance(self.recharge, (int, float)):
                    # Only value in self.climatic (steady)
                    self.rchData[kper] = self.recharge
                else:
                    if kper == 0:
                        if self.first_clim == "mean":
                            self.rchData[kper] = np.nanmean(self.recharge)
                        if self.first_clim == "first":
                            self.rchData[kper] = self.recharge.iloc[0]
                        if isinstance(self.first_clim, (int, float)):
                            self.rchData[kper] = self.first_clim
                    else:
                        # More flexibility in the possible format of the climatic chronicles
                        # Should only be used exceptionnaly (pandas series recommended)
                        try:
                            self.rchData[kper] = self.recharge.iloc[kper]
                        except:
                            self.rchData[kper] = self.recharge.iloc[kper].values[0]

        # Sets recharge to modflow through flopy
        # ---- flopy.modflow.ModflowRch
        self.rch = flopy.modflow.ModflowRch(self.mf, rech=self.rchData)

        # %% Drain package

        # DRN is applied to all the surface of the model: enables seepage on the top layer
        
        if 'drainage' in self.flow.boundary_conditions.keys():
            self.drnData = np.zeros((int(np.sum(self.drain_array)), 5))
            compt = 0
            self.drnData[:, 0] = 0  # First value (0): layer
            for i in range(0, self.nrow):
                for j in range(0, self.ncol):
                    if self.drain_array[i, j] == 1:
                        self.drnData[compt, 1] = i  # Second value (1): row number
                        self.drnData[compt, 2] = j  # Third value (2): column number
                        self.drnData[compt, 3] = self.dem[i, j]  # Fourth value (3): altitude
                        # Fifth value (4): value of the conductivity of the drain (integrated over the surface of the cell)
                        if self.sink_fill == False:
                            if self.flow.boundary_conditions['drainage'].value > 0:
                                self.drnData[compt, 4] = self.flow.boundary_conditions['drainage'].value
                            else:
                                self.drnData[compt, 4] = (self.hk[0, i, j] * self.resolution**2)
                        else:
                            if self.sink[i, j] > 0:
                                self.drnData[compt, 4] = 0
                            else:
                                if self.flow.boundary_conditions['drainage'].value > 0:
                                    self.drnData[compt, 4] = self.flow.boundary_conditions['drainage'].value
                                else:
                                    self.drnData[compt, 4] = (
                                        self.hk[0, i, j] * self.resolution**2
                                    )
                        compt += 1

            # Imposes DRN condition to Modflow through flopy
            lrcec = {0: self.drnData}
            # ---- flopy.modflow.ModflowDrn
            self.drn = flopy.modflow.ModflowDrn(self.mf, stress_period_data=lrcec)

        # %% Well package

        if (self.well_coords != []) or (len(self.well_coords) > 0):

            # Number of stress periods
            n_stress_periods = len(self.recharge)
            n_wells = len(self.well_coords)

            # Initialize the dictionary
            self.lrcq = {}

            # Populate the dictionary with well data for each stress period
            for t in range(n_stress_periods):
                list_t = []
                for n in range(n_wells):
                    list_t.append([*self.well_coords[n], self.well_fluxes[n][t]])
                self.lrcq[t] = list_t

            # ---- flopy.modflow.ModflowWel
            self.wel = flopy.modflow.ModflowWel(
                self.mf, ipakcb=self.wel_ipakcb, stress_period_data=self.lrcq
            )

        # %% Output control

        stress_period_data = {}
        for kper in range(self.nper):
            kstp = self.nstp[kper]
            # Saves head (hds) and budget (cbc) for each of the stress periods
            stress_period_data[(kper, kstp - 1)] = ["save head", "save budget"]
        # ---- flopy.modflow.ModflowOc
        self.oc = flopy.modflow.ModflowOc(
            self.mf,
            stress_period_data=stress_period_data,
            extension=["oc", "hds", "cbc"],
            unitnumber=None,
            compact=self.oc_compact,
        )
        self.oc.reset_budgetunit(fname=self.model_name + ".cbc")

        # Check grid
        def check_water_flow_connectivity(grid):
            layers, rows, cols = grid.shape
            problematic_cells = []  # Store problematic cells

            for z in range(layers - 1):  # Focus on flow between layers
                logger.debug("Checking layer %d", z)
                for y in range(rows):
                    for x in range(cols):
                        # Skip if the current cell is inactive (e.g., NaN or specific inactive value)
                        if np.isnan(grid[z, y, x]) or np.isnan(grid[z + 1, y, x]):
                            continue

                        # Current cell's top and bottom elevations
                        current_top = grid[z, y, x]
                        current_bottom = grid[z + 1, y, x]

                        neighbors = []

                        # Collect adjacent neighbors' top and bottom elevations
                        if y > 0 and not (
                            np.isnan(grid[z, y - 1, x])
                            or np.isnan(grid[z + 1, y - 1, x])
                        ):  # Left neighbor
                            neighbors.append((grid[z, y - 1, x], grid[z + 1, y - 1, x]))
                        if y < rows - 1 and not (
                            np.isnan(grid[z, y + 1, x])
                            or np.isnan(grid[z + 1, y + 1, x])
                        ):  # Right neighbor
                            neighbors.append((grid[z, y + 1, x], grid[z + 1, y + 1, x]))
                        if x > 0 and not (
                            np.isnan(grid[z, y, x - 1])
                            or np.isnan(grid[z + 1, y, x - 1])
                        ):  # Front neighbor
                            neighbors.append((grid[z, y, x - 1], grid[z + 1, y, x - 1]))
                        if x < cols - 1 and not (
                            np.isnan(grid[z, y, x + 1])
                            or np.isnan(grid[z + 1, y, x + 1])
                        ):  # Back neighbor
                            neighbors.append((grid[z, y, x + 1], grid[z + 1, y, x + 1]))

                        # If there are neighbors, check if water can flow
                        if neighbors:
                            can_flow = False
                            for neighbor_top, neighbor_bottom in neighbors:
                                # Check if current cell's range overlaps with neighbor's range
                                if (
                                    current_bottom <= neighbor_top
                                    and current_top >= neighbor_bottom
                                ):
                                    can_flow = True
                                    break

                            if not can_flow:
                                problematic_cells.append((z, y, x))

            return problematic_cells

        if self.check_grid == True:
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

        # CrossSection figure
        if self.plot_cross == True:

            fig, axs = plt.subplots(1, 2, figsize=(14, 4), dpi=300)
            axs = axs.ravel()

            grid_model = self.mf.modelgrid

            modelxsect1 = flopy.plot.PlotCrossSection(
                model=self.mf, line={"Row": int((grid_model.shape[1]) / 2)}
            )
            imhk = modelxsect1.plot_array(
                self.hk / 24 / 3600,
                masked_values=[-9999],
                cmap="jet",
                alpha=0.5,
                lw=0.1,
                ax=axs[0],
                # norm=mpl.colors.LogNorm(vmin=self.hk.min(), vmax=self.hk.max())
                norm=mpl.colors.LogNorm(vmin=1e-10, vmax=1e-1),
            )
            # modelxsect1.plot_grid(ax=axs[0])
            axs[0].set_title("West-East (Row), K [m/s]", fontsize=12)
            if self.cross_ylim == []:
                axs[0].set_ylim(
                    np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                    np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)),
                )
            else:
                axs[0].set_ylim(self.cross_ylim[0], self.cross_ylim[1])
            axs[0].set_xlabel("Distance [m]")
            axs[0].set_ylabel("Elevation [m]")
            # divider = make_axes_locatable(axs[0])
            # cax = divider.append_axes('right', size='5%', pad=0.05)
            # fig.colorbar(imhk, cax=cax, orientation='vertical')
            fig.colorbar(imhk)

            modelxsect2 = flopy.plot.PlotCrossSection(
                model=self.mf, line={"Column": int((grid_model.shape[2]) / 2)}
            )
            imsy = modelxsect2.plot_array(
                self.sy * 100,
                masked_values=[-9999],
                cmap="jet",
                alpha=0.5,
                lw=0.1,
                ax=axs[1],
                # norm=mpl.colors.LogNorm(vmin=self.sy.min(), vmax=self.sy.max())
                norm=mpl.colors.LogNorm(vmin=0.1, vmax=100),
            )
            # modelxsect2.plot_grid(ax=axs[1])
            axs[1].set_title("North-South (Column), Sy [%]", fontsize=12)
            if self.cross_ylim == []:
                axs[1].set_ylim(
                    np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                    np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)),
                )
            else:
                axs[1].set_ylim(self.cross_ylim[0], self.cross_ylim[1])
            axs[1].set_xlabel("Distance [m]")
            axs[1].set_ylabel("Elevation [m]")
            # divider = make_axes_locatable(axs[1])
            # cax = divider.append_axes('right', size='5%', pad=0.05)
            # fig.colorbar(imsy, cax=cax, orientation='vertical')
            fig.colorbar(imsy)

            fig.suptitle(self.model_name.upper(), y=1.0, fontsize=10)
            fig.tight_layout()

    # %% PROCESSING

    def processing(
        self,
        write_model: bool = True,
        run_model: bool = False,
        link_mt3dms: bool = False,
    ):
        """
        Run the hydrologic model.

        Parameters
        ----------
        write_model : bool, optional
            Flag to write input files or not. The default is True.
        run_model : bool, optional
            Flag to run model or not. The default is False.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation is done correctly.

        """

        if link_mt3dms == True:
            lmt = flopy.modflow.ModflowLmt(
                self.mf,
                output_file_name=self.lmt_output_file_name,
                extension=self.lmt_extension,
                output_file_format=self.lmt_output_format,
                unitnumber=None,
            )

        # Create modflow files
        if write_model == True:
            # Write input files
            self.mf.write_input()

        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mf.run_model(
                silent=not verbose
            )  # True without msg

        return success_model

    # %% POST-PROCESSING

    def post_processing(
        self,
        model_modflow: object,
        watertable_elevation: bool = True,
        watertable_depth: bool = True,
        seepage_areas: bool = True,
        outflow_drain: bool = True,
        groundwater_flux: bool = True,
        groundwater_storage: bool = True,
        accumulation_flux: bool = True,
        persistency_index: bool = False,
        intermittency_yearly: bool = False,
        intermittency_monthly: bool = False,
        intermittency_weekly: bool = False,
        intermittency_daily: bool = False,
        export_all_tif: bool = False,
    ):
        """
        Create outputs files.

        Parameters
        ----------
        model_modflow : object
            MODFLOW Python object.
        watertable_elevation : bool, optional
            Write watertable elevation outputs. The default is True.
        watertable_depth : bool, optional
            Write watertable depth outputs. The default is True.
        seepage_areas : bool, optional
            Write seepage areas outputs. The default is True.
        outflow_drain : bool, optional
            Write outflow drain outputs. The default is True.
        groundwater_flux : bool, optional
            Write groundwater flux outputs. The default is True.
        groundwater_storage : bool, optional
            Write groundwater storage outputs. The default is True.
        accumulation_flux : bool, optional
            Write accumulation flux outputs. The default is True.
        persistency_index : bool, optional
            Write persistency index outputs. The default is False.
        intermittency_monthly : bool, optional
            Write intermittency monthly outputs. The default is False.
        intermittency_weekly : bool, optional
            Write intermittency weekly outputs. The default is False.
        intermittency_daily : bool, optional
            Write intermittency daily outputs. The default is False.
        export_all_tif : bool, optional
            Write all files .tif at each time step. The default is False.
        """
        # Create folders
        self.save_file = os.path.join(self.full_path, "_postprocess")
        toolbox.create_folder(self.save_file)

        self.figure_file = os.path.join(self.full_path, "_postprocess", "_figures")
        toolbox.create_folder(self.figure_file)

        self.temporary_file = os.path.join(self.full_path, "_postprocess", "_temporary")
        toolbox.create_folder(self.temporary_file)

        self.tifs_file = os.path.join(self.full_path, "_postprocess", "_rasters")
        toolbox.create_folder(self.tifs_file)

        self.save_fig = os.path.join(self.model_folder, "_figures")
        toolbox.create_folder(self.save_fig)

        # %% Load essential data

        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name)

        # Files have been output in the processing phase and are re-read here
        self.dem_mask = self.dem < -9999
        # heads
        self.head_fpu = fpu.HeadFile(self.path_file + ".hds")
        # fluxes
        self.cbb = fpu.CellBudgetFile(self.path_file + ".cbc")

        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkpers = self.head_fpu.get_kstpkper()

        # Params model
        self.nper = self.dis.nper
        self.kper = np.arange(0, self.nper, 1)
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1

        # %% Export results over times

        # Fill dictionnaries .npy or .nc over times and create .tif

        # Create dictionnaries for each of the results to extract
        # x[time]=matrix
        #   - x: type of output
        #   - time: time at which it is taken
        #   - matrix: 2D matrix of values
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
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

        # Loop over times: fills each of the previous structures and create raster
        for item, time in enumerate(self.times):
            logger.info(
                "Post-processing stress period %d/%d", item + 1, len(self.times)
            )

            if len(self.times) == 1:
                self.kstpkper = self.kstpkpers[0]

            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])

            lead_numb = str(item)

            export_tif = True
            if export_all_tif == False:
                if item > 0:
                    export_tif = False

            # Search watertable data positive values
            self.head = self.head_fpu.get_data(
                totim=time
            )  # self.head_all = self.head_fpu.get_alldata(), self.head_all[item][0]
            if self.nlay == 1:
                self.head_data = self.head[0]
            else:
                ### Option 1
                self.head_data = pp.get_water_table(self.head, -100)  # -9999
                ### Option 2
                # head_final = np.zeros([self.nrow,self.ncol])
                # for i in range(0,self.nrow):
                #     for j in range (0,self.ncol):
                #         for k in range(0,self.nlay):
                #             if self.head[k,i,j] > 0:
                #                 head_final[i,j] = self.head[k,i,j]
                #                 break
                # self.head_data = head_final.copy()

            if watertable_elevation == True:
                ### Watertable elevation
                self.wt_elev = self.head_data.copy()
                self.wt_elev[self.dem_mask] = -9999
                output_path = (
                    self.tifs_file + "/watertable_elevation_t(" + lead_numb + ").tif"
                )
                if export_tif == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.wt_elev, output_path, -9999
                    )
                self.dict_watertable_elevation[item] = self.wt_elev

            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = self.dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                output_path = (
                    self.tifs_file + "/watertable_depth_t(" + lead_numb + ").tif"
                )
                if export_tif == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.wt_depth, output_path, -9999
                    )
                self.dict_watertable_depth[item] = self.wt_depth

            if seepage_areas == True:
                ### Seepage areas
                self.seep_area = self.dem - self.wt_elev.copy()
                self.seep_area[self.seep_area >= 0] = 0
                self.seep_area[self.seep_area < 0] = 1
                self.seep_area[self.dem_mask] = -9999
                output_path = self.tifs_file + "/seepage_areas_t(" + lead_numb + ").tif"
                if export_tif == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.seep_area, output_path, -9999
                    )
                self.dict_seepage_areas[item] = self.seep_area

            if outflow_drain == True:
                ### Outflow drain
                self.drain = self.cbb.get_data(
                    text="DRAINS", kstpkper=self.kstpkper, totim=time
                )
                self.out_all = np.zeros((1, self.dis.nrow, self.dis.ncol))
                sim = 0
                count = 0
                for i in range(0, self.dis.nrow):
                    for j in range(0, self.dis.ncol):
                        if self.drain_array[i, j] == 1:
                            self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                            count = count + 1
                self.out_drn = self.out_all[0]
                self.out_drn[self.dem_mask] = -9999
                output_path = self.tifs_file + "/outflow_drain_t(" + lead_numb + ").tif"
                if accumulation_flux == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.out_drn, output_path, -9999
                    )
                else:
                    if export_tif == True:
                        toolbox.export_tif(
                            self.dem_watershed_path, self.out_drn, output_path, -9999
                        )
                self.dict_outflow_drain[item] = self.out_drn

            if groundwater_flux == True:
                ### Groundwater flux
                self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
                self.frf = self.cbb.get_data(
                    text="FLOW RIGHT FACE", kstpkper=self.kstpkper, totim=time
                )[0]
                self.fff = self.cbb.get_data(
                    text="FLOW FRONT FACE", kstpkper=self.kstpkper, totim=time
                )[0]
                if self.nlay == 1:
                    self.flux = np.sqrt(self.frf**2 + self.fff**2)
                if self.nlay > 1:
                    self.flf = self.cbb.get_data(
                        text="FLOW LOWER FACE", kstpkper=self.kstpkper, totim=time
                    )[
                        0
                    ]  # > 1 lay
                    self.flux = np.sqrt(self.frf**2 + self.fff**2 + self.flf**2)
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                output_path = (
                    self.tifs_file + "/groundwater_flux_t(" + lead_numb + ").tif"
                )
                if export_tif == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.flux_top, output_path, -9999
                    )
                self.dict_groundwater_flux[item] = self.flux_top

            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem < 0] = np.nan
                self.wt_sto = (
                    (self.wt_sto - self.zbot[-1])
                    * (self.resolution**2)
                    * np.nanmean(self.sy)
                )
                output_path = (
                    self.tifs_file + "/groundwater_storage_t(" + lead_numb + ").tif"
                )
                if export_tif == True:
                    toolbox.export_tif(
                        self.dem_watershed_path, self.wt_sto, output_path, -9999
                    )
                self.dict_groundwater_storage[item] = self.wt_sto

            if accumulation_flux == True:
                ### Accumulation flux
                accumulated_flow = masstransfer.Masstransfer(
                    self.geographic,
                    "outflow_drain_t(" + lead_numb + ").tif",
                    "tracept_t(" + lead_numb + ").shp",
                    "accumulation_flux_t(" + lead_numb + ").tif",
                    extraction_folder=self.save_file,
                )
                accumulated_flow.trace_cumulated()
                output_path = (
                    self.tifs_file + "/accumulation_flux_t(" + lead_numb + ").tif"
                )
                with rasterio.open(output_path) as src:
                    self.dict_accumulation_flux[item] = src.read(1)

        ### Save dictionaries to npy
        if watertable_elevation == True:
            logger.info("Exporting watertable elevation time series")
            np.save(
                self.save_file + "/watertable_elevation", self.dict_watertable_elevation
            )
        if watertable_depth == True:
            logger.info("Exporting watertable depth time series")
            np.save(self.save_file + "/watertable_depth", self.dict_watertable_depth)
        if seepage_areas == True:
            logger.info("Exporting seepage areas time series")
            np.save(self.save_file + "/seepage_areas", self.dict_seepage_areas)
        if outflow_drain == True:
            logger.info("Exporting outflow drain time series")
            np.save(self.save_file + "/outflow_drain", self.dict_outflow_drain)
        if groundwater_flux == True:
            logger.info("Exporting groundwater flux time series")
            np.save(self.save_file + "/groundwater_flux", self.dict_groundwater_flux)
        if groundwater_storage == True:
            logger.info("Exporting groundwater storage time series")
            np.save(
                self.save_file + "/groundwater_storage", self.dict_groundwater_storage
            )
        if accumulation_flux == True:
            logger.info("Exporting accumulation flux time series")
            np.save(self.save_file + "/accumulation_flux", self.dict_accumulation_flux)

        if persistency_index == True:
            ### Persistency index
            logger.info("Exporting persistency index maps")
            acc_npy_raw = np.load(
                os.path.join(self.save_file, "accumulation_flux.npy"), allow_pickle=True
            ).item()
            acc_npy = list(acc_npy_raw.items())[:]
            for key in range(len(acc_npy)):
                with rasterio.open(self.geographic.watershed_box_buff_dem) as src:
                    mask = src.read(1)
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask < 0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo > 0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            pi_export = days_flux.copy()
            self.pi = np.ma.masked_where(days_flux <= 0, days_flux)
            self.dict_persistency_index[0] = self.pi
            pi_export[days_flux <= 0] = -9999
            pi_export[mask <= 0] = -9999
            output_path = self.tifs_file + "/persistency_index_t(" + "-" + ").tif"
            toolbox.export_tif(self.dem_watershed_path, pi_export, output_path, -9999)

            np.save(self.save_file + "/persistency_index", self.dict_persistency_index)

        if intermittency_daily == True:
            ### Intermittency daily
            logger.info("Exporting daily intermittency maps")
            acc_npy_raw = np.load(
                os.path.join(self.save_file, "accumulation_flux.npy"), allow_pickle=True
            ).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw) >= 365:
                inf = 0
                sup = 365
                step = int(round(len(acc_npy_raw) / 365))
                compt = 0
                for i in range(step):
                    logger.debug("Processing daily intermittency t: %d / %d", i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(
                            interv[key][1], mask=(mask < 0)
                        )
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo > 0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask < 0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k] <= 0, interv[k])
                        tempo[days_flux < 365] = 0
                        tempo[days_flux == 365] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k] <= 0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k] <= 0] = -9999
                        tempo_export[mask <= 0] = -9999
                        output_path = (
                            self.tifs_file
                            + "/intermittency_daily_t("
                            + str(compt)
                            + ").tif"
                        )
                        # if export_tif==True:
                        toolbox.export_tif(
                            self.geographic.watershed_dem,
                            tempo_export,
                            output_path,
                            -9999,
                        )
                        compt += 1
                    inf += 365
                    sup += 365
            np.save(
                self.save_file + "/intermittency_daily", self.dict_intermittency_daily
            )

        if intermittency_weekly == True:
            logger.info("Exporting weekly intermittency maps")
            acc_npy_raw = np.load(
                os.path.join(self.save_file, "accumulation_flux.npy"), allow_pickle=True
            ).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw) >= 52:
                inf = 0
                sup = 52
                step = int(round(len(acc_npy_raw) / 52))
                compt = 0
                for i in range(step):
                    logger.debug("Processing weekly intermittency t: %d / %d", i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(
                            interv[key][1], mask=(mask < 0)
                        )
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo > 0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask < 0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k] <= 0, interv[k])
                        tempo[days_flux < 52] = 0
                        tempo[days_flux == 52] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k] <= 0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k] <= 0] = -9999
                        tempo_export[mask <= 0] = -9999
                        output_path = (
                            self.tifs_file
                            + "/intermittency_weekly_t("
                            + str(compt)
                            + ").tif"
                        )
                        # if export_tif==True:
                        toolbox.export_tif(
                            self.geographic.watershed_dem,
                            tempo_export,
                            output_path,
                            -9999,
                        )
                        compt += 1
                    inf += 52
                    sup += 52
            np.save(
                self.save_file + "/intermittency_weekly", self.dict_intermittency_weekly
            )

        if intermittency_monthly == True:
            ### Intermittency monthly
            logger.info("Exporting monthly intermittency maps")
            acc_npy_raw = np.load(
                os.path.join(self.save_file, "accumulation_flux.npy"), allow_pickle=True
            ).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw) >= 12:
                inf = 0
                sup = 12
                step = int(round(len(acc_npy_raw) / 12))
                compt = 0
                for i in range(step):
                    logger.debug("Processing monthly intermittency t: %d / %d", i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(
                            interv[key][1], mask=(mask < 0)
                        )
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo > 0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask < 0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k] <= 0, interv[k])
                        tempo[days_flux < 12] = 0
                        tempo[days_flux == 12] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k] <= 0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k] <= 0] = -9999
                        tempo_export[mask <= 0] = -9999
                        output_path = (
                            self.tifs_file
                            + "/intermittency_monthly_t("
                            + str(compt)
                            + ").tif"
                        )
                        toolbox.export_tif(
                            self.geographic.watershed_dem,
                            tempo_export,
                            output_path,
                            -9999,
                        )
                        compt += 1
                    inf += 12
                    sup += 12
            np.save(
                self.save_file + "/intermittency_monthly",
                self.dict_intermittency_monthly,
            )

        if intermittency_yearly == True:
            ### Intermittency monthly
            logger.info("Exporting yearly intermittency maps")
            acc_npy_raw = np.load(
                os.path.join(self.save_file, "accumulation_flux.npy"), allow_pickle=True
            ).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw) >= 1:
                inf = 0
                sup = 1
                step = int(round(len(acc_npy_raw) / 1))
                compt = 0
                for i in range(step):
                    logger.debug("Processing yearly intermittency t: %d / %d", i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(
                            interv[key][1], mask=(mask < 0)
                        )
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo > 0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask < 0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k] <= 0, interv[k])
                        tempo[days_flux < 1] = 0
                        tempo[days_flux == 1] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k] <= 0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k] <= 0] = -9999
                        tempo_export[mask <= 0] = -9999
                        output_path = (
                            self.tifs_file
                            + "/intermittency_yearly_t("
                            + str(compt)
                            + ").tif"
                        )
                        toolbox.export_tif(
                            self.geographic.watershed_dem,
                            tempo_export,
                            output_path,
                            -9999,
                        )
                        compt += 1
                    inf += 12
                    sup += 12
            np.save(
                self.save_file + "/intermittency_yearly",
                self.dict_intermittency_monthly,
            )


# %% NOTES
