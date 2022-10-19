# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

# Modules
import flopy
import numpy as np
import os
import pandas as pd
import sys
import imageio                           # Import raster to numpy matrix (not georeferenced but handy)
from os.path import dirname, abspath
from osgeo import gdal                   # Gdal: referenced rasters (complex objects)
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import geopandas as gpd
import glob
from matplotlib.collections import LineCollection

import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from tools import toolbox

# Surface routing 
from surface_flow import routing_accflux

#%% CLASS

class Modflow():
    """
    
    Preprocessing, processing and postprocessing of modflow (groundwater flow)
        Discretization: by default, the number of rows and columns is the DEM discretization
        
    Simulation on a model given by its DEM for close subsurface saturated flows
        Prepares and runs the model for conditions of significant interactions with the surface
        
    Spatio-temporal discretizations are given 
        - By the DEM for the spatial discretization 
        - By the recharge for the temporal discretization 
        
    Recharge can be
        - Steady
        - Transient following some climatological conditions
        - Transient with synthetic forcings
    
    Initial conditions are
        - steady-state with the mean or last recharge value within the chronicle
        - an imposed value externally from the simulation 
        
    Boundary condtions are 
        - No flow on the side boundaries
        - Seepage on the surface
        - Imposed head on specific zone (sea-level boundary condition)
    
    Sink/Source Term 
    #ALEXANDRE: is it technically a sink/source term or a boundary condition?
        - Recharge imposed on the surface
    
    Model Properties (hydraulic conductivity and porosity)
        - Laterally: Homogeneous or Heterogeneous (defined by zones)
        - Vertically: Homogeneous or Layered 
    
    Source terms
        Between the two possibilities (evt and rch, rch should rather be used)
        - Negative recharge values (P-E): ETP managed as a pumping term 
        - Positive recharge values (P-E): Recharge to the aquifer
    
    Methods
    -------
    Preprocessing: 
        Model construction from 
            - domain definition
            - boundary conditions
            - initial conditions
            - parameter values
        
    Processing: 
        Runs the modflow once modeled has been parameterized
        
    Postprocessing: 
        Exports Tiff and Raster files from specific modflow files 
        Raster will be re-read in another script 

    Attributes, public
    -------------------
    mf: class specific to "flopy"
        Modflow model (custom object impossible to edit with spyder)
        
    nwt: class of flopy 
        Details of the nwt version of modfow used (flopy format)
        Contains all numerical parameters of the simulation (e.g. tolerances, max number of iterations)
        
    Domain definition, hydraulic properties and discretization 
    ----------------------------------------------------------

    - 2D LATERAL

    geographic: class Geographic
        Model geometry (eg DEM path)
        
    dem: np array
        DEM for the zone studied
        
    dem_path: string
        path = directory + file name of the DEM
        
    nrow: int
        number of rows (derived from DEM resolution)
        
    ncol: int 
        number of columns (derived from DEM resolution)
    
    resolution: float
        Resolution of the discertization
        EQUAL TO THAT OF THE DEM (geographic)
        
    sink_fill: bool
        Should it fill the holes in the DEM that mess the groundwater flow simulations
        Difition of the hole in the DEM: convergence of flow lines to a cell (endoreism)
        It should be checked that the filling of the sinks lead to a new dem (is it intended?)
            
    sink:
        Parameters of the hole
    
    multip_cond: vector of floats
        Multiple hdyraulic conductivies for the simulation of heterogeneous domains
        
    xul: float
        xmin for the domain to simulate
            
    yul: float
        ymax for the domain to simulate
            
    hyd_cond: matrix class:`numpy.ndarray` (:data:`nrow`, :data:`ncol`) 
        - homogeneous : float
        - heterogeneous : numpy array (same size as the dem)
        -- initial value: :data:`hyd_cond_init`
        only 2D, generalization 3D in the script specific to modflow
        
    porosity: (:data:`nrow`, :data:`ncol`) 
        - homogeneous : float
        - heterogeneous : numpy array (same size as the dem)
        -- initial value: :data:`porosity_init`
        :vartype porosity: :class:`numpy.ndarray`
        
    - VERTICAL

    thick: float
        aquifer thickness () 
        
    thick_exp: float
        Exponential increase of the mesh thickness
        Default value: 1, exponential decay not activated 
        Hydraulic conductivies are calculated in flowpy
        
    bottom: float
        == None : constant thickness of the aquifer equal to attribute "thickness"
        other value: flat bottom which altitude is equal to "bottom" (reference: m NGF)
                
    nlay: int
        number of layers 
    
    cond_decay: float
        Exponential decay thickness of the hydraulic conductivity (only, not porosity)
        Default value: 0, exponential decay not activated 
        K = Ksurface * exp (- cond_decay * z)
        
    verti_k: vector of floats
        Applies different hydraulic conductivities with layers 
        Default: None
        
    zbot: np matrix of floats
        altitude of bottom for each of the dem cells
        
    laytype: 2D np array
        cells where water can seep (by default, all the domain)
    
    Hydraulic properties (discretized)
    ----------------------------------
    hK: 3D np array 
        hydraulic conductivity discretized on the grid

    hK: porosity
        hydraulic conductivity discretized on the grid 
        
    Boundary Conditions
    -------------------
    bc_left: flopy class
        Boundary conditions 
        
    bc_right: flopy class
        Boundary conditions 
    
    sea_level: float or series (set as a climatic chronicle)
        constant sea level (no transience: # JR: To check)
                            
    iboundData: 3D np array
        one value per cell (flopy coding)
        -1: Constant head (null flux)
         0: Inactive Cell (no flow)
        +1: Active Cell 
        
    strtData: 3D np array
        Value affected to the boundary condition
        = Altitude 
    
    Sink/Source Terms
    -----------------
    init_rech: string of float 
        == "mean" : takes the mean value and applies it as the first value of forcing
        == "first": takes the first value and applies it as the first value of forcing
        == float : recharge value
        Initial recharge applied on the first time step
        Used for synthetic simulation to determine drainage time of aquifer
        
    climatic: float
        Recharge applied to the model 
        By defaut, in steady state, a value
        Otherwise pandas series given by a database (eg SURFEX)
        
    evt: class climatic
        Package to apply evapotranspiration directly to the saturation of the groundwater
        
    Time definition and discretization 
    ---------------------------------- 
    nper: vector of int
        Number of forcing periods (recharge)
        
    perlen: float
        Length of period
    
    nstp: vector of float
        Steps in a given period (not used here)
        
    steady: vector of bool 
        Is simulation in steady state
        
    start_datetime: float
        First date of climatic recharge
        
    """

    #%% INIT

    def __init__(self, geographic, sink_fill = False, box=True,
                 climatic=8e-4, lay_number=1, thick=50,
                 bottom=None, thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, 
                 sea_level=None, cond_decay=0., multip_cond=None, init_rech='mean',
                 bc_left=None, bc_right=None, verti_k=None,
                 model_name='modflow_model',
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):
        """
        
        Constructor
 
        Arguments
        ----------
        geographic: class Geographic
            Model geometry (eg DEM path)
            
        sink_fill: bool 
            Fills the holes in the DEM
            Smoothens the DEM to avoid small scale holes
            = true : modifies the way drainace is implemented 
            
        box: bool 
            Specifies if the studied watershed is embedded in a rectangle 
            
        climatic: float
            Recharge applied to the model 
            By defaut, in steady state, a value
            Otherwise pandas series given by a database (eg SURFEX)
        
        lay_number: int
            Number of layers (vertical discretization)
            
        thick: float
            aquifer thickness () 
        
        cond_decay: float
            Exponential decay thickness of the hydraulic conductivity (only, not porosity)
            Default value: 0, exponential decay not activated 
            K = Ksurface * exp (- cond_decay * z)
            
        thick_exp: float
            Exponential increase of the mesh thickness
            Default value: 1, exponential decay not activated 
            Hydraulic conductivies are calculated in flowpy
            
        hyd_cond: matrix class:`numpy.ndarray` (:data:`nrow`, :data:`ncol`) 
            -- initial value: :data:`hyd_cond_init`
            only 2D, generalization 3D in the script specific to modflow
            
        porosity: (:data:`nrow`, :data:`ncol`) 
            -- initial value: :data:`porosity_init`
            :vartype porosity: :class:`numpy.ndarray`
        
        nlay: int
            number of layers 
            
        bottom: float
            == None : constant thickness of the aquifer equal to attribute "thickness"
            other value: flat bottom which altitude is equal to "bottom" (reference: m NGF)

        model_folder: string
            Folder where results will be stored
        
        model_name: string
            id of the model (model configuration + hour/date)
            
        sea_level: float or series (set as a climatic chronicle)
            constant sea level (no transience: # JR: To check)
                                
        init_rech: string of float 
            == "mean" : takes the mean value and applies it as the first value of forcing
            == "first": takes the first value and applies it as the first value of forcing
            == float : recharge value
            Initial recharge applied on the first time step
            Used for synthetic simulation to determine drainage time of aquifer
        
        bc_left: flopy class
            Boundary conditions 
            
        bc_right: flopy class
            Boundary conditions 
            
        verti_k: vector of floats
            Applies different hydraulic conductivities with layers 
            Default: None
            
        """
        
        #%% Initialization

        self.model_name = model_name
        self.model_folder = model_folder
        self.exe = exe
        self.full_path = os.path.join(model_folder, model_name) #'modraw'
        
        #%% Domain definition 
        
        self.thick = thick
        self.thick_exp = thick_exp
        self.geographic = geographic
        self.resolution = geographic.resolution
        self.sink_fill = sink_fill
        self.multip_cond = multip_cond
        
        try : 
            self.sink = geographic.depressions_data
        except:
            pass
        
        self.bottom = bottom
        self.nlay = lay_number
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        
        # if sea_level == None:
        # Enlarges the modeled domain
        if box == True:
            self.dem = geographic.dem_box_data  
            self.dem_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_path = geographic.watershed_buff_dem
        
        #%% Boundary conditions
        
        self.bc_left = bc_left
        self.bc_right = bc_right
        self.sea_level = sea_level 
        
        #%% Source/Sink terms
        
        self.init_rech = init_rech
        if isinstance(climatic, float) == False :  
            self.climatic = climatic.copy()
        else: 
            self.climatic = climatic
                
        #%% Model parameters 
        
        self.verti_k = verti_k
        self.hyd_cond = hyd_cond
        self.porosity = porosity
        self.cond_decay = cond_decay

    #%% PRE-PROCESSING

    def pre_processing(self, verbose=False):
        """
        
        Prerpocessing
            - 3D Discretization by flopy of the domain according to the DEM and to the vertical discretization
 
        Arguments
        ----------
        verbose: bool 
            Displays messages in command window
            
        """
        
        #%% Initialization
        
        if verbose == True:
            print('Build model')
            
        # Flopy initialization of Modflow model
        self.mf = flopy.modflow.Modflow(self.model_name, 
                                        exe_name=self.exe, version='mfnwt', listunit=2, verbose=False,
                                        model_ws=self.full_path) # external_path=self.full_path
        
        # Uses Nwt for Modflow 2005, necessary for unconfined aquifers (improved interactions between surface and aquifer)
        # Sets up numerical parameters 
        self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                            thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1, options='COMPLEX',
                                            Continue=False, backflag=0) # ibotav=0
        
        # Preprocess conductivity values 
        #ALEXANDRE
        try:
            # For heterogeneous cases of hydraulic conducitivy, inactivation of part of the dem 
            # Should still be checked: is it still used? Remove? 
            if len(self.hyd_cond)!=1:
                self.dem[self.hyd_cond<0]=-9999
        except:
            pass

        #%% Discreitzation
        
        # Time step is driven by recharge
        
        if isinstance(self.climatic,(int,float))==True:
            # Steady state
            self.nper = 1               # Number of forcing periods (recharge)
            self.perlen = 1             # Length of period
            self.nstp = [1]             # Steps in a given period (not used here)
            self.steady = True          # Steady state
            self.start_datetime = None
        else:
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

        # Model Domain definition and discretization 
        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = self.dem.shape[0]
        self.ncol = self.dem.shape[1]
        
        # Bottom definition for each of the layers 
        self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
        if self.bottom is None:
            bottom_layer = self.dem - self.thick    # Matrix for constant thickness case
        else:
            bottom_layer = self.bottom              # Float for flat bottom case

        # Modification of layer thickness for exponentially decreasing hydraulic conductivity cases
        if self.thick_exp != 1.:
            exp_scale = 1-self.thick_exp**self.nlay
    
        # p: evoling proportions of bottom layer to surface values
        for i in range(1, self.nlay+1):
            if self.thick_exp == 1.:
                p = i / self.nlay    # Uniform thicknesses
            else:
                p = (1-self.thick_exp**i) / exp_scale   # Increasing thicknesses with depth
            # Weighted formula to go from bottom_layer to surface (self.dem)
            self.zbot[i-1] = bottom_layer * p + self.dem * (1-p)
        
        '''
        if self.verti_k != None:
            self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
            # self.zbot[0,:,:] = self.dem - self.verti_k[1][0]
            # self.zbot[1,:,:] = bottom_layer
            for i in range(len(self.verti_k[1])):
                self.zbot[i,:,:] = self.dem - self.verti_k[1][i]
            self.zbot[-1,:,:] = bottom_layer
        '''
            
        # Imposes discretization to modflow model through flopy
        self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, 
            delr=self.resolution, delc=self.resolution, top=self.dem.data, 
            botm=self.zbot, itmuni=4, lenuni=2, nper=self.nper, perlen=self.perlen, 
            nstp=self.nstp, steady=self.steady, xul=self.xul, yul=self.yul,
            start_datetime=self.start_datetime) # itmuni = 0 ==> undefined
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
        if  isinstance(self.bc_left,(int,float)) == True:
           self.iboundData[:,:,0] = -1                      
           self.strtData[:,:,0] = self.bc_left
       
        # SYNTHETIC CASE: FIXED HEAD ON THE RIGHT BORDER (square domain), no longer actively used
        if  isinstance(self.bc_right,(int,float)) == True:
           self.iboundData[:,:,-1] = -1
           self.strtData[:,:,-1] = self.bc_right
           
        # NO FLOW BOUNDARY CONDITIONS 
        for i in range (self.nlay):
            if isinstance(self.sea_level,(int,float)) == True:
                self.iboundData[i][self.dem <= self.sea_level] = -1
                self.strtData[self.iboundData == -1] = self.sea_level
            self.iboundData[i][self.dem < -1000] = 0     # O is for NO FLOW               

        self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)
            
        ### Constant Head boundary conditions of No Flow (at sea level)
        
        if self.sea_level != None:
            package = np.zeros((self.nper,self.nrow, self.ncol))
            if isinstance(self.sea_level,(int,float)) == False:
                self.chdData = {}
                for kper in range(0, self.nper):
                    chdKper = []
                    for i in range (0,self.nrow):
                        for j in range (0, self.ncol):
                            if self.dem[i,j] < self.sea_level[kper]:
                                package[kper,i,j] = 1
                                chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
                            self.rchData[kper] = chdKper
                                    
        #%% Parametrization
        
        # lpf package
        self.laywet = np.zeros(self.nlay)
        self.laytype = np.ones(self.nlay)

        # Necessary to give hydraulic conductivity: 3D matrix of hydraulic conductivities
        # Homogeneous or heterogeneous hydraulic conductivity 
        # self.hyd_cond is either a scalar (for homogeneous cases) or a 2D array (for heterogeneous cases)
        self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hyd_cond
        
        if self.cond_decay != 0.:
            depth = np.zeros(self.hk.shape)
            depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
            self.hk *= np.exp(-self.cond_decay*depth)
            
        # Depth-dependent hydraulic conductivity (disconnected from the vertical discretization)
        if self.verti_k != None:
            for j in range(len(self.verti_k)):
                # print('j', j)
                for i in range(len(self.zbot)):
                    # print('i', i)
                    k_val = self.verti_k[j][0]
                    d1 = self.verti_k[j][1][0]
                    d2 = self.verti_k[j][1][1]
                    cond_d1 = (self.dem - d1)
                    cond_d2 = (self.dem - d2)
                    mask = ((self.zbot[i] <= cond_d1) & (self.zbot[i] >= cond_d2))
                    self.hk[i][mask] = k_val
                    # print(k_val)
               
        #ALEXANDRE: should it be put again in the code without comments? 
        '''
        for i in range(0,len(self.number_structure)):
            for j in range(0,nlay):
                self.hk[j][self.structure.geology==self.number_structure[i]]= logParamValue[i]*3600*24
		   '''
           
        """
        if self.verti_k != None:
            Kv = np.zeros((self.nlay,self.nrow,self.ncol))
            # Kv[0,:,:] = self.verti_k[0][0] #first layer of lime
            # Kv[1,:,:] = np.mean(self.hk) #second layer of sand
            for i in range(len(self.verti_k[0])):
                Kv[i,:,:] = self.verti_k[0][i]
            Kv[-1,:,:] = np.mean(self.hk)
            self.hk = Kv.copy()
        """
        
        self.upw = flopy.modflow.ModflowUpw(self.mf, iphdry=1, hdry=-100, 
                                            laytyp=self.laytype, laywet=self.laywet, 
                                            hk=self.hk,
                                            vka=1, sy=self.porosity, noparcheck=False, extension='upw', unitnumber=31)
        
        
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
            if verbose == True:
                print('ETR activated')
                # print(self.evt)
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
                    self.rchData[kper] = np.nanmean(self.climatic)
                    if self.init_rech == 'first':
                        # First value of the cimatic chronicle
                        self.rchData[kper] = self.climatic.iloc[0]
                        print('Init rech is "first"')
                    if isinstance(self.init_rech,(int,float)):
                        # Imposed value (if steady state: just one value)
                        self.rchData[kper] = self.init_rech
                        print('Init rech is "a value"')
                else:
                    # More flexibility in the possible format of the climatic chronicles 
                    # Should only be used exceptionnaly (pandas series recommended)
                    try:
                        self.rchData[kper] = self.climatic[kper]
                    except:
                        self.rchData[kper] = self.climatic.iloc[kper].values[0]
        if verbose == True:
            print('REC')
            # print(self.climatic)
        # Sets recharge to modflow through flopy
        self.rch = flopy.modflow.ModflowRch(self.mf, rech=self.rchData)
                
        #%% Drain package
        
        # (DRN)
        # Applied to all the surface of the model : enables seepage on the top layer
        
        self.drnData = np.zeros((self.nrow*self.ncol, 5))
        compt = 0
        # First value (0): layer number
        self.drnData[:, 0] = 0 # layer
        for i in range (0,self.nrow):
            for j in range (0, self.ncol):
                self.drnData[compt, 1] = i # Second value (1): row number
                self.drnData[compt, 2] = j # Third value (2): column number
                self.drnData[compt, 3]= self.dem[i, j] # Fourth value (3): altitude
                # Fifth value (4): value of the conductivity of the drain (integrated over the surface of the cell)
                if self.sink_fill == False:
                    if self.multip_cond != None:
                        #ALEXANDRE: pourquoi self.multip_cond utilisée ici aussi, faut-il modifier pour avoir 2 noms de variables différents? 
                        self.drnData[compt, 4] = self.multip_cond 
                    else:
                        self.drnData[compt, 4] = self.hk[0, i, j] * self.resolution** 2
                else:
                    if self.sink[i,j]>0:
                        #ALEXANDRE: when filled, no possible drains, why?
                        self.drnData[compt, 4] = 0
                    else:
                        if self.multip_cond != None:
                            self.drnData[compt, 4] = self.multip_cond 
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
        """
        fig = plt.figure(figsize=(10, 5))
        ax = fig.add_subplot(1, 1, 1)
        modelxsect = flopy.plot.PlotCrossSection(model=self.mf, line={'Row': int((self.hk.shape[1])/2)})
        linecollection = modelxsect.plot_grid()
        modelxsect.plot_array(self.hk)
        """
        
    #%% PROCESSING
    
    def processing(self, verbose=False):
        if verbose == True:
            print('Simulation d\'un modèle')
        # write input files
        self.mf.write_input()
        # run model
        succes, buff = self.mf.run_model(silent=not verbose)# True without msg
        return succes
        
    #%% POST-PROCESSING
    
    def post_processing(self, first_only = False,
                              watertable_elevation = True, watertable_depth=True, 
                              seepage_areas = True, outflow_drain = True,
                              groundwater_flux = True, specific_discharge = False,
                              accumulation_flux = True, perenn_intermit_shp = False,
                              groundwater_storage = False, residence_times = False,
                              verbose = True, export_tif = True):
        # self.wt_elev = []
        # self.wt_depth = []
        # self.seep_area = []
        # self.out_drn  = []
        # self.gw_flux = []
        # self.spe_disch = []
        # self.flux_top = []
        
        if verbose == True:
            print('Extract results of the simulation')
        
        # Create folders        
        self.save_file = os.path.join(self.full_path, '_watershed')
        toolbox.create_folder(self.save_file)        
        
        self.figure_file = os.path.join(self.full_path, '_figures')
        toolbox.create_folder(self.figure_file)
        
        self.surfaceflow_file = os.path.join(self.full_path, '_watershed','_surfaceflow')
        toolbox.create_folder(self.surfaceflow_file)
        
        self.tifs_file = os.path.join(self.full_path, '_watershed', '_tifs')
        toolbox.create_folder(self.tifs_file)
        
        #%% Model parameters
        
        self.path_file = os.path.join(self.full_path, self.model_name)
        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1) # ==> time
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1
        self.rechval = self.rch.rech[0][0,0]
        col = ['nrow','ncol','res','nlay','nper','rech','hk','sy']
        var = [self.nrow,self.ncol,self.resolution,self.nlay,self.nper,
               np.mean(self.rechval),np.mean(self.hyd_cond),np.mean(self.porosity)]
        params = pd.DataFrame(var).T
        params.columns = col
        params = params.round(3)
        self.params = params
        self.params.to_csv(self.full_path+'/_model_parameters.txt', sep=';', index=False)

        #%% Import essential data 
        
        # Modflow specific files (written in the processing phase)
        
        # Files have been output in the processing phase and are re-read here
        self.dem_mask = (self.dem<-4000)  # 4000 meters (sure no DEM value below: equivalent to no data value)
        # heads
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds') 
        # fluxes
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')
        # self.zcbc
        
        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        # Stress periods (flopy "language")
        if len(self.times) == 1:
            self.kstpkper = self.kstpkper[0]
             
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
        self.list_traces = []
        
        # self.dict_watertable_elevation = (self.save_file+'/watertable_elevation'+'.h5')
        # self.dict_watertable_depth = (self.save_file+'/watertable_depth'+'.h5')
        # self.dict_seepage_areas = (self.save_file+'/seepage_areas'+'.h5')
        # self.dict_outflow_drain = (self.save_file+'/outflow_drain'+'.h5')
        # self.dict_groundwater_flux = (self.save_file+'/groundwater_flux'+'.h5')
        # self.dict_specific_discharge = (self.save_file+'/specific_discharge'+'.h5')
        # self.dict_accumulation_flux = (self.save_file+'/accumulation_flux'+'.h5')
        
        if verbose == True:
            print('Post-processing in progress')
        
        # Loop over times, fills each of the previous structures 
        for item, time in enumerate(self.times):
            if verbose == True:
                print('     Time : ', item)
                     
            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])
            
            # lead_numb = "%03d" % (item,)
            lead_numb = str(item)
            
            if first_only==True:
                if item>0:
                    export_tif=False
            
            # Watertable data
            # if self.nlay > 1:
            #     self.head_all = self.head_fpu.get_alldata() # mflay=None
            #     self.head_data = self.head_all[item][0]
            # else:
            #     self.head_data = self.head_fpu.get_data(totim=time)
            #     self.head_data = self.head_data[0]
            
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
            # print(self.head_data.shape)
            
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
                # Outflow data
                self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
            
                ### Outflow drain
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
                # Groundwater data
                self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
                self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
                self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
                if self.nlay == 1:
                    self.flux = np.sqrt(self.frf**2 + self.fff**2)        
                if self.nlay > 1:
                    self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
                    self.flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
            
                ### Groundwater flux
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                # self.gw_flux.to_hdf(self.dict_groundwater_flux, lead_numb)
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.flux_top, -9999, output_path)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                # Groundwater data
                # print(self.kstpkper)
                
                # if time == 0:
                #     self.sto = np.ones((1, self.dis.nrow, self.dis.ncol)) * np.nan
                # else:
                #     self.sto = self.cbb.get_data(text='STORAGE', kstpkper=self.kstpkper, totim=time)[0]
                # self.gw_storage = self.sto.copy()
                # self.dict_groundwater_storage[item] = self.gw_storage
                
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                self.wt_sto = ( self.wt_sto - (self.dem-self.thick) ) * (self.resolution**2) * self.porosity
                self.dict_groundwater_storage[item] = self.wt_sto
                
                # np.count_nonzero(~np.isnan(dem))
                # self.gw_sto = np.nansum(self.wt_sto)
            
            if specific_discharge == True:                
                ### Specific discharge
                # Import data
                if self.nlay == 1:
                    self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, None), self.mf, self.wt_elev.copy())
                if self.nlay > 1:
                    self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, self.flf), self.mf, self.wt_elev.copy())            
                self.specif_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
                self.specif_disch_top = self.specif_disch[0]
                self.specif_disch_top[self.dem_mask] = -9999
                # self.specif_disch.to_hdf(self.dict_specific_discharge, lead_numb)
                output_path = self.tifs_file+'/specific_discharge_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.specif_disch_top, -9999, output_path)
                self.dict_specific_discharge[item] = self.specif_disch_top

            if residence_times == True:
                print('residence_times')
                # path_file = "D:/Users/abherve/DYNAMIC/Lasset/results_simulations/case4_0.05500000000000001/case4_0.05500000000000001"
                # res_time = np.zeros(np.shape(imageio.imread(BV.geographic.watershed_dem)))
                # pthobj = flopy.utils.PathlineFile(self.path_file+'.mppth')
                # pth_data = pthobj.get_alldata()
                res_time = np.zeros(np.shape(self.dem)) * np.nan
                endobj = flopy.utils.EndpointFile(self.path_file+'.mpend')
                e = endobj.get_alldata()
                for k in range(len(e)):
                    # time_out = pth_data[j].time[0] # explore pathlines
                    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
                    # res_time[e[j].i,e[j].j] = np.log10(e[j].time) # where outputed
                    res_time[e[k].i,e[k].j] = (e[k].time) / 365 # where outputed in years
                if export_tif==True:
                    output_path = self.tifs_file+'/residence_times_t('+lead_numb+').tif'
                    toolbox.export_tif(self.dem_path, res_time, -9999, output_path)
            
                # if zone_bud == True:...
                    
                
            # Surface flow activation
            surface_flow = routing_accflux.RoutingAccflux(self.geographic,
                                                          'outflow_drain_t('+lead_numb+').tif',
                                                          'tracept_t('+lead_numb+').shp',
                                                          'accumulation_flux_t('+lead_numb+').tif',
                                                          extraction_folder=self.save_file)
            
            if accumulation_flux == True:
                ### Accumulation flux
                surface_flow.trace_cumulated()
                output_path = self.tifs_file+'/accumulation_flux_t('+lead_numb+').tif'
                try:
                    self.dict_accumulation_flux[item] = imageio.v2.imread(output_path) #replaces former 'imageio.imread(output_path)' [MARTIN 20/09/2022]
                except:
                    self.dict_accumulation_flux[item] = imageio.imread(output_path)
                    pass
                
            if perenn_intermit_shp == True:
                surface_flow.trace_downslope()
        
        # Save dictionaries to npy
        try:
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
            if specific_discharge == True:   
                np.save(self.save_file+'/specific_discharge', self.dict_specific_discharge)
            if groundwater_storage == True:
                np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        except:
            pass
        
        try:
            if accumulation_flux == True:
                np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)
        except:
            pass
        
        if perenn_intermit_shp == True:
            self.list_traces = sorted(glob.glob(self.surfaceflow_file+'/'+'tracept_t*.shp'), key=os.path.getmtime)
            # print(self.list_traces)
            cpt = 1
            inf = 0
            sup = 12
            step = int(round(len(self.list_traces)/12))
            for i in range(step):
                interv = self.list_traces[inf:sup]
                coord = []
                print('Check intermittency : '+str(cpt)+'/'+str(step))
                for file in interv:
                    outflow = gpd.read_file(file)
                    x_list = outflow.geometry.x
                    y_list = outflow.geometry.y
                    mix = list(zip(x_list, y_list))
                    coord.extend(mix)
                dfc = pd.DataFrame(coord, columns=['x','y'])
                dfc['z'] = dfc['x'].astype(str) + dfc['y'].astype(str)
                values = dfc['z'].value_counts()
                values = values[values>=12]
                for bis in interv:
                    outflow = gpd.read_file(bis)
                    outflow['x'] = outflow.geometry.x
                    outflow['y'] = outflow.geometry.y
                    outflow['z'] = outflow['x'].astype(str) + outflow['y'].astype(str)
                    val = 0
                    outflow['Persistanc'] = val
                    for xy in values.index:
                        val = 1
                        outflow.loc[outflow['z']==xy,'Persistanc'] = val
                    outflow.to_file(bis)
                inf+=12
                sup+=12
                cpt+=1

#%% NOTES

            