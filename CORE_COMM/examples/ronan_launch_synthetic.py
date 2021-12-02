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
                                      load=load)
    except:
        notok.append(watershed_name)
        print('NOT OK')

    BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                      first_year = 2005, last_year = 2019, 
                                      time_step = 'M', sim_state='transient')
    
    
    fig = plt.subplots(1,1, figsize=(6,3))
    rech = BV.forcing.recharge
    plt.plot(rech*1000, c='k', lw=0.5)
    
    sce0 = BV.forcing.update_sinusoid_recharge(rech, 'M', 1, 1, 1, 1) # serie, period, amplitude, offset, omega, phase
    plt.plot(BV.forcing.recharge*1000, c='blue')
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
    

    # BV.calib_dichotomy(ident=None, calib=True, type_river='streams', climatic=rech.mean(),
    #                     lay_number=1, thick=30, bottom=None, thick_exp=1., 
    #                     first=1, last=15000, gap=1, porosity=0.01, sea_level=None, cond_decay=0.)
    
    df = pd.read_csv(simulations_folder+'_dichotomy_'+'streams'+'.csv', sep=';', header=0)
    koptim = df.iloc[-1]['K'].round(1) # / 30 / 3600 / 24
    
    k = koptim
    BV.hydrodynamic.update_hyd_cond(k)
    sy = 0.01
    BV.hydrodynamic.update_porosity(sy)
    ep = 30
    BV.hydrodynamic.update_thickness(ep)
    
    ident = 'rech_'+str(koptim)+'_'+str(sy)+'_'+str(ep)+'_'+'1990-2019'
    # BV.run_modflow(ident=ident, modpath_sim=False, calib=False, sink_fill=False, 
    #                 lay_number=1, bottom=None, thick_exp=1., sea_level=None, cond_decay=0., verbose=True)

    # from groundwater_flow import vizualisation
    # visu = vizualisation.Vizualisation(BV, ident)
    # visu.visual3D(interactive=True, object_list=['grid','watertable','watertable_depth'], view='south-west')
    
#%%
