# -*- coding: utf-8 -*-
"""
Created on Fri Jan 31 15:22:31 2025

@author: delarueo
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import math as m

import geopandas as gpd
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

#%%

class TimeSerie:
    def __init__(self,file_path):
        
        self.file_path = file_path        
        self.loc = 0
        self.crs = 4326
        self.timeserie = pd.DataFrame()
        
    def load_data(self):
        print('aaaaaaaaa')
        
        
        

# class PixelTimeSerie(TimeSerie):
    
#     def __init__(self,file_path):
        
#         self.file_path = file_path        
#         self.loc = 0
#         self.pixel = Polygon()
#         self.crs = 4326
#         self.timeserie = pd.DataFrame()
    
    

# class PointTimeSerie(TimeSerie):
    
    