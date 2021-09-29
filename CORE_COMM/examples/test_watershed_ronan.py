# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

# Modules
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from osgeo import gdal
import rasterio as rio

import warnings

warnings.filterwarnings("ignore", 
                        message=".*An exception was ignored while fetching the attribute.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*`np.object` is a deprecated alias for the builtin `object`.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*is deprecated. Use tobytes().*",
                        category=DeprecationWarning)

warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                                            
# HydroModPy modules
from watershed import watershed_root
from tools import tif_adds, serie_transf

#%% ALL

# Users
user = "Ronan"

if user=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user=="Jean-Raynald":
    root_path= "C:/DATA/codes-gitlab-public/HydroModPy_data/"
    out_path = "C:/DATA/results/HydroModPy"
elif user=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
    # out_path = "D:/Users/abherve/RESULTS/rejets_metropole"
    analy_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/rejets_metropole"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = True
# watershed_name = 'Canut'
watershed_name = 'Lasset'
library_path = df + '/watershed' + '/watershed_library.csv'
# library_path = analy_path + '/outlets_basins.txt'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

dem_path = root_path + "/DEM/" + "BDALTI_09_25m.tif"
ndraster = gdal.Open(dem_path)  #read raster to get ND-value
ndband = ndraster.GetRasterBand(1) # read band to pick ND-value
ndar = ndraster.GetRasterBand(1).ReadAsArray()
ndval = ndband.GetNoDataValue()

surfex_path =  None
geology_path = root_path + 'GEOLOGY'
hydrology_path = root_path + 'HYDROLOGY'
modflow_path = root_path + 'MODFLOW'
piezometry_path = None
oceanic_path = None

########################################
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              library_path=library_path,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path,
                              geology_path=geology_path,
                              hydrology_path=hydrology_path,
                              piezometry_path=piezometry_path,
                              oceanic_path=oceanic_path, 
                              modflow_path=modflow_path,
                              load=load)

#%% RUN MODFLOW

rch = 1e-3
e=25;
K=rch*200;
porosity = 0.1
ident = str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch,3))

BV.run_modflow(ident=ident,
               climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
               hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)

#%% MERGE ZH STREAMS

pt_streams = stable_folder + 'hydrology/' + 'streams_pt.shp'
pt_zh = stable_folder + 'hydrology/' + 'zh_pt.shp'
merge_path = pt_streams+';'+pt_zh
pt_zhstreams = stable_folder + 'hydrology/' + 'zhstreams_pt.shp'
wbt.merge_vectors(merge_path, pt_zhstreams)

tif_streams = stable_folder + 'hydrology/' + 'streams.tif'
tif_zh = stable_folder + 'hydrology/' + 'zh.tif'
merge_path = tif_streams+';'+tif_zh
tif_zhstreams = stable_folder + 'hydrology/' + 'zhstreams.tif'
wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")

#%% DICHOTOMY CALIBRATION

type_river = 'zhstreams'

BV.calib_dichotomy(ident=None, calib=True, type_river=type_river, climatic=pd.Series(1e-3), 
                   lay_number=1, thick=50, bottom=None, thick_exp=1., 
                   first=1, last=500, gap=10, porosity=0.01, 
                   sea_level=None, cond_decay=0.)

#%%

# zh = hydrology_path +'/zhtempo_09.shp'
# watershed_shp = stable_folder + 'geographic/' + 'watershed.shp'
# watershed_dem = stable_folder + 'geographic/' + 'watershed_dem.tif'

# clip_zh = stable_folder + 'hydrology/' + 'zh.shp'
# wbt.clip(zh, watershed_shp, clip_zh)

# tif_zh = stable_folder + 'hydrology/' + 'zh.tif'
# wbt.vector_polygons_to_raster(zh, tif_zh, field="FID", base=watershed_dem)
# pt_streams = stable_folder + 'hydrology/' + 'zh_pt.shp'

# wbt.raster_to_vector_points(tif_zh, pt_zh)

#%%

# rea_path = stable_folder+'climatic/'+'REA.h5'
# first = 1960
# last = 2019

# rech = pd.read_hdf(rea_path,'REC/'+'historic')
# rech = rech[(rech.index.year >= first) & (rech.index.year <= last)]
# rech = rech.MEAN
# rech = rech.resample('M').sum()
# rech = rech / 1000

# runof = pd.read_hdf(rea_path,'RUN/'+'historic')
# runof = runof[(runof.index.year >= first) & (runof.index.year <= last)]
# runof = runof.MEAN
# runof = runof.resample('M').sum()
# runof = runof / 1000

#%%
