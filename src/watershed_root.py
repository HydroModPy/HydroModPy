# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ---- LIBRAIRIES

#%% DEFAULT SITE PACKAGES

# Libraries installed by default
import sys
import glob
import os
import fnmatch
import random
import pickle
from datetime import datetime
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl        # install automatically by geopandas
import matplotlib.pyplot as plt
from matplotlib import cm
import matplotlib.pylab as pl
import matplotlib.dates as mdates
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable

# Libraries added from 'conda forge' procedure
from osgeo import gdal, osr # or import gdal
import rasterio

# # Libraries added from 'pip install' procedure
import deepdish as dd
import flopy
import imageio
import vedo
import hydroeval
import xarray	
import netCDF4
import matplotlib_scalebar	
import contextily
import pyproj # uninstall before install
import selenium
import shapefile # named pyshp for install
import jupyter
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% HYDROMODPY ROOT PATH

from os.path import dirname, abspath
root_dir = (dirname(abspath(__file__)))
sys.path.append(root_dir)

#%% HYDROMODPY IMPORT MODULES

# Import HydroModPy modules
import watershed_root
from watershed import climatic, geographic, geometric, hydraulic, hydrography, hydrometry, intermittency, lithology, oceanic, piezometry, subbasin
from modeling import downslope, modflow, modpath, timeseries
from display import visualization_watershed, visualization_results, export_vtuvtk
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Watershed :

    #%% INIT

    def __init__(self, 
                 dem_path: str, 
                 out_path: str,
                 load: bool = False,
                 watershed_name: str = 'Default',
                 from_lib: list = None, # os.path.join(root_dir,'watershed_library.csv')
                 from_dem: list = None, # [path, cell size]
                 from_shp: list = None, # [path, buffer size]
                 from_xyv: list = None, # [x, y, snap distance, buffer size]
                 bottom_path: str = None, # path
                 modflow_path: str = os.path.join(root_dir,'bin/'), 
                 save_object: bool = True):

        self.dem_path = dem_path
        self.out_path = out_path
        self.load = load
        self.watershed_name = watershed_name
        self.from_lib = from_lib
        self.from_dem = from_dem
        self.from_shp = from_shp
        self.from_xyv = from_xyv
        self.bottom_path = bottom_path
        self.modflow_path = modflow_path
        
        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)
        
        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)
        
        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)
        
        # self.add_data_folder = os.path.join(self.stable_folder, 'add_data/')
        # toolbox.create_folder(self.add_data_folder)
        
        self.figure_folder = os.path.join(self.stable_folder, '_figures/')
        toolbox.create_folder(self.figure_folder)
        
        # self.calibration_folder = os.path.join(self.watershed_folder, 'results_calibration')
        # toolbox.create_folder(self.calibration_folder)
        
        self.elt_def = []
        
        success = False
        if load==True:
             # Load from previously stored (saved) watershed
             success = self.load_object()
             print("Object was loaded successfully")
        else: 
             print("Object was not loaded as demanded, but created from scratch")
             
        if load==False or success==False: 
            print("Create new object, will removed previousy stored object")
            # Definition of the watershed
            self.init_object()
            # Creation of the watershed defined at the previous line
            self.create_object()
            # Save object
            if save_object == True:
                self.save_object()
        
    #%% PYTHON OBJECT
    
    def load_object(self):
        
        if os.path.exists(os.path.join(self.watershed_folder, 'watershed_object')):
            # Test the existence of the stored watershed within the default path name "watershed_object"
            with open(os.path.join(self.watershed_folder, 'watershed_object'), 'rb') as config_dictionary_file:
              BV = pickle.load(config_dictionary_file)
            # At least geographic should have been stored
            if ('geographic' in BV.__dir__()) == True:
                self.geographic = BV.geographic
                self.elt_def.append('geographic')
            else:
                print("Warning : geographic doesn't exist in object")
                return False
            if ('subbasin' in BV.__dir__()) == True:   # Generates basin where there are hydrological stations
                self.subbasin = BV.subbasin
                self.elt_def.append('subbasin')
            # Sub-surface (compulsory: hydrodynamic)
            if ('hydraulic' in BV.__dir__()) == True:
                self.hydraulic = BV.hydraulic
                self.elt_def.append('hydraulic')
            if ('geologic' in BV.__dir__()) == True:
                self.geology = BV.geologic
                self.elt_def.append('geologic')
            if ('piezometric' in BV.__dir__()) == True:
                self.piezometric = BV.piezometric
                self.elt_def.append('piezometric')
            # Surface
            if ('hydrologic' in BV.__dir__()) == True:
                self.hydrologic = BV.hydrologic
                self.elt_def.append('hydrologic')
            if ('hydrometric' in BV.__dir__()) == True:
                self.hydrometric = BV.hydrometric
                self.elt_def.append('hydrometric')
            # Atmospheric (compulsory: hydrodynamic)
            if ('climatic' in BV.__dir__()) == True:
                self.climatic = BV.climatic
                self.elt_def.append('climatic')
            if ('oceanic' in BV.__dir__()) == True:
                self.oceanic = BV.oceanic
                self.elt_def.append('oceanic')
            return True 
        else:
            print("Warning : file doesn't exist, watershed_object", self.watershed_folder)
            return False

    def init_object(self):
        
        # Conditions that should all be fulfilled to generate watershed from watershed library outlet
        
        if self.from_lib != None:
            watershed_list = pd.read_csv(self.from_lib, delimiter=';')
            watershed_info = watershed_list.loc[watershed_list['watershed_name'] == self.watershed_name]
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = watershed_info.iloc[0]['x_outlet']
            self.y_outlet = watershed_info.iloc[0]['y_outlet']
            self.snap_dist = watershed_info.iloc[0]['snap_dist']
            self.buff_percent = watershed_info.iloc[0]['buff_percent']
            self.crs_proj = watershed_info.iloc[0]['crs_proj']
            
        if self.from_dem != None:
            dem = gdal.Open(self.from_dem[0])
            proj = osr.SpatialReference(wkt=dem.GetProjection())
            self.dem_path = self.from_dem[0]
            self.bottom_path = self.bottom_path
            self.cell_size = self.from_dem[1]
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = None
            self.crs_proj = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
                        
        if self.from_shp != None:
            shp_file = gpd.read_file(self.from_shp[0])
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = self.from_shp[1]
            self.crs_proj = shp_file.srs.upper()
        
        if self.from_xyv != None:
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = self.from_xyv[0]
            self.y_outlet = self.from_xyv[1]
            self.snap_dist = self.from_xyv[2]
            self.buff_percent = self.from_xyv[3]
            self.crs_proj = self.from_xyv[4]

    def create_object(self):
        
        # Structure data
        # self.geographic = geographic.Geographic(dem_path=self.dem_path,
        #                                         bottom_path=self.bottom_path,
        #                                         cell_size=self.cell_size,
        #                                         x_outlet=self.x_outlet,
        #                                         y_outlet=self.y_outlet,
        #                                         snap_dist=self.snap_dist,
        #                                         buff_percent=self.buff_percent,
        #                                         crs_proj=self.crs_proj,
        #                                         out_path=self.watershed_folder,
        #                                         from_lib=self.from_lib,
        #                                         from_dem=self.from_dem,
        #                                         from_shp=self.from_shp,
        #                                         from_xyv=self.from_xyv)
        
        self.geographic = geographic.Geographic(self.dem_path,
                                                self.bottom_path,
                                                self.cell_size,
                                                self.x_outlet,
                                                self.y_outlet,
                                                self.snap_dist,
                                                self.buff_percent,
                                                self.crs_proj,
                                                self.watershed_folder,
                                                self.from_lib,
                                                self.from_dem,
                                                self.from_shp,
                                                self.from_xyv)
        
        self.elt_def.append('geographic')

    def save_object(self):

        # If folder already exists, removes it
        if os.path.exists(os.path.join(self.watershed_folder,'watershed_object')):
            os.remove(os.path.join(self.watershed_folder,'watershed_object'))
        with open(os.path.join(self.watershed_folder,'watershed_object'), 'xb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        # pickle.dump(self, open(self.watershed_folder + '/watershed_object', "wb")) xb

    def display_object(self,dtype: str = 'watershed_dem'):
        
        if dtype == 'watershed_dem':
            visualization_watershed.watershed_dem(self)
        if dtype == 'watershed_geology':
            visualization_watershed.watershed_geology(self)
        if dtype == 'watershed_zones':
            visualization_watershed.watershed_zones(self) 

    #%% ADDING DATA
        
    def add_climatic(self):
        self.climatic = climatic.Climatic(out_path=self.watershed_folder)
        self.elt_def.append('climatic')
        self.save_object()
        
    def add_lithology(self, lithology_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG'):
        self.lithology_path = lithology_path
        self.lithology = lithology.Lithology(out_path=self.watershed_folder,
                                             geographic=self.geographic,
                                             geo_path = self.geologic_path,
                                             landsea=None,
                                             types_obs=types_obs,
                                             fields_obs= fields_obs)
        self.elt_def.append('geologic')
        self.save_object()
        
    def add_geometric(self):
        self.geometric = None
        self.elt_def.append('geometric')
        self.save_object()
    
    def add_hydraulic(self):
        self.hydraulic = hydraulic.Hydraulic(nrow=self.geographic.y_pixel,
                                             ncol=self.geographic.x_pixel,
                                             box_dem=self.geographic.watershed_box_buff_dem)
        self.elt_def.append('hydraulic')
        self.save_object()
        
    def add_hydrography(self,
                        hydrography_path,
                        types_obs=['streams'], 
                        fields_obs=['FID'], 
                        reset=False):
        self.hydrography_path = hydrography_path
        self.types_obs = types_obs
        self.fields_obs = fields_obs
        self.hydrography = hydrography.Hydrography(out_path=self.watershed_folder,
                                                   types_obs=self.types_obs,
                                                   fields_obs=self.fields_obs,
                                                   geographic=self.geographic,
                                                   hydro_path=self.hydrography_path)
        self.elt_def.append('hydrography')
        self.save_object()

    def add_hydrometric(self, hydrometry_path):
        self.hydrometry_path = hydrometry_path
        self.hydrometry = hydrometry.Hydrometry(out_path=self.watershed_folder, 
                                                hydrometry_path=self.hydrometry_path, 
                                                geographic=self.geographic)
        self.elt_def.append('hydrometry')
        self.save_object()
        
    def add_intermittency(self, intermittency_path):
        self.intermittency_path = intermittency_path
        self.intermittency = intermittency.Intermittency(out_path=self.watershed_folder, 
                                                         intermittency_path=self.intermittency_path, 
                                                         geographic=self.geographic)
        self.elt_def.append('intermittency')
        self.save_object()
        
    def add_oceanic(self, oceanic_path):
        self.oceanic = oceanic.Oceanic()
        self.oceanic_path = oceanic_path
        self.oceanic.extract_data(out_path=self.watershed_folder,
                                  oceanic_path=self.oceanic_path,
                                  geographic=self.geographic)
        self.elt_def.append('oceanic')
        self.save_object()
        
    def add_piezometry(self):
        self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,
                                                geographic=self.geographic)
        self.elt_def.append('piezometry')
        self.save_object()
                    
    def add_subbasin(self):
        if hasattr(self, 'hydrometry') == False:
            self.hydrometry=None
        self.subbasin = subbasin.Subbasin(geographic=self.geographic, hydrometry=self.hydrometry, intermittency=self.intermittency, out_path=self.watershed_folder)
        self.elt_def.append('subbasin')
        self.save_object()


#     #%% MODEL MODFLOW

#     def run_modflow(self, ident: str = 'modflow',run: bool = True, modpath_sim: bool = False, 
#                     zone_partic: str = 'watershed', box: bool = True,
#                     first_only: bool = True, sink_fill: bool = False, lay_number: int = 1, 
#                     bottom: float = None, thick_exp: float = 1., cond_decay: float = 0., poro_decay: float = 0.,
#                     multip_cond: float = None,
#                     verbose: bool = False, post_process: bool = False,
#                     time_step: str = 'M', calib: str = None, init_rech: str = 'mean', bc_left: (float) = None, bc_right: (float) = None,
#                     verti_k: list = None):
#         """ 
        
#         Build and run modflow model
        
#         Arguments
#         ---------
#         ident: string
#             identity name of the model (file that will be generated for this simulation (eg: steady_K.._teta...))
#         modpath_sim
#             run modapth model
#         calib: string
#             calib == None: classical simulation
#             calib != None: calibration, and in this case, calib is the folder where to store the calibration results
#         run: bool
#             run == True: should run the modflow model
#             model is preprocessed for modflow but not processed
            
#         Returns
#         --------
#         success: boolean
#             success = True : model has run correctly
        
#         flow_model: class Modflow
#             Modflow model & attributes
#             (not the results of the modflow model)
        
#         Read the docs
#         -------------
#         :param modpath_sim: run modapth model
#         :param ident: identity name of the model (file that will be generated for this simulation (eg: steady_K.._teta...))
#         :return succes: True if the simulation is succesfully
#         :param lay_number: number of layer of the model
#         :param bottom: if bottom is None, the model has a constant thickness.if bottom is float, the model has a flat bottom at the float elevation
#         :param cond_decay: changes the hydraulic conductivity exponentially with the depth. lay_number must be >1.
#         :param poro_decay: changes the porosity exponentially with the depth. lay_number must be >1.
#         :param thick_exp: changes the thickness of the layers exponentially. lay_number must be >1.
#         :meta public:
            
#         """
        
#         # Type of run: classical simulation or calibration
#         if calib == None:
#             model_folder = self.simulations_folder
#         else:
#             model_folder = calib
        
#         flow_model = modflow.Modflow(self.geographic,
#                                      sink_fill=sink_fill,
#                                      box=box,
#                                      lay_number=self.hydrodynamic.nlay,
#                                      thick=self.hydrodynamic.thickness,
#                                      thick_exp=self.hydrodynamic.thick_exp,
#                                      bottom=self.hydrodynamic.bottom,
#                                      hyd_cond=self.hydrodynamic.hyd_cond,
#                                      cond_decay=self.hydrodynamic.cond_decay,
#                                      poro_decay=self.hydrodynamic.poro_decay,
#                                      porosity=self.hydrodynamic.porosity,
#                                      climatic=self.forcing.recharge,
#                                      sea_level=self.oceanic.MSL,
#                                      init_rech=init_rech,
#                                      model_name=ident,
#                                      model_folder=model_folder,
#                                      multip_cond=multip_cond,
#                                      bc_left=bc_left, 
#                                      bc_right=bc_right,
#                                      verti_k=verti_k,
#                                      exe=self.modflow_path +'/bin/mfnwt.exe')
        
#         # Preprocessing Modflow
#         flow_model.pre_processing(verbose = verbose)
        
#         # Processing Modflow
#         if run == True:
#             success = flow_model.processing(verbose = verbose)
#         else:
#             success = True
    
#         # Postprocessing and Modpath simulation
#         if (run == True) & (success == True):
#             if post_process == True:
#                 flow_model.post_processing(verbose = verbose)
#             if modpath_sim == True:
#                 # print(self.hydrodynamic.porosity)
#                 transport_model = modpath.Modpath(self.geographic,model_name=ident,
#                                                   zone_partic=zone_partic,
#                                                   model_folder=self.simulations_folder,
#                                                   exe=self.modflow_path + '/bin/mp6.exe',
#                                                   # porosity=self.hydrodynamic.porosity,
#                                                   porosity=flow_model.ps)  
#                 transport_model.pre_processing(verbose = verbose)
#                 if run == True:
#                     transport_model.processing(verbose = verbose)
#                 # transport_model.post_processing()
        
#         #RONAN: removes these lines
#         if hasattr(self, 'list_model_name') == False:
#             self.list_model_name = []
#             self.list_of_success = []
#             self.list_flow_model = []  
        
#         self.list_model_name.append(ident)
#         self.list_of_success.append(success)
#         self.list_flow_model.append(flow_model)
#         # self.save_object()
        
#         return success, flow_model

#     #%% POSTPROCESS MODEL    

#     def matrix_modflow(self,                       
#                        success,
#                        flow_model,
#                        first_only = True,
#                        watertable_elevation = True,
#                        watertable_depth= True, 
#                        seepage_areas = True,
#                        outflow_drain = True,
#                        groundwater_flux = True,
#                        specific_discharge = False,
#                        accumulation_flux = True,
#                        perenn_intermit_shp=True,
#                        groundwater_storage = True,
#                        residence_times = False,
#                        verbose = True,
#                        export_tif = True,
#                        calib=None):
#         """
#         Postprocessing

#         Arguments
#         ----------
#         success : TYPE
#             DESCRIPTION.
#         flow_model : TYPE
#             DESCRIPTION.
#         first_only : TYPE, optional
#             DESCRIPTION. The default is True.
#         watertable_elevation : TYPE, optional
#             DESCRIPTION. The default is True.
#         watertable_depth : TYPE, optional
#             DESCRIPTION. The default is True.
#         seepage_areas : TYPE, optional
#             DESCRIPTION. The default is True.
#         outflow_drain : TYPE, optional
#             DESCRIPTION. The default is True.
#         groundwater_flux : TYPE, optional
#             DESCRIPTION. The default is True.
#         specific_discharge : TYPE, optional
#             DESCRIPTION. The default is False.
#         accumulation_flux : TYPE, optional
#             DESCRIPTION. The default is True.
#         perenn_intermit_shp : TYPE, optional
#             DESCRIPTION. The default is True.
#         groundwater_storage : TYPE, optional
#             DESCRIPTION. The default is False.
#         residence_times : TYPE, optional
#             DESCRIPTION. The default is False.
#         verbose : TYPE, optional
#             DESCRIPTION. The default is True.
#         export_tif : TYPE, optional
#             DESCRIPTION. The default is True.
#         calib : TYPE, optional
#             DESCRIPTION. The default is None.

#         Returns
#         -------
#         None.

#         """
        
#         if success == True:
#             flow_model.post_processing(first_only = first_only,
#                                        watertable_elevation = watertable_elevation,
#                                        watertable_depth = watertable_depth, 
#                                        seepage_areas = seepage_areas,
#                                        outflow_drain = outflow_drain,
#                                        groundwater_flux = groundwater_flux,
#                                        specific_discharge = specific_discharge,
#                                        accumulation_flux = accumulation_flux,
#                                        perenn_intermit_shp=perenn_intermit_shp,
#                                        groundwater_storage = groundwater_storage,
#                                        residence_times = residence_times,
#                                        verbose = verbose,
#                                        export_tif = export_tif)

#     def results_modflow(self, ident='modflow', recharge=250, runoff=25,
#                         actual_date=True, time_step='M', calib=None):
#         """
        
#         Gets the results of Matrix Modflow (raster tiffs) and generates aggregated characteristics
#             mean piezometry
#             mean flows... 
#             Results are averaged at the scale of the watershed
#         Saves results in model folder (as csv file)
        
#         Retunrs
#         -------
#         simulated_results: Dataframe pandas
#             Datafrome of temporal chronicles (first column: time)
            
#         """
        
#         if calib == None:
#             model_folder = self.simulations_folder
#         else:
#             model_folder = calib
            
#         results = modflow_results.Results(self.geographic,
#                                 recharge=recharge,
#                                 runoff=runoff,
#                                 actual_date=actual_date,
#                                 stable_folder=self.stable_folder,
#                                 model_name=ident,
#                                 model_folder=model_folder)
#         simulated_results = results.mfdata
        
#         return simulated_results

#     #%% MODEL HS1D                
    
#     def run_hs1D(self):
#         """
        
#         Coming soon !
        
#         """
        
#         return self

# #%% NOTES

          