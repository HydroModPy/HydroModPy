# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé

Simple example for basic execution of HydroModPy (execution should be of the order of seconds)
- NW of Brittany (France), some km2 catchment
- Extract watershed
- Hydrological extraction of stream network
- GW simulation with synthetic recharge
- No calibration 
- Some visualization
"""

# %% LOCALIZATION OF CODES AND PATHS IN THE CURRENT REPOSITORY

# File system to define in sys.path for the code to work
from os.path import dirname, abspath, join
import os 
import sys
# Current Directory stored in DIR 
DIR = os.path.join(os.getenv("HYDROMODPY_ROOT").replace('/',os.sep),"HydroModPy","CORE_COMM")
sys.path.append(os.path.join(dirname(DIR),"Tools","Parameters","Parameters"))
sys.path.append(DIR)
out_path = os.getenv("HYDROMODPY_RESULTS")


# %% GENERAL LIBRARIES

# from glob import glob
import numpy as np
import pandas as pd
import osgeo
from osgeo import gdal, osr
from IPython import get_ipython
from tools import toolbox, vtk

get_ipython().run_line_magic('matplotlib', 'inline')

# # Plot
import matplotlib.pyplot as plt
# from matplotlib.font_manager import FontProperties
# import matplotlib as mpl
# from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
# from mpl_toolkits.axes_grid1 import make_axes_locatable
# from matplotlib.colors import LightSource
# from matplotlib.pyplot import cm
# from matplotlib.ticker import MaxNLocator
# # Gis
# from osgeo import gdal
# import rasterio
# import geopandas as gpd
# import warnings  
import imageio
import whitebox
import logging


# %% PROPRIETARY TOOLS 

# Organization of loaded files (several possibilities)
import pathstructure as path

# Parameter structure
import ParametersGroup as pg
from options import parameter_choice


# %% HYDROMODPY MODULES

from watershed import watershed_root, forcing, watershed_display
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import modflow_display, visualization



def run_example(out_path, regression_test=False, parameters=None):
   
    print('Function ready !')
    
    parameters = parameters.getgroup('simulation')
                         
    # Creation of basis whitebox class (wbt)
    wbt = whitebox.WhiteboxTools()
    wbt.verbose = True
    # Warnings: Mask error messages and captures them (logging)
    
    # warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*`np.typeDict` is a deprecated alias for `np.sctypeDict`.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore") # not working
    # warnings.simplefilter("ignore", category=DeprecationWarning) # not working
    # warnings.warn("You won't see this warning", category=DeprecationWarning) # to modify warnings
    logging.captureWarnings(True)

    
    #%% LAYOUT PLOT
    fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large
    
    #%% NECESSARY PATHS
    dems_path, hydrology_path, modflow_path, climate_path, \
        intermittency_path, hydrometry_path, piezometry_path, geology_path, \
            oceanic_path, surfex_path, library_path = path.path_classical(DIR)
    
    # Indicate the name of the regional DEM
    #JR:PARAMETERS
    dem_name = parameter_choice("DEM_test_75m_LAMB93.tif", parameters.getgroup('simul').getparam("dem").getvalue())
    
    dem_path = dems_path + dem_name
    
    dem = osgeo.gdal.Open(dem_path)
    proj = osgeo.osr.SpatialReference(wkt=dem.GetProjection())    # Retrieves projection system attached to the dem
    crs = int(proj.GetAttrValue('AUTHORITY',1))             # Gets name of the projection system
    
    # Import the library of watersheds (maybe several watersheds in the loaded file: library of watersheds)
    library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied
    
    # Selection of the watershed to deal within from the just loaded library of watersheds
    #JR:PARAMETERS
    watershed_name = parameter_choice('Example', parameters.getgroup('watershed_root').getparam("watershed_name").getvalue())
     # add manually study site information in map units  #JR:Parameters
    #RONAN: Supprimer la ligne?
    mysite = library[library['watershed_name'] == watershed_name] # specific row
    
    # Paths generated automatically but necessary for plots
    out_path = '/home/agauvain/Documents/HydroModPy'
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    #%% GENERATING WATERSHED
    
    # If watershed has already been generated, use the generated one instead to recreate it again
    #JR:PARAMETERS
    load = parameter_choice(False, parameters.getgroup('simul').getparam("load").getvalue())
    
    print('##### '+watershed_name.upper()+' #####')
    
    subbasin_path = True   # generate subbasins from stations or manual points
    from_shp = None        # specify a path if process start from a given shapefile
    from_dem = False       # True or False if the process start from a given DEM of xyz file
    cell_size = None       # specify new resolution from a given DEM or None
    from_xy = []
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=from_xy,
                                  cell_size=cell_size,
                                  parameters=parameters.getgroup('watershed_root'))
    
    #%% ADD SPECIFIC DATA
    
    # Specify the hydrologic layers to clip
    types_obs = ['streams','sections'] # list of shapefile name layers  #JR:Parameters
    fields_obs = ['FID','Persistanc'] # list of shapefile name columns to translate in a tif #JR:Parameters
    
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    
    BV.add_hydrodynamic()
    BV.add_forcing()
    BV.add_oceanic(oceanic_path)
    
    watershed_display.watershed_dem(BV)
    watershed_display.watershed_local(dem_path, BV)
    
    #%% SET PARAMETERS
    
    # Choice the state of the simulation
    sim_state = 'steady' # steady
    first = 2010
    last = 2010
    time_step = 'M'
    
    # Recharge from a csv
    rec = pd.read_csv(climate_path+'_REC_'+time_step+'.csv', sep=';', index_col=[0], parse_dates=True)
    rec = rec[(rec.index.year>=first) & (rec.index.year<=last)]
    rec = rec.squeeze()
    BV.forcing.update_recharge(values = (rec) / 1000, sim_state=sim_state)
    
    # Finally the rehcarge is set as a value or a serie
    R = BV.forcing.recharge # mm/month to m/month
    
    # Plot to control recharge
    if sim_state == 'transient':
        fig, ax = plt.subplots(1,1, figsize=(6,3))
        ax.plot(R*1000, c='k', lw=0.5)
    
    # Update hydrualic conductivity
    K = 1e-5 * 3600 * 24 * 30 # m/second to m/month
    BV.hydrodynamic.update_hyd_cond(K)
    
    # Update aquifer thickness
    E = 30 # m
    BV.hydrodynamic.update_thickness(E)
    
    # Update effective porosity
    P = 0.01 # -
    BV.hydrodynamic.update_porosity(P)
    
    # Set name of the model
    model_name = sim_state
    model_name = 'test'
    
    #%% RUN MODEL
    
    # Launch a model
    
    success, flow_model= BV.run_modflow(ident=model_name, modpath_sim=False, first_only=True,
                                        sink_fill=False, box=False,
                                        lay_number=1, bottom=None, thick_exp=1., cond_decay=0., 
                                        verbose=True)
    
    print('Modeling process completed')
    
    #%% POST PROCESS
    
    success = True
    
    BV.matrix_modflow(success,
                      flow_model,
                      first_only = True,
                      watertable_elevation = True,
                      watertable_depth = True, 
                      seepage_areas = True,
                      outflow_drain = True,
                      groundwater_flux = False,
                      specific_discharge = False,
                      accumulation_flux = True,
                      perenn_intermit_shp = False,
                      groundwater_storage = True,
                      residence_times = False,
                      verbose = True,
                      export_tif = True)
    
    BV.results_modflow(ident=model_name, actual_date=True, time_step='M')
    print('Result chronics extraction completed')
    
    #%% VISUALIZATION 3D
    
    if regression_test == False:
    
        vtk.VTK(BV, model_name)
        visu = visualization.Visualization(BV, model_name)
        visu.visual3D(interactive=True,
                      object_list=['grid','watertable', 'watertable_depth',
                                   # 'pathlines',
                                   'surface_flow', 'drain_flow'],
                      view='south-west', 
                      # lines=200, cloc=(0.7,0.1)
                      )

    #%% PLOT SURFACE OUTPUTS
    
    if sim_state == 'transient':
        modflow_display.SurfaceOutputs(R, simulations_folder, stable_folder, model_name,
                                       types_obs, freq_interv=12, save_gif=True)
    if sim_state == 'steady':
        # Control plot
        x = np.load(simulations_folder+'/test/_watershed/accumulation_flux.npy', allow_pickle=True).item()
        x = x[0]
        x[x<=0] = np.nan
        plt.imshow(x, cmap='jet')
    
    #%% INTERACTIVE CROSS-SECTION
    
    if regression_test == False:
    
        # Dem data
        dem_data = BV.geographic.dem_data
        # dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif')
        # dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')
        
        # Wt data
        wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # buffer size no masked
        
        # River data
        river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif')
        
        # Function
        modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=True)

#%% LAUNCH

####################################################

out_path=path.results_folder()
    
####################################################


def xml_parameters(): 
    # local folder of example
    folder = dirname(abspath(__file__))
    # Initialization of Reference ParametersGroup
    file_ref = join(folder,"a_given_params.xml")
    # ref = pg.ParametersGroup(file_ref)   
    # Loads User ParametersGroup
    file_usr = join(folder,"a_given_params.xml")  
    # Results folder: defines and creates
    #JR-ATTENTION: folder_res à transmettre pour les résultats
    vec=folder.split('\\')
    folder_res = join(os.getenv("HYDROMODPY_RESULTS").replace('/',os.sep),vec[-2],vec[-1])
    os.makedirs(folder_res,exist_ok=True)
    # Merges the two structures and affects default_values to values when necessary
    paramgroup = pg.ParametersGroup.merge_diff(file_ref,file_usr,pg.EXPLOPT.REPLACE,folder_res)[0]
    return paramgroup


if __name__ == "__main__":
    print ("Executed when invoked directly")   
    run_example(out_path, regression_test=False, parameters=xml_parameters())
else:
    print ("Executed when imported")
    

