# -*- coding: utf-8 -*-
"""
Created on Mon Feb 17 15:53:39 2025

@author: delarueo
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import math as m

import geopandas as gpd
from shapely.geometry import Polygon

import rioxarray

import xarray as xr

import cartopy.crs as ccrs
import cartopy
import cartopy.feature as cfeature

import rasterio
from rasterio.plot import show
import numpy as np
import matplotlib.contour as contour

import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.ticker import LongitudeLocator, LatitudeLocator
from matplotlib.ticker import MaxNLocator

import netCDF4

import reanalysis_data_cerra as reanalysis

#%%

if __name__ == "__main__":

    # command = input("Select an action ['load' 'display' 'plot' 'close' 'stop']:")

    # Define path polygone
    polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
    polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
    # Load the polygon
    polygon = gpd.read_file(polygon_path)
    polygon = polygon.to_crs(epsg=4326) 


    
    ## Case open one file
    year = 1984
    # Define path data
    path_data = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
    # Initialize the object with the NetCDF file path        
    data = CerraData(path_data) 
    data.load_data()
    print(data.dataset)
    


