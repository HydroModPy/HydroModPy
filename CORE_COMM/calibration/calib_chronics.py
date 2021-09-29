# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

import geopandas as gpd
from glob import glob
from osgeo import gdal
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import shutil
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)

from tools import file_adds
from tools import tif_masks
from tools import tif_masks
from tools import tif_features

class Comparison:
    def __init__(self, geographic, outlet_type=None, mask=False, hydrology_path=None, subbasins_folder=None):
        
        bv = gdal.Open(geographic.watershed_dem)
        geodata = bv.GetGeoTransform()
        self.dem_clip = bv.GetRasterBand(1).ReadAsArray()
        self.resolution = geodata[1]
        
        self.mask = mask
        self.outlet_type = outlet_type
        self.hydrology_path = hydrology_path
        self.subbasins_folder = subbasins_folder
    
    # def import_climate:
        
    # def efficiency_indicators:
        
    def compar_discharge(self):

        
        return obs_data, sim_data
        
    # def compar_onde:
        
    # def display_discharge:
        
    # def display_onde:
    
    