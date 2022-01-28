# -*- coding: utf-8 -*-
"""
Created on Tue Sep 14 18:07:38 2021

@author: Alexandre Gauvain
"""

# Librairies
import os
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.plot import show

# Plots
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib_scalebar.scalebar import ScaleBar

# Hydromodpy
from tools import toolbox

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
medium = 10
large = 12

plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=medium)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)        # fontsize of the axes title
plt.rc('axes', labelsize=smal, labelpad=0)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
plt.rcParams["font.family"] = "serif"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

def watershed_local(regional_dem_path, BV):
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    shp = gpd.read_file(BV.geographic.watershed_shp)
    dem = rasterio.open(regional_dem_path)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)  
    ax.set(aspect='equal')
    show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), ax=ax, transform=dem.transform, 
         cmap='terrain', alpha=1, zorder=2, aspect="auto")
    shp.plot(ax=ax, lw=2, color='yellow', zorder=4,legend=True, label='Watershed')
    contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')
    fig.tight_layout()
    fig.savefig(os.path.join(BV.figure_folder,'watershed_local.png'), dpi=300, 
                bbox_inches='tight', transparent=False)
    
def watershed_dem(BV):
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    
    #polyg = gpd.read_file(BV.geographic.watershed_shp)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
    #bounds = contour.geometry.total_bounds
    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower center')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    #ax.set_title(BV.name, fontproperties=fontprop)
    ax.set(aspect='equal') 
    image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                             cmap='terrain')
    show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, transform=dem.transform, 
         cmap='terrain', alpha=1, zorder=2, aspect="auto")
    try:
        streams = gpd.read_file(BV.hydrology.streams)
        streams.plot(ax=ax, lw=2, color='navy', zorder=3,legend=True, label='Streams')
    except:
        pass
    contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')
    try:
        if os.path.exists(BV.piezometry.piezos_shp):
            piezos = gpd.read_file(BV.piezometry.piezos_shp)
            piezos.plot(ax=ax, color='red', marker='^', zorder=6, 
                        edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
        if len(BV.piezometry.x_coord_discrete)>0:
            ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete, c='darkorange',
                       marker='^', zorder=5, label='Piezometers: discrete')
        if os.path.exists(BV.hydrometry.hydrometric_clip):
            hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
            hydromet.plot(ax=ax, color='white', zorder=7, marker='o',
                          edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
        if os.path.exists(BV.intermittency.onde_clip):
            intermit = gpd.read_file(BV.intermittency.onde_clip)
            intermit.plot(ax=ax, color='grey', zorder=8, marker='s',
                          edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
    except:
        pass
    ax.legend(loc='best', title = BV.watershed_name,framealpha=0.8)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes(size="4%",position='right', pad=0.05)
    fig.add_axes(cax)
    cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
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
    cbar.ax.yaxis.set_ticks_position('right')
    cbar.ax.tick_params(size=2)
    # cbar.set_label('Elevation (m)', labelsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(BV.figure_folder,'watershed_dem.png'), dpi=300, 
                bbox_inches='tight', transparent=False)

def watershed_geology(BV):
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
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
    #ax.set_title(BV.name, fontproperties=fontprop)
    ax.set(aspect='equal') 
    geol = gpd.read_file(BV.geology.geol_file)
    geol['R_col'] = (1 - geol['C_FOND']/100) * (1 - geol['N_FOND']/100)
    geol['G_col'] = (1 - geol['M_FOND']/100) * (1 - geol['N_FOND']/100)
    geol['B_col'] = (1 - geol['J_FOND']/100) * (1 - geol['N_FOND']/100)

    geol['couleur'] = list(zip(round(geol['R_col']).astype(int), 
                             round(geol['G_col']).astype(int), 
                             round(geol['B_col']).astype(int)))

    for i in range(len(geol)):
        geol.loc[i,'hex'] = mpl.colors.to_hex([geol.loc[i,'couleur'][0],
                                geol.loc[i,'couleur'][1],
                                 geol.loc[i,'couleur'][2]])

    geol.plot(ax=ax, color=list(geol['hex']),alpha=1, edgecolor='dimgrey', zorder=0,legend=True, label='Geology')
    
    streams.plot(ax=ax, lw=1.5, color='navy', zorder=3,legend=True, label='Streams')
    contour.plot(ax=ax, lw=1.5, color='k', zorder=4,legend=True, label='Watershed')
    if os.path.exists(BV.piezometry.piezos_shp):
        piezos = gpd.read_file(BV.piezometry.piezos_shp)
        piezos.plot(ax=ax, color='r',zorder=5,legend=True, label='Piezometers')
    if len(BV.piezometry.x_coord_discrete)>0:
        ax.plot(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete, '^b', zorder=5, label='Piezometers: discrete')
    ax.legend(loc='best', title = BV.watershed_name,framealpha=0.8)
    fig.tight_layout ()
    fig.savefig(os.path.join(BV.figure_folder,'watershed_geology.png'), dpi=300, bbox_inches='tight', transparent=False)


