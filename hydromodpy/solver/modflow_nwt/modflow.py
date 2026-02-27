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
from numbers import Real
import flopy
import numpy as np
import os
import pandas as pd
import sys
import rasterio
from os.path import dirname, abspath
import matplotlib.pyplot as plt
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
from hydromodpy.modeling import masstransfer
from hydromodpy.domain.surface import Surface
from hydromodpy.solver import Solver
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.solver.utils.temporal.tmesh_generation import (
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
        modflow_config: ModflowConfig | Mapping[str, object] | None = None,
        # Worflow settings
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default",
        bin_path: str = "bin",
        box: bool = True,
        sink_fill: bool = False,
        plot_cross: bool = True,
        cross_ylim: list = [],
        check_grid: bool = True,
        # Climatic settings
        recharge=0.001,
        first_clim: str = "mean",
        dis_perlen: bool = False):
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
        plot_cross : bool, optional
            If True, display a cross section of the model. The default is True.
        check_grid : bool, optional
            If True, check if the water connectivity is respected with the meshgrid. The default is True.
        recharge : float or list, optional
            Recharge [L/T] as input of the model. The default is 0.001.
        first_clim : str, optional
            If 'mean': the first recharge value is the mean of the chronicle.
            If 'first': the first recharge value is the first value of the timeseries.
            If a 'float' : the first recharge is the fixed value.
            The default is 'mean'.
        modflow_config : ModflowConfig | Mapping | None, optional
            Expert MODFLOW-NWT package parameters loaded from
            `[modflow.runtime]`, `[modflow.process_specific]`, and `[modflow.sgrid]` in TOML.
            If None, internal defaults from ModflowConfig are used.
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

        # %% Input and discretization termes

        self.recharge = recharge

        self.flow_regime = self._resolve_flow_regime()
        self.first_clim = first_clim
        self.dis_perlen = dis_perlen

        # %% Plot things

        self.plot_cross = plot_cross
        self.cross_ylim = cross_ylim
        self.check_grid = check_grid

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

    # %% PRE-PROCESSING

    def _get_domain_surfaces(self):
        """
        Return explicit domain surfaces used by the MODFLOW spatial grid.
        """
        if self.domain is None:
            raise ValueError(
                "Modflow spatial geometry is domain-only: a Domain object is required."
            )

        surface_topo = getattr(self.domain, "surface_topo", None)
        substratum = getattr(self.domain, "substratum", None)
        if surface_topo is None or substratum is None:
            raise ValueError(
                "Modflow spatial geometry is domain-only: domain.surface_topo "
                "and domain.substratum are required."
            )
        if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
            raise TypeError("Domain surfaces must be Surface instances.")

        top = np.asarray(surface_topo.as_array(), dtype=float)
        bot = np.asarray(substratum.as_array(), dtype=float)
        if top.shape != bot.shape:
            raise ValueError(
                f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}."
            )
        if top.shape != self.dem.shape:
            raise ValueError(
                "Domain surface shape must match active DEM support "
                f"({top.shape} vs {self.dem.shape})."
            )

        surface_topo.assert_same_geographic_domain(substratum)
        return surface_topo, substratum

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

    def _build_well_stress_period_data(self, n_stress_periods: int) -> dict[int, list[list[float]]]:
        """Build MODFLOW WEL stress-period payload from flow.sinks_sources.wells."""
        if n_stress_periods <= 0 or self.flow is None:
            return {}

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        if not isinstance(sinks_sources, Mapping):
            return {}

        wells = sinks_sources.get("wells", {})
        if wells is None:
            return {}
        if not isinstance(wells, Mapping):
            raise TypeError(
                "flow.sinks_sources['wells'] must be a mapping of well ids to payloads."
            )
        if len(wells) == 0:
            return {}

        normalized_wells: list[tuple[str, tuple[int, int, int], np.ndarray]] = []
        for raw_well_id, raw_well_payload in wells.items():
            well_id = str(raw_well_id).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty ids.")

            if isinstance(raw_well_payload, Mapping):
                cell_payload = raw_well_payload.get("cell")
                flux_payload = raw_well_payload.get("flux")
            else:
                cell_payload = getattr(raw_well_payload, "cell", None)
                flux_payload = getattr(raw_well_payload, "flux", None)

            if cell_payload is None:
                raise ValueError(f"flow.sinks_sources.wells.{well_id}.cell is required")
            if flux_payload is None:
                raise ValueError(f"flow.sinks_sources.wells.{well_id}.flux is required")

            if isinstance(cell_payload, Mapping):
                cell_seq = [
                    cell_payload.get("lay"),
                    cell_payload.get("row"),
                    cell_payload.get("col"),
                ]
            else:
                cell_seq = list(cell_payload)
            if len(cell_seq) != 3:
                raise ValueError(
                    f"flow.sinks_sources.wells.{well_id}.cell must contain 3 values: [lay,row,col]"
                )

            cell_parsed: list[int] = []
            for axis, raw_index in zip(("lay", "row", "col"), cell_seq):
                if isinstance(raw_index, bool) or not isinstance(raw_index, Real):
                    raise TypeError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be numeric"
                    )
                numeric_index = float(raw_index)
                if not numeric_index.is_integer():
                    raise TypeError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be an integer"
                    )
                int_index = int(numeric_index)
                if int_index < 0:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.cell.{axis} must be >= 0"
                    )
                cell_parsed.append(int_index)
            cell = (cell_parsed[0], cell_parsed[1], cell_parsed[2])

            if isinstance(flux_payload, bool):
                raise TypeError(
                    f"flow.sinks_sources.wells.{well_id}.flux must be numeric or list of numeric values"
                )
            if isinstance(flux_payload, Real):
                flux_vector = np.full(n_stress_periods, float(flux_payload), dtype=float)
            else:
                flux_vector = np.asarray(flux_payload, dtype=float).reshape(-1)
                if flux_vector.size == 0:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.flux cannot be empty"
                    )
                if flux_vector.size == 1:
                    flux_vector = np.full(n_stress_periods, float(flux_vector[0]), dtype=float)
                elif flux_vector.size != n_stress_periods:
                    raise ValueError(
                        f"flow.sinks_sources.wells.{well_id}.flux length ({flux_vector.size}) "
                        f"must be 1 or match nper ({n_stress_periods})"
                    )

            normalized_wells.append((well_id, cell, flux_vector))

        lrcq: dict[int, list[list[float]]] = {}
        for t in range(n_stress_periods):
            lrcq[t] = [
                [cell[0], cell[1], cell[2], float(flux_vector[t])]
                for _, cell, flux_vector in normalized_wells
            ]
        return lrcq

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

        ### Temporal: model time definition from [modflow.tgrid]
        if self.tgrid_config is None:
            raise ValueError(
                "Missing [modflow.tgrid] configuration: a typed TMeshConfigModel "
                "is required to generate temporal discretization."
            )
        builder_kwargs = self.tgrid_config.to_builder_kwargs()
        flow_regime = self._resolve_flow_regime()
        if flow_regime is None:
            raise ValueError(
                "Missing flow.flow_regime configuration: Modflow temporal setup "
                "must be driven by [flow].flow_regime."
            )
        builder_kwargs["flow_regime"] = flow_regime

        builder = TMesh_Generation(**builder_kwargs)
        tgrid = builder.run()
        self.flow_regime = flow_regime
        dis_itmuni = getattr(tgrid, "time_units", self.dis_itmuni)
        dis_nper = int(np.asarray(getattr(tgrid, "perlen", []), dtype=float).size)
        dis_perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
        dis_nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
        dis_steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
        dis_start_datetime = getattr(tgrid, "start_datetime", None)
        if dis_nper == 0:
            raise ValueError("modflow.tgrid produced an empty perlen vector.")
        self.dis_itmuni = dis_itmuni
        self.nper = dis_nper
        self.perlen = dis_perlen
        self.nstp = dis_nstp
        self.steady = dis_steady
        self.start_datetime = dis_start_datetime

        ### Sptial: model domain definition and discretization

        top_surface, bottom_surface = self._get_domain_surfaces()
        self.dem = np.asarray(top_surface.as_array(), dtype=float)
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]

        if self.sgrid_config is None:
            raise ValueError(
                "Missing [modflow.sgrid] configuration: a typed VerticalGridConfig "
                "is required to generate the structured grid."
            )
        vertical_cfg = self.sgrid_config
        sgrid = StructuredGridBuilder().build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_cfg,
        )
        self.nlay = int(sgrid.nlay)
        self.nrow = int(sgrid.nrow)
        self.ncol = int(sgrid.ncol)
        self.zbot = np.asarray(sgrid.botm, dtype=float)
        self.bottom_layer = np.asarray(self.zbot[-1], dtype=float)
        
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
            itmuni=dis_itmuni,
            nper=dis_nper,
            perlen=dis_perlen,
            nstp=dis_nstp,
            steady=dis_steady,
            start_datetime=dis_start_datetime)

        # %% Boundary conditions

        ### Initialze the top boundary condition of DRN package
        self.drain_array = np.ones((self.nrow, self.ncol))

        ### Constant head boundary conditions of no flow (sides of domain)

        self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
        # iboundData=1: Should compute head in cells
        # iboundData=0: Nothing is calculated in cells
        # iboundData=-1: Values imposed at the value of strtData

        # Free surface level is set to the surface (altitude of DEM)
        if self.flow.initial_conditions["h"].type == "top":
            self.strtData = np.ones((self.nlay, self.nrow, self.ncol)) * self.dem
        if self.flow.initial_conditions["h"].type == "bot":
            self.strtData = np.ones((self.nlay, self.nrow, self.ncol)) * self.bottom_layer
        if self.flow.initial_conditions["h"].type == "custom":
            self.strtData = np.ones((self.nlay, self.nrow, self.ncol)) * self.flow.initial_conditions["h"].value

        # Fixed head on the left (better for square domain)
        if "west_boundary" in self.flow.boundary_conditions.keys():
            self.iboundData[:, :, 0] = -1
            self.strtData[:, :, 0] = self.flow.boundary_conditions["west_boundary"].value

        # Fixed head on the right (better for square domain)
        if "east_boundary" in self.flow.boundary_conditions.keys():
            self.iboundData[:, :, -1] = -1
            self.strtData[:, :, -1] = self.flow.boundary_conditions["east_boundary"].value
        
        if "north_boundary" in self.flow.boundary_conditions.keys():
            self.iboundData[:, 0, :] = -1
            self.strtData[:, 0, :] = self.flow.boundary_conditions["north_boundary"].value
        
        if "south_boundary" in self.flow.boundary_conditions.keys():
            self.iboundData[:, -1, :] = -1
            self.strtData[:, -1, :] = self.flow.boundary_conditions["south_boundary"].value

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
                if self.flow_regime == "steady":
                    self.rchData = sum(self.recharge.values()) / len(self.recharge)
                if self.flow_regime == "transient":
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

        self.lrcq = self._build_well_stress_period_data(n_stress_periods=int(self.nper))
        if self.lrcq:
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
