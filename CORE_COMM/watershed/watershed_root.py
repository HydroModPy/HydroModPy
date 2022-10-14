# -*- coding: utf-8 -*-
"""

Created on Thu Sep  9 14:52:56 2021

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Modules
import os
import pandas as pd
import pickle
import sys
from os.path import dirname, abspath
data_dir = os.path.join(dirname(abspath(__file__)),'data')
sys.path.append(data_dir)
root_dir = dirname(abspath(__file__))
sys.path.append(root_dir)

# HydroModPy modules
#from watershed.data import  climatic, oceanic, piezometry, hydrology
import climatic, drias, oceanic, piezometry, hydrology, geology, hydrometry, intermittency
from groundwater_flow import modflow, modpath, modflow_results
from tools import toolbox
from watershed import forcing, geographic, hydrodynamic, watershed_display
from calibration import calib_dichotomy

#%% CLASS

class Watershed :
    """
    
    class Watershed is used to extract watershed and its data from regional DEM
        Hub to all elements necessary or optional to construct watersheds (meaning catchements) and run modflow simulations
    
    Attributes, public
    -------------------
    watershed_name: str 
        Name of the watershed
        
    watershed_def_option: str
        Option for the definition of the Watershed 

    from_shp: str   #RONAN: from_dem_file
        Path to the shapefile that will be used as "Watershed"
        With such an option, Watershed is not generated but loaded from the file
    
    from_dem: boolean
        Uses DEM instead of shapefile
        True if the process start from a given DEM of xyz file
        Cases where domain is not georeferenced (e.g. synthetic geometry, erosion models)
        
    cell_size: float
        Modifies the resolution of the DEM, a new value rather than the DEM resolution

    outlet_def_option: str #RONAN
        Method to define the watershed outlets 

    from_xy: list of floats
        Definition of the outlets directly with the list of coordinates (floats)
        
    library_path: str  #RONAN: from_library_file
        definition of the outlets of the watershed loaded from watershed_library.csv file.
        
    elt_def: list of names
        List classes that have been instantiated (hydrodynamic, geology....)
    
    Subsurface properties
    ---------------------
    hydrodynamic: class Hydrodynamic (COMPULSORY to run modflow simulations, not necessary to generate watershed by clipping)
        hydrodynamic properties (hydraulic conductivity, porosity, reservoir thickness, exponential decrease)
    
    geology: class Geology
        lateral ("2D") geological description (loaded from the database, clipped at the watershed scale)
        hydrodynamic class will be defined according from the geological description (through common indexes)
        
    piezometry: class Piezometry
        Ensemble of piezometers for which data are provided (sofar from ADES-BRGM database)
    
    Surface properties
    ------------------
    hydrology: class Hydrology
        Hydrographic network, clipped from a database like BD-TOPAGE
        format: Humid zones (polygones), streams (polylines), landslides, sources, wells (points), raster
        
    hydrometry: class Hydrometry
        Hydrological stations within the considered watershed from a French specific shapefile avialable from internet
    
    intermittency: class Intermittency
        Intermittent streams from "onde" network obtained from public database avialable from internet 
        Specific shapefile
        Point based (from individual stations)
        
    subbasin: class Subbasin
        Catchments defined from the existing hydrologic stations = hydrometry + intermittency + points of interest
        points of interest are given in a text file (defined in the class)
    
    Atmospheric
    -----------
    forcing: class Forcing (COMPULSORY to run modflow simulations, not necessary to generate watershed by clipping)
        Recharge chronicle at the entry of modflow (permanent or transient, surfex or drias data)
        Not spatialized (same recharge everywhere, mean of the recharge over the watershed)
        Rechargemay not be linked to surfex or drias, may be generated synthetically

    climatic: class Climatic
        netCDF et h5 climatic data obtained from surfex clipped to the defined watershed
        
    drias: class Drias
        netCDF et h5 climatic data obtained from drias clipped to the defined watershed
    
    Oceanic
    -------
    oceanic: class Oceanic
        sea level chronicles (loaded from "maregraph" data)
        may be a direct input to the model

    
    METHODS PUBLIC
    --------------
    constructor: 
        Stores options
        (Loads or Generates) and saves watershed
        Geographic will be loaded or created in all cases
        Other classes (hydrology, hydrodynamic...) will only be loaded if previously stored, otherwise they will not be filled
        
    add_forcing: 
        Creates forcing and adds it to the class members
        
    add_...
        Creates "..." and adds it to the class members
        
    run_modflow 
        Build and run modflow model
        
    matrix_modflow
        postprocessing modflow results (handle to another function)
    
    results_modflow
        Process Modflow results to provide targetted temporal chronicles (storage included)
        
    display
        Display watershed figure
    
    METHODS PRIVATE
    --------------       
    define_watershed_charac: 
        Load watershed informations from watershed.csv file
    
    load_object:
        Loads pwatershed when it has already been generated (Uses pickle)
        
    create_object:
        Creates watershed by defining geographic
        
    save_object:
        Saves python object (using pickle)
    
    Read the docs
    -------------
    :param str name: name of watershed.
    :param dem_path: folder of the regional DEM.
    :param out_path: root directory of results.
    :param surfex_path: root directory of surfex data.
    :param oceanic_path: root directory of oceanic data.
    :param geology_path: root directory of geology data.
    :param hydrology_path: root directory of hydrology data.
    :param piezometry_path: download franch piezometric data.
    :param modflow_path: root directory of modflow executable.
    :param save_object: save the watershed object in pickle file.
    :param load: load the pickle file. Doesn't build the watershed object.
    :param types_obs: list of observations data. Only if hydrology_path is not None.
    :param fields_obs: list of observations fields. Only if hydrology_path is not None.
    :ivar str watershed_folder: root directory of results of watershed class
    :ivar add_data_folder: folder if you want add data manually
    :vartype add_data_folder: :class:`str`
    :ivar simulations_folder: root directory of simulation results
    :vartype simulations_folder: :class:`str`
    :ivar stable_folder: root directory of stable results
    :vartype stable_folder: :class:`str`
    :ivar figure_folder: root directory of figures folder
    :vartype figure_folder: :class:`str`
    :ivar elt_def: list of elements in the python object
    :vartype elt_def: :class:`list`
    :ivar geographic: geographic object
    :vartype geographic: :class:`object`
    :ivar hydrodynamic: hydrodynamic object
    :vartype hydrodynamic: :class:`object`
    :ivar forcing: forcing object
    :vartype forcing: :class:`object`
    :ivar climatic: climatic object
    :vartype climatic: :class:`object`
    :ivar hydrology: hydrology object
    :vartype hydrology: :class:`object`
    :ivar oceanic: oceanic object
    :vartype oceanic: :class:`object`
    :ivar geology: geology object
    :vartype geology: :class:`object`
    :ivar piezometry: piezometry object
    :vartype piezometry: :class:`object`
    :ivar x_outlet: x coordinate of the watershed outlet.
    :vartype x_outlet: :class:`float`
    :ivar y_outlet: y coordinate of the watershed outlet.
    :vartype y_outlet: :class:`float`
    :ivar snap_dist: maximum distance snappin of the watershed outlet.
    :vartype snap_dist: :class:`float`
    :ivar buff_percent: percentage of the watershed to build the buffer around it.
    :vartype buff_percent: :class:`float`
    :ivar crs_proj: coordiante system of projection
    :vartype crs_proj: :class:`str`
    :meta public:
        
    """
    
    #%% INIT

    def __init__(self, watershed_name: str, dem_path: str, 
                 out_path: str, library_path: str = os.path.join(root_dir,'watershed_library.csv'), 
                 modflow_path: str = None, save_object: bool = True, load: bool = False,
                 from_shp: str = None, from_dem: bool = False, cell_size: int = 100,
                 from_xy: list = [], regio_out: bool = False):
        """  
        
        Arguments
        ---------
        load: boolean
            True: the watershed should be loaded from the one saved of a previous simulation
            False: the watershed will be generated (and not loaded)
            
        """

        self.watershed_name = watershed_name
        self.library_path = library_path
        
        self.from_shp = from_shp
        self.from_dem = from_dem
        self.from_xy = from_xy
        
        self.cell_size = cell_size
        
        self.dem_path = dem_path
        self.out_path = out_path
        self.modflow_path = modflow_path
                
        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)
        
        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)
        
        self.add_data_folder = os.path.join(self.stable_folder, 'add_data/')
        toolbox.create_folder(self.add_data_folder)
        
        self.figure_folder = os.path.join(self.stable_folder, '_figures/watershed/')
        toolbox.create_folder(self.figure_folder)
        
        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)
        
        self.calibration_folder = os.path.join(self.watershed_folder, 'results_calibration')
        toolbox.create_folder(self.calibration_folder)
        
        if regio_out == True:
            self.regio_path = os.path.join(out_path, '_regional')
            toolbox.create_folder(self.regio_path)
        else:
            self.regio_path = None
        
        self.elt_def = []
        
        success = False
        if load==True:
             # Load from previously stored (saved) watershed
             success = self.load_object()
             print("Object was loaded successfully")
        else: 
             print("Object was not loaded as demanded but created from scratch")
             
        if load==False or success==False: 
            print("Create new object, will removed previousy stored object at the same place")
            # Definition of the watershed
            self.define_watershed_charac()
            # Creation of the watershed defined at the previous line
            self.create_object()
            # Save object
            if save_object == True:
                self.save_object()
        
    #%% PYTHON OBJECT
    
    def define_watershed_charac(self):
        """
        
        Load watershed informations from watershed.csv file
        
        Modifies
        -------
        All characteristics necessary to define watershed    
            x-outlet, y_outlet
            snap_dist, buff_percent
            crs_proj
            
        """
        
        # Conditions that should all be fulfilled to generate watershed from watershed library outlet
        if (self.from_shp == None) & (self.from_dem == False) & (self.from_xy == []) :
            try:
                # Reads the indexed watersheds from the file where they are stored
                watershed_list = pd.read_csv(self.library_path, delimiter=';')
                # Finds the watershed within the list
                watershed_info = watershed_list.loc[watershed_list['watershed_name'] == self.watershed_name]
                self.x_outlet = watershed_info.iloc[0]['x_outlet']
                self.y_outlet = watershed_info.iloc[0]['y_outlet']
                self.snap_dist = watershed_info.iloc[0]['snap_dist']
                self.buff_percent = watershed_info.iloc[0]['buff_percent']
                self.crs_proj = watershed_info.iloc[0]['crs_proj']
            except:
                print("Warning : The name of watershed is not in the watershed list or watershed list does not exist")
                sys.exit()
                return watershed_list
        else:
            # Outlet will be defined later in geographic class (test on x_outlet == None)
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = 5
            self.crs_proj = None
            
            
    def load_object(self):
        """
        
        Loads python object
            Load watershed when it has already been generated
            Uses pickle library to store and load watershed
        
        Modifies
        --------
            All structures of the watershed
            
        Returns
        -------
            sucess: boolean
                watershed has or has not been loaded
                
        """
        
        if os.path.exists(os.path.join(self.watershed_folder, 'python_object')):
            # Test the existence of the stored watershed within the default path name "python_object"
            with open(os.path.join(self.watershed_folder, 'python_object'), 'rb') as config_dictionary_file:
              BV = pickle.load(config_dictionary_file)
            # At least geographic should have been stored
            if ('geographic' in BV.__dir__()) == True:
                self.geographic = BV.geographic
                self.elt_def.append('geographic')
            else:
                print("Warning : geographic doesn't exist in object")
                return False
            # SubSurface (compulsory: hydrodynamic)
            if ('hydrodynamic' in BV.__dir__()) == True:
                self.hydrodynamic = BV.hydrodynamic
                self.elt_def.append('hydrodynamic')
            if ('geology' in BV.__dir__()) == True:
                self.geology = BV.geology
                self.elt_def.append('geology')
            if ('piezometry' in BV.__dir__()) == True:
                self.piezometry = BV.piezometry
                self.elt_def.append('piezometry')
            # Surface
            if ('hydrology' in BV.__dir__()) == True:
                self.hydrology = BV.hydrology
                self.elt_def.append('hydrology')
            if ('hydrometry' in BV.__dir__()) == True:
                self.hydrometry = BV.hydrometry
                self.elt_def.append('hydrometry')
            if ('intermittency' in BV.__dir__()) == True:
                self.intermittency = BV.intermittency
                self.elt_def.append('intermittency')
            if ('subbasin' in BV.__dir__()) == True:   # Generates basin where there are hydrological stations
                self.subbasin = BV.subbasin
                self.elt_def.append('subbasin')
            # Atmospheric (compulsory: hydrodynamic)
            if ('forcing' in BV.__dir__()) == True:
                self.forcing = BV.forcing
                self.elt_def.append('forcing')
            if ('climatic' in BV.__dir__()) == True:
                self.climatic = BV.climatic
                self.elt_def.append('climatic')
            if ('drias' in BV.__dir__()) == True:
                self.drias = BV.drias
                self.elt_def.append('drias')
            if ('oceanic' in BV.__dir__()) == True:
                self.oceanic = BV.oceanic
                self.elt_def.append('oceanic')
            return True 
        else:
            print("Warning : file doesn't exist, python_object", self.watershed_folder)
            return False


    def create_object(self):
        """
        
        Creates watershed by defining geographic
        
        MODIFIES
        --------
        geographic: creates it
        
        """
        
        # Structure data
        self.geographic = geographic.Geographic(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet,
                                                snap_dist=self.snap_dist, buff_percent=self.buff_percent,
                                                out_path=self.watershed_folder,
                                                from_shp=self.from_shp, from_dem=self.from_dem,
                                                from_xy=self.from_xy, regio_path=self.regio_path,
                                                cell_size=self.cell_size) #2D
        self.elt_def.append('geographic')

    def save_object(self):
        """
        
        Saves python object (using pickle)
        
        """
        
        # If folder already exists, removes it
        if os.path.exists(os.path.join(self.watershed_folder,'python_object')):
            os.remove(os.path.join(self.watershed_folder,'python_object'))
        with open(os.path.join(self.watershed_folder,'python_object'), 'xb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        # pickle.dump(self, open(self.watershed_folder + '/python_object', "wb"))

    def display(self,dtype: str = 'watershed_dem'):
        """
        
        Display watershed figure

        :param dtype: type of figure. Can be 'watershed_dem' or 'watershed_geology'
        
        """
        
        if dtype == 'watershed_dem':
            watershed_display.watershed_dem(self)
        if dtype == 'watershed_geology':
            watershed_display.watershed_geology(self)
        if dtype == 'watershed_zones':
            watershed_display.watershed_zones(self) 

    #%% DATA OBJECT
        
    def add_forcing(self):
        self.forcing = forcing.Forcing(out_path=self.watershed_folder)
        self.elt_def.append('forcing')
        #MARTIN self.save_object()
        
    def add_hydrodynamic(self):
        # self.hydrodynamic = hydrodynamic.Hydrodynamic(self.geographic.y_pixel, self.geographic.x_pixel)
        self.hydrodynamic = hydrodynamic.Hydrodynamic()
        self.elt_def.append('hydrodynamic')
        #self.hillslope = hillslope() #1D Doesn't exist
        #MARTIN self.save_object()
        
    def add_hydrology(self, hydrology_path, types_obs = ['streams'], fields_obs = ['FID'], reset = False):
        self.hydrology_path = hydrology_path
        self.types_obs = types_obs
        self.fields_obs = fields_obs
        self.hydrology = hydrology.Hydrology(out_path=self.watershed_folder, types_obs=self.types_obs, fields_obs=self.fields_obs, geographic=self.geographic, hydro_path=self.hydrology_path)
        self.elt_def.append('hydrology')
        self.save_object()

    def add_geology(self, geology_path, types_obs = 'GEO1M.shp', fields_obs = 'CODE_LEG'):
        self.geology_path = geology_path
        self.geology =  geology.Geology(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path, landsea=None, types_obs=types_obs, fields_obs= fields_obs)
        self.elt_def.append('geology')
        self.save_object()

    def add_oceanic(self, oceanic_path):
        self.oceanic = oceanic.Oceanic()
        self.oceanic_path = oceanic_path
        self.oceanic.extract_data(out_path=self.watershed_folder,
                                  oceanic_path=self.oceanic_path,
                                  geographic=self.geographic)
        self.elt_def.append('oceanic')
        self.save_object()

    def add_surfex(self, surfex_path):
        self.surfex_path = surfex_path
        self.climatic = climatic.Climatic(out_path=self.watershed_folder, surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
        climatic.Merge(out_path=self.watershed_folder)
        self.elt_def.append('surfex')
        #MARTIN self.save_object()
        
    def add_drias(self, drias_path, list_models='all', list_vars='all'):
        self.drias_path = drias_path
        self.drias = drias.Drias(out_path=self.watershed_folder,
                                 drias_path=self.drias_path,
                                 watershed_shp=self.geographic.watershed_shp,
                                 list_models=list_models, 
                                 list_vars=list_vars)
        # drias.Merge(out_path=self.watershed_folder)
        self.elt_def.append('drias')
        # self.save_object()

    def add_piezometry(self):
        self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,geographic=self.geographic)
        self.elt_def.append('piezometry')
        self.save_object()

    def add_hydrometry(self, hydrometry_path):
        self.hydrometry_path = hydrometry_path
        self.hydrometry = hydrometry.Hydrometry(out_path=self.watershed_folder, hydrometry_path=self.hydrometry_path, geographic=self.geographic)
        self.elt_def.append('hydrometry')
        #MARTIN self.save_object()
                    
    def add_intermittency(self, intermittency_path):
        self.intermittency_path = intermittency_path
        self.intermittency = intermittency.Intermittency(out_path=self.watershed_folder, intermittency_path=self.intermittency_path, geographic=self.geographic)
        self.elt_def.append('intermittency')
        #MARTIN self.save_object()
                    
    def add_subbasin(self):
        if hasattr(self, 'hydrometry') == False:
            self.hydrometry=None
        self.subbasin = geographic.Subbasin(geographic=self.geographic, hydrometry=self.hydrometry, intermittency=self.intermittency, out_path=self.watershed_folder)
        self.elt_def.append('subbasin')
        #MARTIN self.save_object()

    #%% MODEL MODFLOW

    def run_modflow(self, ident: str = 'modflow',run: bool = True, modpath_sim: bool = False, box: bool = True,
                    first_only: bool = True, sink_fill: bool = False, lay_number: int = 1, 
                    bottom: float = None, thick_exp: float = 1., cond_decay: float = 0., multip_cond: float = None,
                    verbose: bool = False, post_process: bool = False,
                    time_step: str = 'M', calib: str = None, init_rech: str = 'mean', bc_left: (float) = None, bc_right: (float) = None,
                    verti_k: list = None):
        """ 
        
        Build and run modflow model
        
        Arguments
        ---------
        ident: string
            identity name of the model (file that will be generated for this simulation (eg: steady_K.._teta...))
        modpath_sim
            run modapth model
        calib: string
            calib == None: classical simulation
            calib != None: calibration, and in this case, calib is the folder where to store the calibration results
        run: bool
            run == True: should run the modflow model
            model is preprocessed for modflow but not processed
            
        Returns
        --------
        success: boolean
            success = True : model has run correctly
        
        flow_model: class Modflow
            Modflow model & attributes
            (not the results of the modflow model)
        
        Read the docs
        -------------
        :param modpath_sim: run modapth model
        :param ident: identity name of the model (file that will be generated for this simulation (eg: steady_K.._teta...))
        :return succes: True if the simulation is succesfully
        :param lay_number: number of layer of the model
        :param bottom: if bottom is None, the model has a constant thickness.if bottom is float, the model has a flat bottom at the float elevation
        :param cond_decay: changes the hydraulic conductivity exponentially with the depth. lay_number must be >1.
        :param thick_exp: changes the thickness of the layers exponentially. lay_number must be >1.
        :meta public:
            
        """
        
        # Type of run: classical simulation or calibration
        if calib == None:
            model_folder = self.simulations_folder
        else:
            model_folder = calib
        
        flow_model = modflow.Modflow(self.geographic,
                                     sink_fill=sink_fill,
                                     box=box,
                                     lay_number=self.hydrodynamic.nlay,
                                     thick=self.hydrodynamic.thickness,
                                     thick_exp=self.hydrodynamic.thick_exp,
                                     bottom=self.hydrodynamic.bottom,
                                     hyd_cond=self.hydrodynamic.hyd_cond,
                                     cond_decay=self.hydrodynamic.cond_decay,
                                     porosity=self.hydrodynamic.porosity,
                                     climatic=self.forcing.recharge,
                                     sea_level=self.oceanic.MSL,
                                     init_rech=init_rech,
                                     model_name=ident,
                                     model_folder=model_folder,
                                     multip_cond=multip_cond,
                                     bc_left=bc_left, 
                                     bc_right=bc_right,
                                     verti_k=verti_k,
                                     exe=self.modflow_path +'/bin/mfnwt.exe')
        
        # Preprocessing Modflow
        flow_model.pre_processing(verbose = verbose)
        
        # Processing Modflow
        if run == True:
            success = flow_model.processing(verbose = verbose)
        else:
            success = True
    
        # Postprocessing and Modpath simulation
        if success == True:
            if post_process == True:
                flow_model.post_processing(verbose = verbose)
            if modpath_sim == True:
                # print(self.hydrodynamic.porosity)
                transport_model = modpath.Modpath(self.geographic,model_name=ident,  
                                            model_folder=self.simulations_folder,
                                            exe=self.modflow_path + '/bin/mp6.exe',
                                            porosity=self.hydrodynamic.porosity)  
                transport_model.pre_processing(verbose = verbose)
                transport_model.processing(verbose = verbose)
                # transport_model.post_processing()
        
        #RONAN: removes these lines
        if hasattr(self, 'list_model_name') == False:
            self.list_model_name = []
            self.list_of_success = []
            self.list_flow_model = []  
        
        self.list_model_name.append(ident)
        self.list_of_success.append(success)
        self.list_flow_model.append(flow_model)
        # self.save_object()
        
        return success, flow_model

    #%% POSTPROCESS MODEL    

    def matrix_modflow(self,                       
                       success,
                       flow_model,
                       first_only = True,
                       watertable_elevation = True,
                       watertable_depth= True, 
                       seepage_areas = True,
                       outflow_drain = True,
                       groundwater_flux = True,
                       specific_discharge = False,
                       accumulation_flux = True,
                       perenn_intermit_shp=True,
                       groundwater_storage = False,
                       residence_times = False,
                       verbose = True,
                       export_tif = True,
                       calib=None):
        """
        Postprocessing

        Arguments
        ----------
        success : TYPE
            DESCRIPTION.
        flow_model : TYPE
            DESCRIPTION.
        first_only : TYPE, optional
            DESCRIPTION. The default is True.
        watertable_elevation : TYPE, optional
            DESCRIPTION. The default is True.
        watertable_depth : TYPE, optional
            DESCRIPTION. The default is True.
        seepage_areas : TYPE, optional
            DESCRIPTION. The default is True.
        outflow_drain : TYPE, optional
            DESCRIPTION. The default is True.
        groundwater_flux : TYPE, optional
            DESCRIPTION. The default is True.
        specific_discharge : TYPE, optional
            DESCRIPTION. The default is False.
        accumulation_flux : TYPE, optional
            DESCRIPTION. The default is True.
        perenn_intermit_shp : TYPE, optional
            DESCRIPTION. The default is True.
        groundwater_storage : TYPE, optional
            DESCRIPTION. The default is False.
        residence_times : TYPE, optional
            DESCRIPTION. The default is False.
        verbose : TYPE, optional
            DESCRIPTION. The default is True.
        export_tif : TYPE, optional
            DESCRIPTION. The default is True.
        calib : TYPE, optional
            DESCRIPTION. The default is None.

        Returns
        -------
        None.

        """
        
        if success == True:
            flow_model.post_processing(first_only = first_only,
                                       watertable_elevation = watertable_elevation,
                                       watertable_depth = watertable_depth, 
                                       seepage_areas = seepage_areas,
                                       outflow_drain = outflow_drain,
                                       groundwater_flux = groundwater_flux,
                                       specific_discharge = specific_discharge,
                                       accumulation_flux = accumulation_flux,
                                       perenn_intermit_shp=perenn_intermit_shp,
                                       groundwater_storage = groundwater_storage,
                                       residence_times = residence_times,
                                       verbose = verbose,
                                       export_tif = export_tif)

    def results_modflow(self, ident='modflow', recharge=250, runoff=25,
                        actual_date=True, time_step='M', calib=None):
        """
        
        Gets the results of Matrix Modflow (raster tiffs) and generates aggregated characteristics
            mean piezometry
            mean flows... 
            Results are averaged at the scale of the watershed
        Saves results in model folder (as csv file)
        
        Retunrs
        -------
        simulated_results: Dataframe pandas
            Datafrome of temporal chronicles (first column: time)
            
        """
        
        if calib == None:
            model_folder = self.simulations_folder
        else:
            model_folder = calib
            
        results = modflow_results.Results(self.geographic,
                                recharge=recharge,
                                runoff=runoff,
                                actual_date=actual_date,
                                stable_folder=self.stable_folder,
                                model_name=ident,
                                model_folder=model_folder)
        simulated_results = results.mfdata
        return simulated_results

    #%% MODEL HS1D                
    
    def run_hs1D(self):
        """
        
        Coming soon !
        
        """
        
        return self

#%% NOTES

          