# -*- coding: utf-8 -*-
"""
Created on Thu Aug 19 08:43:31 2021

@author: ronan
"""

import os
import sys
import pandas as pd

import geopandas as gpd
from osgeo import gdal, osr
from shutil import copyfile
import numpy as np
from IPython.core.debugger import set_trace as st
### Method 1
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)


comm = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
sys.path.append(comm+"src/")
import watershed as wat

spec = "D:/Users/abherve/GITHUB/HydroModPy/DEV_SPEC/Ronan/"

dem_path = spec + "test/" + "Bretagne.tif"
outlets_path = spec + "test/" + "outlets_test.txt"

outlets = pd.read_csv(outlets_path, sep='\t', header=None, engine='python')

for idx, serie in outlets.iterrows():
    
    outlet = outlets.loc[[idx]]
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    
    outlet = outlet.iloc[:,1:3]
    
    wat.extract_watershed(dem_path,
                          site,
                          outlet,
                          snap_dist=snap,
                          buff_dist=1000,
                          save_gis=True,
                          box = False,
                          tmp_path=spec + 'tmp/',
                          out_path=spec + 'output/')