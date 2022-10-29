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

def run_example(out_path, regression_test=False):

    #%% GENERAL LIBRARIES
    
    # General
    import sys
    import os
    from os.path import dirname, abspath
    # Current Directory stored in DIR 
    DIR = dirname(dirname(dirname(abspath(__file__))))
    sys.path.append(DIR)
    #MARTIN: Add test to confirm that current folder is CORE_COMM
    # If not, returns error message and stop running execution 
    
    from glob import glob
    import numpy as np
    import pandas as pd
    from osgeo import gdal, osr
    from IPython import get_ipython
    
    get_ipython().run_line_magic('matplotlib', 'inline')
    # Plot
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    import matplotlib as mpl
    from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    from matplotlib.colors import LightSource
    from matplotlib.pyplot import cm
    from matplotlib.ticker import MaxNLocator
    # Gis
    from osgeo import gdal
    import imageio
    import rasterio
    import geopandas as gpd
    import whitebox
    # Creation of basis whitebox class (wbt)
    wbt = whitebox.WhiteboxTools()
    wbt.verbose = True
    # Warnings: Mask error messages and captures them (logging)
    import logging
    import warnings  
    # warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore", message=".*`np.typeDict` is a deprecated alias for `np.sctypeDict`.*", category=DeprecationWarning)
    # warnings.filterwarnings("ignore") # not working
    # warnings.simplefilter("ignore", category=DeprecationWarning) # not working
    # warnings.warn("You won't see this warning", category=DeprecationWarning) # to modify warnings
    logging.captureWarnings(True)
                     
    # HYDROMODPY MODULES
             
    from watershed import watershed_root, forcing, watershed_display
    from tools import toolbox, vtk
    from watershed.data import hydrology, climatic, oceanic, piezometry
    from groundwater_flow import modflow_display, visualization
    
    #%% LAYOUT PLOT
    
    fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large
    
    #%% NECESSARY PATHS
        
    # Path to the git repositoty home page
    git_path = DIR
    # Path to the test folder
    test_path = git_path + "/examples/a_given/"
    
    # We suggest that data be stored in the following suite of specific folders
    # 1 folder for each of the type of data and "process" to be simulated
    dems_path = test_path + 'dem/'
    hydrology_path = test_path + 'hydrology/'   # add hydrographic shapefiles
    modflow_path = test_path + 'modflow/'       # add bin/ folder with necessary .exe
    climate_path =test_path + 'climate/'
    intermittency_path = test_path + 'intermittency/'
    hydrometry_path = test_path + 'hydrometry/'
    piezometry_path = None                      # add piezometry data or nothing for automatic download
    geology_path = None                         # add geologic layers
    oceanic_path = 'None'                         # add specific sea level files
    
    # Specifically designed to process SURFEX data (France scale)
    surfex_path =  None # add surfex models in .h5 format
    
    # Indicate the name of the regional DEM
    dem_name = "DEM_test_75m_LAMB93.tif"           #JR:Parameters
    # dem_name = "DEM_bzh_75m_LAMB93.tif"
    dem_path = dems_path + dem_name
    
    dem = gdal.Open(dem_path)
    proj = osr.SpatialReference(wkt=dem.GetProjection())    # Retrieves projection system attached to the dem
    crs = int(proj.GetAttrValue('AUTHORITY',1))             # Gets name of the projection system
    
    # Import the library of watersheds (maybe several watersheds in the loaded file: library of watersheds)
    library_path = test_path + 'watershed_library.csv' # each row is a study site
    library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied
    
    # Selection of the watershed to deal within from the just loaded library of watersheds
    watershed_name = 'Example' # add manually study site information in map units  #JR:Parameters
    #RONAN: Supprimer la ligne?
    mysite = library[library['watershed_name'] == watershed_name] # specific row
    
    # Paths generated automatically but necessary for plots
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    #%% GENERATING WATERSHED
    
    # If watershed has already been generated, used the generated one instead of recreating it
    load = False
    
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
                                  cell_size=cell_size)
    
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
    
        from tools import toolbox, vtk
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

user = 'Martin'
user = 'Ronan'

# Path where the results will be stored (SHOULD BE SPECIFIED BY THE USER)
if user == 'Jean-Raynald':
    out_path = "D:/results/HydroModPy/"
if user == 'Alexandre':
    out_path = "C:/Users/alexa/Dropbox/HydroModPy/"
if user == 'Martin':
    out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
if user == 'Ronan':
    out_path = 'D:/Users/abherve/TEST/'

####################################################

if __name__ == "__main__":
    print ("Executed when invoked directly")
    run_example(out_path, regression_test=False)
else:
    print ("Executed when imported")
    

