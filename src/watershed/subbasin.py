# -*- coding: utf-8 -*-
"""

"""

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
wbt.verbose = True

#%% HYDROMODPY ROOT PATH

from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

cwd = os.getcwd()
if cwd == root_dir:
    print("Root path directory is: {0}".format(cwd))
else:
    os.chdir(root_dir)
    print("Root path directory is: {0}".format(cwd))

#%% HYDROMODPY IMPORT MODULES

# Import HydroModPy modules
import watershed_root
from watershed import climatic, geographic, geometric, hydraulic, hydrography, hydrometry, intermittency, lithology, oceanic, piezometry
from modeling import downslope, modflow, modpath, timeseries
from display import visualization_watershed, visualization_results, export_vtuvtk
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% SPECIFIC INPORT MODULES

from pyproj import Transformer
from geopy.geocoders import Nominatim
import shutil

#%% CLASS

class Subbasin:
    
    #%% INIT
    
    def __init__(self, geographic, hydrometry, intermittency,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):        
        print('Extraction des données sous-bassins')
        
        self.subbasin_path = os.path.join(out_path, 'results_stable/subbasin/')
        if not os.path.exists(self.subbasin_path):
            toolbox.create_folder(self.subbasin_path)
        
        self.adddata_path = os.path.join(out_path, 'results_stable/add_data/')
        if not os.path.exists(self.adddata_path):
            toolbox.create_folder(self.adddata_path)
        
        try:
            code_bh = hydrometry.code_bh
            x_coord = hydrometry.x_coord
            y_coord = hydrometry.y_coord
            for i in range(len(code_bh)):
                sub_path = os.path.join(self.subbasin_path, 'hydrometry_'+code_bh[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
        
        try:
            code_onde = intermittency.code_onde
            x_coord = intermittency.x_coord
            y_coord = intermittency.y_coord
            for i in range(len(code_onde)):
                sub_path = os.path.join(self.subbasin_path, 'intermittency_'+code_onde[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
        
        try:
            code_sub, x_coord, y_coord = self.add_coord_manual()
            for i in range(len(code_sub)):
                sub_path = os.path.join(self.subbasin_path, 'subbasin_'+code_sub[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
    
    #%% SUB-CATCHMENT FROM STATIONS
    
    # Extract sub-catchment from existing stations : hydrometry or intermittency
    
    def extract_interest_zones(self, geographic, X, Y, outpath):
        # Path of subbasin
        if os.path.exists(outpath):
            shutil.rmtree(outpath)
        toolbox.create_folder(outpath)        
        # Coordinates
        outpath = outpath + '/'
        df = pd.DataFrame({'x': [X], 'y': [Y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=geographic.crs)
        outlet_shp = outpath + 'outlet.shp'
        gdf.to_file(outlet_shp)
        # Snap the outlet shapefile from the flow accumulation
        outlet_snap_shp = outpath + 'outlet_snap.shp'
        wbt.snap_pour_points(outlet_shp, geographic.reg_path + 'region_acc.tif', 
                             outlet_snap_shp, geographic.snap_dist)
        # Generate raster watershed
        watershed = outpath + 'watershed.tif'
        wbt.watershed(geographic.reg_path + 'region_direc.tif', outlet_snap_shp, watershed, esri_pntr=False)
        # Create shapefile polygon of the watershed
        watershed_shp = outpath + 'watershed.shp'
        wbt.raster_to_vector_polygons(watershed, watershed_shp)
        shp = gpd.read_file(watershed_shp)
        shp.set_crs(geographic.crs, inplace=True, allow_override=True)
        shp.to_file(watershed_shp)
        wbt.polygon_area(watershed_shp)
        area = gpd.read_file(watershed_shp).AREA[0]/1000000
        area = np.abs(area)
        # Create shapefile polyline of the watershed
        watershed_contour_shp = outpath + 'watershed_contour.shp'
        wbt.polygons_to_lines(watershed_shp, watershed_contour_shp)
        # Clip buffer watershed DEM from watershed shapefile polygon
        watershed_dem = outpath + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(geographic.watershed_buff_dem, watershed_shp, watershed_dem, maintain_dimensions=True)        
    
    #%% SUB-CATCHMENT FROM XY POINT
    
    # From a .csv file with x, y coordinates representing the outlet desired sub-catchments
    
    def add_coord_manual(self):
        path_coord = glob.glob(self.adddata_path+'/'+'*')[0]
        print(self.adddata_path)
        sub_list = pd.read_csv(path_coord, sep=';')
        print(sub_list)
        code_sub = sub_list['code_sub'].to_list()
        x_coord = sub_list['x_outlet'].to_list()
        y_coord = sub_list['y_outlet'].to_list()
        return code_sub, x_coord, y_coord
        
#%% NOTES
