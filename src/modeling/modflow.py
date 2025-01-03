# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import xarray as xr
xr.set_options(keep_attrs = True)
import sys
import imageio                           # Import raster to numpy matrix (not georeferenced but handy)
from os.path import dirname, abspath
import matplotlib.pyplot as plt
import flopy.utils.binaryfile as fpu
from flopy.utils.sfroutputfile import SfrFile

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from tools import toolbox
from modeling import downslope

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
                 plot_cross: bool=True, 
                 # Climatic settings
                 climatic=0.001, runoff=0.001/10, first_clim: str='mean', split_temp: bool=False,
                 # Hydraulic settings
                 nlay: int=1, lay_decay: float=1.,
                 bottom: float=None, thick: float=100.,
                 verti_cond=None, verti_poro=None, verti_ss=None,
                 hyd_cond=0.0864, porosity: float=0.1, ss: float=1e-5,
                 cond_decay: float=0., poro_decay: float=0., ss_decay: float=0.,
                 vka: float=1.0,
                 # Boundary settings
                 cond_drain: float=None, sea_level=None, bc_left: float=None, bc_right: float=None,
                 streamflow_seepage:object=None, inputflow=None, lakeres:object=None):
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
            if True, display a cross section of the model. The default is True.
        climatic : float or list, optional
            recharge value. The default is 0.001.
        runoff : float or list, optional
            runoff value. The default is 0.0001.
        first_clim : str, optional
            'mean': the first recharge value is the mean of the chronicle. 'first': the first recharge is keep. The default is 'mean'.
        nlay : int, optional
            Number of layer. The default is 1.
        lay_decay : float, optional
            Modification of layer thickness for exponentially decreasing whit depth. The default is 1..
        bottom : float, optional
            Fixe a flat boundary at the bottom of the model. The default is None.
        thick : float, optional
            Fixe the tickness of the model. The default is 100..
        hyd_cond : float or 2D float 
            Fixe the hydraulic conductivity value. default is 0.0864.
        cond_decay : float, optional
            Modification of hydraulic conductivity for exponentially decreasing whit depth. The default is 0..
        verti_cond : list, optional
            Depth-dependent hydraulic conductivity. The default is None.
        verti_poro : list, optional
            Depth-dependent porosity. The default is None.
        cond_drain : float, optional
            Fixe the conductance value of the drainage package. The default is None.
        porosity : float or 2D float, optional
            Fixe the porosity value. The default is 0.1.
        ss : float or 2D float, optional
            Fixe the specifc storage value. Activate for confined layers. The default is 1e-5 (1/day).
        poro_decay : float, optional
            Modification of porosity (specific yield) for exponentially decreasing whit depth. The default is 0.
        ss_decay : float, optional
            Modification of porosity (specific storage) for exponentially decreasing whit depth. The default is 0.
        sea_level : float, optional
            Fixed head on each cell below this value. The default is None.
        bc_left : float, optional
            Fixed head on the left border of the domain. The default is None.
        bc_right : float, optional
            Fixed head on the right border of the domain. The default is None.
        streamflow_seepage : object, optional
            Object streamflow_seepage built by HydroModPy.
            Replace the module DRN with the module SFR for modeling the seepage.
            The default is None.
        inputflow : optional
            Boundary flow injected in the system
        lakeres : object, optional
            Object lakeres built by HydroModPy.
            The default is None.
        use_lakeres : bool, optional
            Flag whether the system includes at least one lake/reservoir or not
        aquifer_top_layer : int
            Aquifer top layer identifiyer
        init:
            0
        """
        
        #%% Initialization
        
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
        self.sim_state = sim_state
        self.plot_cross = plot_cross
        
        #%% Boundary conditions
        
        self.bc_left = bc_left
        self.bc_right = bc_right
        self.sea_level = sea_level 
        self.inputflow = inputflow
        
        #%% Domain definition 
        
        self.box = box
        self.sink_fill = sink_fill
        self.geographic = geographic
        self.resolution = geographic.resolution
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        try : 
            self.sink = geographic.depressions_data
        except:
            pass
        # Enlarges the modeled domain
        if box == True:
            self.dem = geographic.dem_box_data  
            self.dem_watershed_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_watershed_path = geographic.watershed_buff_dem
        self.dem[self.dem<=-9999] = -9999
        self.dem[self.dem>=9999] = -9999
        try:
            if self.sea_level == None:
                self.dem[(self.dem<0)&(self.dem>-200)] = 0
        except:
            pass
        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]
    
        #%% Source/Sink terms
        
        if isinstance(climatic, float) == False :  
            self.climatic = climatic.copy()
        else: 
            self.climatic = climatic
        self.first_clim = first_clim  
        self.runoff = runoff
        self.split_temp = split_temp
            
        #%% Model parameters 
        
        self.nlay = nlay
        self.lay_decay = lay_decay
        self.bottom = bottom
        self.thick = thick
        
        self.hyd_cond = hyd_cond
        self.cond_decay = cond_decay
        self.porosity = porosity
        self.ss = ss
        self.poro_decay = poro_decay
        self.ss_decay = ss_decay
        self.vka = vka
        
        self.verti_cond = verti_cond
        self.verti_poro = verti_poro
        self.verti_ss = verti_ss
        self.cond_drain = cond_drain
        
        #%% Seepage modeled with StreamFlow Routing instead of Drain
        
        self.streamflow_seepage = streamflow_seepage
        
        #%% Lakes/reservoirs
        
        self.lakeres = lakeres
        
        if self.lakeres and self.lakeres.n_lakeres > 0:
            self.use_lakeres = True
            self.aquifer_top_layer = 1
        else:
            self.use_lakeres = False
            self.aquifer_top_layer = 0
        
        #%% Specific modifications
        
        # Preprocess conductivity values 
        #ALEXANDRE
        try:
            # For heterogeneous cases of hydraulic conducitivy, inactivation of part of the dem 
            # Should still be checked: is it still used? Remove? 
            if len(self.hyd_cond)!=1:
                self.dem[self.hyd_cond<0]=-9999
        except:
            pass

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
        self.mf = flopy.modflow.Modflow(self.model_name, 
                                        exe_name=self.exe,
                                        version='mfnwt',
                                        listunit=2,
                                        verbose=False,
                                        model_ws=self.full_path) # external_path=self.full_path
        
        # Uses Nwt for Modflow 2005, necessary for unconfined aquifers (improved interactions between surface and aquifer)
        # Sets up numerical parameters 
        self.thickfact = 1e-05 # also used for lake/reservoir thickness computations
        
        self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                            thickfact=self.thickfact, linmeth=1, iprnwt=1, ibotav=1,
                                            options='COMPLEX', Continue=False, backflag=0) # ibotav=0
        # Change headtol and fluxtol with results ==> convergency criteria

        #%% Discretization
        
        ### Time step is driven by recharge
        
        if self.sim_state == 'steady': # if isinstance(self.climatic,(int,float))==True
            # Steady state
            self.nper = 1               # Number of forcing periods (recharge)
            self.perlen = 1             # Length of period
            self.nstp = [1]             # Steps in a given period (not used here)
            self.steady = True          # Steady state
            self.start_datetime = None
            
        if self.sim_state == 'transient':
            # Transient state
            if isinstance(self.climatic,(dict))==True:
                self.start_datetime = 0 
            else:
                self.start_datetime = self.climatic.index[0]            # First date of climatic recharge
                # To cooridate with forcing and/or climatic
                """
                if type(self.climatic.index)==pd.core.indexes.datetimes.DatetimeIndex:
                    if pd.infer_freq(self.climatic.index) != 'D':
                        for i in range(1,len(self.climatic)):      
                            dif = self.climatic.index[i]-self.climatic.index[i-1]
                            self.perlen[i] = dif.days
                """
            self.steady = np.zeros(len(self.climatic),dtype=bool)   # Vector of booleans (transient state at each time step)
            self.steady[0] = True       # Steady state for the first time step (initialization of head values by a steady state)
            self.nstp = np.ones(len(self.climatic))     # One step per time step
            self.nper = len(self.climatic)
            # Definition of period duration (forcing is constant on a period)
            #       As many periods as recharge values 
            #       Extracts from climatic data the time steps (self.perlen)
            
            if self.split_temp == True:
                ### DISCUSS WITH ALEXANDREFOR THIS PART
                if isinstance(self.climatic, pd.core.series.Series):
                    if isinstance(self.climatic.index[0], datetime.datetime):
                        # self.perlen = self.climatic.index.to_series().diff().dt.days.values
                        self.perlen = self.climatic.index.to_series().diff().dt.total_seconds().values/86400 # values converted into float days
                    else:
                        self.perlen = self.climatic.index.to_series().diff().values
            if isinstance(self.split_temp, list) == True:
                self.perlen = self.split_temp
            if self.split_temp == False:
                self.perlen = np.ones(len(self.climatic))
            # print(self.split_temp)
            # First timestep is steady state:
            self.perlen[0] = 1
                        
        ### Model Domain definition and discretization 
                
        # Bottom definition for each of the layers 
        self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
        if self.bottom is None:
            self.bottom_layer = self.dem - self.thick    # Matrix for constant thickness case
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
        
        # Definition of top (when there are lakes, top != dem)
        self.top = self.dem
        
        # Adding a superficial layer for lakes/reservoirs (if used)
        if self.use_lakeres:
            stages, lakarr_lay0, laklay_top, bdlknc_lay0, flux_data, self.dem = self.lakeres.format_to_modflow(
                self.geographic, self.climatic, self.nper, self.thickfact, self.dem, self.dem_watershed_path)
            
            self.nlay = self.nlay + 1
            self.top = laklay_top
            self.zbot = np.insert(self.zbot, 0, self.dem, axis=0)
            
            lakarr = np.zeros((self.nlay, self.nrow, self.ncol))
            lakarr[0] = lakarr_lay0
            
            bdlknc = np.zeros((self.nlay, self.nrow, self.ncol))
            bdlknc[0] = bdlknc_lay0
        
        # Imposes discretization to modflow model through flopy
        self.dis = flopy.modflow.ModflowDis(self.mf, itmuni=0, lenuni=2,
                                            nlay=self.nlay, nrow=self.nrow, ncol=self.ncol, 
                                            delr=self.resolution, delc=self.resolution,
                                            top=self.top, botm=self.zbot, xul=self.xul, yul=self.yul,
                                            nper=self.nper, perlen=self.perlen, nstp=self.nstp,
                                            steady=self.steady, start_datetime=self.start_datetime) 
                                            # itmuni = 0 ==> undefined
                                            # itmuni_values = {'days': 4, 'hours': 3, 'minutes': 2, 'seconds': 1, 'undefined': 0, 'years': 5}
        # proj4_str=self.dem.crs)
    
        #%% Boundary conditions
        
        ### Constant Head boundary conditions of No Flow (sides of domain)
        
        # iboundData=1: Should compute head in cells 
        # iboundData=0: Nothing is calculated in celles (should not be really used)
        # iboundData=-1: Values imposed at the value of strtData
        self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
        
        # Correct ibound in the lake/reservoir layer (1st layer)
        if self.use_lakeres:
            self.iboundData[0, :, :] = 0
        
        # Free surface level is set to the surface (altitude of DEM)
        self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem   
        
        # SYNTHETIC CASE: FIXED HEAD ON THE LEFT BORDER (square domain), no longer actively used
        if  isinstance(self.bc_left,(int,float)) == True: ### BE CAREFUL !
           self.iboundData[:,:,0] = -1                      
           self.strtData[:,:,0] = self.bc_left
       
        # SYNTHETIC CASE: FIXED HEAD ON THE RIGHT BORDER (square domain), no longer actively used
        if  isinstance(self.bc_right,(int,float)) == True: ### BE CAREFUL !
           self.iboundData[:,:,-1] = -1
           self.strtData[:,:,-1] = self.bc_right
           
        # NO FLOW BOUNDARY CONDITIONS 
        for i in range (self.nlay):
            if isinstance(self.sea_level,(int,float)) == True:
                # print('niv0')
                self.iboundData[i][self.dem <= self.sea_level] = -1
                self.strtData[self.iboundData == -1] = self.sea_level
            self.iboundData[i][self.dem < -1000] = 0     # O is for NO FLOW               

        self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)
            
        ### Constant Head boundary conditions of No Flow (at sea level)
        
        self.drain_array = np.ones((self.nrow, self.ncol))
        if isinstance(self.sea_level, (int,float,pd.Series,list)) == True: # Martin on 15/11/2022: before was: if self.sea_level != None:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            # print('niv1')
            if isinstance(self.sea_level,(int,float)) == False:
                # print('niv2')
                self.chData = {} #Martin on 15/11/2022: before was: self.chdData = {}
                for kper in range(0, self.nper):
                    # print(kper)
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < np.max(self.sea_level):
                                if self.iboundData[self.aquifer_top_layer,i,j] != 0: #no-flow cells cannot be converted to specified head cells
                                    self.drain_array[i,j] = 0
                                    package[kper,i,j] = 1
                                    chdKper.append([self.aquifer_top_layer,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.chData[kper] = chdKper #Martin on 15/11/2022: before was: self.rchData[kper] = chdKper
                            
                flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)
                    
        #%% Parametrization
        
        # lpf package
        self.laywet = np.zeros(self.nlay)
        self.laytype = np.ones(self.nlay)

        # Necessary to give hydraulic conductivity: 3D matrix of hydraulic conductivities
        # Homogeneous or heterogeneous hydraulic conductivity 
        # self.hyd_cond is either a scalar (for homogeneous cases) or a 2D array (for heterogeneous cases)
        # print(self.nlay, self.nrow, self.ncol)
        # print(self.hyd_cond)
        # print(self.hyd_cond.shape)        
        self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hyd_cond
        
        if self.cond_decay != 0.:
            # print('DECAY EXPO CONDH')
            depth = np.zeros(self.hk.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.hk *= np.exp(-self.cond_decay*depth)
        
        self.ps = np.ones((self.nlay, self.nrow, self.ncol))*self.porosity
        self.ss = np.ones((self.nlay, self.nrow, self.ncol))*self.ss
            
        if self.poro_decay != 0.:
            # print('DECAY EXPO POROSITY')
            depth = np.zeros(self.ps.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.ps *= np.exp(-(self.poro_decay)*depth)
            # η=2 is a coefficient related to
            # the medium structure that we chose to be equal to 2, as com-
            # monly reported in the literature (Cardenas and Jiang, 2010;
            # Bernabé et al., 2003)

        if self.ss_decay != 0.:
            # print('DECAY EXPO POROSITY')
            depth = np.zeros(self.ps.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.ss *= np.exp(-(self.ss_decay)*depth)
            # η=2 is a coefficient related to
            # the medium structure that we chose to be equal to 2, as com-
            # monly reported in the literature (Cardenas and Jiang, 2010;
            # Bernabé et al., 2003)
            
        # Depth-dependent hydraulic conductivity (disconnected from the vertical discretization)
        if self.verti_cond != None:
            for j in range(len(self.verti_cond)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    k_val = self.verti_cond[j][0]
                    d1 = self.verti_cond[j][1][0]
                    d2 = self.verti_cond[j][1][1]
                    cond_d1 = (self.dem - d1)
                    cond_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= cond_d1) & (self.zbot[i] >= cond_d2))
                    self.hk[i][mask] = k_val
                    # print(k_val)
        
        # Depth-dependent porosity (disconnected from the vertical discretization)
        if self.verti_poro != None:
            for j in range(len(self.verti_poro)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    sy_val = self.verti_poro[j][0]
                    d1 = self.verti_poro[j][1][0]
                    d2 = self.verti_poro[j][1][1]
                    poro_d1 = (self.dem - d1)
                    poro_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= poro_d1) & (self.zbot[i] >= poro_d2))
                    self.ps[i][mask] = sy_val
                    # print(k_val)
                
            for j in range(len(self.verti_ss)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    ss_val = self.verti_ss[j][0]
                    d1 = self.verti_ss[j][1][0]
                    d2 = self.verti_ss[j][1][1]
                    ss_d1 = (self.dem - d1)
                    ss_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= ss_d1) & (self.zbot[i] >= ss_d2))
                    self.ss[i][mask] = ss_val
                    # print(k_val)   
        
        # Lateral heterogeneity of hk ?
        # for i in range(0,len(self.number_structure)):
        #     for j in range(0,nlay):
        #         self.hk[j][self.structure.geology==self.number_structure[i]]= logParamValue[i]*3600*24
        
        self.upw = flopy.modflow.ModflowUpw(self.mf, 
                                            laytyp=self.laytype, laywet=self.laywet, 
                                            hk=self.hk, sy=self.ps,
                                            ss=self.ss,
                                            iphdry=1, hdry=-100, vka=self.vka, noparcheck=False,
                                            layvka=1, # because 1, it is the anisotropy ratio
                                            extension='upw',
                                            # unitnumber=31
                                            unitnumber=None
                                            )
        # layvka: a flag for each layer that indicates whether variable VKA is vertical hydraulic conductivity or the ratio of horizontal to vertical hydraulic conductivity
        #   0—indicates VKA is vertical hydraulic conductivity
        #   not 0—indicates VKA is the ratio of horizontal to vertical hydraulic conductivity, where the horizontal hydraulic conductivity is specified as HK in item 9.
        # vka (float or array of floats (nlay, nrow, ncol)): vertical hydraulic conductivity or the ratio of horizontal to vertical hydraulic conductivity depending on the value of LAYVKA. (default is 1.0).
        
        #%% Source terms (other than artificial filling/pumping of lakes/reservoirs)
        
        ### Source term & initial conditions: recharge (and evapotranspiration) on the top of the model 
        
        # EVAPOTRANSPIRATION FROM THE AQUIFER
            # from the watertable: evt package (from negative value, should always be positive)
        if isinstance(self.climatic,(dict))==False:
            if isinstance(self.climatic,float)==False and (self.climatic < 0).any().any() == True:
                # self.climatic : recharge values (float in steady state or chronicles in transient state)
                # Modifies ETP values (self.climatic): from negative to positive values (sink term)
                #      package evt requires positive values (negative values are not allowed)
                self.evt = self.climatic.copy() 
                # All positive values are set to 0 (no negative values)
                self.evt[self.evt>=0] = 0
                # All negative values are set to positive values
                self.evt = abs(self.evt)
                # Remove aquifer evaporation on lakes/reservoirs
                if self.use_lakeres:
                    self.evt[lakarr_lay0 > 0] = 0
                    self.climatic[lakarr_lay0 > 0] = 0
# Extract ETR on the lake
# =============================================================================
#                 for id_lakeres in range(0, len(self.lakeresData)): 
#                     self.evt_lakeres[id_lakeres] = self.evt[
#                         self.lakeresData[id_lakeres]['mask_largest']
#                         ].mean()
#                     # mean because LAKE package needs rates per unit area
#                     self.evt[self.lakeresData[id_lakeres]['mask_largest']] = 0
# =============================================================================
# Remove recharge on the lake
# =============================================================================
#         for lake_id in self.lakeres.indexes: 
#             self.rch_lakeres[lake_id] = self.climatic[
#                 self.lakeres.masks[lake_id]
#                 ].sum()
#             self.climatic[self.lakeres.masks[lake_id]] = 0
#             # Usefull to store the value, in order to compare to dam leakage
# =============================================================================
                self.evtData = {}
                # Loop over all time steps to make a dictionnary from a scalar or a dictionnary
                for kper in range(0, self.nper):
                    if isinstance(self.evt,(int,float)):
                        # If integer or float, do it only once (steady state)
                        self.evtData[kper] = self.evt
                    else:
                        # Transient state: 
                        if kper == 0:
                            # self.evtData[kper] = np.nanmean(self.evt)
                            self.evtData[kper] = 0
                        else:
                            self.evtData[kper] = self.evt[kper]
                # expd = self.thick : ETP can take water all over the aquifer thickness
                self.evt = flopy.modflow.ModflowEvt(self.mf,
                                                    evtr=self.evtData,
                                                    surf = self.dem,
                                                    nevtop = 1, # default: 1 (top), 2 (layer), 3 (highest active)
                                                    exdp = 10, # default: 1 (from surf normally)
                                                    ievt = 1, # default: 1 (if layer)
                                                    ipakcb = 1 # default: 0 
                                                    )
                # Sets all negative of self.climatic to values (they have just been accounted as pumping terms)
                if not isinstance(self.climatic,(int,float)):
                    self.climatic[self.climatic<0] = 0
                
        # RECHARGE TO THE AQUIFER
            # over the surface: rch package (should always be positive)        
        self.rchData = {}
        for kper in range(0, self.nper):
            if isinstance(self.climatic,(dict))==True:
                self.rchData = self.climatic
            else:
                if isinstance(self.climatic,(int,float)):
                    # Only value in self.climatic (steady)
                    self.rchData[kper] = self.climatic
                else:
                    if kper == 0:
                        # First value: steady (to reach equilibrium before starting the transient state of the simulation)
                        # By default mean of the climatic chronicle
                        if self.first_clim == 'mean':
                            self.rchData[kper] = np.nanmean(self.climatic)
                        if self.first_clim == 'first':
                            # First value of the cimatic chronicle
                            self.rchData[kper] = self.climatic.iloc[0]
                        if isinstance(self.first_clim,(int,float)):
                            # Imposed value (if steady state: just one value)
                            self.rchData[kper] = self.first_clim
                    else:
                        # More flexibility in the possible format of the climatic chronicles 
                        # Should only be used exceptionnaly (pandas series recommended)
                        try:
                            self.rchData[kper] = self.climatic[kper]
                        except:
                            self.rchData[kper] = self.climatic.iloc[kper].values[0]        
            
        # Sets recharge to modflow through flopy
        self.rch = flopy.modflow.ModflowRch(self.mf, rech=self.rchData)

        #%% Streamflow Routing package        
        if self.streamflow_seepage is not None:
            # ---- Main flags
            istcb2 = 81 # or 81? option for output files format
            ipakcb = 53
            
            # Not needed because nstrm > 0:
            isfropt = 0 # No infiltration beneath streams, and stream variables are
                        # read for each stress period.
            
# =============================================================================
#             isfropt = 1 # No infiltration beneath streams, and stream parameters are
#                       # only read once at the beginning of the simulation. 
#             # In that case, it is required to fill strtop	and slope in
#             # ex3_test1_reach_data.csv.
#             # Apparently also when isforpt = 0 and nstrm > 0
# =============================================================================
    
            # Deactivation of the transient routing via kinematic-wave equation:
            irtflg = 0 # if =1, nstrm should be = -nstrm
            
            # ---- Initiate the SFR_seepage module
            self.streamflow_seepage.SFR_seepage_area(self.geographic, self.dem,
                                                     self.dem_watershed_path)
            if self.use_lakeres:
                self.streamflow_seepage.compute_data(lakarr_lay0)
            else:
                self.streamflow_seepage.compute_data()
            self.streamflow_seepage.reach_data['k'] = self.aquifer_top_layer # layer
            
            # ---- Improve and correct values
            if self.streamflow_seepage.critical_mode is not None:
                self.streamflow_seepage.correct_critical_cells(self.geographic)
                
            if self.streamflow_seepage.correction_multiple_reaches == True:
                self.streamflow_seepage.remove_multiple_reaches()
            
            if self.streamflow_seepage.correction_elevations == True:
                self.dem = self.streamflow_seepage.correct_elevations(self.dem)
                
            if self.use_lakeres:
                for num_id in self.lakeres.lake_by_num_id.keys():
                    lake_id = self.lakeres.lake_by_num_id[num_id]
                    nsegs = self.streamflow_seepage.segment_data_1[
                        self.streamflow_seepage.segment_data_1.iupseg == -num_id].index
                    # Update reach_data info
                    for iseg in nsegs:
                        idx = self.streamflow_seepage.reach_data[
                            self.streamflow_seepage.reach_data.iseg == iseg].index
                        self.streamflow_seepage.reach_data.loc[
                            idx, 'strtop'] = self.lakeres.ssmx_by_lake[lake_id]
                    # Update segment_data info
                    self.streamflow_seepage.segment_data_1.loc[
                        nsegs, ['elevup', 'roughch']] = [
                            self.lakeres.ssmx_by_lake[lake_id],
                            0.03*100]

# =============================================================================
#             if self.streamflow_seepage.apply_elevations == True:
#                 self.dem = self.streamflow_seepage.apply_strtop_to_dem(self.geographic, self.dem)
# =============================================================================
    
            # ---- Convert pandas.DataFrames into numpy.recarrays
            reach_data_rec = self.streamflow_seepage.reach_data.to_records(
                index = False,
                column_dtypes = {'k': '<i8', 'i': '<i8', 'j': '<i8', 
                       'iseg': '<i8', 'ireach': '<i8', 'rchlen': '<f8', 
                       'strtop': '<f8', 'slope': '<f8'})
            
            segment_data_1_rec = self.streamflow_seepage.segment_data_1.to_records(
                index = True,
                column_dtypes = {'icalc': '<i8', 'outseg': '<i8', 
                       'iupseg': '<i8', 'nstrpts': '<i8', 'flow': '<f8', 
                       'roughch': '<f8', 'roughbk': '<f8', 'cdpth': '<f8', 
                       'fdpth': '<f8', 'awdth': '<f8', 'bwdth': '<f8', 
                       'hcond1': '<f8', 'thickm1': '<f8', 'elevup': '<f8', 
                       'width1': '<f8', 'depth1': '<f8', 'hcond2': '<f8', 
                       'thickm2': '<f8', 'elevdn': '<f8', 'width2': '<f8', 
                       'depth2': '<f8', 'runoff': '<f8'},
                index_dtypes = {'nseg': '<f8'})
            
            # ---- Convert recarrays into maps
            sfr_map, _, _, nodata = toolbox.load_to_numpy(
                self.geographic.watershed_dem, src_crs = self.geographic.crs_proj, 
                base_path = self.geographic.watershed_dem, dst_crs = self.geographic.crs_proj)
            sfr_map[sfr_map > nodata] = 0
            sfr_map_reach = sfr_map.copy()
            for _, r in self.streamflow_seepage.reach_data.iterrows():
                sfr_map[r['i'], r['j']] = r['iseg']
                sfr_map_reach[r['i'], r['j']] = r['ireach']
            elev_map = sfr_map.copy()
            hcond1_map = sfr_map.copy()
            hcond2_map = sfr_map.copy()
            for _, r in self.streamflow_seepage.reach_data.iterrows():
                elev_map[r['i'], r['j']] = r['strtop']
                hcond1_map[r['i'], r['j']] = self.streamflow_seepage.segment_data_1.loc[r['iseg'], 'hcond1']
                hcond2_map[r['i'], r['j']] = self.streamflow_seepage.segment_data_1.loc[r['iseg'], 'hcond2']
            hcond_map = (hcond1_map + hcond2_map)/2
            
            # ---- Correct drain_array (used in next section)
            self.drain_array[sfr_map > 0] = 0
            
            # ---- SFR2 function call
# =============================================================================
#             segment_data = {0: segment_data_1_rec}
# =============================================================================
            segment_data = {per: segment_data_1_rec.copy() for per in range(0, self.nper)}
            
            nstrm = len(reach_data_rec) # > 0
            nss = len(segment_data_1_rec)
            itmp = np.ones(self.nper, dtype = int) * -1 # first period input values repeated over time
            
            # Return flow (restitution)
            if self.use_lakeres:
                for num_id in self.lakeres.lake_by_num_id.keys():
                    lake_id = self.lakeres.lake_by_num_id[num_id]
                    nsegs = self.streamflow_seepage.segment_data_1[
                        self.streamflow_seepage.segment_data_1.iupseg == -num_id].index
                    if self.lakeres.rtrn_by_lake[lake_id] is not None:
                        for d in self.lakeres.rtrn_by_lake[lake_id].index:
                            per = self.climatic.index.get_loc(d)
                            runoff_prev = segment_data[per]['runoff'].copy()
                            runoff = runoff_prev.copy()
                            runoff[nsegs] = self.lakeres.rtrn_by_lake[lake_id].loc[self.climatic.index[per]]/len(nsegs) #self.lakeres.rtrn_by_lake[lake_id]/len(nsegs)
                            segment_data[per]['runoff'] = runoff_prev + runoff
                            itmp[per] = nss # time-varying inputs
            
            # Runoff
            if self.streamflow_seepage.runoff is not None:
                if isinstance(self.streamflow_seepage.runoff, (int, float)):
                    for per in range(0, self.nper):
                        runoff_prev = segment_data[per]['runoff'].copy()
                        runoff = runoff_prev + self.streamflow_seepage.runoff
                        segment_data[per]['runoff'] = runoff
                    itmp[:] = nss
                elif isinstance(self.streamflow_seepage.runoff, pd.core.series.Series):
                    for d in self.streamflow_seepage.runoff.index:
                        per = self.climatic.index.get_loc(d)
                        runoff_prev = segment_data[per]['runoff'].copy()
                        runoff = runoff_prev + self.streamflow_seepage.runoff
                        segment_data[per]['runoff'] = runoff
                        itmp[per] = nss # time-varying inputs
                elif isinstance(self.streamflow_seepage.runoff, xr.core.dataset.Dataset):
                    print("xaray.Datasets not implemented yet for runoff input to SFR (modflow.py L781)")
            
            itmp[0] = nss # time-varying inputs
            irdflag = 0 # to print input data
            iptflag = 0 # to print streamflow routing outputs
            dataset_5 = {per: [itmp[per], irdflag, iptflag] for per in range(0, self.nper)}
            # dataset_5 = {per: [itmp, irdflag, iptflag] for per in range(0, self.nper)}
                # dataset_5 = {0: [itmp, irdflag, iptflag]}
                # or
                # dataset_5 = {0: [itmp, irdflag, iptflag],
                #              1: [-1,   irdflag, iptflag],
                #              2: [-1,   irdflag, iptflag],
                #              ...}
            
            nsfrpar = 0 # number of parameters
            nparseg = 0 # number of parameters per segment
            
            self.sfr2 = flopy.modflow.ModflowSfr2(
                self.mf, nstrm=nstrm, nss=nss, nsfrpar=nsfrpar, nparseg=nparseg,
                isfropt=isfropt, irtflg=irtflg, dataset_5=dataset_5,
                # streams parameters:
                reach_data=reach_data_rec, segment_data=segment_data, 
                # default values:
                numtim=2, weight=0.75,
                # to create the .sfr.out file
                istcb2=istcb2,
                # uncertain how to use:
                ipakcb=ipakcb, 
# =============================================================================
#                 # no infiltration:
#                 dleak, ipakcb, nstrail, isuzn, nsfrsets,
# =============================================================================
# =============================================================================
#                 # no kinematic-wave used for transient routing:
#                 flwtol,
# =============================================================================
# =============================================================================
#                 # No stream channel geometry (when icalc=2) (see item 6d)
#                 channel_geometry_data,
# =============================================================================
# =============================================================================
#                 # No calibration curve ("courbe de tarage") (when icalc=4) (see item 6e)
#                 channel_flow_data,
# =============================================================================
                const=86400, # m3/d, # value is not used because no Manning
                )
            
            # ---- sfr2 correct, repair & check
            # Compute slopes
            self.sfr2.get_slopes(default_slope=0.005)
            
            # Repair segments ordering and outsegs
# =============================================================================
#             self.sfr2.renumber_segments() # restart segment numbering from 1
# =============================================================================
            
            # Correct reach and segment maps:
            for r in self.sfr2.reach_data:
                sfr_map[int(r['i']), int(r['j'])] = r['iseg']
                sfr_map_reach[int(r['i']), int(r['j'])] = r['ireach']
# =============================================================================
#             self.sfr2.repair_outsegs() # correct the terminal reaches
#             self.sfr2.reset_reaches() # restart reach numbering from 1 for each segment
# =============================================================================
# =============================================================================
#             self.sfr2.set_outreaches()
# =============================================================================
            
            # [temp] Verbose verification
            self.sfr2.check()
            
            # ---- Export
            self.sfr2.export_linkages(
                os.path.join(self.streamflow_seepage.sfr_seepage_folder, "streams.shp"), 
                epsg=int(self.geographic.crs_proj.split(':')[-1]))
            self.sfr2.export_outlets(
                os.path.join(self.streamflow_seepage.sfr_seepage_folder, "outlets.shp"), 
                epsg=int(self.geographic.crs_proj.split(':')[-1]))
            
            np.savetxt(
                os.path.join(self.streamflow_seepage.sfr_seepage_folder, "reach_data.csv"), 
                self.sfr2.reach_data, 
                delimiter=";", 
                header=';'.join(self.sfr2.reach_data.dtype.names))
            np.savetxt(
                os.path.join(self.streamflow_seepage.sfr_seepage_folder, "segment_data.csv"), 
                self.sfr2.segment_data[0], 
                delimiter=";", 
                header=';'.join(self.sfr2.segment_data[0].dtype.names))
            
            toolbox.export_tif(self.geographic.watershed_dem, 
                               sfr_map, 
                               os.path.join(self.streamflow_seepage.sfr_seepage_folder, "stream_segments.tif"),
                               self.geographic.nodata)
            toolbox.export_tif(self.geographic.watershed_dem, 
                               sfr_map_reach, 
                               os.path.join(self.streamflow_seepage.sfr_seepage_folder, "stream_reaches.tif"),
                               self.geographic.nodata)
            toolbox.export_tif(self.geographic.watershed_dem, 
                               self.drain_array,
                               os.path.join(self.streamflow_seepage.sfr_seepage_folder, "remaining_DRN.tif"),
                               self.geographic.nodata)
            toolbox.export_tif(self.geographic.watershed_dem, 
                               elev_map,
                               os.path.join(self.streamflow_seepage.sfr_seepage_folder, "streambed_tops.tif"),
                               self.geographic.nodata)
            toolbox.export_tif(self.geographic.watershed_dem, 
                               hcond_map,
                               os.path.join(self.streamflow_seepage.sfr_seepage_folder, "conductances.tif"),
                               self.geographic.nodata)
            if self.streamflow_seepage.crit_area is not None:
                self.streamflow_seepage.crit_area[self.streamflow_seepage.crit_area.mask] = nodata
                toolbox.export_tif(self.geographic.watershed_dem, 
                                   self.streamflow_seepage.crit_area, 
                                   os.path.join(self.streamflow_seepage.sfr_seepage_folder, "sink_cells(debug).tif"),
                                   self.geographic.nodata,)
# =============================================================================
#             wbt.slope(elev_map,
#                       # os.path.join(self.streamflow_seepage.sfr_seepage_folder, 'slopes.tif'),
#                       r"D:\slopes.tif",
#                       units="percent")
# =============================================================================
# =============================================================================
#             wbt.basins(d8_pntr = self.geographic.watershed_box_buff_direc, 
#                         output = os.path.join(self.streamflow_seepage.sfr_seepage_folder, "basins.tif"), 
#                         esri_pntr=False)
# =============================================================================
        
        #%% Lake package (LAK)
        
        # This function is run in #%% Discretization section:
# =============================================================================
#         stages, lakarr_lay0, laklay_top, bdlknc_lay0, flux_data = self.lakeres.format_to_modflow(
#             self.geographic, self.climatic, self.nper, self.thickfact)
# =============================================================================
       
        if self.use_lakeres:       
            self.lak = flopy.modflow.ModflowLak(self.mf,
                                                nlakes = self.lakeres.n_lakeres,
                                                ipakcb = 1, # save cell-by-cell seepage
                                                theta = 0, # 0: explicit # 1: implicit
                                                stages = stages,
                                                lakarr = lakarr,
                                                bdlknc = bdlknc,
                                                flux_data = flux_data)
            
            # Remove drains under lakes
            self.drain_array[lakarr_lay0 != 0] = 0
            
# =============================================================================
#         #%%% To impose outflow from the lake/reservoir (return flow)
#         self.fhb = flopy.modflow.ModflowFhb(self.mf)
# =============================================================================

        #%% Drain package
    
        # (DRN)
        # Applied to all the surface of the model : enables seepage on the top layer

# =============================================================================
#         if self.streamflow_seepage != None: # if the object streamflow_seepage is not None:
#             if self.cond_drain != None:
#                 print("cond_drain overwritten with streamflow_seepage values")
#                 self.cond_drain = self.streamflow_seepage.cond_drain*100
# =============================================================================
            
        self.drnData = np.zeros((int(np.sum(self.drain_array)), 5))
        compt = 0
        # First value (0): layer number
        self.drnData[:, 0] = self.aquifer_top_layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                if self.drain_array[i,j] == 1:
                    self.drnData[compt, 1] = i # Second value (1): row number
                    self.drnData[compt, 2] = j # Third value (2): column number
                    self.drnData[compt, 3] = self.dem[i, j] # Fourth value (3): altitude
                    # Fifth value (4): value of the conductivity of the drain (integrated over the surface of the cell)
                    if self.sink_fill == False:
                        if self.cond_drain != None:
                            #ALEXANDRE: pourquoi self.multip_cond utilisée ici aussi, faut-il modifier pour avoir 2 noms de variables différents? 
                            self.drnData[compt, 4] = self.cond_drain 
                        else:
                            self.drnData[compt, 4] = (self.hk[0, i, j] * self.resolution** 2)
                    else:
                        if self.sink[i,j]>0:
                            #ALEXANDRE: when filled, no possible drains, why?
                            self.drnData[compt, 4] = 0 # hcond_low
                        else:
                            if self.cond_drain != None:
                                self.drnData[compt, 4] = self.cond_drain 
                            else:
                                self.drnData[compt, 4] = self.hk[0, i, j] * self.resolution** 2 
                    
                    # If a correction of conductances is needed for SFR, 
                    # then it is also applied to DRN:
                    if self.streamflow_seepage is not None:
                        if self.streamflow_seepage.critical_mode is not None:
                            if self.streamflow_seepage.crit_area[i,j] >= self.streamflow_seepage.sink_threshold:
                                self.drnData[compt, 4] = min(self.drnData[compt, 4], 
                                                             self.streamflow_seepage.hcond_min)
                            
                    compt += 1

        # Imposes condition to Modflow through flopy
        lrcec= {0:self.drnData}
        self.drn = flopy.modflow.ModflowDrn(self.mf, stress_period_data=lrcec)

        #%% Output control
        
        # OC : output control
        
        stress_period_data = {}
        for kper in range(self.nper):
            kstp = self.nstp[kper]
            # Saves head (hds) and budget (cbc) for each of the stress periods (flopy)
            stress_period_data[(kper, kstp-1)] = ['save head', 'save budget'] #['save head','save budget',]
        self.oc = flopy.modflow.ModflowOc(self.mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                # unitnumber=[14, 51, 52, 53, 0],
                                unitnumber=None,
                                compact=True)
        self.oc.reset_budgetunit(fname= self.model_name+'.cbc')

        # CrossSection figure
        if self.plot_cross == True:
            
            fig, axs = plt.subplots(1, 2, figsize=(14,4), dpi=300)
            axs = axs.ravel()
            
            grid_model = self.mf.modelgrid
            
            modelxsect1 = flopy.plot.PlotCrossSection(model=self.mf, line={'Row': int((grid_model.shape[1])/2)})
            imhk = modelxsect1.plot_array(self.hk/24/3600, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[0],
                                    # norm=mpl.colors.LogNorm(vmin=self.hk.min(), vmax=self.hk.max())
                                    norm=mpl.colors.LogNorm(vmin=1e-13, vmax=1e-1)
                                   )
            # modelxsect1.plot_grid(ax=axs[0])
            axs[0].set_title('West-East (Row), K [m/s]', fontsize=12)
            axs[0].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
            axs[0].set_xlabel('Distance [m]')
            axs[0].set_ylabel('Elevation [m]')
            # divider = make_axes_locatable(axs[0])
            # cax = divider.append_axes('right', size='5%', pad=0.05)
            # fig.colorbar(imhk, cax=cax, orientation='vertical')
            fig.colorbar(imhk)
            
            modelxsect2 = flopy.plot.PlotCrossSection(model=self.mf, line={'Column': int((grid_model.shape[2])/2)})
            imsy = modelxsect2.plot_array(self.ps*100, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[1],
                                           norm=mpl.colors.LogNorm(vmin=0.1, vmax=100))
            # modelxsect2.plot_grid(ax=axs[1])
            axs[1].set_title('North-South (Column), Sy [%]', fontsize=12)
            axs[1].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
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
                   run_model:bool=False):
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
        # Create modflow files
        if write_model == True:
            # write input files
            self.mf.write_input()
            # model_modflow.mf.write_input()
        
        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mf.run_model(silent=not verbose) # True without msg
            # success_model = model_modflow.mf.run_model(silent=not verbose) # True without msg
        
        return success_model
     
    #%% UPDATE
    def update(self, model_modflow:object,
               update_dict:dict):
        
        #%%% Update model name
        if 'model_name' in update_dict:
            self.model_name = update_dict['model_name']
            self.mf.name = self.model_name
            # To correct the filepath for results
            if 'full_path' not in update_dict:
                self.full_path = os.path.join(self.model_folder, self.model_name) #'modraw'
                self.mf.model_ws = self.full_path
            # to update the filepaths for .hds, .cbc and .sfr.out
            self.mf.output_fnames = [
                '.'.join([update_dict['model_name']] + elem.split('.')[1:])
                for elem in self.mf.output_fnames
                ]
            
# =============================================================================
#             self.oc.reset_budgetunit(fname = self.model_name+'.cbc')
# =============================================================================
        
        #%%% Update model path
        if 'full_path' in update_dict:
            self.full_path = update_dict['full_path']
            self.mf.model_ws = self.full_path
        
        #%%% Update sim_state
        if 'sim_state' in update_dict:
            self.sim_state = update_dict['sim_state']
        
        #%%% Update heads
        if 'heads' in update_dict:
            self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=update_dict['heads'], hnoflo=-9999)
        
        #%%% Update time discretisation
        if 'recharge' in update_dict:
            self.climatic = update_dict['recharge']
            
            # ---- Update time discretization (driven by recharge)
            if self.sim_state == 'steady': # if isinstance(self.climatic,(int,float))==True
                # Steady state
                self.nper = 1               # Number of forcing periods (recharge)
                self.perlen = 1             # Length of period
                self.nstp = [1]             # Steps in a given period (not used here)
                self.steady = True          # Steady state
                self.start_datetime = None
                
            if self.sim_state == 'transient':
                # Transient state
                if isinstance(self.climatic,(dict))==True:
                    self.start_datetime = 0 
                else:
                    self.start_datetime = self.climatic.index[0]            # First date of climatic recharge
                    # To cooridate with forcing and/or climatic
                    """
                    if type(self.climatic.index)==pd.core.indexes.datetimes.DatetimeIndex:
                        if pd.infer_freq(self.climatic.index) != 'D':
                            for i in range(1,len(self.climatic)):      
                                dif = self.climatic.index[i]-self.climatic.index[i-1]
                                self.perlen[i] = dif.days
                    """
                self.steady = np.zeros(len(self.climatic),dtype=bool)   # Vector of booleans (transient state at each time step)
                self.nstp = np.ones(len(self.climatic))     # One step per time step
                self.nper = len(self.climatic)
                # Definition of period duration (forcing is constant on a period)
                #       As many periods as recharge values 
                #       Extracts from climatic data the time steps (self.perlen)
                
                if self.split_temp == True:
                    ### DISCUSS WITH ALEXANDREFOR THIS PART
                    if isinstance(self.climatic, pd.core.series.Series):
                        if isinstance(self.climatic.index[0], datetime.datetime):
                            # self.perlen = self.climatic.index.to_series().diff().dt.days.values
                            self.perlen = self.climatic.index.to_series().diff().dt.total_seconds().values/86400 # values converted into float days
                        else:
                            self.perlen = self.climatic.index.to_series().diff().values
                if isinstance(self.split_temp, list) == True:
                    self.perlen = self.split_temp
                if self.split_temp == False:
                    self.perlen = np.ones(len(self.climatic))
                # print(self.split_temp)
                # First timestep is steady state:
                self.perlen[0] = 1
        
        #%%% Update lakeres
        if ('lakeres' in update_dict) |  \
        (('recharge' in update_dict) & (self.lakeres is not None)):
            
            if 'lakeres' in update_dict:
                self.lakeres = update_dict['lakeres']
            else:
                print('Warning: Recharge has been updated but lake/reservoir flux_data has not')
            
            # These lak parameters need to be updated when nper is changed
            stages, lakarr_lay0, laklay_top, bdlknc_lay0, flux_data, self.dem = self.lakeres.format_to_modflow(
                self.geographic, self.climatic, self.nper, self.thickfact, self.dem, self.dem_watershed_path,
                export_lakarr = False)
            
            lakarr = np.zeros((self.nlay, self.nrow, self.ncol))
            lakarr[0] = lakarr_lay0
            
            bdlknc = np.zeros((self.nlay, self.nrow, self.ncol))
            bdlknc[0] = bdlknc_lay0
            
            # NB: lakarr != self.lak.lakarr.array
            
            self.lak = flopy.modflow.ModflowLak(self.mf,
                                                nlakes = self.lakeres.n_lakeres,
                                                ipakcb = self.lak.ipakcb,
                                                theta = self.lak.ipakcb, # 0: explicit # 1: implicit
                                                stages = stages,
                                                lakarr = lakarr,
                                                bdlknc = bdlknc,
                                                flux_data = flux_data)
            
            # Remove drains under lakes
            self.drain_array[lakarr_lay0 != 0] = 0
        
        #%%% Update recharge
        if 'recharge' in update_dict:
            
            # ---- Update evapotranspiration from the aquifer (if applicable)
                # from the watertable: evt package (from negative value, should always be positive)
            if isinstance(self.climatic,(dict))==False:
                if isinstance(self.climatic,float)==False and (self.climatic < 0).any().any() == True:
                    # self.climatic : recharge values (float in steady state or chronicles in transient state)
                    # Modifies ETP values (self.climatic): from negative to positive values (sink term)
                    #      package evt requires positive values (negative values are not allowed)
                    self.evt = self.climatic.copy() 
                    # All positive values are set to 0 (no negative values)
                    self.evt[self.evt>=0] = 0
                    # All negative values are set to positive values
                    self.evt = abs(self.evt)
                    # Remove aquifer evaporation on lakes/reservoirs
                    if self.use_lakeres:
                        self.evt[lakarr_lay0 > 0] = 0
                        self.climatic[lakarr_lay0 > 0] = 0
                    self.evtData = {}
                    # Loop over all time steps to make a dictionnary from a scalar or a dictionnary
                    for kper in range(0, self.nper):
                        if isinstance(self.evt,(int,float)):
                            # If integer or float, do it only once (steady state)
                            self.evtData[kper] = self.evt
                        else:
                            # Transient state: 
                            if kper == 0:
                                # self.evtData[kper] = np.nanmean(self.evt)
                                self.evtData[kper] = 0
                            else:
                                self.evtData[kper] = self.evt[kper]
                    # expd = self.thick : ETP can take water all over the aquifer thickness
                    self.evt = flopy.modflow.ModflowEvt(self.mf,
                                                        evtr=self.evtData,
                                                        surf = self.dem,
                                                        nevtop = 1, # default: 1 (top), 2 (layer), 3 (highest active)
                                                        exdp = 10, # default: 1 (from surf normally)
                                                        ievt = 1, # default: 1 (if layer)
                                                        ipakcb = 1 # default: 0 
                                                        )
                    # Sets all negative of self.climatic to values (they have just been accounted as pumping terms)
                    if not isinstance(self.climatic,(int,float)):
                        self.climatic[self.climatic<0] = 0
            
            # ---- Update recharge values over the surface: rch package (should always be positive)  
            self.rchData = {}
            for kper in range(0, self.nper):
                if isinstance(self.climatic,(dict))==True:
                    self.rchData = self.climatic
                else:
                    if isinstance(self.climatic,(int,float)):
                        # Only value in self.climatic (steady)
                        self.rchData[kper] = self.climatic
                    else:
                        if kper == 0:
                            # First value: steady (to reach equilibrium before starting the transient state of the simulation)
                            # By default mean of the climatic chronicle
                            if self.first_clim == 'mean':
                                self.rchData[kper] = np.nanmean(self.climatic)
                            if self.first_clim == 'first':
                                # First value of the cimatic chronicle
                                self.rchData[kper] = self.climatic.iloc[0]
                            if isinstance(self.first_clim,(int,float)):
                                # Imposed value (if steady state: just one value)
                                self.rchData[kper] = self.first_clim
                        else:
                            # More flexibility in the possible format of the climatic chronicles 
                            # Should only be used exceptionnaly (pandas series recommended)
                            try:
                                self.rchData[kper] = self.climatic[kper]
                            except:
                                self.rchData[kper] = self.climatic.iloc[kper].values[0]        
            
            # Sets recharge to modflow through flopy
            # flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)
            self.rch = flopy.modflow.ModflowRch(self.mf, rech=self.rchData)
            
        #%%% Update runoff
        if 'runoff' in update_dict:
            self.runoff = update_dict['runoff']
                
        #%%% Update Dis
        if 'recharge' in update_dict:
            # Discretization is impacted by nper
            self.dis = flopy.modflow.ModflowDis(self.mf, itmuni=0, lenuni=2,
                                                nlay=self.nlay, nrow=self.nrow, ncol=self.ncol, 
                                                delr=self.resolution, delc=self.resolution,
                                                top=self.top, botm=self.zbot, xul=self.xul, yul=self.yul,
                                                nper=self.nper, perlen=self.perlen, nstp=self.nstp,
                                                steady=self.steady, start_datetime=self.start_datetime) 
                                                # itmuni = 0 ==> undefined
                                                # itmuni_values = {'days': 4, 'hours': 3, 'minutes': 2, 'seconds': 1, 'undefined': 0, 'years': 5}
            
        #%%% Update StreamFlow Seepage
# === In case of user-defined StreamFLow Seepage update (not implemented yet) =
#         if ('streamflow_seepage' in update_dict) |  \
#             (('recharge' in update_dict) & (self.streamflow_seepage is not None)):
#             
#             if 'streamflow_seepage' in update_dict:
#                 self.streamflow_seepage = update_dict['streamflow_seepage']
# =============================================================================

        if ('recharge' in update_dict) & (self.streamflow_seepage is not None):    
            segment_data_1_rec = self.sfr2.segment_data[0]
            segment_data_1_rec['runoff'] = 0
            segment_data = {per: segment_data_1_rec.copy() for per in range(0, self.nper)}
            
            nstrm = len(self.sfr2.reach_data) # > 0
            nss = len(segment_data_1_rec)
            itmp = np.ones(self.nper, dtype = int) * -1 # first period input values repeated over time
            
            # Return flow (restitution)
            if self.use_lakeres:
                for num_id in self.lakeres.lake_by_num_id.keys():
                    lake_id = self.lakeres.lake_by_num_id[num_id]
                    nsegs = self.streamflow_seepage.segment_data_1[
                        self.streamflow_seepage.segment_data_1.iupseg == -num_id].index
                    if self.lakeres.rtrn_by_lake[lake_id] is not None:
                        for d in self.lakeres.rtrn_by_lake[lake_id].index:
                            per = self.climatic.index.get_loc(d)
                            runoff_prev = segment_data[per]['runoff'].copy()
                            runoff = runoff_prev.copy()
                            runoff[nsegs] = self.lakeres.rtrn_by_lake[lake_id].loc[self.climatic.index[per]]/len(nsegs) #self.lakeres.rtrn_by_lake[lake_id]/len(nsegs)
                            segment_data[per]['runoff'] = runoff_prev + runoff
                            itmp[per] = nss # time-varying inputs
            
            # Runoff
            if self.streamflow_seepage.runoff is not None:
                if isinstance(self.streamflow_seepage.runoff, (int, float)):
                    for per in range(0, self.nper):
                        runoff_prev = segment_data[per]['runoff'].copy()
                        runoff = runoff_prev + self.streamflow_seepage.runoff
                        segment_data[per]['runoff'] = runoff
                    itmp[:] = nss
                elif isinstance(self.streamflow_seepage.runoff, pd.core.series.Series):
                    for d in self.streamflow_seepage.runoff.index:
                        per = self.climatic.index.get_loc(d)
                        runoff_prev = segment_data[per]['runoff'].copy()
                        runoff = runoff_prev + self.streamflow_seepage.runoff
                        segment_data[per]['runoff'] = runoff
                        itmp[per] = nss # time-varying inputs
                elif isinstance(self.streamflow_seepage.runoff, xr.core.dataset.Dataset):
                    print("xaray.Datasets not implemented yet for runoff input to SFR (modflow.py L781)")
            
            itmp[0] = nss # time-varying inputs
            irdflag = 0 # to print input data
            iptflag = 0 # to print streamflow routing outputs
            dataset_5 = {per: [itmp[per], irdflag, iptflag] for per in range(0, self.nper)}
            
            nsfrpar = 0 # number of parameters
            nparseg = 0 # number of parameters per segment
            
            self.sfr2 = flopy.modflow.ModflowSfr2(
                self.mf, nstrm=nstrm, nss=nss, nsfrpar=nsfrpar, nparseg=nparseg,
                isfropt=self.sfr2.isfropt, irtflg=self.sfr2.irtflg, dataset_5=dataset_5,
                # streams parameters:
                reach_data=self.sfr2.reach_data, segment_data=segment_data, 
                # default values:
                numtim=2, weight=0.75,
                # to create the .sfr.out file
                istcb2=self.sfr2.istcb2,
                # uncertain how to use:
                ipakcb=self.sfr2.ipakcb, 
                const=self.sfr2.const, # m3/d, # value is not used because no Manning
                )
            
# === In case of user-defined StreamFLow Seepage update (not implemented yet) =
#             # sfr2 correct, repair & check
#             # Compute slopes
#             self.sfr2.get_slopes(default_slope=0.005)
# =============================================================================
        
                
        #%%% Update Constant Head Boundary (sea level)
        if ('sea_level' in update_dict) |  \
            (('recharge' in update_dict) & (self.sea_level is not None)):
            
            if 'sea_level' in update_dict:
                self.sea_level = update_dict['sea_level']
                
        if isinstance(self.sea_level, (int,float,pd.Series,list)) == True: # Martin on 15/11/2022: before was: if self.sea_level != None:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            # print('niv1')
            if isinstance(self.sea_level,(int,float)) == False:
                # print('niv2')
                self.chData = {} #Martin on 15/11/2022: before was: self.chdData = {}
                for kper in range(0, self.nper):
                    # print(kper)
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < np.max(self.sea_level):
                                if self.iboundData[self.aquifer_top_layer,i,j] != 0: #no-flow cells cannot be converted to specified head cells
                                    self.drain_array[i,j] = 0
                                    package[kper,i,j] = 1
                                    chdKper.append([self.aquifer_top_layer,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.chData[kper] = chdKper #Martin on 15/11/2022: before was: self.rchData[kper] = chdKper
                            
                flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)
        
        #%%% Update OC : output control
        if 'recharge' in update_dict:
            stress_period_data = {}
            for kper in range(self.nper):
                kstp = self.nstp[kper]
                # Saves head (hds) and budget (cbc) for each of the stress periods (flopy)
                stress_period_data[(kper, kstp-1)] = ['save head', 'save budget'] #['save head','save budget',]
            self.oc = flopy.modflow.ModflowOc(self.mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                    # unitnumber=[14, 51, 52, 53, 0],
                                    unitnumber=None,
                                    compact=True)
            self.oc.reset_budgetunit(fname= self.model_name+'.cbc')
        
# =============================================================================
#         # Newton solver
#         self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=5000,
#                                             thickfact=self.thickfact, linmeth=1, iprnwt=1, ibotav=1,
#                                             options='COMPLEX', Continue=False, backflag=0) # ibotav=0
# =============================================================================
    
    #%% POST-PROCESSING
    
    def post_processing(self, model_modflow:object,
                        watertable_elevation:bool=True,
                        watertable_depth:bool=True, 
                        seepage_areas:bool=True,
                        outflow_drain:bool=True,
                        groundwater_flux:bool=True,
                        groundwater_storage:bool=True,
                        accumulation_flux:bool=True,
                        lake_leakage:bool=True,
                        persistency_index:bool=False,
                        intermittency_monthly:bool=False,
                        intermittency_weekly:bool=False,
                        intermittency_daily:bool=False,
                        export_all_tif:bool=False,):
        """
        Create outputs files.

        Parameters
        ----------
        model_modflow : object
            Object floyp modflow.
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
        # Correct lake_leakage condition
        if self.use_lakeres == False:
            lake_leakage = False
        
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

        #%% Import essential data 
        
        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name)
        
        # Files have been output in the processing phase and are re-read here
        self.dem_mask = (self.dem<-4000)  # 4000 meters (sure no DEM value below: equivalent to no data value)
        # heads
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds') 
        # fluxes
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')
        
        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        # Stress periods (flopy "language")
        if len(self.times) == 1:
            self.kstpkper = self.kstpkper[0]
            
        # Import streamflows (if SFR is used)
        if self.streamflow_seepage is not None:
            sfrout = SfrFile(self.path_file+".sfr.out")
            sfrout_df = sfrout.get_dataframe()
   
        # Params model
        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1) # ==> time
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1
             
        #%% Aggregated results over times
        
        # Fill dictionnaries (save to .h5) over times and create .tifs 
        
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
        self.dict_lake_leakage = {}
        self.dict_saturated_storage = {}
        self.dict_groundwater_storage = {}
        # self.dict_residence_times = {}
        self.dict_persistency_index = {}
        self.dict_intermittency_monthly = {}
        self.dict_intermittency_weekly = {}
        self.dict_intermittency_daily = {}
        self.list_traces = []
        
        # Loop over times, fills each of the previous structures 
        for item, time in enumerate(self.times):
            print('    Time: ', item)
            lake_lateralflow_count = 0
                     
            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])
            
            lead_numb = str(item) # "%03d" % (item,)
            
            export_tif = True
            if export_all_tif == False:
                if item > 0:
                    export_tif = False
            
            # Search watertable data positive values
            self.head = self.head_fpu.get_data(totim=time)
            if self.nlay == 1:
                self.head_data = self.head[0]
            else:
                head_final = np.zeros([self.nrow,self.ncol])
                for i in range(0,self.nrow):
                    for j in range (0,self.ncol):
                        for k in range(0,self.nlay): 
                            if self.head[k,i,j] > 0:
                                head_final[i,j] = self.head[k,i,j]
                                break   
                self.head_data = head_final.copy()
            # if self.nlay > 1:
            #     self.head_all = self.head_fpu.get_alldata() # mflay=None
            #     self.head_data = self.head_all[item][0]
            # else:
            #     self.head_data = self.head_fpu.get_data(totim=time)
            #     self.head_data = self.head_data[0]
            
            if watertable_elevation == True:   
                ### Watertable elevation
                self.wt_elev = self.head_data.copy()
                self.wt_elev[self.dem_mask] = -9999
                # self.wt_elev.to_hdf(self.dict_watertable_elevation, lead_numb)
                output_path = self.tifs_file+'/watertable_elevation_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_elev, output_path, -9999)                  
                self.dict_watertable_elevation[item] = self.wt_elev
            
            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = self.dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                # self.wt_depth.to_hdf(self.dict_watertable_depth, lead_numb)
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
                # self.seep_area.to_hdf(self.dict_seepage_areas, lead_numb)
                output_path = self.tifs_file+'/seepage_areas_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.seep_area, output_path, -9999)
                self.dict_seepage_areas[item] = self.seep_area
            
            if outflow_drain == True:
                # Standard case: seepage is modeled with DRN package
                if not self.streamflow_seepage: 
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
                    # self.out_drn.to_hdf(self.dict_outflow_drain, lead_numb)
                    output_path = self.tifs_file+'/outflow_drain_t('+lead_numb+').tif' 
                    if accumulation_flux==True:
                        toolbox.export_tif(self.dem_watershed_path, self.out_drn, output_path, -9999)
                    else:
                        if export_tif==True:
                            toolbox.export_tif(self.dem_waterhsed_path, self.out_drn, output_path, -9999)
                    self.dict_outflow_drain[item] = self.out_drn
                # Otherwise, if the object streamflow_seepage is not None, 
                # the outflow_drain is computed differently
                else:
                    ### Outflow drain
                    # TEMP SFR : Pas encore implémenté
                    self.out_all = np.zeros((1, self.dis.nrow, self.dis.ncol))
                    self.out_drn = self.out_all[0]
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
                self.flux_top = self.flux[self.aquifer_top_layer]
                self.flux_top[self.dem_mask] = -9999
                # self.gw_flux.to_hdf(self.dict_groundwater_flux, lead_numb)
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.flux_top, output_path, -9999)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                # self.wt_sto = ( self.wt_sto - (self.dem-self.thick) ) * (self.resolution**2) * self.porosity
                self.wt_sto = ( self.wt_sto - self.zbot[-1] ) * (self.resolution**2) * self.porosity
                output_path = self.tifs_file+'/groundwater_storage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_sto, output_path, -9999)
                self.dict_saturated_storage[item] = self.wt_sto

                if item == 0:
                    self.sto = np.ones((1, self.dis.nrow, self.dis.ncol)) * np.nan
                else:
                    self.kstpkper_bis = (self.kstp[item], time)
                    try:
                        self.sto = self.cbb.get_data(text='STORAGE', kstpkper=self.kstpkper_bis)[0]
                    except:
                        pass
                self.gw_storage = np.sum(self.sto, axis=0)
                self.dict_groundwater_storage[item] = self.gw_storage

            if accumulation_flux == True:
                # Standard case: seepage is modeled with DRN package
                if not self.streamflow_seepage: 
                    ### Accumulation flux
                    accumulated_flow = downslope.Downslope(self.geographic,
                                                                  'outflow_drain_t('+lead_numb+').tif',
                                                                  'tracept_t('+lead_numb+').shp',
                                                                  'accumulation_flux_t('+lead_numb+').tif',
                                                                  extraction_folder=self.save_file)
                    accumulated_flow.trace_cumulated()
                    output_path = self.tifs_file+'/accumulation_flux_t('+lead_numb+').tif'
                    try:
                        self.dict_accumulation_flux[item] = imageio.v2.imread(output_path) #replaces former 'imageio.imread(output_path)' [MARTIN 20/09/2022]
                    except:
                        self.dict_accumulation_flux[item] = imageio.imread(output_path)
                        pass
                # Otherwise, if the object streamflow_seepage is not None, 
                # the accumulation_flux is computed differently
                else:
                    ### Accumulation flux
                    # TEMP SFR : Pas encore implémenté
                    sfr_Qmap = np.zeros((self.dis.nrow, self.dis.ncol))
                    for _, r in sfrout_df[sfrout_df.kstpkper == self.kstpkper].iterrows():
                        sfr_Qmap[r['i'], r['j']] = r['Qout']
                    self.dict_accumulation_flux[item] = sfr_Qmap

            if lake_leakage == True:
                ### Flux from lake to groundwater
                self.lake = self.cbb.get_data(text='LAKE', kstpkper=self.kstpkper, totim=time)                     
                # flow left face (j-1)
                self.lake_leakage_flf = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))
                # flow right face (j+1)
                self.lake_leakage_frf = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))
                # flow back face (i-1)
                self.lake_leakage_fbf = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))
                # flow front face (i+1)
                self.lake_leakage_fff = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))
                # flow top face (k-1)
                self.lake_leakage_ftf = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))
                # flow deeper (lower) face (k+1)
                self.lake_leakage_fdf = np.zeros((self.nlay, self.dis.nrow, self.dis.ncol))

                for n in range(0, len(self.lake[0])):
                    cell = self.lake[0][n].node-1
                    j = cell%self.dis.ncol
                    i = cell//self.dis.ncol%self.dis.nrow
                    k = cell//self.dis.ncol//self.dis.nrow
                    # Note: cell = self.dis.ncol*self.dis.nrow*k + self.dis.ncol*i + j
                    lake_data = self.lake[0][n]
                    # Note: lake_data[2] == lake_data['IFACE           ']
                    if lake_data[2] == 1: # to the left (j-1) 
                        self.lake_leakage_flf[k, i, j] += lake_data.q
                    elif lake_data[2] == 2: # to the right (j+1)
                        self.lake_leakage_frf[k, i, j] += lake_data.q
                    elif lake_data[2] == 3: # towards front (i+1)
                        self.lake_leakage_fff[k, i, j] += lake_data.q
                    elif lake_data[2] == 4: # towards back (i-1)
                        self.lake_leakage_fbf[k, i, j] += lake_data.q
                    elif lake_data[2] == 5: # to the bottom of the layer (k+1)
                        self.lake_leakage_fdf[k, i, j] += lake_data.q
                    elif lake_data[2] == 6: # to the top of the layer (k-1)
                        self.lake_leakage_ftf[k, i, j] += lake_data.q
                
                self.lake_vertical_leakage = self.lake_leakage_ftf[self.aquifer_top_layer]
# =============================================================================
#                 # Other method:
#                 self.lake_vertical_leakage = self.cbb.get_data(
#                     text='LAKE', kstpkper=self.kstpkper, 
#                     totim=time, full3D = True)[1]
# =============================================================================
                # Temp (just for testing)
                if (self.lake_leakage_flf.sum() > 0) | (self.lake_leakage_frf.sum() > 0):
                    lake_lateralflow_count += 1
                if (self.lake_leakage_fff.sum() > 0) | (self.lake_leakage_fbf.sum() > 0):
                    lake_lateralflow_count += 1
                # NB: self.lake_leakage_flf, frf, fff and fbf == 0 everywhere

                self.lake_vertical_leakage[self.dem_mask] = -9999
                output_path = self.tifs_file+'/lake_leakage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.lake_vertical_leakage, output_path, -9999)                  
                self.dict_lake_leakage[item] = self.lake_vertical_leakage
        print(f"\nNOTE: Lake lateral flows have been non null for {lake_lateralflow_count} time steps\n")
            
        ### Save dictionaries to npy
        if watertable_elevation == True:
            np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
        if watertable_depth == True:
            np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
        if groundwater_flux == True:
            np.save(self.save_file+'/groundwater_flux', self.dict_groundwater_flux)
        if groundwater_storage == True:
            np.save(self.save_file+'/saturated_storage', self.dict_saturated_storage)
            np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        if seepage_areas == True:
            np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
        if outflow_drain == True:
            np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
        if accumulation_flux == True:
            np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)
        
        if lake_leakage == True:
            np.save(self.save_file+'/lake_leakage', self.dict_lake_leakage)

        if persistency_index == True:
            ### Persistency index
            acc_npy_raw = np.load(os.path.join(self.save_file,'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            for key in range(len(acc_npy)):
                # mask = imageio.imread(self.geographic.watershed_dem)
                mask = imageio.imread(self.geographic.watershed_box_buff_dem)
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
            # if export_tif==True:
            toolbox.export_tif(self.dem_watershed_path, pi_export, output_path, -9999)
        
            np.save(self.save_file+'/persistency_index', self.dict_persistency_index)
                    
        if intermittency_monthly == True:
            ### Intermittency yearly
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=12:
                inf = 0
                sup = 12
                step = int(round(len(acc_npy_raw)/12))
                compt=0            
                for i in range(step):
                    print('Export intermittency: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
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
                        # if export_tif==True:
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1                    
                    inf+=12
                    sup+=12
                    
            np.save(self.save_file+'/intermittency_monthly', self.dict_intermittency_monthly)
        
        if intermittency_weekly == True:
            ### Intermittency yearly
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=52:
                inf = 0
                sup = 52
                step = int(round(len(acc_npy_raw)/52))
                compt=0            
                for i in range(step):
                    print('Export intermittency: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
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
            
        if intermittency_daily == True:
            ### Intermittency yearly
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=365:
                inf = 0
                sup = 365
                step = int(round(len(acc_npy_raw)/365))
                compt=0            
                for i in range(step):
                    print('Export intermittency: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
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
            
    
#%% NOTES
