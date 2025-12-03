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

#%% LIBRAIRIES

# Python
import flopy
import numpy as np
import os
import datetime
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

logger = get_logger(__name__)

import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable

#%% CLASS

class Modflow:
    """
    Class Modflow.

    To build, run the hydrologic model and manage/format simulation outputs.
    """

    def __init__(self, geographic: object,
                 # Worflow settings
                 model_folder: str='HydroModPy_outputs',  model_name: str='Default',
                 bin_path: str='bin', box: bool=True, sink_fill: bool=False, sim_state: str='steady',
                 plot_cross: bool=True, cross_ylim: list=[], check_grid: bool=True,
                 # Climatic settings
                 recharge=0.001, runoff=None, first_clim: str='mean', dis_perlen: bool=False,
                 # Hydraulic settings
                 nlay: int=1, lay_decay: float=1.,
                 bottom: float=None, thick: float=100.,
                 verti_hk=None, verti_sy=None, verti_ss=None,
                 hk_value=0.0864, sy_value: float=0.1, ss_value: float=1e-5,
                 hk_decay: list=[0.,None,False,[]], sy_decay: list=[0.,None,False,[]], ss_decay: list=[0.,None,False,[]],
                 vka: float=1.0,
                 exdp: float=1,
                 # Well settings
                 well_coords: list=[], well_fluxes: list=[],
                 # Boundary settings
                 cond_drain: float=None, sea_level=None, bc_left: float=None, bc_right: float=None):

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
        verti_hk : list, optional
            Depth-dependent hydraulic conductivity. The default is None.
        verti_sy : list, optional
            Depth-dependent specific yield. The default is None.
        verti_ss : list, optional
            Depth-dependent specific storage. The default is None.
        hk_value : float or 2D float
            Fix the hydraulic conductivity value. default is 0.0864.
        sy_value : float or 2D float, optional
            Fixe the specific yield value. The default is 0.1.
        ss_value : float or 2D float, optional
            Fixe the specifc storage value. Activated for confined layers. The default is 1e-5 (1/day).
        hk_decay : float, optional
            Exponential decay of hydraulic conductivity whith depth. The default is 0.
        sy_decay : float, optional
            Exponential specific yield of hydraulic conductivity whith depth. The default is 0.
        ss_decay : float, optional
            Exponential specific storage of hydraulic conductivity whith depth. The default is 0.
        vka : list, optional
            Ratio of horizontal to vertical hydraulic conductivity. The default is 1.
        wells_coord : list
            Inform the outlet coordinates of wells [lay,row,col].
            Example for 2 wells: [ [1,20,30], [1,15,15] ]
        wells_fluxes : list
            Inform the fluxes [L3/T] for each stress-periods, for different wells.
            Example for 2 wells and 5 stress-periods: [ [-100,0,-100,0,-100], [-100,0,-100,0,-100] ]
        cond_drain : float, optional
            Fix the conductance value of the drai (DRN) package. The default is None.
        sea_level : float, optional
            Fix head on each cell below this value. The default is None.
        bc_left : float, optional
            Fix head on the left border of the domain. The default is None.
        bc_right : float, optional
            Fix head on the right border of the domain. The default is None.
        """

        #%% Initialization paths

        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            toolbox.create(self.model_folder)

        self.model_name = model_name

        if (sys.platform == 'win32') or (sys.platform == 'win64'):
            self.exe = os.path.join(bin_path, 'win' ,'mfnwt.exe')
        if (sys.platform == 'linux'):
            self.exe = os.path.join(bin_path, 'linux' ,'mfnwt')
        if (sys.platform == 'darwin'):
            self.exe = os.path.join(bin_path, 'mac' ,'mfnwt')

        self.full_path = os.path.join(model_folder, model_name) #'modraw'

        #%% Domain definition

        # General
        self.geographic = geographic

        #######################################################################
        #self.geographic.watershed_dem = 'C:/Users/rabherve/Simulations/Lasset/Lasset_25m/results_stable/geographic/watershed_dem.tif'
        #self.geographic.watershed_box_buff_dem = 'C:/Users/rabherve/Simulations/Lasset/Lasset_25m/results_stable/geographic/watershed_box_buff_dem.tif'
        #######################################################################

        self.resolution = geographic.resolution
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        self.sink_fill = sink_fill
        try :
            self.sink = geographic.depressions_data
        except:
            pass

        # Enlarges the modeled domain
        self.box = box
        if box == True:
            self.dem = geographic.dem_box_data
            self.dem_watershed_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_watershed_path = geographic.watershed_buff_dem
        self.dem[self.dem<=-9999] = -9999
        self.dem[self.dem>=9999] = -9999

        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]

        #%% Boundary conditions

        self.bc_left = bc_left
        self.bc_right = bc_right
        self.sea_level = sea_level
        try:
            if self.sea_level == None:
                self.dem[(self.dem<0)&(self.dem>-200)] = 0
        except:
            pass

        #%% Input and discretization termes

        self.recharge = recharge
        self.runoff = runoff

        self.sim_state = sim_state
        self.first_clim = first_clim
        self.dis_perlen = dis_perlen

        #%% Model parameters

        self.bottom = bottom
        self.thick = thick

        self.nlay = nlay
        self.lay_decay = lay_decay

        self.hk_value = hk_value
        self.hk_decay = hk_decay
        self.verti_hk = verti_hk

        self.vka = vka
        self.exdp = exdp

        self.sy_value = sy_value
        self.sy_decay = sy_decay
        self.verti_sy = verti_sy

        self.ss_value = ss_value
        self.ss_decay = ss_decay
        self.verti_ss = verti_ss

        self.cond_drain = cond_drain

        #%% Specific case implementation

        # Preprocess conductivity values
        try:
            # This tips can be used to inactive some cells from hk_values grid
            self.dem[self.hk_value<0]=-9999
        except:
            pass

        #%% Plot things

        self.plot_cross = plot_cross
        self.cross_ylim = cross_ylim
        self.check_grid = check_grid

        #%% Well settings

        self.well_coords = well_coords
        self.well_fluxes = well_fluxes

    #%% PRE-PROCESSING

    def pre_processing(self):
        """
        Pre-processing to build the hydrologic model.

        Returns
        -------
        None.

        """
        #%% Initialization

        # Flopy initialization of Modflow model
        # ---- flopy.modflow.Modflow
        self.mf = flopy.modflow.Modflow(self.model_name,
                                        exe_name=self.exe,
                                        version='mfnwt',
                                        listunit=2,
                                        verbose=False,
                                        model_ws=self.full_path) # external_path=self.full_path

        # Uses Nwt for Modflow 2005, necessary for unconfined aquifers (improved interactions between surface and aquifer)
        # Sets up numerical parameters
        # ---- flopy.modflow.ModflowNwt
        self.nwt = flopy.modflow.ModflowNwt(self.mf,
                                            # headtol=1e-5*(np.nanmax(self.dem)-np.nanmin(self.dem)), # 1e-4
                                            # fluxtol=1e-3*np.nanmean(self.recharge)*self.resolution*self.resolution, # 500
                                            headtol=1e-4, # default 1e-4
                                            fluxtol=500, # default 500
                                            maxiterout=5000,
                                            thickfact=1e-05,
                                            linmeth=1,
                                            iprnwt=1,
                                            ibotav=1,
                                            options='COMPLEX',
                                            Continue=False,
                                            backflag=0,
                                            stoptol=1e-10 # 1e-10
                                            )

        #%% Discretization

        ### Temporal: time step is driven by recharge

        # Steady state
        if self.sim_state == 'steady':
            self.nper = 1               # Number of forcing periods (recharge)
            self.perlen = 1             # Length of period
            self.nstp = [1]             # Steps in a given period (not used here)
            self.steady = True          # Steady state
            self.start_datetime = None

        # Transient state
        if self.sim_state == 'transient':
            if isinstance(self.recharge,(dict))==True:
                self.start_datetime = 0
            else:
                self.start_datetime = self.recharge.index[0]        # First date of recharge
            self.steady = np.zeros(len(self.recharge),dtype=bool)   # Vector of booleans (transient state at each time step)
            self.steady[0] = True                                   # Steady state for the first time step (initialization of head values by a steady state)
            self.nstp = np.ones(len(self.recharge))                 # One step per time step
            self.nper = len(self.recharge)
            # Definition of period duration (forcing is constant on a period)
            #       As many periods as recharge values
            #       Extracts from climatic data the time steps (self.perlen)
            if self.dis_perlen == True:
                if isinstance(self.recharge, pd.core.series.Series):
                    if isinstance(self.recharge.index[0], datetime.datetime):
                        self.perlen = self.recharge.index.to_series().diff().dt.total_seconds().values/86400 # values converted into float days
                    else:
                        self.perlen = self.recharge.index.to_series().diff().values
            if isinstance(self.dis_perlen, list) == True:
                self.perlen = self.dis_perlen
            if self.dis_perlen == False:
                self.perlen = np.ones(len(self.recharge))
            if isinstance(self.recharge,(dict))==True:
                self.perlen = np.ones(len(self.recharge))
            # First timestep is steady state:
            self.perlen[0] = 1

        ### Sptial: model domain definition and discretization

        # Bottom definition for each of the layers
        self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
        if self.bottom is None:
            self.bottom_layer = self.dem - self.thick        # Matrix for constant thickness case
            self.bottom_layer[self.dem<=-9999]=-9999
        else:
            if isinstance(self.bottom,(int,float))==True:
                self.bottom_layer = self.bottom              # Float for flat bottom case or 2D
            else:
                if len(self.bottom.shape) == 2:
                    self.bottom_layer = self.bottom
                    self.bottom_layer[self.dem<=-9999]=-9999

        # Modification of layer thickness exponentially
        if self.lay_decay != 1.:
            exp_scale = 1-self.lay_decay**self.nlay

        # Parameters for proportions of bottom layer to surface values
        for i in range(1, self.nlay+1):
            if self.lay_decay <= 1:
                p = i / self.nlay    # Uniform thicknesses
            else:
                p = (1-self.lay_decay**i) / exp_scale   # Increasing thicknesses with depth
            # Weighted formula to go from bottom_layer to surface (self.dem)
            if i == 1:
                self.zbot[i-1] = self.dem  - ((self.dem - self.bottom_layer) * p)
            else:
                self.zbot[i-1] = self.bottom_layer * p + self.dem * (1-p)

        # Imposes discretization to modflow model through
        # ---- flopy.modflow.ModflowDis
        self.dis = flopy.modflow.ModflowDis(self.mf,
                                            itmuni=0, # itmuni = 0 ==> undefined
                                            lenuni=2, # itmuni_values = {'days': 4, 'hours': 3, 'minutes': 2, 'seconds': 1, 'undefined': 0, 'years': 5}
                                            nlay=self.nlay, nrow=self.nrow, ncol=self.ncol,
                                            delr=self.resolution, delc=self.resolution,
                                            top=self.dem, botm=self.zbot, xul=self.xul, yul=self.yul,
                                            nper=self.nper, perlen=self.perlen, nstp=self.nstp,
                                            steady=self.steady, start_datetime=self.start_datetime)

        #%% Boundary conditions

        ### Constant head boundary conditions of no flow (sides of domain)

        self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
                # iboundData=1: Should compute head in cells
                # iboundData=0: Nothing is calculated in cells
                # iboundData=-1: Values imposed at the value of strtData

        # Free surface level is set to the surface (altitude of DEM)
        self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem

        # Fixed head on the left (better for square domain)
        if  isinstance(self.bc_left,(int,float)) == True:
           self.iboundData[:,:,0] = -1
           self.strtData[:,:,0] = self.bc_left

        # Fixed head on the right (better for square domain)
        if  isinstance(self.bc_right,(int,float)) == True:
           self.iboundData[:,:,-1] = -1
           self.strtData[:,:,-1] = self.bc_right

        # No flow boundary conditions
        for i in range (self.nlay):
            if isinstance(self.sea_level,(int,float)) == True:
                self.iboundData[i][self.dem <= self.sea_level] = -1
                self.strtData[self.iboundData == -1] = self.sea_level
            self.iboundData[i][self.dem < -1000] = 0     # 0 is for NO FLOW

        # ---- flopy.modflow.ModflowBas
        self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)

        ### Initialze the top boundary condition of DRN package

        self.drain_array = np.ones((self.nrow, self.ncol))

        ### Constant head boundary conditions of no f : specific for sea level

        if isinstance(self.sea_level, (int,float,pd.Series,list)) == True:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            if isinstance(self.sea_level,(int,float)) == False:
                self.chData = {}
                for kper in range(0, self.nper):
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < np.max(self.sea_level):
                                if self.iboundData[0,i,j] != 0: # no-flow cells cannot be converted to specified head cells
                                    self.drain_array[i,j] = 0
                                    package[kper,i,j] = 1
                                    chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.chData[kper] = chdKper
                # ---- flopy.modflow.ModflowChd
                self.chd = flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)

        #%% Parametrization

        # Specify the unconfined conditions of the aquifer
        self.laywet = np.zeros(self.nlay) # wettable
        self.laytype = np.ones(self.nlay) # convertible

        # Necessary to give hydraulic conductivity: 3D matrix of hydraulic conductivities
                # Homogeneous or heterogeneous hydraulic conductivity
                # self.hk_value is always a 3D matrix create from hydraulic.py

        ### FUNCTION FOR GRADIENT DECAY LINKED TO DEM ELEVATION
        def compute_values(dem, dem_min, dem_max, dcal, dadj):
            # Compute boundary values
            val_min = (1/dcal)
            val_max = (1/dcal) + dadj  # Ensure positive denominator
            if val_max <0:
                val_max=1
            result = np.ones((dem.shape[0], dem.shape[1]))
            result = np.where((dem>dem_min) & (dem<dem_max),
                              (val_min + (val_max - val_min) * ((dem - dem_min) / (dem_max - dem_min))),
                              result)
            result =  np.where(dem <= dem_min, val_min, result)
            result =  np.where(dem >= dem_max, val_max, result)
            result[result<=0] = val_max
            return result

        ### Hydraulic conductivty
        self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hk_value
        # Exponential decay
        if self.hk_decay[0] != 0:
            grad_elev = self.hk_decay[3]
            if grad_elev != []:
                dem_min = grad_elev[0]
                dem_max = grad_elev[1]
                dadj = grad_elev[2]
                dcal = self.hk_decay[0]
                self.kdec_inv = compute_values(self.dem, dem_min, dem_max, dcal, dadj)
                self.kdec = 1/self.kdec_inv
            else:
                self.kdec = self.hk_decay[0]
            kmin = self.hk_decay[1]
            kmax = self.hk_value
            hklog_transf = self.hk_decay[2]
            if kmin == None:
                depth = np.zeros(self.hk.shape)
                depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
                self.hk *= np.exp(-self.kdec*depth)
                logger.debug('Decay without Kmin')
            if kmin != None:
                depth = np.zeros(self.hk.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:] # self.zbot[:-1,:,:]
                self.hk = (kmin)+((kmax)-(kmin))*np.exp(-self.kdec*depth)
                # self.hk[self.hk<kmin] = kmin
                logger.debug('Decay with Kmin')
            if (kmin != None) and (hklog_transf==True):
                depth = np.zeros(self.hk.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:] # self.zbot[:-1,:,:]
                self.hk = np.log10(kmin)+(np.log10(kmax)-np.log10(kmin))*np.exp(-self.kdec*depth)
                self.hk = 10**self.hk
                logger.debug('Decay with Kmin and log transform')
                # self.hk[self.hk<10**kmin] = 10**kmin
        # Define values for some thickness (disconnected from the vertical discretization)
        if self.verti_hk != None:
            for j in range(len(self.verti_hk)):
                logger.debug('Processing verti_hk layer j=%d', j)
                for i in range(len(self.zbot)):
                    logger.debug('Processing zbot layer i=%d', i)
                    k_val = self.verti_hk[j][0]
                    d1 = self.verti_hk[j][1][0]
                    d2 = self.verti_hk[j][1][1]
                    hk_d1 = (self.dem - d1)
                    hk_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= hk_d1) & (self.zbot[i] >= hk_d2))
                    self.hk[i][mask] = k_val
                    logger.debug('Applied k_val=%s', k_val)

        ### Specific yield
        self.sy = np.ones((self.nlay, self.nrow, self.ncol))*self.sy_value
        # Exponential decay
        if self.sy_decay[0] != 0:
            grad_elev = self.sy_decay[3]
            if grad_elev != []:
                dem_min = grad_elev[0]
                dem_max = grad_elev[1]
                dadj = grad_elev[2]
                dcal = self.sy_decay[0]
                self.sydec_inv = compute_values(self.dem, dem_min, dem_max, dcal, dadj)
                self.sydec = 1/self.sydec_inv
            else:
                self.sydec = self.sy_decay[0]
            symin = self.sy_decay[1]
            symax = self.sy_value
            sylog_transf = self.sy_decay[2]
            if symin == None:
                depth = np.zeros(self.sy.shape)
                depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
                self.sy *= np.exp(-self.sydec*depth)
            if symin != None:
                depth = np.zeros(self.sy.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:]
                self.sy = (symin)+((symax)-(symin))*np.exp(-self.sydec*depth)
                # self.sy[self.sy<symin] = symin
            if (symin != None) and (sylog_transf==True):
                depth = np.zeros(self.sy.shape)
                depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
                self.sy = np.log10(symin)+(np.log10(symax)-np.log10(symin))*np.exp(-self.sydec*depth)
                self.sy = 10**self.sy
                # self.sy[self.sy<10**symin] = 10**symin
        # Define values for some thickness (disconnected from the vertical discretization)
        if self.verti_sy != None:
            for j in range(len(self.verti_sy)):
                logger.debug('Processing verti_sy layer j=%d', j)
                for i in range(len(self.zbot)):
                    logger.debug('Processing zbot layer i=%d', i)
                    sy_val = self.verti_sy[j][0]
                    d1 = self.verti_sy[j][1][0]
                    d2 = self.verti_sy[j][1][1]
                    sy_d1 = (self.dem - d1)
                    sy_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= sy_d1) & (self.zbot[i] >= sy_d2))
                    self.sy[i][mask] = sy_val
                    logger.debug('Applied sy_val=%s', sy_val)

        ### Specific storage
        self.ss = np.ones((self.nlay, self.nrow, self.ncol))*self.ss_value
        # Exponential decay
        if self.ss_decay[0] != 0:
            grad_elev = self.ss_decay[3]
            if grad_elev != []:
                dem_min = grad_elev[0]
                dem_max = grad_elev[1]
                dadj = grad_elev[2]
                dcal = self.ss_decay[0]
                self.ssdec_inv = compute_values(self.dem, dem_min, dem_max, dcal, dadj)
                self.ssdec = 1/self.ssdec_inv
            else:
                self.ssdec = self.ss_decay[0]
            ssmin = self.ss_decay[1]
            ssmax = self.ss_value
            sslog_transf = self.ss_decay[2]
            if symin == None:
                depth = np.zeros(self.ss.shape)
                depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
                self.ss *= np.exp(-self.ssdec*depth)
            if symin != None:
                depth = np.zeros(self.ss.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:]
                self.ss = (ssmin)+((ssmax)-(ssmin))*np.exp(-self.ssdec*depth)
                # self.ss[self.ss<ssmin] = ssmin
            if (symin != None) and (sslog_transf==True):
                depth = np.zeros(self.ss.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:]
                self.ss = np.log10(ssmin)+(np.log10(ssmax)-np.log10(ssmin))*np.exp(-self.ssdec*depth)
                self.ss = 10**self.ss
                # self.ss[self.ss<10**ssmin] = 10**ssmin
        # Define values for some thickness (disconnected from the vertical discretization)
        if self.verti_ss != None:
            for j in range(len(self.verti_ss)):
                logger.debug('Processing verti_ss layer j=%d', j)
                for i in range(len(self.zbot)):
                    logger.debug('Processing zbot layer i=%d', i)
                    ss_val = self.verti_ss[j][0]
                    d1 = self.verti_ss[j][1][0]
                    d2 = self.verti_ss[j][1][1]
                    ss_d1 = (self.dem - d1)
                    ss_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= ss_d1) & (self.zbot[i] >= ss_d2))
                    self.ss[i][mask] = ss_val
                    logger.debug('Applied ss_val=%s', ss_val)

        # ---- flopy.modflow.ModflowUpw
        self.upw = flopy.modflow.ModflowUpw(self.mf,
                                            laytyp=self.laytype,
                                            laywet=self.laywet,
                                            hk=self.hk,
                                            sy=self.sy,
                                            ss=self.ss,
                                            vka=self.vka,
                                            iphdry=1,
                                            hdry=-100,
                                            layvka=1, # 1: anisotropy ratio, 0: vertical hk in model unit
                                            extension='upw',
                                            unitnumber=None, # unitnumber=31
                                            noparcheck=False
                                            )

        #%% Source terms

        # Activated only when recharge values are negative (king of pumping)
        if isinstance(self.recharge,(dict))==False:
            if isinstance(self.recharge,float)==False and (self.recharge < 0).any().any() == True:
                self.evt = self.recharge.copy()
                # All positive values are set to 0 (no negative values)
                self.evt[self.evt>=0] = 0
                # All negative values are set to positive values
                self.evt = abs(self.evt)
                self.evtData = {}
                # Loop over all time steps to make a dictionnary from a scalar or a dictionnary
                for kper in range(0, self.nper):
                    if isinstance(self.evt,(int,float)):
                        # Steady state:
                        self.evtData[kper] = self.evt
                    else:
                        # Transient state:
                        if kper == 0:
                            self.evtData[kper] = 0
                        else:
                            self.evtData[kper] = self.evt[kper]
                # ---- flopy.modflow.ModflowEvt
                self.evt = flopy.modflow.ModflowEvt(self.mf,
                                                    evtr=self.evtData,
                                                    surf = self.dem,
                                                    nevtop = 3, # 1 (top), 2 (layer), 3 (highest active) is default
                                                    exdp = self.exdp, # default is 1 (1m from surface)
                                                    ievt = 1, # default: 1 (if layer) ==> activated only if nevtop = 2
                                                    ipakcb = 1 # default: 0
                                                    )
                # Finally sets all negative of self.recharge to zero values for simulation
                if not isinstance(self.recharge,(int,float)):
                    self.recharge[self.recharge<0] = 0

        # Recharge of the aquifer on the top of the water table
        self.rchData = {}
        for kper in range(0, self.nper):
            if isinstance(self.recharge,(dict))==True:
                if self.sim_state == 'steady':
                    self.rchData = (sum(self.recharge.values()) / len(self.recharge))
                if self.sim_state == 'transient':
                    self.rchData = self.recharge
            else:
                if isinstance(self.recharge,(int,float)):
                    # Only value in self.climatic (steady)
                    self.rchData[kper] = self.recharge
                else:
                    if kper == 0:
                        if self.first_clim == 'mean':
                            self.rchData[kper] = np.nanmean(self.recharge)
                        if self.first_clim == 'first':
                            self.rchData[kper] = self.recharge.iloc[0]
                        if isinstance(self.first_clim,(int,float)):
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

        #%% Drain package

        # DRN is applied to all the surface of the model: enables seepage on the top layer

        self.drnData = np.zeros((int(np.sum(self.drain_array)), 5))
        compt = 0
        self.drnData[:, 0] = 0 # First value (0): layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                if self.drain_array[i,j] == 1:
                    self.drnData[compt, 1] = i # Second value (1): row number
                    self.drnData[compt, 2] = j # Third value (2): column number
                    self.drnData[compt, 3]= self.dem[i, j] # Fourth value (3): altitude
                    # Fifth value (4): value of the conductivity of the drain (integrated over the surface of the cell)
                    if self.sink_fill == False:
                        if self.cond_drain != None:
                            self.drnData[compt, 4] = self.cond_drain
                        else:
                            self.drnData[compt, 4] = (self.hk[0, i, j] * self.resolution** 2)
                    else:
                        if self.sink[i,j]>0:
                            self.drnData[compt, 4] = 0
                        else:
                            if self.cond_drain != None:
                                self.drnData[compt, 4] = self.cond_drain
                            else:
                                self.drnData[compt, 4] = self.hk[0, i, j] * self.resolution** 2
                    compt += 1

        # Imposes DRN condition to Modflow through flopy
        lrcec= {0:self.drnData}
        # ---- flopy.modflow.ModflowDrn
        self.drn = flopy.modflow.ModflowDrn(self.mf, stress_period_data=lrcec)

        #%% Well package

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
            self.wel = flopy.modflow.ModflowWel(self.mf,
                                                ipakcb=1,
                                                stress_period_data=self.lrcq)

        #%% Output control

        stress_period_data = {}
        for kper in range(self.nper):
            kstp = self.nstp[kper]
            # Saves head (hds) and budget (cbc) for each of the stress periods
            stress_period_data[(kper, kstp-1)] = ['save head', 'save budget']
        # ---- flopy.modflow.ModflowOc
        self.oc = flopy.modflow.ModflowOc(self.mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                unitnumber=None, # unitnumber=[14, 51, 52, 53, 0],
                                compact=True)
        self.oc.reset_budgetunit(fname= self.model_name+'.cbc')

        # Check grid
        def check_water_flow_connectivity(grid):
            layers, rows, cols = grid.shape
            problematic_cells = []  # Store problematic cells

            for z in range(layers - 1):  # Focus on flow between layers
                logger.debug('Checking layer %d', z)
                for y in range(rows):
                    for x in range(cols):
                        # Skip if the current cell is inactive (e.g., NaN or specific inactive value)
                        if np.isnan(grid[z, y, x]) or np.isnan(grid[z+1, y, x]):
                            continue

                        # Current cell's top and bottom elevations
                        current_top = grid[z, y, x]
                        current_bottom = grid[z+1, y, x]

                        neighbors = []

                        # Collect adjacent neighbors' top and bottom elevations
                        if y > 0 and not (np.isnan(grid[z, y-1, x]) or np.isnan(grid[z+1, y-1, x])):  # Left neighbor
                            neighbors.append((grid[z, y-1, x], grid[z+1, y-1, x]))
                        if y < rows - 1 and not (np.isnan(grid[z, y+1, x]) or np.isnan(grid[z+1, y+1, x])):  # Right neighbor
                            neighbors.append((grid[z, y+1, x], grid[z+1, y+1, x]))
                        if x > 0 and not (np.isnan(grid[z, y, x-1]) or np.isnan(grid[z+1, y, x-1])):  # Front neighbor
                            neighbors.append((grid[z, y, x-1], grid[z+1, y, x-1]))
                        if x < cols - 1 and not (np.isnan(grid[z, y, x+1]) or np.isnan(grid[z+1, y, x+1])):  # Back neighbor
                            neighbors.append((grid[z, y, x+1], grid[z+1, y, x+1]))

                        # If there are neighbors, check if water can flow
                        if neighbors:
                            can_flow = False
                            for neighbor_top, neighbor_bottom in neighbors:
                                # Check if current cell's range overlaps with neighbor's range
                                if (current_bottom <= neighbor_top and current_top >= neighbor_bottom):
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

            fig, axs = plt.subplots(1, 2, figsize=(14,4), dpi=300)
            axs = axs.ravel()

            grid_model = self.mf.modelgrid

            modelxsect1 = flopy.plot.PlotCrossSection(model=self.mf, line={'Row': int((grid_model.shape[1])/2)})
            imhk = modelxsect1.plot_array(self.hk/24/3600, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[0],
                                          # norm=mpl.colors.LogNorm(vmin=self.hk.min(), vmax=self.hk.max())
                                          norm=mpl.colors.LogNorm(vmin=1e-10, vmax=1e-1)
                                          )
            # modelxsect1.plot_grid(ax=axs[0])
            axs[0].set_title('West-East (Row), K [m/s]', fontsize=12)
            if self.cross_ylim == []:
                axs[0].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                                np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
            else:
                axs[0].set_ylim(self.cross_ylim[0], self.cross_ylim[1])
            axs[0].set_xlabel('Distance [m]')
            axs[0].set_ylabel('Elevation [m]')
            # divider = make_axes_locatable(axs[0])
            # cax = divider.append_axes('right', size='5%', pad=0.05)
            # fig.colorbar(imhk, cax=cax, orientation='vertical')
            fig.colorbar(imhk)

            modelxsect2 = flopy.plot.PlotCrossSection(model=self.mf, line={'Column': int((grid_model.shape[2])/2)})
            imsy = modelxsect2.plot_array(self.sy*100, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[1],
                                          # norm=mpl.colors.LogNorm(vmin=self.sy.min(), vmax=self.sy.max())
                                          norm=mpl.colors.LogNorm(vmin=0.1, vmax=100)
                                          )
            # modelxsect2.plot_grid(ax=axs[1])
            axs[1].set_title('North-South (Column), Sy [%]', fontsize=12)
            if self.cross_ylim == []:
                axs[1].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                                np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
            else:
                axs[1].set_ylim(self.cross_ylim[0], self.cross_ylim[1])
            axs[1].set_xlabel('Distance [m]')
            axs[1].set_ylabel('Elevation [m]')
            # divider = make_axes_locatable(axs[1])
            # cax = divider.append_axes('right', size='5%', pad=0.05)
            # fig.colorbar(imsy, cax=cax, orientation='vertical')
            fig.colorbar(imsy)

            fig.suptitle(self.model_name.upper(), y=1.0, fontsize=10)
            fig.tight_layout()

    #%% PROCESSING

    def processing(self,
                   write_model:bool=True,
                   run_model:bool=False,
                   link_mt3dms:bool=False):
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
            lmt = flopy.modflow.ModflowLmt(self.mf,
                                           output_file_name='mt3d_link.ftl',
                                           extension='lmt8', output_file_format='unformatted', unitnumber=None) # unitnumber=30 (Luca)

        # Create modflow files
        if write_model == True:
            # Write input files
            self.mf.write_input()

        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mf.run_model(silent=not verbose) # True without msg

        return success_model

    #%% POST-PROCESSING

    def post_processing(self, model_modflow:object,
                        watertable_elevation:bool=True,
                        watertable_depth:bool=True,
                        seepage_areas:bool=True,
                        outflow_drain:bool=True,
                        groundwater_flux:bool=True,
                        groundwater_storage:bool=True,
                        accumulation_flux:bool=True,
                        persistency_index:bool=False,
                        intermittency_yearly:bool=False,
                        intermittency_monthly:bool=False,
                        intermittency_weekly:bool=False,
                        intermittency_daily:bool=False,
                        export_all_tif:bool=False):
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
        self.save_file = os.path.join(self.full_path, '_postprocess')
        toolbox.create_folder(self.save_file)

        self.figure_file = os.path.join(self.full_path, '_postprocess', '_figures')
        toolbox.create_folder(self.figure_file)

        self.temporary_file = os.path.join(self.full_path, '_postprocess','_temporary')
        toolbox.create_folder(self.temporary_file)

        self.tifs_file = os.path.join(self.full_path, '_postprocess', '_rasters')
        toolbox.create_folder(self.tifs_file)

        self.save_fig = os.path.join(self.model_folder, '_figures')
        toolbox.create_folder(self.save_fig)

        #%% Load essential data

        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name)

        # Files have been output in the processing phase and are re-read here
        self.dem_mask = (self.dem<-9999)
        # heads
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds')
        # fluxes
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')

        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkpers = self.head_fpu.get_kstpkper()

        # Params model
        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1)
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1

        #%% Export results over times

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

        logger.debug('Post-processing MODFLOW: %s', self.model_name)

        # Loop over times: fills each of the previous structures and create raster
        for item, time in enumerate(self.times):
            logger.info('Post-processing stress period %d/%d', item + 1, len(self.times))

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
            self.head = self.head_fpu.get_data(totim=time)  # self.head_all = self.head_fpu.get_alldata(), self.head_all[item][0]
            if self.nlay == 1:
                self.head_data = self.head[0]
            else:
                ### Option 1
                self.head_data = pp.get_water_table(self.head, -100) # -9999
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
                output_path = self.tifs_file+'/watertable_elevation_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_elev, output_path, -9999)
                self.dict_watertable_elevation[item] = self.wt_elev

            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = self.dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                output_path = self.tifs_file+'/watertable_depth_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_depth, output_path, -9999)
                self.dict_watertable_depth[item] = self.wt_depth

            if seepage_areas == True:
                ### Seepage areas
                self.seep_area = self.dem - self.wt_elev.copy()
                self.seep_area[self.seep_area >= 0] = 0
                self.seep_area[self.seep_area < 0] = 1
                self.seep_area[self.dem_mask] = -9999
                output_path = self.tifs_file+'/seepage_areas_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.seep_area, output_path, -9999)
                self.dict_seepage_areas[item] = self.seep_area

            if outflow_drain == True:
                ### Outflow drain
                self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
                self.out_all = np.zeros((1, self.dis.nrow, self.dis.ncol))
                sim = 0
                count = 0
                for i in range(0, self.dis.nrow):
                    for j in range(0, self.dis.ncol):
                      if self.drain_array[i,j] == 1:
                        self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                        count = count + 1
                self.out_drn = self.out_all[0]
                self.out_drn[self.dem_mask] = -9999
                output_path = self.tifs_file+'/outflow_drain_t('+lead_numb+').tif'
                if accumulation_flux==True:
                    toolbox.export_tif(self.dem_watershed_path, self.out_drn, output_path, -9999)
                else:
                    if export_tif==True:
                        toolbox.export_tif(self.dem_watershed_path, self.out_drn, output_path, -9999)
                self.dict_outflow_drain[item] = self.out_drn

            if groundwater_flux == True:
                ### Groundwater flux
                self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
                self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
                self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
                if self.nlay == 1:
                    self.flux = np.sqrt(self.frf**2 + self.fff**2)
                if self.nlay > 1:
                    self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
                    self.flux = np.sqrt(self.frf**2 + self.fff**2 + self.flf**2)
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.flux_top, output_path, -9999)
                self.dict_groundwater_flux[item] = self.flux_top

            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                self.wt_sto = ( self.wt_sto - self.zbot[-1] ) * (self.resolution**2) * np.nanmean(self.sy)
                output_path = self.tifs_file+'/groundwater_storage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_sto, output_path, -9999)
                self.dict_groundwater_storage[item] = self.wt_sto

            if accumulation_flux == True:
                ### Accumulation flux
                accumulated_flow = masstransfer.Masstransfer(self.geographic,
                                                             'outflow_drain_t('+lead_numb+').tif',
                                                             'tracept_t('+lead_numb+').shp',
                                                             'accumulation_flux_t('+lead_numb+').tif',
                                                             extraction_folder=self.save_file)
                accumulated_flow.trace_cumulated()
                output_path = self.tifs_file+'/accumulation_flux_t('+lead_numb+').tif'
                with rasterio.open(output_path) as src:
                    self.dict_accumulation_flux[item] = src.read(1)

        ### Save dictionaries to npy
        if watertable_elevation == True:
            logger.info('Exporting watertable elevation time series')
            np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
        if watertable_depth == True:
            logger.info('Exporting watertable depth time series')
            np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
        if seepage_areas == True:
            logger.info('Exporting seepage areas time series')
            np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
        if outflow_drain == True:
            logger.info('Exporting outflow drain time series')
            np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
        if groundwater_flux == True:
            logger.info('Exporting groundwater flux time series')
            np.save(self.save_file+'/groundwater_flux', self.dict_groundwater_flux)
        if groundwater_storage == True:
            logger.info('Exporting groundwater storage time series')
            np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        if accumulation_flux == True:
            logger.info('Exporting accumulation flux time series')
            np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)

        if persistency_index == True:
            ### Persistency index
            logger.info('Exporting persistency index maps')
            acc_npy_raw = np.load(os.path.join(self.save_file,'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            for key in range(len(acc_npy)):
                with rasterio.open(self.geographic.watershed_box_buff_dem) as src:
                    mask = src.read(1)
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            pi_export = days_flux.copy()
            self.pi = np.ma.masked_where(days_flux <= 0, days_flux)
            self.dict_persistency_index[0] = self.pi
            pi_export[days_flux <= 0] = -9999
            pi_export[mask<=0] = -9999
            output_path = self.tifs_file+'/persistency_index_t('+'-'+').tif'
            toolbox.export_tif(self.dem_watershed_path, pi_export, output_path, -9999)

            np.save(self.save_file+'/persistency_index', self.dict_persistency_index)

        if intermittency_daily == True:
            ### Intermittency daily
            logger.info('Exporting daily intermittency maps')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=365:
                inf = 0
                sup = 365
                step = int(round(len(acc_npy_raw)/365))
                compt=0
                for i in range(step):
                    logger.debug('Processing daily intermittency t: %d / %d', i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<365] = 0
                        tempo[days_flux==365] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_daily_t('+str(compt)+').tif'
                        # if export_tif==True:
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1
                    inf+=365
                    sup+=365
            np.save(self.save_file+'/intermittency_daily', self.dict_intermittency_daily)

        if intermittency_weekly == True:
            logger.info('Exporting weekly intermittency maps')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=52:
                inf = 0
                sup = 52
                step = int(round(len(acc_npy_raw)/52))
                compt=0
                for i in range(step):
                    logger.debug('Processing weekly intermittency t: %d / %d', i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<52] = 0
                        tempo[days_flux==52] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_weekly_t('+str(compt)+').tif'
                        # if export_tif==True:
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1
                    inf+=52
                    sup+=52
            np.save(self.save_file+'/intermittency_weekly', self.dict_intermittency_weekly)

        if intermittency_monthly == True:
            ### Intermittency monthly
            logger.info('Exporting monthly intermittency maps')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=12:
                inf = 0
                sup = 12
                step = int(round(len(acc_npy_raw)/12))
                compt=0
                for i in range(step):
                    logger.debug('Processing monthly intermittency t: %d / %d', i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<12] = 0
                        tempo[days_flux==12] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_monthly_t('+str(compt)+').tif'
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1
                    inf+=12
                    sup+=12
            np.save(self.save_file+'/intermittency_monthly', self.dict_intermittency_monthly)

        if intermittency_yearly == True:
            ### Intermittency monthly
            logger.info('Exporting yearly intermittency maps')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=1:
                inf = 0
                sup = 1
                step = int(round(len(acc_npy_raw)/1))
                compt=0
                for i in range(step):
                    logger.debug('Processing yearly intermittency t: %d / %d', i, step)
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        with rasterio.open(self.geographic.watershed_dem) as src:
                            mask = src.read(1)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                    zero = acc_npy_raw[0] * 0
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<1] = 0
                        tempo[days_flux==1] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_yearly_t('+str(compt)+').tif'
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1
                    inf+=12
                    sup+=12
            np.save(self.save_file+'/intermittency_yearly', self.dict_intermittency_monthly)

#%% NOTES
