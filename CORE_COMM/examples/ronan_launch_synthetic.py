# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

#%% IMPORT MODULES

# Modules
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
from glob import glob
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator

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
from watershed import watershed_root, forcing
from tools import tif_adds, serie_transf, tif_features, file_adds
from watershed.data import hydrology, climatic, oceanic, piezometry

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% PARAMETERS ARTCLE

mpl.style.use('classic')
# mpl.rcParams['backend'] = 'wxAgg'
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['axes.linewidth'] = 1.5
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
mpl.rcParams['axes.xmargin'] = 0.05
mpl.rcParams['axes.ymargin'] = 0.05
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.major.size'] = 5
mpl.rcParams['xtick.minor.size'] = 3
mpl.rcParams['xtick.major.width'] = 1.5
mpl.rcParams['xtick.minor.width'] = 1
mpl.rcParams['ytick.major.size'] = 5
mpl.rcParams['ytick.minor.size'] = 1.5
mpl.rcParams['ytick.major.width'] = 1.5
mpl.rcParams['ytick.minor.width'] = 1
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

smal = 8
intm = 15
medium = 18
large = 20

plt.rc('font', size=smal)                         # controls default text sizes **font
plt.rc('figure', titlesize=large)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('font', family='arial')
fontprop = FontProperties()
fontprop.set_family('arial') # for x and y label
fontdic = {'family' : 'arial', 'weight' : 'bold'} # for legend

par = {'mathtext.default': 'regular' }          
mpl.rcParams.update(par)

#%% PATHS LOAD

# Users
git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
root_path= "D:/Users/abherve/HYDROMODPY/_data/"
out_path = "D:/Users/abherve/SYNTHETIC"

geology_path = None
hydrology_path = root_path + 'HYDROLOGY'
modflow_path = root_path + 'MODFLOW'
piezometry_path = None
oceanic_path = None
dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

library_path = DIR + '/watershed' + '/watershed_library.csv'
surfex_path =  root_path + 'SURFEX/ebr/'
watershed_name = 'Canut'
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['name'] == watershed_name]

# library_path = df + '/watershed' + '/watershed_bretagne_library.csv'
# surfex_path =  root_path + 'SURFEX/bzh/'
# outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')

notok = []

types_obs = ['streams_fr', 'sections_fr']
fields_obs = ['FID', 'Persistanc']

for idx, row in outlets.iloc[:].iterrows():
    
    load = True
    watershed_name = row['name']
    
    print('##### '+watershed_name.upper()+' #####')

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    try:
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      surfex_path=surfex_path, 
                                      geology_path = geology_path, 
                                      hydrology_path=hydrology_path,
                                      oceanic_path=oceanic_path, 
                                      piezometry_path=piezometry_path,
                                      modflow_path=modflow_path,
                                      library_path=library_path,
                                      load=load,
                                      types_obs=types_obs,
                                      fields_obs=fields_obs)
    except:
        notok.append(watershed_name)
        print('NOT OK')

#%% SLECT RECHARGE

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                  first_year = 1990, last_year = 2019, 
                                  time_step = 'M', sim_state='transient')

fig = plt.subplots(1,1, figsize=(6,3))
rech = BV.forcing.recharge
plt.plot(rech*1000, c='k', lw=0.5)

# sce0 = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1, 1) # serie, period, amplitude, offset, omega, phase
# rech = BV.forcing.recharge
# plt.plot(BV.forcing.recharge*1000, c='blue')
# sce_offm = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1/2, 1, 1)
# plt.plot(BV.forcing.recharge*1000, c='dodgerblue')
# sce_offp = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1*2, 1, 1)
# plt.plot(BV.forcing.recharge*1000, c='dodgerblue')
# sce_omem = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1/2, 1)
# plt.plot(BV.forcing.recharge*1000, c='red')
# sce_omepp = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1*2, 1)
# plt.plot(BV.forcing.recharge*1000, c='red')
# sce_pham = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1, 1/2)
# plt.plot(BV.forcing.recharge*1000, c='forestgreen')
# sce_phapp = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1, 2) # phase * 2 = come back 6 months
# plt.plot(BV.forcing.recharge*1000, c='forestgreen')
# sce_alex = BV.forcing.update_synthetic_recharge(250/1000, 50, 19, start_date="2000-08", freq=None, dis='normal') # rech, shape, years, start_date= "2020-08", freq, dis='normal')
# plt.plot(BV.forcing.recharge*30*1000, c='darkorange')

#%% RUN MODELS

# BV.calib_dichotomy(ident=None, calib=True, type_river='streams', climatic=rech.mean(),
#                     lay_number=1, thick=30, bottom=None, thick_exp=1., 
#                     first=1, last=15000, gap=1, porosity=0.01, sea_level=None, cond_decay=0.)

df = pd.read_csv(simulations_folder+'_dichotomy_'+'streams'+'.csv', sep=';', header=0)
koptim = df.iloc[-1]['K'].round(1) # / 30 / 3600 / 24

sce = 'sinus1'

k = koptim
BV.hydrodynamic.update_hyd_cond(k)
ep = 30
BV.hydrodynamic.update_thickness(ep)
sys = [0.001, 0.01, 0.1]

for sy in sys:
    sy = sy
    BV.hydrodynamic.update_porosity(sy)
    ident = sce+'_'+str(koptim)+'_'+str(sy)+'_'+str(ep)+'_'+'1990-2019'
    # BV.run_modflow(ident=ident, modpath_sim=False, calib=False, sink_fill=False, 
    #                 lay_number=1, bottom=None, thick_exp=1., sea_level=None, cond_decay=0., verbose=True)
    # BV.chronics_modflow(ident=ident, mask=False, outlet_type=True, calib_only=False, 
    #                     first=1990, last=2019, time_step='monthly')

# from groundwater_flow import vizualisation
# visu = vizualisation.Vizualisation(BV, ident)
# visu.visual3D(interactive=True, object_list=['grid','watertable','watertable_depth'], view='south-west')
    
#%% HYSTERESIS FUNCTIONS

import matplotlib.pylab as pl
import math
import scipy.stats as sp
import shapely.geometry as SG
import seaborn as sns

def hysteresis_total(station, index, xm, ym, out, first, last, xlim, ylim):
    # Create figure
    fig, ax = plt.subplots(1,1,figsize=(5, 4))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
    plt.xlabel("P - E [mm]", labelpad=+15)
    plt.ylabel("Q / A [mm]", labelpad=+25)
    cmap = 'jet'
    # Create variables
    xm = xm
    ym = ym
    cms = pd.Series(index.month)
    cms = cms.replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
    # Create intermensual  
    xintm = xm.groupby([lambda x: x.month]).mean()
    yintm = ym.groupby([lambda x: x.month]).mean()
    cintm = xintm.index
    # Create xerror bar                
    xerr = pd.DataFrame()
    xerr['q25'] = (xm.groupby(df.index.month).quantile(0.25))
    xerr['q75'] = (xm.groupby(df.index.month).quantile(0.75))
    xerr['moy'] = xm.groupby(df.index.month).mean()
    # Create yerror bar                   
    yerr = pd.DataFrame()
    yerr['q25'] = (ym.groupby(df.index.month).quantile(0.25))
    yerr['q75'] = (ym.groupby(df.index.month).quantile(0.75))
    yerr['moy'] = ym.groupby(df.index.month).mean()    
    # Plot x/y points                
    scat = ax.scatter(xm, ym, c=cms,cmap=cmap, marker="o", s=15, vmin=1, vmax=12, ec='none')
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    # Plot intermensual points            
    ax.plot(xintm, yintm, marker="o", markersize=12, markeredgecolor='black', 
            markerfacecolor='white', linestyle = 'None')    
    # Plot annotate intermensual points                
    for k in cintm:
        ax.annotate(k,(xintm[k],yintm[k]), family='sans-serif', fontsize=7, 
                    color='black', weight="bold", ha='center', va='center')
    # Plot 1:1 line           
    x = np.linspace(*ax.get_xlim())
    ax.plot(x, x, linestyle='--',color='black', linewidth=1, zorder=1)
    # Plot error bars
    ax.errorbar(xintm, yintm, yerr=np.vstack([yintm-yerr.q25, yerr.q75-yintm]),
                              xerr=np.vstack([xintm-xerr.q25, xerr.q75-xintm]),
                              ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
                              capthick=0.5, zorder=1)
    # Parameter log
    ax.set_yscale('log')
    # Parameter lim       
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    # ax.set_xticks(np.linspace(-150, 150, 5))
    # Parameter title 
    ax.set_title(station.upper(), pad=+10) 
    # Tidy
    plt.tight_layout()
    # Color bar        
    position = fig.add_axes([0.95,0.32,0.02,0.5])
    cb = plt.colorbar(scat,cax=position)
    x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
    squad = ['Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep']
    cb.set_ticks(x1)
    cb.set_ticklabels(squad)
    cb.ax.tick_params(labelsize=10)
    cb.update_ticks()
    # Save
    fig.savefig(simulations_folder+ident+'/_figure/'+'hysteresis_total'+'.png', dpi=300, bbox_inches='tight')
    # plt.close()

def hysteresis_superpose(ident, df, xlim, ylim):
    cp = 0
    couleur = 'red'
    fig, ax = plt.subplots(1,1,figsize=(5.5, 4.5))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
    plt.xlabel("P - E [mm.m$^-$$^1$]", labelpad=+15)
    plt.ylabel("Q / A [mm.m$^-$$^1$]", labelpad=+25)
    df_concat = df
    # Create variables
    xm = df_concat.eff
    ym = df_concat.spe
    cms = pd.Series(df_concat.index.month)
    cms = cms.replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
    # Create intermensual  
    df_intm = df_concat.groupby([lambda x: x.month]).mean()
    df_intm['m'] = df_intm.index   
    xintm = df_intm.eff
    yintm = df_intm.spe
    cintm = df_intm.m            
    # Create xerror bar                
    xerr = pd.DataFrame()
    xerr['q25'] = (xm.groupby(df_concat.index.month).quantile(0.25))
    xerr['q75'] = (xm.groupby(df_concat.index.month).quantile(0.75))
    xerr['moy'] = xm.groupby(df_concat.index.month).mean()
    # Create yerror bar                   
    yerr = pd.DataFrame()
    yerr['q25'] = (ym.groupby(df_concat.index.month).quantile(0.25))
    yerr['q75'] = (ym.groupby(df_concat.index.month).quantile(0.75))
    yerr['moy'] = ym.groupby(df_concat.index.month).mean()                  
    # Plot intermensual points            
    # ax.plot(xintm, yintm, marker="o", markersize=14,
    #                   markeredgecolor=couleur,markerfacecolor='white',
    #                   mew=2, linestyle = 'None', zorder=3+cp)
    # # Plot annotate intermensual points   
    # for k in cintm:
    #     ax.annotate(cintm[k],(xintm[k],yintm[k]),
    #                   family='sans-serif', fontsize=8, 
    #                   color='k', weight="bold", ha='center', va='center',
    #                   zorder=4+cp)
    # Plot lines
    xline = xintm.append(xintm.iloc[[0]])
    xline.index = np.arange(1,14,1)
    yline = yintm.append(yintm.iloc[[0]])
    yline.index = np.arange(1,14,1)
    ax.plot(xline, yline, linestyle = '-', lw=3, color=couleur, zorder=2+cp)    
    # Plot error bars
    # ax.errorbar(xintm, yintm, 
    #                     yerr=np.vstack([yintm-yerr.q25, yerr.q75-yintm]),
    #                     xerr=np.vstack([xintm-xerr.q25, xerr.q75-xintm]),
    #                     ecolor = couleur, fmt = 'none', capsize = 1, elinewidth=0.5, 
    #                     capthick=0.5, zorder=1+cp)        
    # Parameter log
    ax.set_yscale('log')        
    # Parameter lim   
    # minx = -100
    # maxx = 100
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    # Plot 1:1 line
    x = np.linspace(*ax.get_xlim())
    ax.plot(x, x, linestyle='-',color='k', linewidth=2, zorder=0)
    # Parameter title 
    ax.set_title(ident.upper(), pad=10)
    ax.grid(True)
    # Tidy
    plt.tight_layout()
    cp += 3
    fig.savefig(simulations_folder+ident+'/_figure/'+'hysteresis_superpose'+'.png', dpi=300, bbox_inches='tight')
    
def linregress(inx,iny):
    x=np.array(inx.values, dtype=float)
    y=np.array(iny.values, dtype=float)
    xmas = np.ma.masked_array(x,mask=np.isnan(y)).compressed()
    ymas = np.ma.masked_array(y,mask=np.isnan(y)).compressed()
    slope, intercept, r_value, p_value, std_err = sp.linregress(xmas,ymas)    
    xf = np.linspace(min(x),max(x),100)
    xf1 = xf.copy()
    xf1 = pd.to_datetime(xf1)
    yf = (slope*xf)+intercept
    center_x = xf.mean()
    center_y = yf.mean()
    lenght_reg = [[xf.min(),xf.max()],[yf.min(),yf.max()]]
    return (center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg)

def line(x, line_point1, line_point2, get_eq=False):
    m = (line_point1[1] - line_point2[1])/(line_point1[0] - line_point2[0])
    b = line_point1[1] - m*line_point1[0]
    if get_eq:
        return m, b
    else:
        return m*x + b
    
def perpendicular_line(x, line_point1, line_point2, random_point, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2
    
def get_intersection(line_point1, line_point2, random_point):
    m, b = line(0, line_point1, line_point2, True)
    m2, b2 = perpendicular_line(0, line_point1, line_point2, random_point, True)
    x = (b2 - b) / (m - m2)
    y = line(x, line_point1, line_point2)
    return [x, y]

def plus_sum(aList):
    s = 0 
    for l in aList:
       if l > 0:
           s = s + l
    return s

def minus_sum(aList):
    s = 0 
    for l in aList:
       if l <= 0:
           s = s + l
    return s

def parameters_loop(station, index, xm, ym, out):
        # Create variables
        xm = xm
        ym = ym
        cms = pd.Series(index.month)
        cms = cms.replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
        
        # Create intermensual  
        xintm = xm.groupby([lambda x: x.month]).mean()
        yintm = ym.groupby([lambda x: x.month]).mean()
        cintm = xintm.index  
    
        # Create line
        xline = xintm.append(xintm.iloc[[0]])
        xline.index = np.arange(1,14,1)
        yline = yintm.append(yintm.iloc[[0]])
        yline.index = np.arange(1,14,1)
        data= pd.DataFrame()
        data['inx'] = xline
        data['iny'] = yline
        
        # Indicators
        qmax = data.iny.max()
        qmin = data.iny.min()
        q0 = data.iny[10]    # octobre
        qmid = (q0+qmax)/2
        qsep = (qmin+qmax)/2
        
        line = SG.LineString(list(zip(data.inx,data.iny)))
        y0 = qmid
        yline = SG.LineString([(min(data.inx), y0), (max(data.inx), y0)])
        coords = np.array(line.intersection(yline))
        hi = coords[1,0] - coords[0,0]
        
        # Rescale
        data.inx = data.inx[0:-1]
        data.iny = data.iny[0:-1]
        
        # Regression    
        reg = linregress(data.inx,data.iny)
        reg_stat = pd.DataFrame(columns=['center_x','center_y','slope','intercept',
                                         'r_value','p_value','std_err','lenght_reg'])
        reg_stat.loc[len(reg_stat)] = reg
    
        # Distance
        one = np.arange(min(data.min()),max(data.max()),0.1)
        line_point1 = [one.min(),one.min()]
        line_point2 = [one.max(),one.max()]
        compteur = 1
        ortho = pd.DataFrame(index=range(1,len(data)))
        for d in range(1,len(data)):
            random_point = [data.inx.loc[d], data.iny.loc[d]]
            domain = np.linspace(np.min(data.min()), np.max(data.max()))
            intersection = get_intersection(line_point1, line_point2, random_point)
            xgiv = (random_point[0] - intersection[0])
            ygiv = (random_point[1] - intersection[1])
            distance = ((random_point[0] - intersection[0])**2 + (random_point[1] - intersection[1])**2)**0.5
            if ygiv <= 0:
                distance = distance * -1
            ortho.loc[compteur,'ecart'] = distance
            ortho.loc[compteur,'inters_x'] = intersection[0]
            ortho.loc[compteur,'inters_y'] = intersection[1]
            compteur += 1
            
        # Center regression distance
        random_point = [reg_stat.center_x, reg_stat.center_y]
        domain = np.linspace(xm.min(), xm.max())
        intersection = get_intersection(line_point1, line_point2, random_point)
        xgiv = (random_point[0] - intersection[0])
        ygiv = (random_point[1] - intersection[1])
        ecart_center = ((random_point[0] - intersection[0])**2 + (random_point[1] - intersection[1])**2)**0.5
            
        return qmax, qmin, q0, qmid, qsep, hi, reg_stat, ortho, intersection, ecart_center

def hysteresis_describe(ident, df, stable_folder, xlim, ylim):
    recap = pd.DataFrame()
    compt = 0
    station = ident
    qmax, qmin, q0, qmid, qsep, hi, reg_stat, ortho, intersection, ecart_center = parameters_loop(station, df.index, df.eff, df.spe, stable_folder)
    first = df.spe.first_valid_index().year
    last = df.spe.last_valid_index().year
    # Parameters
    horiz = ortho.inters_x
    verti = ortho.ecart
    points = pd.Series(ortho.index)
    data_color = points.replace([10,11,12,1,2,3,4,5,6,7,8,9],[1,2,3,4,5,6,7,8,9,10,11,12])
    frame ={'xm':df.eff,'ym':df.spe}
    scatot = pd.DataFrame(frame)
    scatot = scatot.dropna()
    # Plot
    fig, ax = plt.subplots(1,1,figsize=(6, 5))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
    plt.xlabel("Proj. P - E [mm]", labelpad=+15)
    plt.ylabel("Proj. Q / A [mm]", labelpad=+25)
    cmap = 'jet'
    n = 12
    colors = pl.cm.jet(np.linspace(0,1,n))
    cmap = 'jet'
    forme = ax.scatter(horiz, verti, c = data_color, cmap=cmap, alpha=0.5, s = 180, edgecolor = 'grey')
    for col in range(1,len(ortho)+1):
        if verti[col] < 0 :
            lines = ax.plot((horiz[col],horiz[col]),(verti[col]+1,0),linestyle='-', lw=1,color = 'grey')
        if verti[col] > 0 :
            lines = ax.plot((horiz[col],horiz[col]),(verti[col]-1,0),linestyle='-', lw=1,color = 'grey')        
    for k in range(1,len(ortho)+1):
            ax.annotate(points[k-1],(horiz[k],verti[k]),family='sans-serif', fontsize=9, color='black', weight="bold", ha='center', va='center')        
    ax.axhline(y=0, color='k', linestyle='-',linewidth = 1)
    ax.plot(intersection[0], ecart_center, marker ='+', markersize=11, mew=2, color = 'k')
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title(station.upper(), pad=10)
    ax.grid(color='grey',alpha=0.2)
    # Store                   
    recap.loc[compt,'stations'] = station
    recap.loc[compt,'qmid'] = qmid
    recap.loc[compt,'counts'] = len(scatot)
    recap.loc[compt,'qsep'] = qsep
    recap.loc[compt,'hi'] = hi
    recap.loc[compt,'slope'] = reg_stat.loc[0,'slope']
    recap.loc[compt,'rval'] = reg_stat.loc[0,'r_value']
    recap.loc[compt,'interc'] = reg_stat.loc[0,'intercept']
    recap.loc[compt,'center'] = ecart_center[0]
    recap.loc[compt,'centerx'] = reg_stat.center_x.values[0]
    recap.loc[compt,'centery'] = reg_stat.center_y.values[0]
    recap.loc[compt,'linreg'] = abs(reg_stat.loc[0,'lenght_reg'][0][1] - reg_stat.loc[0,'lenght_reg'][0][0])
    recap.loc[compt,'psum'] = plus_sum(verti)
    recap.loc[compt,'nsum'] = minus_sum(verti)
    recap.loc[compt,'tsum'] = plus_sum(verti) + abs(minus_sum(verti))
    recap.loc[compt,'pmoy'] = plus_sum(verti) / len(verti.loc[verti > 0])
    recap.loc[compt,'nmoy'] = minus_sum(verti) / len(verti.loc[verti <= 0])
    recap.loc[compt,'tmoy'] = (plus_sum(verti) + abs(minus_sum(verti))) / 12
    recap.loc[compt,'long'] = horiz.max()-horiz.min()
    recap.loc[compt,'haut'] = verti.max()-verti.min()
    recap.loc[compt,'excent'] =  recap.loc[compt,'haut'] / recap.loc[compt,'long']
    recap.loc[compt,'execent_bis'] = np.sqrt(1-((recap.loc[compt,'haut']**2)/(recap.loc[compt,'long']**2)))
    recap.loc[compt,'aire'] = math.pi * recap.loc[compt,'haut'] * recap.loc[compt,'long']
    recap = recap.round(2)
    recap.loc[compt,'geol'] = '?'
    # Add legend
    ax.text(0.76, 0.82, 
                     'Counts = ' +str(recap.loc[compt,'counts']) + '\n'
                     'Qmid = '+str(recap.loc[compt,'qmid']) + '\n'
                     'Qsep = '+str(recap.loc[compt,'qsep']) + '\n'
                     'Interc = '+str(recap.loc[compt,'interc']) + '\n'
                     'Center = '+str(recap.loc[compt,'center']) + '\n'
                     'HI = '+str(recap.loc[compt,'hi']) + '\n',
                     horizontalalignment='left',
                     verticalalignment='center', 
                     transform=ax.transAxes,
                     fontsize = 10)
    ax.text(0.046, 0.17, 
                     'Length = ' +str(recap.loc[compt,'long']) + '\n'
                     'Height = ' +str(recap.loc[compt,'haut']) + '\n'
                     'Excent = '+str(recap.loc[compt,'excent']) + '\n'
                     'Slope = '+str(recap.loc[compt,'slope']) + '\n'
                     'Posit = ' +str(recap.loc[compt,'psum']) + '\n'
                     'Negat - = ' +str(recap.loc[compt,'nsum']) + '\n'
                     'Total = = ' +str(recap.loc[compt,'tsum']) + '\n',
                     horizontalalignment='left',
                     verticalalignment='center', 
                     transform=ax.transAxes,
                     fontsize = 10)
    # End parameters
    plt.tight_layout()
    fig.savefig(simulations_folder+ident+'/_figure/'+'hysteresis_describe'+'.png', dpi=300, bbox_inches='tight')
    compt += 1
    return recap

def hysteresis_boxplot(recap):
    fig, axs = plt.subplots(5,5,figsize=(15, 15))
    axs = axs.ravel()
    cols = recap.columns[1:-1]
    for idx, to_look in enumerate(cols):
        ax=axs[idx]
        bplot=sns.boxplot(ax=ax, y=to_look, x='geol', 
                          data=recap, 
                          width=0.5)                  
        # for i in range(0,3):
            # mybox = bplot.artists[i]
            # mybox.set_facecolor(color_dict[geol[i]])
        bplot = sns.stripplot(ax=ax, y=to_look, x='geol', 
                              data=recap,
                              jitter=True, marker='o',
                              alpha=0.8, 
                              color="black")
        plt.xticks(rotation = 10, fontsize=8, horizontalalignment="center")
        ax.get_xaxis().set_visible(False)
        ax.yaxis.label.set_visible(False)
        ax.set_title(to_look.upper())
    plt.tight_layout()

#%% LAUNCH FUNCTIONS

sce = 'rech'
sys = [0.001, 0.01, 0.1]
    
for sy in sys:

    sy = sy
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    ident = sce+'_'+str(koptim)+'_'+str(sy)+'_'+str(ep)+'_'+'1990-2019'
    df = pd.read_csv(simulations_folder+ident+'/_extraction/'+'_simulated_chronics.csv', sep=';', index_col='date', parse_dates=True)
    first = df.first_valid_index().year
    last = df.last_valid_index().year
    
    ppt = pd.read_csv(stable_folder+'climatic/'+'_PPT_M.csv', sep=';', index_col=[0], parse_dates=True) / 1000
    etp = pd.read_csv(stable_folder+'climatic/'+'_ETP_M.csv', sep=';', index_col=[0], parse_dates=True) / 1000
    
    dem_data = imageio.imread(stable_folder+'geographic/watershed_dem.tif')
    area = tif_features.basin_area(dem_data, dem_data, '<=', -1000, 75)

    df['spe'] = (df.outflow_drain) * 1000 # mm/m
    # df['spe'] = (df.seepage_areas) # %
    df['eff'] = (ppt['REA_historic']-etp['REA_historic']) * 1000
    # df['eff'] = rech * 1000
    df['rec'] = rech * 1000
        
    xlim = (-150,+150)
    ylim = (0.1,150)
    hysteresis_total(ident, df.index, df.eff, df.spe, stable_folder, first, last, xlim, ylim)
    # xlim = (-20,+50)
    # ylim = (0.5,100)
    # hysteresis_superpose(ident, df, xlim, ylim)
    # xlim = (0,+50)
    # ylim = (-20,20)
    # recap = hysteresis_describe(ident, df, stable_folder, xlim, ylim)
    # hysteresis_boxplot(recap)

#%% GIF INTERMITTENCY

    dir_to_analyse = simulations_folder + ident + '/_extraction/'
    list_traces = glob(dir_to_analyse+'_surfaceflow/'+'trace_*.shp')
    
    figdir = dir_to_analyse + '_fig/'
    pngdir = dir_to_analyse + '_fig/_png/'
    gifdir = dir_to_analyse + '_fig/_gif/'
    file_adds.create_folder(figdir)
    file_adds.create_folder(pngdir)
    file_adds.create_folder(gifdir)
    
    ### INTERMITTENCY ###
    compt = 1
    c1 = 0
    c12 = 12
    one = pd.DataFrame(columns=['x','y'])
    for i in list_traces:    
        inter = list_traces[c1:c12]
        one_x = []
        one_y = []
        test = []
        for j in inter:
            outflow = gpd.read_file(j)
            x_list = outflow.geometry.x
            y_list = outflow.geometry.y
            mix = list(zip(x_list, y_list))
            test.extend(mix)
        dfc = pd.DataFrame(test, columns=['x','y'])
        dfc['z'] = dfc['x'].astype(str) + dfc['y'].astype(str)
        values = dfc['z'].value_counts()
        values = values[values==12]
        for j in inter:
            
            outflow = gpd.read_file(j)
            outflow['x'] = outflow.geometry.x
            outflow['y'] = outflow.geometry.y
            outflow['z'] = outflow['x'].astype(str) + outflow['y'].astype(str)
            outflow['persit'] = 0
            for h in values.index:
                # print('Detect intermittency : '+str(compt))
                outflow.loc[outflow['z']==h,'persit'] = 1
            outflow.to_file(j) 
        c1+=12
        c12+=12
        compt+=1
    
    ### PLOT STREAMS ###
    compt = 0
    for i in list_traces:
        lead_numb = "%03d" % (compt,)
        print(lead_numb)
        outflow = gpd.read_file(i)
        fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
        dem = rasterio.open(BV.geographic.watershed_dem)
        img = imageio.imread(BV.geographic.watershed_dem)
        contour = gpd.read_file(stable_folder+'/geographic/'+'watershed_contour.shp')
        streams = gpd.read_file(stable_folder+'/hydrology/'+'streams_fr.shp')
        sections = gpd.read_file(stable_folder+'/hydrology/'+'sections_fr.shp')
        sections[sections.Persistanc=='3'].plot(ax=ax, lw=1, color='grey', ls='-', zorder=7)
        sections[sections.Persistanc=='4'].plot(ax=ax, lw=1, color='k', ls='-', zorder=7)
        bounds = contour.geometry.total_bounds
        xlim = ([bounds[0], bounds[2]])
        ylim = ([bounds[1], bounds[3]])
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        ax.set_title(str(df.index[compt])[:10], fontproperties=fontprop)
        ax.set(aspect='equal') 
        image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), cmap='Greys')
        mnt = rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), ax=ax, transform=dem.transform,
                                 cmap='Greys', alpha=0.5, zorder=2)
        contour.plot(ax=ax, lw=1.5, color='k', zorder=6)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="1%", pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
        val = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
        minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        cbar.set_ticks([minVal, meanVal, maxVal])
        cbar.set_ticklabels([minVal, meanVal, maxVal])
        cbar.mappable.set_clim(minVal, maxVal)
        cbar.ax.tick_params(labelsize=10)
        # outflow.plot(ax=ax, alpha=1, column='persit', cmap="winter_r", 
        #               marker='s', markersize=7.5, lw=0.1, edgecolor='none',
        #               scheme="User_Defined", 
        #               classification_kwds=dict(bins=[1, 0]),
        #               zorder=4)
           
        # from matplotlib.colors import ListedColormap
        # cmap = ListedColormap(['darkorange','blue'])
        outflow[outflow.persit==0].plot(ax=ax, alpha=1, column='persit', color='darkorange', 
                                        marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                                        zorder=4)
        outflow[outflow.persit==1].plot(ax=ax, alpha=1, column='persit', color='dodgerblue', 
                                        marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                                        zorder=4)
        hydro = gpd.read_file(stable_folder + '/hydrology/' + 'hydrometric.shp')
        hydro.plot(ax=ax, lw=1, facecolor='white', marker='o', edgecolor='k', alpha=1, zorder=7)
        onde = gpd.read_file(stable_folder + '/hydrology/' + 'onde.shp')
        allsta = onde['<LbSiteHyd'].unique()
        for idx, lib in enumerate(allsta):
            sta = onde[onde['<LbSiteHyd']==lib]
            sta.plot(ax=ax, lw=1, facecolor='yellow', marker='^', edgecolor='k', alpha=1, zorder=8)
        name_fig = 'interm_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(pngdir + name_fig)
        plt.close()
        compt+=1
    
    ### MAKE GIF ###
    filenames = glob(pngdir+'/'+'interm_*.png')  
    import imageio
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))
    imageio.mimsave(gifdir+'/'+'interm_outflow.gif', images, duration=0.5, loop=1)

    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    ident = sce+'_'+str(koptim)+'_'+str(sy)+'_'+str(ep)+'_'+'1990-2019'
    df = pd.read_csv(simulations_folder+ident+'/_extraction/'+'_simulated_chronics.csv', sep=';', index_col='date', parse_dates=True)
    first = df.first_valid_index().year
    last = df.last_valid_index().year    
    ppt = pd.read_csv(stable_folder+'climatic/'+'_PPT_M.csv', sep=';', index_col=[0], parse_dates=True) / 1000
    etp = pd.read_csv(stable_folder+'climatic/'+'_ETP_M.csv', sep=';', index_col=[0], parse_dates=True) / 1000
    dem_data = imageio.imread(stable_folder+'geographic/watershed_dem.tif')
    area = tif_features.basin_area(dem_data, dem_data, '<=', -1000, 75)
    df['spe'] = (df.outflow_drain) * 1000 # mm/m
    # df['eff'] = (ppt['REA_historic']-etp['REA_historic']) * 1000
    df['eff'] = rech * 1000
    df['rec'] = rech * 1000

#%% GIF DISCHARGE
    
    ##### DEM #####
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
    
    ##### MODLOW #####
    dir_to_analyse = simulations_folder + ident + '/_extraction/'
    mass_to_analyse = simulations_folder + ident + '/_extraction/_surfaceflow/'
    figdir = dir_to_analyse + '_fig/'
    pngdir = dir_to_analyse + '_fig/_png/'
    gifdir = dir_to_analyse + '_fig/_gif/'
    file_adds.create_folder(figdir)
    file_adds.create_folder(pngdir)
    file_adds.create_folder(gifdir)
    water_table_path = dir_to_analyse + 'watertable_elevation.npy'
    outflow_path = dir_to_analyse + 'outflow_drain.npy'
    wt_all = np.load(water_table_path, allow_pickle=True).item() 
    outflow_all = np.load(outflow_path, allow_pickle=True).item() 
    surface_sat = []
    rch_for_gif = []
    time_for_gif = []
    flow_rate = []
    time_tot = df.index
    
    ##### LOOP #####
    for key in wt_all:
        ### PREP ###  
        outflow = outflow_all[key]
        msk_outflow = (outflow==np.min(outflow))
        outflow = np.ma.masked_array(outflow, mask=msk_outflow)
        outflow = np.ma.masked_where(outflow==0,outflow)
        outflow_len = len(outflow[outflow>0])
        cell = demData.count()
        flow_rate_temp = np.sum(outflow) / (cell * 75**2)
        flow_rate.append(flow_rate_temp)
        wt = wt_all[key]
        wt = np.ma.masked_array(wt, mask=msk)
        wt_len = len(wt[wt>0])
        surface_sats = outflow_len/wt_len*100
        surface_sat.append(surface_sats)
    
    for key in wt_all:
        lead_numb = "%03d" % (key,)
        t_temp = df.index[key]
        time_for_gif.append(t_temp)
        outflow = imageio.imread(mass_to_analyse+'mass_outflow_drain_t('+lead_numb+')'+'.tif')
        msk_outflow = (outflow<0)
        outflow = np.ma.masked_array(outflow, mask=msk_outflow)
        outflow = np.ma.masked_where(outflow==0, outflow) / 75**2 * 1000
        outflow_len = len(outflow[outflow>0])
        cell = demData.count()
        wt = wt_all[key]
        wt = np.ma.masked_array(wt, mask=msk)
        wt_len = len(wt[wt>0])
        ls = LightSource(azdeg=45, altdeg=45)
        cmap = plt.cm.Greys
        rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=dx, dy=dy)
        
        ### PLOT ###
        fig = plt.figure(figsize=(11,6))
        gs = fig.add_gridspec(3,2)
        ax1 = fig.add_subplot(gs[:, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 1])
        ax4 = fig.add_subplot(gs[2, 1])
        ax = ax1
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
        # levels = np.arange(1000, 3000, 100)
        hc=ax.contour(xx, yy, wt, alpha=0.25, cmap=mpl.colors.ListedColormap('k'), linewidths=1)
        ax.clabel(hc, inline=True, fontsize=8, fmt='%1.0f')
        # levels_outflow = np.arange(-1, 3.5, 0.5)
        # cf=ax.contourf(xx, yy, np.log10(outflow), levels=levels_outflow, cmap='jet_r', alpha=1, antialiased = True)
        # norm = mpl.colors.Normalize(vmin=-1, vmax=4)
        # cf=ax.imshow(np.log10(outflow), cmap='jet_r', alpha=1, vmin=-1, vmax=4)
        cf=ax.imshow(outflow / 75**2, cmap='jet_r', alpha=1, vmin=0, vmax=int(round(df.spe.mean())))
        plt.xlim(xx_mi-0.1*ext_x,xx_ma+0.1*ext_x)
        plt.ylim(yy_ma+0.1*ext_y,yy_mi-0.1*ext_y)
        divider = make_axes_locatable(ax)
        # Legend 1
        cax = divider.append_axes("right", size="1%", pad=0.05)
        fig.add_axes(cax)
        cbar = fig.colorbar(im, cax=cax, orientation="vertical")
        val = np.ma.masked_where(demData < 0, demData)
        minVal =  int(round(np.min(val[np.nonzero(val)],0)))
        maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
        meanVal = int(round(minVal+((maxVal-minVal)/2),0))
        cbar.set_ticks([minVal, meanVal, maxVal])
        cbar.set_ticklabels([minVal, meanVal, maxVal])
        cbar.mappable.set_clim(minVal, maxVal)
        cbar.ax.tick_params(labelsize=10)
        # Legend 2
        cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
        fig.add_axes(cax)
        cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
        ticks = np.arange(0, int(round(df.spe.mean()))+5, 5)
        cbar.set_ticks(ticks)
        cbar.set_ticklabels(ticks)
        cbar.set_label('Cumulated upstream discharge [mm/M]')
        plt.tight_layout()
        
        ax = ax2
        xlim = [pd.to_datetime(str(first-1)), pd.to_datetime(str(last+2))]
        rechs = df.iloc[key]
        rch_for_gif.append(rechs)
        ax.set_title("Recharge, [mm/M]")
        ax.plot(time_tot, df.rec, color='magenta', lw=2)
        ax.axvline(x=t_temp, color='k', lw=2)
        plt.setp(ax.get_xticklabels(), visible=False)
        ax.set_xlim(xlim)
        ax.set_ylim(df.rec.min(), df.rec.max())
        plt.tight_layout()
    
        ax = ax3
        #ax3.set_xlabel("time")
        ax.set_title("Saturated area, [%]")
        ax.plot(time_tot, surface_sat,'darkorange', lw=2)
        plt.setp(ax.get_xticklabels(), visible=False)
        ax.axvline(x=t_temp, color='k', lw=2)
        ax.set_xlim(xlim)
        ax.set_ylim(np.array(surface_sat).min(), np.array(surface_sat).max())
        plt.tight_layout()
    
        ax = ax4
        ax.set_xlabel("Time")
        ax.set_title("Discharge, [mm/M]")
        ax.plot(time_tot, np.array(flow_rate)*1000,'dodgerblue', lw=2)
        ax.axvline(x=t_temp, color='k', lw=2)
        # ax.set_yscale("log")
        ax.invert_yaxis()
        ax.set_xlim(xlim)
        ax.set_ylim(np.array(flow_rate).min()*1000, np.array(flow_rate).max()*1000)
        plt.tight_layout()
        
        name_fig = 'dyn_' + str(lead_numb) + '.png'
        plt.tight_layout()
        plt.savefig(pngdir + name_fig)
        plt.close(fig)
        print(str(key))
               
    filenames = glob(pngdir+'/'+'dyn_*.png')  
    import imageio
    images = []
    for filename in filenames:
        ima = imageio.imread(filename)
        images.append(ima)
    imageio.mimsave(gifdir+'/'+'dyn_outflow.gif', images, duration=0.5, loop=1)
    
    # from PIL import Image
    # frame_folder = pngdir
    # path_gif = gifdir
    # def make_gif(frame_folder):
    #     frames = [Image.open(image) for image in glob(f"{frame_folder}/*.PNG")]
    #     frame_one = frames[0]
    #     frame_one.save(path_gif + 'dyn_outflow.gif', format="GIF", append_images=frames,
    #                save_all=True, duration=200, loop=0)
    # if __name__ == "__main__":
    #     make_gif(frame_folder)
    
#%% YVEL

yvelgpd = gpd.read_file('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/YVEL/StreamWaterChemistry.csv')
yveldf = pd.read_csv('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/YVEL/StreamWaterChemistry.csv',
                     parse_dates=True, index_col='date.sampling', sep=';', error_bad_lines=False)
uni = yveldf['flow.condition'].unique()
yveldf['code'] = np.nan

lists = yveldf['p.sampling'].unique()
for samp in lists:
    fig, ax = plt.subplots(1,1, figsize=(5,3))
    df = yveldf[yveldf['p.sampling']==samp]
    ax.plot(df.index, df['temperature'])


