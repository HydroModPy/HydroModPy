# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import os
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.plot import show
import contextily as cx
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib_scalebar.scalebar import ScaleBar
import matplotlib.patches as mpatches
try:
    from colormap.colors import rgb2hex, hex2rgb
except:
    pass

# HydroModPy
from hydromodpy.tools import toolbox

#%% PLOT SETTINGS

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

#%% FUNCTIONS

def watershed_dem(BV):
    """
    Plot contour watershed and DEM.

    Parameters
    ----------
    BV : object
        Variable object of the model domain (watershed).
    """
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    try:
        contour = gpd.read_file(BV.geographic.watershed_contour_shp)
        bounds_shp = contour.geometry.total_bounds
    except:
        pass
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower left', rotation='horizontal-only')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set(aspect='equal') 
    image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                              cmap='terrain')
    show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, transform=dem.transform, 
          cmap='terrain', alpha=0.75, zorder=2, aspect="auto")
    legend_handles = []
    try:
        streams = gpd.read_file(BV.hydrography.streams)
        legend_handles += streams.plot(ax=ax, lw=1.5, color='navy', zorder=3, legend=True, label='Streams').get_legend_handles_labels()[0]
    except Exception:
        pass
    try:
        h = contour.plot(ax=ax, lw=1.5, zorder=4, legend=True, label='Watershed', edgecolor='k', facecolor='None')
        legend_handles += h.get_legend_handles_labels()[0]
    except Exception:
        pass
    try:
        if os.path.exists(BV.piezometry.piezos_shp):
            piezos = gpd.read_file(BV.piezometry.piezos_shp)
            h = piezos.plot(ax=ax, color='blue', marker='^', zorder=6,
                            edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
            legend_handles += h.get_legend_handles_labels()[0]
    except Exception:
        pass
    try:
        if len(BV.piezometry.x_coord_discrete)>0:
            h = ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete, c='darkorange',
                        marker='^', zorder=5, label='Piezometers: discrete')
            legend_handles.append(h)
    except Exception:
        pass
    try:
        if os.path.exists(BV.hydrometry.hydrometric_clip):
            hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
            h = hydromet.plot(ax=ax, color='white', zorder=7, marker='o',
                          edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
            legend_handles += h.get_legend_handles_labels()[0]
    except Exception:
        pass
    try:
        if os.path.exists(BV.intermittency.onde_clip):
            intermit = gpd.read_file(BV.intermittency.onde_clip)
            h = intermit.plot(ax=ax, color='grey', zorder=8, marker='s',
                          edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
            legend_handles += h.get_legend_handles_labels()[0]
    except Exception:
        pass
    if legend_handles:
        ax.legend(loc='lower right', title=BV.watershed_name, framealpha=0.8)
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
    # cbar.set_label('Elevation (m)', size=12, rotation=270)
    fig.tight_layout()
    try:
        fig.savefig(os.path.join(BV.figure_folder,'watershed_dem'+'_'+
                    BV.hydrography.streams.split('/')[-1].split('.')[0]+'.png'), dpi=300, 
                    bbox_inches='tight', transparent=False)
    except:
        fig.savefig(os.path.join(BV.figure_folder,'watershed_dem'+'.png'), dpi=300, 
                    bbox_inches='tight', transparent=False)
        pass

def watershed_local(regional_dem_path, BV):
    """
    Plot location of the watershed at the regional scale.

    Parameters
    ----------
    regional_dem_path : str
        Initial path of the regional DEM.
    BV : object
        Variable object of the model domain (watershed).
    """
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    shp = gpd.read_file(BV.geographic.watershed_shp)
    dem = rasterio.open(regional_dem_path)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)  
    ax.set(aspect='equal')
    scalebar = ScaleBar(1, box_alpha=0, scale_loc='top', location='lower left', rotation='horizontal-only')
    ax.add_artist(scalebar)
    dem_data = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
    vmin = np.nanmin(dem_data)
    vmax = np.nanmax(dem_data)
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    im = plt.cm.ScalarMappable(norm=norm, cmap='terrain')
    im.set_array([])
    show(dem_data, ax=ax, transform=dem.transform, cmap='terrain', alpha=1, zorder=2, aspect="auto")
    shp.plot(ax=ax, lw=2, color='yellow', zorder=4)
    cbar = fig.colorbar(im, ax=ax, orientation='horizontal', fraction=0.03, pad=0.02, shrink=0.8)
    cbar.set_label('Topographic elevation [mNGF]', fontsize=8, labelpad=2)
    cbar.ax.tick_params(labelsize=8)
    legend_elements = [
        mpatches.Patch(facecolor='yellow', edgecolor='black', linewidth=1, label='Watershed')
    ]
    ax.legend(handles=legend_elements, loc='lower right', framealpha=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(BV.figure_folder,'watershed_local.png'), dpi=300, 
                bbox_inches='tight', transparent=False)
    
def watershed_geology(BV):
    """
    Plot lithology of the watershed from specific geological map at FRance scale.

    Parameters
    ----------
    BV : object
        Variable object of the model domain (watershed).
    """
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    ax = plt.gca()
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
    polyg = gpd.read_file(BV.geographic.watershed_shp)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    crs = contour.crs
    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set(aspect='equal') 
    cx.add_basemap(ax,crs=crs,source='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')
    geol = gpd.read_file(BV.geology.geol_file)
    try:
        geol['hex']
    except:
        geol = gpd.read_file(BV.geology.geol_file)
        geol['R_col'] = 255 * (1 - geol['C_FOND']/100) * (1 - geol['N_FOND']/100)
        geol['G_col'] = 255 * (1 - geol['M_FOND']/100) * (1 - geol['N_FOND']/100)
        geol['B_col'] = 255 * (1 - geol['J_FOND']/100) * (1 - geol['N_FOND']/100)
        geol['R_col'][geol['R_col']>255] = 255
        geol['G_col'][geol['G_col']>255] = 255
        geol['B_col'][geol['B_col']>255] = 255
        geol['couleur'] = list(zip(round(geol['R_col']).astype(int),
                                   round(geol['G_col']).astype(int),
                                   round(geol['B_col']).astype(int)))
        for i in range(len(geol)):
            geol.loc[i,'hex'] = rgb2hex(geol.loc[i,'couleur'][0],
                                        geol.loc[i,'couleur'][1],
                                        geol.loc[i,'couleur'][2])
        geol = geol.drop(columns=['couleur'])
        geol.to_file(BV.geology.geol_file)
        geol = gpd.read_file(BV.geology.geol_file)
    color = []
    for i in list(geol['hex']):
        color.append(mpl.colors.to_rgb(i))
    geol = geol.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
    geol1 = gpd.clip(geol,polyg)
    handles = []
    for ctype, data in geol.groupby('NATURE'):
        color = data['hex'].iloc[0]
        data.plot(color=color,
              ax=ax,alpha=0.5, edgecolor='dimgrey', zorder=2,
              label='_nolegend_')
    for ctype, data in geol.groupby('NATURE'):
        color = data['hex'].iloc[0]
        if ctype.find('Partie marine')!=0:
            ctype = ctype.split(':')[0]
            patch = mpatches.Patch(facecolor=color, alpha=0.5, label=ctype.upper(), edgecolor='k')
            handles.append(patch)
    l1 = ax.legend(handles=handles, loc='best', ncol=1, fancybox=False,prop={'size':6.5})
    leg = ax.get_legend()
    leg.set_bbox_to_anchor((1,1, 0, 0))
    try:
        streams = gpd.read_file(BV.hydrography.streams)
        streams.plot(ax=ax, lw=1.5, color='navy', zorder=3,legend=True, label='Streams')
    except:
        pass
    contour.plot(ax=ax, lw=1.5, color='k', zorder=4, legend=True, edgecolor='k', facecolor='None', label='Watershed')
    try:
        if len(BV.piezometry.x_coord_discrete)>0:
            piezod = ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete,  c='darkorange',
                       marker='^', zorder=5, label='Piezometers: discrete')
        if os.path.exists(BV.piezometry.piezos_shp):
            piezos = gpd.read_file(BV.piezometry.piezos_shp)
            piezos.plot(ax=ax, color='blue', marker='^', zorder=6, 
                        edgecolor='k',legend=True, label='Piezometers: continue')
    except:
        pass
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower left', rotation='horizontal-only')
    ax.add_artist(scalebar)
    handles2, labels2 = ax.get_legend_handles_labels()
    legend_items = [(h, lbl) for h, lbl in zip(handles2, labels2) if lbl and not lbl.startswith('_')]
    l2 = None
    if legend_items:
        handles2, labels2 = zip(*legend_items)
        l2 = ax.legend(handles2, labels2, loc='lower right', title=BV.watershed_name, framealpha=0.8)
    plt.gca().add_artist(l1)
    fig.tight_layout()
    try:
        fig.savefig(os.path.join(BV.figure_folder,'watershed_geology'+'_'+
                    BV.hydrography.streams.split('/')[-1].split('.')[0]+'.png'), dpi=300, bbox_inches='tight', transparent=False)
    except:
        fig.savefig(os.path.join(BV.figure_folder,'watershed_geology.png'), dpi=300, bbox_inches='tight', transparent=False)
        pass

def watershed_zones(BV):
    fontprop = toolbox.plot_params(8,15,18,20)
    fig, ax = plt.subplots(1, 1, figsize=(5,5), dpi=300)
    try:
        contour = gpd.read_file(BV.geographic.watershed_contour_shp)
        bounds_shp = contour.geometry.total_bounds
    except:
        pass
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower left')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set(aspect='equal') 
    image_hidden = ax.imshow(BV.hydrodynamic.calib_zones,cmap='jet')
    show(BV.hydrodynamic.calib_zones, ax=ax, transform=dem.transform, 
         cmap='jet', alpha=0.75, zorder=2, aspect="auto")
    try:
        streams = gpd.read_file(BV.hydrography.streams)
        streams.plot(ax=ax, lw=1.5, color='navy', zorder=3,legend=True, label='Streams')
    except:
        pass
    try:
        contour.plot(ax=ax, lw=1.5, color='k', edgecolor='k', facecolor='None', zorder=4,legend=True, label='Watershed')
    except:
        pass
    try:
        if os.path.exists(BV.piezometry.piezos_shp):
            piezos = gpd.read_file(BV.piezometry.piezos_shp)
            piezos.plot(ax=ax, color='blue', marker='^', zorder=6, 
                        edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
    except:
        pass
    try:
        if len(BV.piezometry.x_coord_discrete)>0:
            ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete, c='darkorange',
                       marker='^', zorder=5, label='Piezometers: discrete')
    except:
        pass   
    try:
        if os.path.exists(BV.hydrometry.hydrometric_clip):
            hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
            hydromet.plot(ax=ax, color='white', zorder=7, marker='o',
                          edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
    except:
        pass 
    try:
        if os.path.exists(BV.intermittency.onde_clip):
            intermit = gpd.read_file(BV.intermittency.onde_clip)
            intermit.plot(ax=ax, color='grey', zorder=8, marker='s',
                          edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
    except:
        pass
    ax.legend(loc='lower right', title = BV.watershed_name,framealpha=0.8)
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
    # cbar.set_label('Elevation (m)', size=12, rotation=270)
    
    fig.tight_layout()
    fig.savefig(os.path.join(BV.figure_folder,'watershed_zones.png'), dpi=300, 
                bbox_inches='tight', transparent=False)

#%% NOTES
