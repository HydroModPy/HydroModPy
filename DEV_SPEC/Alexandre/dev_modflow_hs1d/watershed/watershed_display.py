# -*- coding: utf-8 -*-
"""
Created on Tue Sep 14 18:07:38 2021

@author: Alexandre Gauvain
"""

# Librairies
import os
import pandas as pd
import numpy as np
from glob import glob
import threading
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
import shutil
import sys
import imageio
import re
import deepdish as dd
from osgeo import gdal
import rasterio

# Plots
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1 import make_axes_locatable

# Parameters plot : v2.0 to classic customized
# mpl.style.use('default')
# mpl.rcParams.update(mpl.rcParamsDefault)

# # # Classic
mpl.style.use('classic')
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers'
# mpl.rcParams['axes.autolimit_mode'] = 'round_numbers' # 'data' 
mpl.rcParams['axes.xmargin'] = 0.1
mpl.rcParams['axes.ymargin'] = 0.1
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.top'] = True
mpl.rcParams['ytick.right'] = True
mpl.rcParams['legend.numpoints'] = 1
mpl.rcParams['legend.scatterpoints'] = 1
mpl.rcParams['legend.edgecolor'] = 'grey'
mpl.rcParams['date.autoformatter.year'] = '%Y'
mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'

# Parameters size plot
smal = 8
medium = 16
large = 20

plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=medium)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
plt.rcParams["font.family"] = "serif"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

def watershed(BV):
    fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
    streams = gpd.read_file(BV.hydrology.streams)
    #polyg = gpd.read_file(BV.geographic.watershed_shp)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)

    
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(BV.name, fontproperties=fontprop)
    ax.set(aspect='equal') 

    """image_hidden = ax.imshow(np.ma.masked_where(BV.geographic.dem_box_data < 0, BV.geographic.dem_box_data), 
                             cmap='terrain')"""

    image_hidden = plt.imshow(BV.geographic.dem_box_data, 
                              cmap='terrain', alpha=1, zorder=2, aspect="auto")


    streams.plot(ax=ax, lw=1.5, color='navy', zorder=3)
    contour.plot(ax=ax, lw=1.5, color='k', zorder=6)
    
    divider = make_axes_locatable(ax)
    cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
    fig.add_axes(cax)
    cbar = fig.colorbar(image_hidden, cax=cax, orientation="horizontal")
    cbar.ax.get_ymajorticklabels()
    list(cbar.get_ticks())
    val = np.ma.masked_where(BV.geographic.dem_box_data < 0, BV.geographic.dem_box_data)
    minVal =  int(round(np.min(val[np.nonzero(val)],0)))
    maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
    meanVal = int(round(minVal+((maxVal-minVal)/2),0))
    cbar.set_ticks([minVal, meanVal, maxVal])
    cbar.set_ticklabels([minVal, meanVal, maxVal])
    cbar.mappable.set_clim(minVal, maxVal)
    cbar.ax.tick_params(labelsize=10)
    cbar.ax.yaxis.set_ticks_position('left')
    cbar.ax.tick_params(size=0)
    
    fig.tight_layout()
    
    fig.savefig(os.path.join(BV.figure_folder,'watershed_dem.png'), dpi=300, bbox_inches='tight', transparent=False)
    