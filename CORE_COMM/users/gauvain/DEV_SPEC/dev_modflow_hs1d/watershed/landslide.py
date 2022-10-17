# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 20:10:52 2021

@author: Alexandre Gauvain
"""

# Modules
import geopandas as gpd
import numpy as np
import os
from osgeo import gdal, osr
import pandas as pd
from pyproj import Transformer
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.set_verbose_mode(False)

# HydroModPy modules
from tools import file_adds

#%% Functions potentially 

def aggregate_raster(dem_path, output_dem_path, new_xres, new_yres):
    inDs = gdal.Open(dem_path)
    outDs = gdal.Warp(output_dem_path, inDs, format = 'GTiff',
                      xRes = new_xres, yRes = new_yres,
                      resampleAlg = gdal.GRA_Average)
    inDs = None
    outDs = None
    
def coord_from_pixel(file,dx,dy):
    px = file.GetGeoTransform()[0]
    py = file.GetGeoTransform()[3]
    rx = file.GetGeoTransform()[1]
    ry = file.GetGeoTransform()[5]
    x = dx*rx + px
    y = dy*ry + py
    return x,y
coord_from_pixel(500,1000)

def pixel_from_coord(file,dx,dy):
    px = file.GetGeoTransform()[0]
    py = file.GetGeoTransform()[3]
    rx = file.GetGeoTransform()[1]
    ry = file.GetGeoTransform()[5]
    ulx, xres, xskew, uly, yskew, yres  = file.GetGeoTransform()
    lrx = px + (file.RasterXSize * xres)
    lry = py + (file.RasterYSize * yres)
    xpiez_pix = (dx - px) / rx
    ypiez_pix = (dy - lry) / abs(ry)
    return xpiez_pix * pix, ypiez_pix * pix

def linregress(inx,iny):
    import scipy as sp
    x=np.array(inx.values, dtype=float)
    y=np.array(iny.values, dtype=float)
    xmas = np.ma.masked_array(x,mask=np.isnan(y)).compressed()
    ymas = np.ma.masked_array(y,mask=np.isnan(y)).compressed()
    slope, intercept, r_value, p_value, std_err = sp.linregress(xmas,ymas) 
    xf = np.linspace(min(x),max(x),100)
    yf = (slope*xf)+intercept
    center_x = xf.mean()
    center_y = yf.mean()
    lenght_reg = [[xf.min(),xf.max()],[yf.min(),yf.max()]]
    return (center_x, center_y, slope, intercept, r_value, p_value, std_err, lenght_reg)

#%%   
    
qh = pdf[idx].flatten('F')
LBINS = 50
# No log
linbins = np.linspace(0,qh.max(),LBINS)
hist_lin, bins_lin = np.histogram(qh, bins=linbins, density=True)
bins_lin_centers = 0.5*(bins_lin[1:]+bins_lin[:-1])
# Log
logbins = np.logspace(np.log10(qh.max())-3,np.log10(qh.max()),LBINS)
hist_log, bins_log = np.histogram(qh, bins=logbins, density=True)
bins_log_centers = 10**(0.5*(np.log10(bins_log[1:])+np.log10(bins_log[:-1])))

#%%

def data_html(path, html_object):
    html = codecs.open(path, 'r')
    html = str(html.read())

    start = html.find("dataX: [[") + len("dataX: [[")
    end = html.find("dataY: [[")
    dataX = html[start:end].split(']]')[0]
    dataX = dataX.split(']')
    dataX = [i.replace(', [','') for i in dataX]
    dataX = [i.replace(' ','') for i in dataX]
    dataX = [i.split(',') for i in dataX]
    dataX = [list(map(float, sublist)) for sublist in dataX]
    
    start = html.find("dataY: [[") + len("dataY: [[")
    end = html.find("seriesLabels: []")
    dataY = html[start:end].split(']]')[0]
    dataY = dataY.split(']')
    dataY = [i.replace(', [','') for i in dataY]
    dataY = [i.replace(' ','') for i in dataY]
    dataY = [i.split(',') for i in dataY]
    dataY = [list(map(float, sublist)) for sublist in dataY]
    
    if html_object == 'longprofile':
        profil = [index for index, value in enumerate(dataX)]
        for i, j in enumerate(profil):
            profil[j] = "\"" + 'Profile' + str(i) +"\""
    if html_object == 'profile':
        start = html.find("seriesLabels: [") + len("seriesLabels: [")
        end = html.find("xAxisLabel: ")
        profil = html[start:end].split(']]')[0]
        profil = profil.split(',')
        profil = [i.replace(' ','') for i in profil]
        profil = [i.replace(']','') for i in profil]
        profil = [i.replace('[','') for i in profil]
        while("\n" in profil) : 
            profil.remove("\n")
    
    return dataX, dataY, profil

#%% 
    
### Slope ###
slope_path = path
wbt.slope(dem_path, slope_path)
##### Stream network of site #####
netw_path = path
wbt.extract_streams(acc_path, netw_path, 8, zero_background=True) # increase = number of rivers
##### Unnset basins #####
unnset = path
wbt.unnest_basins(direc_path, snap_path, unnset_path)
##### Subbasins #####
sub_path = path
wbt.subbasins(direc_path, netw_path, sub_path)
##### Hillslope #####
hill_path = path
wbt.hillslopes(direc_path, netw_path, hill_path)
##### Merge network #####
single_netw_path = path
wbt.single_part_to_multi_part(netw_line_path, single_netw_path, field=None)
##### Main stream #####
main_path = path
wbt.find_main_stem(direc_path, netw_path, main_path, zero_background=False)
##### Density #####
density_path = path
wbt.length_of_upstream_channels(direc_path, netw_path, density_path)
##### Distance #####
outlet_dist_path = path
wbt.distance_to_outlet(direc_path, netw_path, outlet_dist_path)
##### Longitudinal profile #####
longprofile_path = path
wbt.long_profile(direc_path, netw_path, fill_path, longprofile_path)
topoX, topoY, topoP = data_html(longprofile_path, 'longprofile')
for x, y, p in zip(topoX, topoY, topoP):
    ax.plot(x, y)
##### Profile #####
profile = path
wbt.profile(netw_line_path, fill_path, profile_path)
topoX, topoY, topoP = data_html(profile_path, 'profile')
for x, y, p in zip(topoX, topoY, topoP):
    ax.plot(x, y)
##### Hypsometric analysis #####
hypso_path = path
wbt.hypsometric_analysis(dem_path, hypso_path, watershed=None)
##### Strahler bo #####
strah_bo_path = path
wbt.strahler_order_basins(direc_path, netw_path, strah_bo_path)
##### Strahler so #####
strah_so_path = path
wbt.strahler_stream_order(direc_path, netw_path, strah_so_path)
##### Rugnessidx #####
tri_path = path
wbt.ruggedness_index(fill_path, tri_path)
##### Wetnesstopoidx #####
dinf_path = path
wbt.d_inf_flow_accumulation(fill_path, dinf_path, out_type="Specific Contributing Area", 
                            threshold=None, log=False, clip=False, pntr=False)
wti_path = path
wbt.wetness_index(dinf_path, slope_path, wti_path)
##### Pennock #####
pennock_path = path
wbt.pennock_landform_class(fill_path, penok_path, slope=3.0, prof=0.1, plan=0.0, zfactor=1)

#%%

# Modules
from IPython import get_ipython
import matplitliv as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import scipy as sp
get_ipython().run_line_magic('matplotlib', 'qt')
# Import data
Data = dem_data
# Create figures
fig, main_ax = plt.subplots(figsize=(7, 7))
title = plt.suptitle('Interactive cross section head',y=0.87)
divider = make_axes_locatable(main_ax)
top_ax = divider.append_axes("top", 1.05, pad=0.2, sharex=main_ax)
right_ax = divider.append_axes("right", 1.05, pad=0.2, sharey=main_ax)
# Delete axis
top_ax.xaxis.set_tick_params(labelbottom=False)
right_ax.yaxis.set_tick_params(labelleft=False)
# Axis names
main_ax.set_xlabel('X')
main_ax.set_ylabel('Y')
top_ax.set_ylabel('Z profile')
right_ax.set_xlabel('Z profile')
# Dimensions
xvalues = np.linspace(-1,1,Data.shape[1])
yvalues = np.linspace(-1,1,Data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)
# Positions
pos = np.empty(xx.shape + (2,))
pos[:, :, 0] = xx
pos[:, :, 1] = yy
# V and H lines
cur_x = 300
cur_y = 200
# Data head
z_max = Data.max()
# zprof = head_data[0]
zprof = Data.astype(float)
zprof[zprof==-9999] = np.nan
### Line cross-section : neighbours
x0, y0 = 100, 350 # These are in _pixel_ coordinates !
x1, y1 = 500, 50
num = int(np.hypot(x1-x0, y1-y0))
num = x1-x0
x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
zi = zprof[y.astype(np.int), x.astype(np.int)] # or: zi = scipy.ndimage.map_coordinates(z, np.vstack((y,x)))
#    ### Line cross-section : cubic
#    d_x = [500,200]
#    d_y = [50,400]
#    length = int(np.hypot(d_x[1]-d_x[0], d_y[1]-d_y[0]))
#    xd, yd = np.linspace(d_x[0], d_x[1], length), np.linspace(d_y[0], d_y[1], length)
#    zd = sp.ndimage.map_coordinates(zprof, np.vstack((yd,xd))) # Transpose ?
# Plot dem
demPlot = np.ma.masked_array(Data, mask=(Data==-9999))
# demPlot = np.flip(demPlot,axis=0)
main_ax.imshow(demPlot, origin='lower')
plt.gca().invert_yaxis()
# Scaling axis
main_ax.autoscale(enable=False)
right_ax.autoscale(enable=False)
top_ax.autoscale(enable=False)
right_ax.set_xlim(right=z_max)
top_ax.set_ylim(top=z_max)
# Plot lines
v_line = main_ax.axvline(cur_x, color='r')
h_line = main_ax.axhline(cur_y, color='g')
d_line = main_ax.plot((x0,x1),(y0,y1), 'b-')
# Plot cross-sections
v_plot = zprof[:,int(cur_x)]
v_plot[v_plot == 0] = np.nan
h_plot = zprof[int(cur_y),:]
h_plot[h_plot == 0] = np.nan
v_prof, = right_ax.plot(v_plot,np.arange(xx.shape[0]), 'r-')
h_prof, = top_ax.plot(np.arange(xx.shape[1]),h_plot, 'g-')
d_prof, = top_ax.plot(x, zi, 'b-')
# Animation interactive
def on_move(event):
    if event.inaxes is main_ax:
        cur_x = event.xdata
        cur_y = event.ydata        
        v_plot = zprof[:,int(cur_x)]
        v_plot[v_plot == 0] = np.nan
        h_plot = zprof[int(cur_y),:]
        h_plot[h_plot == 0] = np.nan        
        v_line.set_xdata([cur_x, cur_x])
        h_line.set_ydata([cur_y, cur_y])
        v_prof.set_xdata(v_plot)
        h_prof.set_ydata(h_plot)
        fig.canvas.draw_idle()
fig.canvas.mpl_connect('motion_notify_event', on_move)

#%%

from mayavi import mlab

def mayavi_surf(topo_way, wt_way):
    # 1) opening maido geotiff as an array
    topo = gdal.Open(topo_way)
    dem_topo = topo.ReadAsArray()
    # 2) transformation of coordinates
    columns = topo.RasterXSize
    rows = topo.RasterYSize
    gt = topo.GetGeoTransform()
    ndv = topo.GetRasterBand(1).GetNoDataValue()
    x = (columns * gt[1]) + gt[0]
    y = (rows * gt[5]) + gt[3]
    X = np.arange(gt[0], x, gt[1])
    Y = np.arange(gt[3], y, gt[5])
    # 3) creation of a simple grid without interpolation
    X, Y = np.meshgrid(X, Y)
    #Mayavi requires col, row ordering. GDAL reads in row, col (i.e y, x) order
    dem_topo = np.rollaxis(dem_topo,0,2)
    X = np.rollaxis(X,0,2)
    Y = np.rollaxis(Y,0,2)
    # 4) deleting the "no data" values
    dem_topo = dem_topo.astype(np.float32)
    dem_topo[dem_topo == ndv] = np.nan #if it's NaN, mayavi will interpolate
    # delete the last column
    dem_topo = np.delete(dem_topo, len(dem_topo)-1, axis = 0)
    X = np.delete(X, len(X)-1, axis = 0)
    Y = np.delete(Y, len(Y)-1, axis = 0)
    # delete the last row
    dem_topo = np.delete(dem_topo, len(dem_topo[0])-1, axis = 1)
    X = np.delete(X, len(X[0])-1, axis = 1)
    Y = np.delete(Y, len(Y[0])-1, axis = 1)
    # 5) plot
    surf_topo = mlab.surf(X, Y, dem_topo, colormap='jet', warp_scale=10, opacity=1)
    # 1) opening maido geotiff as an array
    wt= gdal.Open(wt_way)
    dem_wt = wt.ReadAsArray()
    # 2) transformation of coordinates
    columns = wt.RasterXSize
    rows = wt.RasterYSize
    gt = wt.GetGeoTransform()
    ndv = wt.GetRasterBand(1).GetNoDataValue()
    x = (columns * gt[1]) + gt[0]
    y = (rows * gt[5]) + gt[3]
    X = np.arange(gt[0], x, gt[1])
    Y = np.arange(gt[3], y, gt[5])
    # 3) creation of a simple grid without interpolation
    X, Y = np.meshgrid(X, Y)
    #Mayavi requires col, row ordering. GDAL reads in row, col (i.e y, x) order
    dem_wt = np.rollaxis(dem_wt,0,2)
    X = np.rollaxis(X,0,2)
    Y = np.rollaxis(Y,0,2)
    # 4) deleting the "no data" values
    dem_wt = dem_wt.astype(np.float32)
    dem_wt[dem_wt == ndv] = np.nan #if it's NaN, mayavi will interpolate
    # delete the last column
    dem_wt = np.delete(dem_wt, len(dem_wt)-1, axis = 0)
    X = np.delete(X, len(X)-1, axis = 0)
    Y = np.delete(Y, len(Y)-1, axis = 0)
    # delete the last row
    dem_wt = np.delete(dem_wt, len(dem_wt[0])-1, axis = 1)
    X = np.delete(X, len(X[0])-1, axis = 1)
    Y = np.delete(Y, len(Y[0])-1, axis = 1)
    # 5) plot
    surf_wt = mlab.surf(X, Y, dem_wt, colormap='binary', warp_scale=10, opacity=1)
    mlab.show(stop=True)

#%%

def mayavi_create(path):
    # 1) opening maido geotiff as an array
    tif = gdal.Open(path)
    dem = tif.ReadAsArray()
    # 2) transformation of coordinates
    columns = tif.RasterXSize
    rows = tif.RasterYSize
    gt = tif.GetGeoTransform()
    ndv = tif.GetRasterBand(1).GetNoDataValue()
    x = (columns * gt[1]) + gt[0]
    y = (rows * gt[5]) + gt[3]
    X = np.arange(gt[0], x, gt[1])
    Y = np.arange(gt[3], y, gt[5])
    # 3) creation of a simple grid without interpolation
    X, Y = np.meshgrid(X, Y)
    #Mayavi requires col, row ordering. GDAL reads in row, col (i.e y, x) order
    dem = np.rollaxis(dem,0,2)
    X = np.rollaxis(X,0,2)
    Y = np.rollaxis(Y,0,2)
    # 4) deleting the "no data" values
    dem = dem.astype(np.float32)
    dem[dem == ndv] = np.nan #if it's NaN, mayavi will interpolate
    # delete the last column
    dem = np.delete(dem, len(dem)-1, axis = 0)
    X = np.delete(X, len(X)-1, axis = 0)
    Y = np.delete(Y, len(Y)-1, axis = 0)
    # delete the last row
    dem = np.delete(dem, len(dem[0])-1, axis = 1)
    X = np.delete(X, len(X[0])-1, axis = 1)
    Y = np.delete(Y, len(Y[0])-1, axis = 1)
    return dem, X, Y    

def mayavi_plot(mode, output_save_path,
                dem, demX, demY, cmap1, exag1, opac1,
                wt, wtX, wtY, cmap2, exag2, opac2):
    # plot
    fig = mlab.figure(size=(3000, 1500), bgcolor = (1,1,1), fgcolor = (0.5, 0.5, 0.5))
    mlab.view(azimuth=-60, elevation=60, distance=0.01, focalpoint=(0,0,0))
    surf1 = mlab.surf(demX, demY, dem, colormap=cmap1, warp_scale=exag1, opacity=opac1, figure=fig)
    surf2 = mlab.surf(wtX, wtY, wt, colormap=cmap2, warp_scale=exag2, opacity=opac2, figure=fig)
    mlab.outline(surf1)
    if mode == 'save_fig':
        mlab.savefig(output_save_path, figure=fig)
        mlab.close(fig)
        mlab.close(all=True)
    if mode == 'show_fig':
        mlab.show(stop=True)
        
#%%
        
dem_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/calibration/analysis/Canut/gis/watershed_dem.tif"
wt_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/calibration/analysis/Canut/dico_s_Canut_1_50_1165.473_0.001_0.688_0.01/watertable.tif"

output_save_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/calibration/analysis/Canut/dico_s_Canut_1_50_1165.473_0.001_0.688_0.01"

import matplotlib.pylab as pl
dem, demX, demY = mayavi_create(dem_path)
wt, wtX, wtY = mayavi_create(wt_path)
# white = (1,1,1)
# black = (0,0,0)
# blue = (0,0,1)
mayavi_plot('save_fig', output_save_path,
            dem, demX, demY, 'binary', 10, 0.7,
            wt, wtX, wtY, 'cool', 10, 1)
image3d = pl.imread(output_save_path)
fig, ax = plt.subplots(1,1,figsize=(6, 6))
ax.imshow(image3d)
#ax.set_xlim(230,1690)
#ax.set_ylim(1170,420)
ax.axes.get_xaxis().set_visible(False)
ax.axes.get_yaxis().set_visible(False)

image3d = pl.imread(output_save_path)
ax.imshow(image3d)

#%%





