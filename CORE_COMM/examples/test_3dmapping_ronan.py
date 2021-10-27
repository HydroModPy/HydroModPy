# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé, modified Clement Roques
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
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.set_verbose_mode(False)

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

# Modules for mapping
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm

#%%

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
    # analy_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/rejets_metropole"
elif user=="Clement":
    root_path= "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_data/"
    out_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/"
    #analy_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_process/"
elif user=="Clement_portable":
    root_path= "G:/My Drive/1.TRAVAIL/PYTHON/FLOPY/_data/"
    out_path = "G:/My Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/"
    #analy_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_process/"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = True
# watershed_name = 'Canut'
watershed_name = 'Canut'
library_path = df + '/watershed' + '/watershed_library.csv'
#library_path = analy_path + '/outlets_basins.txt'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# dem_path = root_path + "/DEM/" + "BDALTI_09_25m.tif"
dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

surfex_path =  root_path + 'SURFEX'
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

#%% EXTRACT RECHARGE FROM SURFEX

rech_path = stable_folder+'climatic/'+'REA.h5'
rech = pd.read_hdf(rech_path,'REC/'+'historic')
first = 1970
last = 2019
rech = rech[(rech.index.year >= first) & (rech.index.year <= last)]
rech = rech.MEAN
rech = rech.resample('M').sum()
rech = rech #mm/M

#%% Import DEM and plot

dem_cut = stable_folder + 'geographic/watershed_dem.tif'
demDs = gdal.Open(dem_cut)
demData = demDs.GetRasterBand(1).ReadAsArray()
geot = demDs.GetGeoTransform()
dx = geot[1] #delta x
dy = abs(geot[5]) #delta y
demData_raw = demData
msk = (demData==np.min(demData))
demData = np.ma.masked_array(demData, mask=msk)

lx,ly = demData.shape
x = np.linspace(0,lx,lx)
y = np.linspace(0,ly,ly)

xx, yy = np.meshgrid(y,x)
xx_mi = np.min(np.ma.array(xx, mask=msk))
xx_ma = np.max(np.ma.array(xx, mask=msk))
ext_x = xx_ma-xx_mi

yy_mi = np.min(np.ma.array(yy, mask=msk))
yy_ma = np.max(np.ma.array(yy, mask=msk))
ext_y = yy_ma-yy_mi

#%% IMPORT modflow results

dir_to_analyse = simulations_folder + 'ext-0.1-19.833-50-0.018/_extraction/'
figdir = dir_to_analyse + 'fig/'
water_table_path = dir_to_analyse + 'watertable_elevation.npy'
outflow_path = dir_to_analyse + 'outflow_drain.npy'

wt_all = np.load(water_table_path, allow_pickle=True).item() 
outflow_all = np.load(outflow_path, allow_pickle=True).item() 

surface_sat = []
rech_for_gif = []
time_for_gif = []
flow_rate = []


for key in wt_all:
    
    t_temp = rech.index[key]
    time_for_gif.append(t_temp)
    
    wt = wt_all[key]
    wt = np.ma.masked_array(wt, mask=msk)
    wt_len = len(wt[wt>0])
    
    outflow = outflow_all[key]
    msk_outflow = (outflow==np.min(outflow))
    outflow = np.ma.masked_array(outflow, mask=msk_outflow)
    outflow = np.ma.masked_where(outflow==0,outflow)
    outflow_len = len(outflow[outflow>0])
    
    flow_rate_temp = np.sum(outflow)
    flow_rate.append(flow_rate_temp)
    
    surface_sats = outflow_len/wt_len*100
    surface_sat.append(surface_sats)
    
   
    #fig, (ax1, ax2, ax3, ax4) = plt.subplots(figsize=(13, 3), ncols=3)
    fig = plt.figure(figsize=(11,6))
    gs = fig.add_gridspec(3,2)
    ax1=fig.add_subplot(gs[:, 0])
    ls = LightSource(azdeg=45, altdeg=45)
    cmap = plt.cm.gist_earth
    rgb = ls.shade(demData, cmap=cmap, blend_mode='soft',
                       vert_exag=2, dx=dx, dy=dy)
    
    ax1.imshow(rgb,alpha=1)
    
    #plot the head contour lines
    cmap = plt.get_cmap('Blues')
    levels = np.arange(1000, 3000, 100)
    hc=ax1.contour(xx, yy, wt, alpha=1, cmap=cmap,linewidths=0.5, levels=levels)
    ax1.clabel(hc, inline=True, fontsize=9, fmt='%1.0f')
    levels_outflow = np.arange(-1, 4, 0.5)
    cf=ax1.contourf(xx, yy, np.log10(outflow), levels=levels_outflow, cmap=cm.afmhot_r, alpha=1,antialiased = True)
    fig.colorbar(cf,ax = ax1)
    plt.xlim(xx_mi-0.1*ext_x,xx_ma+0.1*ext_x)
    plt.ylim(yy_ma+0.1*ext_y,yy_mi-0.1*ext_y)
    
    ax2=fig.add_subplot(gs[0, 1])
    rechs = rech[key]
    rech_for_gif.append(rechs)
    ax2.set_ylabel("recharge, [mm/M]")
    ax2.plot(time_for_gif,rech_for_gif,'m')
    plt.setp(ax2.get_xticklabels(), visible=False)
    
    ax3=fig.add_subplot(gs[1, 1])
    #ax3.set_xlabel("time")
    ax3.set_ylabel("saturated area, [%]")
    ax3.plot(time_for_gif,surface_sat,'r')
    plt.setp(ax3.get_xticklabels(), visible=False)
    
    ax4=fig.add_subplot(gs[2, 1])
    ax4.set_xlabel("time")
    ax4.set_ylabel("discharge, [mm/M]")
    ax4.plot(time_for_gif,flow_rate,'b')
    ax4.set_yscale("log")

    name_fig = 'dyn_' + str(key) + '.png'
    plt.tight_layout()
    plt.savefig(figdir + 'png/' + name_fig)
    plt.close(fig)
    print(str(key))
        
#%% MAKE A GIF
import glob

from PIL import Image

frame_folder = figdir + 'png/'
path_gif = figdir + 'gif/'


def make_gif(frame_folder):
    frames = [Image.open(image) for image in glob.glob(f"{frame_folder}/*.PNG")]
    frame_one = frames[0]
    frame_one.save(path_gif + 'dyn_outflow.gif', format="GIF", append_images=frames,
               save_all=True, duration=200, loop=0)
    

if __name__ == "__main__":
    make_gif(frame_folder)

# water_table =  np.ma.array(water_table, mask=bnd)
# seepage =  np.ma.array(seepage, mask=bnd)
# seepage = ma.masked_where(seepage==0,seepage)



#plot seepage
# plt.contourf(xx, yy, seepage, cmap=cm.afmhot,alpha=0.9,antialiased = True)

#plot catchment boundary
# for contour in bnd_contour:
#     plt.plot(contour[:, 1], contour[:, 0], linewidth=1,color = 'm')
    
# #plot canfinal subcatchment boundary
# for contour in bnd_contour2:
#     plt.plot(contour[:, 1], contour[:, 0], linewidth=1,color = 'r')
    
# #plot poschiavino subcatchment boundary
# for contour in bnd_contour3:
#     plt.plot(contour[:, 1], contour[:, 0], linewidth=1,color = 'r')


#plt.axis('off')





#%%


# BV = watershed_root.Watershed(watershed_name=watershed_name,
#                               library_path=library_path,
#                               dem_path=dem_path, 
#                               out_path=out_path,
#                               surfex_path=surfex_path,
#                               geology_path=geology_path,
#                               hydrology_path=hydrology_path,
#                               piezometry_path=piezometry_path,
#                               oceanic_path=oceanic_path, 
#                               modflow_path=modflow_path,
#                               load=load)


#%% RUN MODFLOW
"""
rch = 1e-3
e=25;
K=rch*200;
porosity = 0.1
ident = str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch,3))

BV.run_modflow(ident=ident,
               climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
               hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
"""

#%% RUN MODFLOW
#Merger les points shp
# pt_streams = stable_folder + 'hydrology/' + 'stream_digit_pt.shp'
# pt_zh = stable_folder + 'hydrology/' + 'zh_digit_pt.shp'
# merge_path = pt_streams+';'+pt_zh
# pt_zhstreams = stable_folder + 'hydrology/' + 'zhstreams_pt.shp'
# wbt.merge_vectors(merge_path, pt_zhstreams)

# #Merger les tifs
# tif_streams = stable_folder + 'hydrology/' + 'stream_digit.tif'
# tif_zh = stable_folder + 'hydrology/' + 'zh_digit.tif'
# merge_path = tif_streams+';'+tif_zh
# tif_zhstreams = stable_folder + 'hydrology/' + 'zhstreams.tif'
# wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")


# #%% EXTRACT RECHARGE FROM SURFEX
# rech_path = stable_folder+'climatic/'+'REA.h5'
# rech = pd.read_hdf(rech_path,'REC/'+'historic')
# first = 1970
# last = 2019
# rech = rech[(rech.index.year >= first) & (rech.index.year <= last)]
# rech = rech.MEAN
# rech = rech.resample('M').sum()
# rech = rech / 1000 #mm to m

# fig1 = plt.figure(1)
# ax1 = fig1.add_subplot(1,1,1)
# ax1.set_xlabel("time, [-]")
# ax1.set_ylabel("recharge [m/M]")
# #ax.set_xscale("log")
# ax1.plot(rech)
# fig1.show()


