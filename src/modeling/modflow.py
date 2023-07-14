# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Python
import flopy
import numpy as np
import os
import pandas as pd
import sys
import imageio                           # Import raster to numpy matrix (not georeferenced but handy)
from os.path import dirname, abspath
import matplotlib.pyplot as plt
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

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

#%% CLASS

class Modflow():

    #%% INIT
    
    def __init__(self,
                 geographic,
                 # Worflow settings
                 model_folder=os.getcwd()[:2]+'/'+'HydroModPy_Output/',
                 model_name='Default',
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe'),
                 box=True,
                 sink_fill=False,
                 sim_state='steady',
                 plot_cross=True,
                 # Climatic settings
                 climatic=500/1000/365,
                 first_clim='mean',
                 # Hydraulic settings
                 nlay=1,
                 lay_decay=1,
                 bottom=None,
                 thick=100,
                 hyd_cond=1e-6*60*60*24,
                 cond_decay=0,
                 verti_cond=None,
                 cond_drain=None,
                 porosity=10/100,
                 poro_decay=0,
                 # Boundary settings
                 sea_level=None,
                 bc_left=None, 
                 bc_right=None):
        
        #%% Initialization
        
        self.model_folder = model_folder
        if not os.path.exists(self.model_folder):
            toolbox.create(self.model_folder)
        self.model_name = model_name
        self.exe = exe
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
            self.dem_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_path = geographic.watershed_buff_dem
        self.dem[self.dem<=-9999] = -9999
        self.dem[self.dem>=9999] = -9999
        if self.sea_level == None:
            self.dem[(self.dem<0)&(self.dem>-200)] = 0
        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]
    
        #%% Source/Sink terms
        
        if isinstance(climatic, float) == False :  
            self.climatic = climatic.copy()
        else: 
            self.climatic = climatic
        self.first_clim = first_clim    
            
        #%% Model parameters 
        
        self.nlay = nlay
        self.lay_decay = lay_decay
        self.bottom = bottom
        self.thick = thick
        
        self.hyd_cond = hyd_cond
        self.cond_decay = cond_decay
        self.porosity = porosity
        self.poro_decay = poro_decay
        
        self.verti_cond = verti_cond
        self.cond_drain = cond_drain
        
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
        self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                            thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1,
                                            options='COMPLEX', Continue=False, backflag=0) # ibotav=0

        #%% Discreitzation
        
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
            self.start_datetime = self.climatic.index[0]            # First date of climatic recharge
            self.steady = np.zeros(len(self.climatic),dtype=bool)   # Vector of booleans (transient state at each time step)
            self.steady[0] = True       # Steady state for the first time step (initialization of head values by a steady state)
            self.nstp = np.ones(len(self.climatic))     # One step per time step
            self.nper = len(self.climatic)
            # Definition of period duration (forcing is constant on a period)
            #       As many periods as recharge values 
            #       Extracts from climatic data the time steps (self.perlen)
            self.perlen = np.ones(len(self.climatic))
            if type(self.climatic.index)==pd.core.indexes.datetimes.DatetimeIndex:
                if pd.infer_freq(self.climatic.index) != 'D':
                    for i in range(1,len(self.climatic)):      
                        dif = self.climatic.index[i]-self.climatic.index[i-1]
                        self.perlen[i] = dif.days

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
        
        # Modification of layer thickness for exponentially decreasing hydraulic conductivity cases
        if self.lay_decay != 1.:
            exp_scale = 1-self.lay_decay**self.nlay
    
        # Parameters for proportions of bottom layer to surface values
        for i in range(1, self.nlay+1):
            if self.lay_decay == 1.:
                p = i / self.nlay    # Uniform thicknesses
            else:
                p = (1-self.lay_decay**i) / exp_scale   # Increasing thicknesses with depth
            # Weighted formula to go from bottom_layer to surface (self.dem)
            self.zbot[i-1] = self.bottom_layer * p + self.dem * (1-p)
            
        # Imposes discretization to modflow model through flopy
        self.dis = flopy.modflow.ModflowDis(self.mf, itmuni=4, lenuni=2,
                                            nlay=self.nlay, nrow=self.nrow, ncol=self.ncol, 
                                            delr=self.resolution, delc=self.resolution,
                                            top=self.dem, botm=self.zbot, xul=self.xul, yul=self.yul,
                                            nper=self.nper, perlen=self.perlen, nstp=self.nstp,
                                            steady=self.steady, start_datetime=self.start_datetime) # itmuni = 0 ==> undefined
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
                print('niv0')
                self.iboundData[i][self.dem <= self.sea_level] = -1
                self.strtData[self.iboundData == -1] = self.sea_level
            self.iboundData[i][self.dem < -1000] = 0     # O is for NO FLOW               

        self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)
            
        ### Constant Head boundary conditions of No Flow (at sea level)
        
        drain_array = np.ones((self.nrow, self.ncol))
        if isinstance(self.sea_level, (int,float,pd.Series,list)) == True: # Martin on 15/11/2022: before was: if self.sea_level != None:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            print('niv1')
            if isinstance(self.sea_level,(int,float)) == False:
                print('niv2')
                self.chData = {} #Martin on 15/11/2022: before was: self.chdData = {}
                for kper in range(0, self.nper):
                    print(kper)
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < np.max(self.sea_level):
                                if self.iboundData[0,i,j] != 0: #no-flow cells cannot be converted to specified head cells
                                    drain_array[i,j] = 0
                                    package[kper,i,j] = 1
                                    chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.chData[kper] = chdKper #Martin on 15/11/2022: before was: self.rchData[kper] = chdKper
                            
                chd = flopy.modflow.ModflowChd(self.mf, stress_period_data=self.chData)
                    
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
        
        if self.poro_decay != 0.:
            # print('DECAY EXPO POROSITY')
            depth = np.zeros(self.ps.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.ps *= np.exp(-(self.poro_decay)*depth)
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
                       
        # Lateral heterogeneity of hk ?
        # for i in range(0,len(self.number_structure)):
        #     for j in range(0,nlay):
        #         self.hk[j][self.structure.geology==self.number_structure[i]]= logParamValue[i]*3600*24
		   
        self.upw = flopy.modflow.ModflowUpw(self.mf, 
                                            laytyp=self.laytype, laywet=self.laywet, 
                                            hk=self.hk, sy=self.ps,
                                            iphdry=1, hdry=-100, vka=1, noparcheck=False,
                                            extension='upw', unitnumber=31)
        
        #%% Source terms
        
        ### Source term & initial conditions: recharge (and evapotranspiration) on the top of the model 
        
        # EVAPOTRANSPIRATION FROM THE AQUIFER
            # from the watertable: evt package (from negative value, should always be positive)
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
            self.evt = flopy.modflow.ModflowEvt(self. mf, nevtop=3,
                                                evtr=self.evtData, 
                                                surf=0, exdp=self.thick)
            # Sets all negative of self.climatic to values (they have just been accounted as pumping terms)
            if not isinstance(self.climatic,(int,float)):
                self.climatic[self.climatic<0] = 0
                
        # RECHARGE TO THE AQUIFER
            # over the surface: rch package (should always be positive)
        self.rchData = {}
        for kper in range(0, self.nper):
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
                        self.rchData[kper] = self.init_rech
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
        
        self.drnData = np.zeros((int(np.sum(drain_array)), 5))
        compt = 0
        # First value (0): layer number
        self.drnData[:, 0] = 0 # layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                if drain_array[i,j] == 1:
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
                                unitnumber=[14, 51, 52, 53, 0], compact=True)
        self.oc.reset_budgetunit(fname= self.model_name+'.cbc')

        # CrossSection figure
        if self.plot_cross == True:
            
            fig, axs = plt.subplots(1, 2, figsize=(12,3))
            axs = axs.ravel()
            
            grid_model = self.mf.modelgrid
            
            # fig = plt.figure(figsize=(10, 5))
            # ax = fig.add_subplot(1, 1, 1)
            modelxsect1 = flopy.plot.PlotCrossSection(model=self.mf, line={'Row': int((grid_model.shape[1])/2)})
            # modelxsect.plot_array(self.hk, ax=axs[0], cmap='viridis')
            pc1 = modelxsect1.plot_array(self.hk, masked_values=[-9999], cmap='viridis', alpha=0.5, ax=axs[0])
            linecollection1 = modelxsect1.plot_grid(ax=axs[0])
            axs[0].set_title('Row, K')
            axs[0].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
            
            # fig = plt.figure(figsize=(10, 5))
            # ax = fig.add_subplot(1, 1, 1)
            modelxsect2 = flopy.plot.PlotCrossSection(model=self.mf, line={'Column': int((grid_model.shape[2])/2)})
            # modelxsect.plot_array(self.ps, ax=axs[0], cmap='plasma')
            pc2 = modelxsect2.plot_array(self.ps, masked_values=[-9999], cmap='plasma', alpha=0.5, ax=axs[1])
            linecollection2 = modelxsect2.plot_grid(ax=axs[1])
            axs[1].set_title('Column, θ')
            axs[1].set_ylim(np.nanmin(np.ma.masked_equal(self.dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(self.dem, -9999, copy=False)))
            
            fig.suptitle(self.model_name.upper(), y=1.05, fontsize=8)

    #%% PROCESSING
    
    def processing(self,
                   write_model=True,
                   run_model=False):
        
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
    
    def post_processing(self, model_modflow,
                        watertable_elevation=True,
                        watertable_depth=True, 
                        seepage_areas=True,
                        outflow_drain=True,
                        groundwater_flux=True,
                        groundwater_storage=True,
                        accumulation_flux=True,
                        export_all_tif=False):
        
        # Create folders        
        self.save_file = os.path.join(self.full_path, '_postprocess')
        toolbox.create_folder(self.save_file)        
        
        self.figure_file = os.path.join(self.full_path, '_postprocess', '_figures')
        toolbox.create_folder(self.figure_file)
        
        self.temporary_file = os.path.join(self.full_path, '_postprocess','_temporary')
        toolbox.create_folder(self.temporary_file)
        
        self.tifs_file = os.path.join(self.full_path, '_postprocess', '_rasters')
        toolbox.create_folder(self.tifs_file)

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
        self.dict_groundwater_storage = {}
        self.dict_residence_times = {}
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
                    toolbox.export_tif(self.dem_path, self.wt_elev, -9999, output_path)
                self.dict_watertable_elevation[item] = self.wt_elev
            
            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = self.dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                # self.wt_depth.to_hdf(self.dict_watertable_depth, lead_numb)
                output_path = self.tifs_file+'/watertable_depth_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.wt_depth, -9999, output_path)
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
                    toolbox.export_tif(self.dem_path, self.seep_area, -9999, output_path)
                self.dict_seepage_areas[item] = self.seep_area
            
            if outflow_drain == True:
                ### Outflow drain
                self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)            
                self.out_all = np.ones((1, self.dis.nrow, self.dis.ncol))
                sim = 0
                count = 0
                for i in range(0, self.dis.nrow):
                    for j in range(0, self.dis.ncol):
                        self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                        count = count + 1
                self.out_drn = self.out_all[0]
                self.out_drn[self.dem_mask] = -9999
                # self.out_drn.to_hdf(self.dict_outflow_drain, lead_numb)
                output_path = self.tifs_file+'/outflow_drain_t('+lead_numb+').tif' 
                if accumulation_flux==True:
                    toolbox.export_tif(self.dem_path, self.out_drn, -9999, output_path)
                else:
                    if export_tif==True:
                        toolbox.export_tif(self.dem_path, self.out_drn, -9999, output_path)
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
                    self.flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                # self.gw_flux.to_hdf(self.dict_groundwater_flux, lead_numb)
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.flux_top, -9999, output_path)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                # self.wt_sto = ( self.wt_sto - (self.dem-self.thick) ) * (self.resolution**2) * self.porosity
                self.wt_sto = ( self.wt_sto - self.zbot[-1] ) * (self.resolution**2) * self.porosity
                output_path = self.tifs_file+'/groundwater_storage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.wt_sto, -9999, output_path)
                self.dict_groundwater_storage[item] = self.wt_sto
                # if time == 0:
                #     self.sto = np.ones((1, self.dis.nrow, self.dis.ncol)) * np.nan
                # else:
                #     self.sto = self.cbb.get_data(text='STORAGE', kstpkper=self.kstpkper, totim=time)[0]
                # self.gw_storage = self.sto.copy()
                # self.dict_groundwater_storage[item] = self.gw_storage

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
            np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        if accumulation_flux == True:
            np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)

#%% NOTES
