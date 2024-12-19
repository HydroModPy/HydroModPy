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
import sys
import imageio                           # Import raster to numpy matrix (not georeferenced but handy)
from os.path import dirname, abspath
import matplotlib.pyplot as plt
import flopy.utils.binaryfile as fpu

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
                 verti_hk=None, verti_sy=None, verti_ss=None,
                 hk_value=0.0864, sy_value: float=0.1, ss_value: float=1e-5,
                 hk_decay: list=[0.,None,False], sy_decay: list=[0.,None,False], ss_decay: list=[0.,None,False],
                 vka: float=1.0,
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
        hk_value : float or 2D float 
            Fixe the hydraulic conductivity value. default is 0.0864.
        hk_decay : float, optional
            Modification of hydraulic conductivity for exponentially decreasing whit depth. The default is 0..
        verti_hc : list, optional
            Depth-dependent hydraulic conductivity. The default is None.
        verti_sy : list, optional
            Depth-dependent porosity. The default is None.
        cond_drain : float, optional
            Fixe the conductance value of the drainage package. The default is None.
        sy_value : float or 2D float, optional
            Fixe the specific yield value. The default is 0.1.
        ss_value : float or 2D float, optional
            Fixe the specifc storage value. Activate for confined layers. The default is 1e-5 (1/day).
        sy_decay : float, optional
            Modification of porosity (specific yield) for exponentially decreasing whit depth. The default is 0.
        ss_decay : float, optional
            Modification of porosity (specific storage) for exponentially decreasing whit depth. The default is 0.
        sea_level : float, optional
            Fixed head on each cell below this value. The default is None.
        bc_left : float, optional
            Fixed head on the left border of the domain. The default is None.
        bc_right : float, optional
            Fixed head on the right border of the domain. The default is None.
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
        
        self.hk_value = hk_value
        self.hk_decay = hk_decay
        self.sy_value = sy_value
        self.ss_value = ss_value
        self.sy_decay = sy_decay
        self.ss_decay = ss_decay
        self.vka = vka
        
        self.verti_hk = verti_hk
        self.verti_sy = verti_sy
        self.verti_ss = verti_ss
        self.cond_drain = cond_drain
        
        #%% Specific modifications
        
        # Preprocess conductivity values 
        #ALEXANDRE
        try:
            # For heterogeneous cases of hydraulic conducitivy, inactivation of part of the dem 
            # Should still be checked: is it still used? Remove? 
            if len(self.hk_value)!=1:
                self.dem[self.hk_value<0]=-9999
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
        # self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.0001, fluxtol=1000, maxiterout=5000,
        #                                     thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1,
        #                                     options='COMPLEX', Continue=False, backflag=0) # ibotav=0
        self.nwt = flopy.modflow.ModflowNwt(self.mf, 
                                            # headtol=1e-5*(np.nanmax(self.dem)-np.nanmin(self.dem)), # 1e-4
                                            # fluxtol=1e-3*np.nanmean(self.climatic)*self.resolution*self.resolution, # 500
                                            headtol=1e-4, # 1e-4
                                            fluxtol=500, # 500
                                            maxiterout=5000,
                                            thickfact=1e-05,
                                            linmeth=1,
                                            iprnwt=1,
                                            ibotav=1,
                                            options='COMPLEX',
                                            Continue=False,
                                            backflag=0,
                                            stoptol=1e-10 # 1e-10
                                            ) # ibotav=0
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
            self.nstp = np.ones(len(self.climatic))    # One step per time step
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
            
        # Imposes discretization to modflow model through flopy
        self.dis = flopy.modflow.ModflowDis(self.mf, itmuni=0, lenuni=2,
                                            nlay=self.nlay, nrow=self.nrow, ncol=self.ncol, 
                                            delr=self.resolution, delc=self.resolution,
                                            top=self.dem, botm=self.zbot, xul=self.xul, yul=self.yul,
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
        if isinstance(self.sea_level, (int,float,pd.Series)) == True: # Martin on 15/11/2022: before was: if self.sea_level != None:
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
                                if self.iboundData[0,i,j] != 0: #no-flow cells cannot be converted to specified head cells
                                    self.drain_array[i,j] = 0
                                    package[kper,i,j] = 1
                                    chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.chData[kper] = chdKper #Martin on 15/11/2022: before was: self.rchData[kper] = chdKper
                            
                flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)
                    
        #%% Parametrization
        
        # lpf package
        self.laywet = np.zeros(self.nlay)
        self.laytype = np.ones(self.nlay)

        # Necessary to give hydraulic conductivity: 3D matrix of hydraulic conductivities
        # Homogeneous or heterogeneous hydraulic conductivity 
        # self.hk_value is either a scalar (for homogeneous cases) or a 2D array (for heterogeneous cases)
        # print(self.nlay, self.nrow, self.ncol)
        # print(self.hc_value)
        # print(self.hc_value.shape)        
        
        self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hk_value
                
        # Exponential decay
        if self.hk_decay[0] != 0:
            kdec = self.hk_decay[0]
            kmin = self.hk_decay[1]
            kmax = self.hk_value
            hklog_trans = self.hk_decay[2]
            if kmin == None:
                depth = np.zeros(self.hk.shape)
                depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
                self.hk *= np.exp(-kdec*depth)
            if kmin != None:
                depth = np.zeros(self.hk.shape)
                depth[1:,:,:] = self.dem - self.zbot[1:,:,:]
                self.hk = (kmin)+((kmax)-(kmin))*np.exp(-kdec*depth)
                self.hk[self.hk<kmin] = kmin
            if (kmin != None) and (hklog_trans==True):
                self.hk = np.log10(kmin)+(np.log10(kmax)-np.log10(kmin))*np.exp(-kdec*depth)
                self.hk = 10**self.hk
                self.hk[self.hk<10**kmin] = 10**kmin
            
        self.sy = np.ones((self.nlay, self.nrow, self.ncol))*self.sy_value
        
        if self.sy_decay[0] != 0:
            depth = np.zeros(self.sy.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            sydec = self.sy_decay[0]
            symin = self.sy_decay[1]
            symax = self.sy_value
            sylog_trans = self.sy_decay[2]
            if symin == None:
                self.sy *= np.exp(-sydec*depth)
            if symin != None:
                self.sy = (symin)+((symax)-(symin))*np.exp(-sydec*depth)
                self.sy[self.sy<symin] = symin
            if (symin != None) and (sylog_trans==True):
                self.sy = np.log10(symin)+(np.log10(symax)-np.log10(symin))*np.exp(-sydec*depth)
                self.sy = 10**self.sy
                self.sy[self.sy<10**symin] = 10**symin
            # η=2 is a coefficient related to
            # the medium structure that we chose to be equal to 2, as com-
            # monly reported in the literature (Cardenas and Jiang, 2010;
            # Bernabé et al., 2003)
            
        self.ss = np.ones((self.nlay, self.nrow, self.ncol))*self.ss_value

        if self.ss_decay[0] != 0:
            depth = np.zeros(self.ss.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            ssdec = self.ss_decay[0]
            ssmin = self.ss_decay[1]
            ssmax = self.ss_value
            sslog_trans = self.ss_decay[2]
            if symin == None:
                self.ss *= np.exp(-ssdec*depth)
            if symin != None:
                self.ss = (ssmin)+((ssmax)-(ssmin))*np.exp(-ssdec*depth)
                self.ss[self.ss<ssmin] = ssmin
            if (symin != None) and (sslog_trans==True):
                self.ss = np.log10(ssmin)+(np.log10(ssmax)-np.log10(ssmin))*np.exp(-ssdec*depth)
                self.ss = 10**self.ss
                self.ss[self.ss<10**ssmin] = 10**ssmin

        # Depth-dependent hydraulic conductivity (disconnected from the vertical discretization)
        if self.verti_hk != None:
            for j in range(len(self.verti_hk)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    k_val = self.verti_hk[j][0]
                    d1 = self.verti_hk[j][1][0]
                    d2 = self.verti_hk[j][1][1]
                    hk_d1 = (self.dem - d1)
                    hk_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= hk_d1) & (self.zbot[i] >= hk_d2))
                    self.hk[i][mask] = k_val
                    # print(k_val)
        
        # Depth-dependent porosity (disconnected from the vertical discretization)
        if self.verti_sy != None:
            for j in range(len(self.verti_sy)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    sy_val = self.verti_sy[j][0]
                    d1 = self.verti_sy[j][1][0]
                    d2 = self.verti_sy[j][1][1]
                    sy_d1 = (self.dem - d1)
                    sy_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= sy_d1) & (self.zbot[i] >= sy_d2))
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
                                            hk=self.hk, sy=self.sy,
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
        
        #%% Source terms
        
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

        #%% Drain package
        
        # (DRN)
        # Applied to all the surface of the model : enables seepage on the top layer
        
        self.drnData = np.zeros((int(np.sum(self.drain_array)), 5))
        compt = 0
        # First value (0): layer number
        self.drnData[:, 0] = 0 # layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                if self.drain_array[i,j] == 1:
                    self.drnData[compt, 1] = i # Second value (1): row number
                    self.drnData[compt, 2] = j # Third value (2): column number
                    self.drnData[compt, 3]= self.dem[i, j] # Fourth value (3): altitude
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
                            self.drnData[compt, 4] = 0
                        else:
                            if self.cond_drain != None:
                                self.drnData[compt, 4] = self.cond_drain 
                            else:
                                self.drnData[compt, 4] = self.hk[0, i, j] * self.resolution** 2 
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
            imsy = modelxsect2.plot_array(self.sy*100, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[1],
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
        self.dict_saturated_storage = {}
        self.dict_groundwater_storage = {}
        self.dict_persistency_index = {}
        self.dict_intermittency_monthly = {}
        self.dict_intermittency_weekly = {}
        self.dict_intermittency_daily = {}
        self.list_traces = []
        
        # Loop over times, fills each of the previous structures 
        for item, time in enumerate(self.times):
            print('    Time: ', item)
                     
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
                # self.gw_flux.to_hdf(self.dict_groundwater_flux, lead_numb)
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.flux_top, output_path, -9999)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                # zbot_ref = self.zbot[-1].copy()
                # zbot_ref[self.dem<0] = np.nan
                # self.wt_sto = ( self.wt_sto - (self.dem-self.thick) ) * (self.resolution**2) * self.porosity
                self.wt_sto = ( self.wt_sto - self.zbot[-1] ) * (self.resolution**2) * np.nanmean(self.sy)
                output_path = self.tifs_file+'/groundwater_storage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_sto, output_path, -9999)
                self.dict_saturated_storage[item] = self.wt_sto

            if accumulation_flux == True:
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
            
        ### Save dictionaries to npy
        if watertable_elevation == True:
            np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
        if watertable_depth == True:
            np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
        if seepage_areas == True:
            np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
        if outflow_drain == True:
            np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
        if groundwater_flux == True:
            np.save(self.save_file+'/groundwater_flux', self.dict_groundwater_flux)
        if groundwater_storage == True:
            np.save(self.save_file+'/saturated_storage', self.dict_saturated_storage)
        if accumulation_flux == True:
            np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)

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
