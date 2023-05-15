# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import flopy
import pickle
import random

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root, calib_analysis

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

# t = imageio.imread('C:/Users/ronan/Documents/SIMULATIONS/WATERLINE/CATCHMENTS/Canut/results_stable/geographic/watershed_direc.tif')

#%% ---- EXTRACT CATCHMENT

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
data_path = "C:/Users/ronan/OneDrive/UNINE/5_Waterline/Data/"
out_path = "C:/Users/ronan/Documents/SIMULATIONS/WATERLINE/CATCHMENTS/"
res_path = 'C:/Users/ronan/OneDrive/UNINE/5_Waterline/Hydromodpy/Catchments/'
modflow_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

subbasin_path = True # generate subbasins from stations or manual points
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xy = []
from_shp = None # specify a path if process start from a given shapefile

watershed_names = ['Vosvozis',
                   'Hoal',
                   'Kocinka',
                   'Temmes',
                   'Canut',
                   'Lasset',
                   'Poschiavino']

# watershed_names = ['Temmes']
# watershed_names = ['Kocinka']
# watershed_names = ['Canut']
# watershed_names = ['Hoal']

#%% DATA TOPO

load = False

dict_utm_path =  {}

for watershed_name in watershed_names[:]:
    
    dems_path = data_path + '_Europe/' + 'Topography/' # reginal DEM or conceptual DEM   

    # if watershed_name == 'Vosvozis':
    #     dem_name = 'EUDTM_Greece.tif'
    # if watershed_name == 'Hoal':
    #     dem_name = 'EUDTM_Austria-Poland.tif'
    # if watershed_name == 'Kocinka':
    #     dem_name = 'EUDTM_Austria-Poland.tif'
    # if watershed_name == 'Temmes':
    #     dem_name = 'EUDTM_Finland.tif'
    # if watershed_name == 'Canut':
    #     dem_name = 'EUDTM_Brittany.tif'
    # if watershed_name == 'Lasset':
    #     dem_name = 'EUDTM_Pyrenees.tif'
    # if watershed_name == 'Poschiavino':
    #     dem_name = 'EUDTM_Alps.tif'
    
    raw_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'.tif'
    
    x = imageio.imread(raw_dem_path)
    plt.imshow(np.ma.masked_where(x<0, x))
    
    # Depending on the choices
    library_path = data_path + 'watershed_library_wgs84.csv'
    library = pd.read_csv(library_path, sep=';') # each row is a study site with outlet coordinates
    lib = library[library['watershed_name']==watershed_name]
    
    # REPROJECT LAYER

    # All metric should be in meters (UTM or Lambert) during process
    # If your projection files is WGS84 (EPSG:4326), these tools could reproject layers
    # Below few examples to convert your data
    
    # d = gdal.Open(dem_path)
    # proj = osr.SpatialReference(wkt=d.GetProjection())
    # crs = int(proj.GetAttrValue('AUTHORITY',1))
    # d = None
    crs = None

    # if crs == 4326:
    
    # Convert longitude and latitude WGS84 to specific UTM
    utm_crs, x_utm, y_utm = toolbox.reproject_coord(lib['x_outlet'].values[0],
                                                    lib['y_outlet'].values[0])
    
    from_xy = [x_utm, y_utm, 300, 10]
    # print(utm_crs) 
    
    if watershed_name == 'Vosvozis':
        from_xy = [x_utm, y_utm, 2000, 10]
    
    if watershed_name == 'Temmes':
        from_xy = [x_utm, y_utm, 1000, 10]
    
    # Reproject raw DEM in WGS84 to specific UTM
    wgs_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'_wgs84'+'.tif'
    utm_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'_utm'+str(utm_crs.split(':')[-1])+'.tif'
    utm_crs = toolbox.reproject_tif(raw_dem_path,
                                    wgs_dem_path,
                                    utm_dem_path)
    # # Reproject shapefile layer to specific UTM
    # toolbox.reproject_shp(data_path + 'hydrology/' + types_obs[0] + '.shp',
    #                       data_path + 'hydrology/' + types_obs[0] + '_utm' + '.shp',
    #                       utm_crs)
    
    resamp_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'_utm'+str(utm_crs.split(':')[-1])+'_resamp100'+'.tif'
    
    ### Resampling
    wbt.resample(
        utm_dem_path, 
        resamp_dem_path, 
        cell_size=100, 
        base=None, 
        method="cc")
    # wbt.modify_no_data_value(
    #     data_path+'DEM_10m.tif',
    #     new_value="-99999")

    with rasterio.open(resamp_dem_path) as src:
        data = src.read()
        ras_meta = src.profile
        ras_meta['crs'] = utm_crs.upper()
    with rasterio.open(resamp_dem_path, "w", **ras_meta) as dest:
        dest.write(data)
    
    print('##### '+watershed_name.upper()+' #####')
    print(utm_crs.upper())
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=resamp_dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=from_xy,
                                  cell_size=cell_size)
    
    dict_utm_path[watershed_name] = [utm_dem_path, int(utm_crs.split(':')[-1])]
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    try:
        print(BV.geographic.area.round(2))
        print(BV.geographic.slope.round(2))
    except:
        pass
    
    try:
        watershed_display.watershed_dem(BV)
        watershed_display.watershed_local(utm_dem_path, BV)
    except:
        pass

#%% DATA TIF

load = True

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dict_utm_path[watershed_name][0], 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 

    # try:    
        
    list_tifs = glob.glob(stable_folder+"geographic/"+"*.tif")
    
    
    # dst_crs = utm_crs
    dst_crs = 'epsg:'+str(dict_utm_path[watershed_name][1])
    # dst_crs = 'epsg:3035'

    for i in list_tifs:

        tif_path = i
    
        with rasterio.open(tif_path, 'r') as src:
            raster = src.read()
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': dst_crs
            })
        with rasterio.open(tif_path, 'w', **kwargs) as dst:
            dst.write(raster)
    
    for i in list_tifs:

        tif_path = i
        
        open_tif = imageio.imread(tif_path)
        tif_name = tif_path.split('\\')[-1]
        # print(tif_name, open_tif.shape)
        
        if tif_name == 'watershed_box_buff_dem.tif':
            base_open_tif = open_tif
            base_dem_path = tif_path
            shape = open_tif.shape
        
        print(tif_name, open_tif.shape)
            
    """    
    for i in list_tifs:
        
        tif_path = i
        
       
        # dst_crs = 'epsg:3035'

        # with rasterio.open(tif_path, 'r') as src:
        #     raster = src.read()
        #     kwargs = src.meta.copy()
        #     kwargs.update({
        #         'crs': dst_crs
        #     })
        # with rasterio.open(tif_path, 'w', **kwargs) as dst:
        #     dst.write(raster)
    
        
        open_tif = imageio.imread(tif_path)
        tif_name = tif_path.split('\\')[-1]
        
        if np.nanmin(open_tif) ==  -99999:
        
            if open_tif.shape != shape:
                toolbox.export_tif(base_dem_path, open_tif, -99999, tif_path)
            
            wbt.set_nodata_value(
                    tif_path, 
                    tif_path, 
                    back_value=-99999)
            
            wbt.modify_no_data_value(
                    tif_path, 
                    new_value="-9999")
        
            # smaller_raster = gdal.Open(tif_path)
            # larger_raster  = gdal.Open(base_dem_path)
            
            # gt = smaller_raster.GetGeoTransform()
            # lt = larger_raster.GetGeoTransform()
            
            # SmlMaxX = gt[0] + (gt[1] * smaller_raster.RasterXSize)
            # SmlMinY = gt[3] + (gt[5] * smaller_raster.RasterYSize)
            # Xoff = int((gt[0] - lt[0])/lt[1]) # cols to skip
            # Yoff = int((gt[3] - lt[3])/lt[5]) # rows to skip
            # Cols = int((SmlMaxX - gt[0])/lt[1])
            # Rows = int((SmlMinY - gt[3])/lt[5])
            
            # # print out some numbers so you can check manually
            # print("X offset {}, Y offset {}".format(Xoff,Yoff))
            # print("Xmax {}, Ymin {}".format(SmlMaxX,SmlMinY))
            # print("Reading {} cols, {} rows".format(Cols,Rows))
            
            # band = larger_raster.GetRasterBand(1)
            # data = larger_raster.ReadAsArray(Xoff,Yoff,Cols,Rows) # read the larger raster
        
        check_tif = imageio.imread(tif_path)
        print(tif_name, check_tif.shape)
    """
    
    # except:
    #     pass

#%% DATA SHP

load = True

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dict_utm_path[watershed_name][0], 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 

    list_shps = glob.glob(stable_folder+"geographic/"+"*.shp")
    
    for i in list_shps:
        print(i)
        
        shp_path = i
        
        s = gpd.read_file(shp_path)
        # s = s.to_crs(3035)
        s = s.to_crs(dict_utm_path[watershed_name][1])
        s.to_file(shp_path)

#%% DATA HYDRO

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dict_utm_path[watershed_name][0], 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    
    hydrology_path = data_path + '_Europe/' + 'Hydrography/'

    h = gpd.read_file(hydrology_path + "EU-HYDRO_"+watershed_name+".gpkg")
    h = h.to_crs(dict_utm_path[watershed_name][1])
    h.to_file(hydrology_path + "EU-HYDRO_"+watershed_name+".shp")
        
    types_obs = ["EU-HYDRO_"+watershed_name]
    fields_obs = ["fid"]
            
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

    BV.add_hydrodynamic()
    BV.add_forcing()
    
    try:
        watershed_display.watershed_dem(BV)
        watershed_display.watershed_local(dict_utm_path[watershed_name][0], BV)
    except:
        pass
    
    """
    streams = hydrology_path + '/' +  types_obs[0] +'.shp'
    print(streams)
    streams_out = "C:/Users/ronan/Documents/SIMULATIONS/WATERLINE/CATCHMENTS/Vosvozis/results_stable/hydrology/" + types_obs[0] +'.shp'
    print(streams_out)
    
    # First clip of the shape file at the watershed scale (classical GIS function performed here in geopandas)
    #       geopandas more robust than wbt for the shapefiles
    #       clips steams_file by watshd_file
    
    streams_file = gpd.read_file(streams)
    watshd_file = gpd.read_file(BV.geographic.watershed_shp)
    file_clipped = gpd.clip(streams_file, watshd_file) # wbt.clip(streams, watershed_shp, self.streams)
    # saves clipped file to the reuslts file structure
    file_clipped.to_file(streams_out)
    
    streams_file.plot()
    watshd_file.plot()
    """

#%% DATA GW

load = True

gw_data = pd.DataFrame(watershed_names, columns=['watershed_names'])

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dict_utm_path[watershed_name][0], 
                                  out_path=out_path,
                                  load=True)
    
    s = gpd.read_file(BV.geographic.watershed_box_shp)
    s = s.to_crs(3035)
    s.to_file(BV.geographic.watershed_box_shp)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    
    gw_path = data_path + '_Europe/' + 'Groundwater/'
    
    toolbox.create_folder(stable_folder+'groundwater/')

    list_gwdata = glob.glob(gw_path+'*.tif')
    
    for i in list_gwdata:
        name = i.split('\\')[-1]
        if name != 'france_potentialrecharge.tif':
            gw_data_path = gw_path + name
            out_gw_path = stable_folder+'groundwater/'+name
            # x='C:/Users/ronan/Documents/SIMULATIONS/WATERLINE/CATCHMENTS/Vosvozis/results_stable/geographic/box_buff_leae.shp'
            wbt.clip_raster_to_polygon(gw_data_path,
                                       BV.geographic.watershed_box_shp,
                                       out_gw_path,
                                       maintain_dimensions=False)
            
            gw_rec_tif = imageio.imread(out_gw_path)
            gw_rec_tif[gw_rec_tif<0] = np.nan
            gw_rec_mean = np.nanmean(gw_rec_tif)
            print(round(gw_rec_mean,1))
            
            gw_data.loc[gw_data['watershed_names']==watershed_name, name[:-4]] = round(gw_rec_mean, 1)
    
    s = gpd.read_file(BV.geographic.watershed_box_shp)
    # s = s.to_crs(3035)
    s = s.to_crs(dict_utm_path[watershed_name][1])
    s.to_file(BV.geographic.watershed_box_shp)
    
#%% ---- MODELING DICHOTOMY

#%% DICHOTOMY STREAMS

# for watershed_name in ['Vosvozis', 'Kocinka', 'Temmes']:
# for watershed_name in ['Vosvozis']:
# for watershed_name in ['Canut']:

for watershed_name in watershed_names[2:]:
    
    if watershed_name != 'Hoal':
    
        df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
        
        for type_obs, field_obs in zip(types_obs, fields_obs):
       
            print('##### '+watershed_name.upper()+' #####')
            
            BV = watershed_root.Watershed(watershed_name=watershed_name,
                                          dem_path=dict_utm_path[watershed_name][0], 
                                          out_path=out_path,
                                          load=True,
                                          modflow_path=modflow_path)
            
            stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
            # BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
            
            BV.add_oceanic('None')
            BV.add_forcing()
            
            recharge = gw_data.loc[gw_data['watershed_names']==watershed_name,'Potential Groundwater Recharge bias corrected'].values[0]
            BV.forcing.update_recharge(recharge / 1000 / 365, sim_state='steady') #♠ mm/y to m/d
            
            BV.add_hydrodynamic()
            BV.hydrodynamic.update_nlay(1)
            BV.hydrodynamic.update_thickness(30)
            BV.hydrodynamic.update_bottom(None)
            BV.hydrodynamic.update_cond_decay(0)
            BV.hydrodynamic.update_thick_exp(1)
            
            params_df = pd.DataFrame(columns=['params',
                                              'init_values','lower_bounds','higher_bounds',
                                              'units','scale'])
            params_df.loc[0] = ['k1',
                                None,
                                1e-08*24*3600,
                                1e-03*24*3600,
                                'm/j',
                                'lin']
            params_file = 'calib_dicot_hom_1v_k1_'
            params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
            calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
            
            dicot = calib.dichotomy(gap=1)
    
            typ_calib = 'streams_calibration'
            list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                                key=os.path.getmtime)
            name_file = list_path[-1].split('\\')[-1]
            calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
            test = calib_analysis.CalibAnalysis(calib_file)
            test.display_objective_function(save=None)
            
            koptim = test.calib['params_values'][-1]
            kr = koptim / test.calib['recharge']
            obj_func = test.calib['objective_function'][-1]
                    
            df.loc[0,type_obs] = koptim / 24 / 3600
            df.loc[1,type_obs] = kr
            df.loc[2,type_obs] = obj_func
            
        df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
        df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% ---- NOTES


