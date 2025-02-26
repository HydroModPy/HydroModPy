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

    year = 1984
    # Define path data
    path_data = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
    # Initialize the object with the NetCDF file path        
    data = reanalysis.CerraData(path_data) 
    data.load_data()
    print(data.dataset)
#%%    
    data.crop_dataset(crop_coords = 'alps',
                      save = True,
                      inplace = True,
                      verbose = True)
    
    data.close()

