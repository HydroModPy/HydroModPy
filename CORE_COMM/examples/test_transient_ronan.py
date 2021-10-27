# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

#%% MODULES

# Modules
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter

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
from tools import file_adds

#%% PARAMS

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

plt.rc('font', size=smal)                         # controls default text sizes **font
plt.rc('figure', titlesize=large)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
plt.rcParams["font.family"] = "arial"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('arial') # for x and y label
fontdic = {'family' : 'arial'} # for legend

#%% PATHS

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
else:
    print("Define a well-validated name of user")

# test of watershed class
load = True
watershed_name = 'Canut2'
# watershed_name = 'Out'
library_path = df + '/watershed' + '/watershed_library.csv'
# library_path = analy_path + '/outlets_basins.txt'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

surfex_path =  root_path + 'SURFEX'
geology_path = root_path + 'GEOLOGY'
hydrology_path = root_path + 'HYDROLOGY'
modflow_path = root_path + 'MODFLOW'
piezometry_path = None
oceanic_path = None

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

rea_path = stable_folder+'climatic/'+'REA.h5'
first = 1960
last = 2019

rech = pd.read_hdf(rea_path,'REC/'+'historic')
rech = rech[(rech.index.year >= first) & (rech.index.year <= last)]
rech = rech.MEAN
rech = rech.resample('M').sum()
rech = rech / 1000

runof = pd.read_hdf(rea_path,'RUN/'+'historic')
runof = runof[(runof.index.year >= first) & (runof.index.year <= last)]
runof = runof.MEAN
runof = runof.resample('M').sum()
runof = runof / 1000

#%% GENERATE SUBBASINS

df_auto, df_manual = BV.generate_subbasins(file_name='station_x.txt',
                                           fonction_column='fonction',
                                           type_data='intermittent',
                                           code_column='name', label_column='name',
                                           x_column='x_outlet', y_column='y_outlet',
                                           start_column=0, end_column=0,
                                           snap_dist=200)

#%% DICHOTOMY CALIBRATION

BV.calib_dichotomy(ident=None, calib=True, type_river='streams',
                   climatic=pd.Series(rech.mean()), lay_number=1, thick=50, bottom=None, thick_exp=1., 
                   first=1, last=10000, gap=10, porosity=0.01, sea_level=None, cond_decay=0.)

#%% EXTRPOLATION CALIBRATION

type_river='streams'
dic = pd.read_csv(simulations_folder+'_dichotomy_'+type_river+'.csv', sep=';')

# Fixed
K = dic.iloc[-1]['K']
# K = 20
e = 50
time_step = 'monthly'

# Extrapolation
porosities = [0.001]

# Time
periods = [[1990,1991]]

for period in periods:
    first = period[0]
    last = period[1]
    
    for i, porosity in enumerate(porosities):
        
        step = 'trans_disch'

        rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
        run = runof[(runof.index.year >= first) & (runof.index.year <= last)]
        print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
        ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
        BV.run_modflow(ident=ident, calib=False,
                        climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
                        hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
        BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=False, 
                            first=first, last=last, time_step='monthly')
        obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_discharge_chronic()
        
        first_year = sim_data.first_valid_index().year
        last_year = sim_data.last_valid_index().year
        obs_data = obs_data[(obs_data.index.year >= first_year) & (obs_data.index.year <= last_year)]
        
        fig, ax = plt.subplots(1,1, figsize=(5,3))
        # ax.plot(rch*1000, color='dodgerblue')
        ax.plot(obs_data['disch_norm']*1000, color='k')
        # ax.plot(sim_data['outflow_drain']*1000, color='darkorange')
        ax.plot(sim_data['outflow_drain']*1000+run*1000, color='red')
        ax.set_yscale('log')
        ax.set_ylim(0.1, None)
        # ax.set_title(mask_name+'\n'+ident)
        ax.set_title(mask_name.split('_')[3])
        ax.grid(True)
        ax.set_xlabel('Date')
        ax.set_ylabel('Discharge [mm/months]')
        yearsFmt = DateFormatter('%Y')
        ax.xaxis.set_major_formatter(yearsFmt)
        
        fig, ax = plt.subplots(1,1, figsize=(4,4))
        ax.scatter(obs_data['disch_norm']*1000, sim_data['outflow_drain']*1000+run*1000, c='dodgerblue')
        ax.set_xscale('log')
        ax.set_yscale('log')
        mini = np.minimum((obs_data['disch_norm']*1000).min(),(sim_data['outflow_drain']*1000+run*1000).min())
        maxi = np.maximum((obs_data['disch_norm']*1000).max(),(sim_data['outflow_drain']*1000+run*1000).max())
        ax.plot((mini,maxi),(mini,maxi),ls='-',c='k')
        ax.set_xlim(1,maxi)
        ax.set_ylim(1,maxi)
        ax.set_xlabel('Observed [mm/m]')
        ax.set_ylabel('Simulated [mm/m]')
        
        def calc_rmse(predictions, targets):
            rmse = np.sqrt(((predictions - targets) ** 2).mean())
            nrmse = rmse / targets.mean() * 100
            return rmse, nrmse
        rmse, nrmspe = calc_rmse(sim_data['outflow_drain']*1000+run*1000, obs_data['disch_norm']*1000)
        
        # obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_saturation_chronic()
      
        #################
"""
        step = 'trans_satur'
        first = 2015
        last = 2016
        rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
        run = runof[(runof.index.year >= first) & (runof.index.year <= last)]
        print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
        ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
        BV.run_modflow(ident=ident, calib=False,
                        climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
                        hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
        BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=True, 
                            first=first, last=last, time_step='monthly')
        obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_saturation_chronic()
"""
#%% DISPLAY CLEMENT

from glob import glob
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm

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

dir_to_analyse = simulations_folder + 'trans_disch-0.001-19.833-50-0.014/_extraction/'
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
rech_for_gif = []
time_for_gif = []
flow_rate = []

##### INTERMITTENCE #####


##### PLOT #####

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
    
    fig = plt.figure(figsize=(11,6))
    gs = fig.add_gridspec(3,2)
    ax1=fig.add_subplot(gs[:, 0])
    ls = LightSource(azdeg=45, altdeg=45)
    cmap = plt.cm.gist_earth
    rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=dx, dy=dy)
    
    ax1.imshow(rgb,alpha=1)    
    cmap = plt.get_cmap('Blues')
    # levels = np.arange(1000, 3000, 100)
    hc=ax1.contour(xx, yy, wt, alpha=1, cmap=cmap, linewidths=0.5)
    ax1.clabel(hc, inline=True, fontsize=9, fmt='%1.0f')
    levels_outflow = np.arange(-1, 4, 0.5)
    cf=ax1.contourf(xx, yy, np.log10(outflow), levels=levels_outflow, cmap=cm.afmhot_r, alpha=1,antialiased = True)
    fig.colorbar(cf,ax = ax1)
    plt.xlim(xx_mi-0.1*ext_x,xx_ma+0.1*ext_x)
    plt.ylim(yy_ma+0.1*ext_y,yy_mi-0.1*ext_y)
    plt.tight_layout()
    
    ax2=fig.add_subplot(gs[0, 1])
    rechs = rech[key]
    rech_for_gif.append(rechs)
    ax2.set_ylabel("recharge, [mm/M]")
    ax2.plot(time_for_gif,rech_for_gif,'m')
    plt.setp(ax2.get_xticklabels(), visible=False)
    plt.tight_layout()
    
    ax3=fig.add_subplot(gs[1, 1])
    #ax3.set_xlabel("time")
    ax3.set_ylabel("saturated area, [%]")
    ax3.plot(time_for_gif,surface_sat,'r')
    plt.setp(ax3.get_xticklabels(), visible=False)
    plt.tight_layout()
    
    ax4=fig.add_subplot(gs[2, 1])
    ax4.set_xlabel("time")
    ax4.set_ylabel("discharge, [mm/M]")
    ax4.plot(time_for_gif,flow_rate,'b')
    ax4.set_yscale("log")
    plt.tight_layout()

    name_fig = 'dyn_' + str(key) + '.png'
    plt.tight_layout()
    plt.savefig(pngdir + name_fig)
    plt.close(fig)
    print(str(key))
        
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

filenames = glob(pngdir+'/'+'*.png')  
import imageio
images = []
for filename in filenames:
    images.append(imageio.imread(filename))
imageio.mimsave(gifdir+'/'+'dyn_outflow.gif', images, duration=1, loop=1)

#%% DISPLAY RONAN

site= 'Canut'

import imageio
import rasterio
import geopandas as gpd
from glob import glob
from mpl_toolkits.axes_grid1 import make_axes_locatable

compt = 1
c1 = 0
c12 = 12

dir_to_analyse = simulations_folder + 'trans_disch-0.001-19.833-50-0.014/_extraction/'
list_traces = glob(dir_to_analyse+'_surfaceflow/'+'trace_*.shp')

figdir = dir_to_analyse + '_fig/'
pngdir = dir_to_analyse + '_fig/_png/'
gifdir = dir_to_analyse + '_fig/_gif/'
file_adds.create_folder(figdir)
file_adds.create_folder(pngdir)
file_adds.create_folder(gifdir)

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
    df = pd.DataFrame(test, columns=['x','y'])
    df['z'] = df['x'].astype(str) + df['y'].astype(str)
    values = df['z'].value_counts()
    values = values[values==12]
    for j in inter:
        outflow = gpd.read_file(j)
        outflow['x'] = outflow.geometry.x
        outflow['y'] = outflow.geometry.y
        outflow['z'] = outflow['x'].astype(str) + outflow['y'].astype(str)
        outflow['persit'] = 0
        for h in values.index:
            outflow.loc[outflow['z']==h,'persit'] = 1
        outflow.to_file(j)
    c1+=12
    c12+=12
    compt+=1

compt = 0
for i in glob(dir_to_analyse+'_surfaceflow/'+'trace_*.shp'):
    outflow = gpd.read_file(i)

    fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
    
    dem = rasterio.open(BV.geographic.watershed_dem)
    img = imageio.imread(BV.geographic.watershed_dem)
    contour = gpd.read_file(stable_folder+'/geographic/'+'watershed_contour.shp')
    
    streams = gpd.read_file(stable_folder+'/hydrology/'+'streams.shp')
    # streams.plot(ax=ax, lw=1.5, color='navy', zorder=3)
    
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(site, fontproperties=fontprop)
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
    
    outflow[outflow.persit==1].plot(ax=ax, alpha=1, column='persit', color='blue', 
                                    marker='s', markersize=7.5, lw=0.1, edgecolor='none',
                                    zorder=4)
    
    name_fig = 'dyn_' + str(compt) + '.png'
    plt.tight_layout()
    plt.savefig(pngdir + name_fig)
    
    compt+=1

filenames = glob(pngdir+'/'+'*.png')  
import imageio
images = []
for filename in filenames:
    images.append(imageio.imread(filename))
imageio.mimsave(gifdir+'/'+'dyn_outflow.gif', images, duration=1, loop=1)

#%%
"""
from watershed import surfaceflow
lead_numb = '005'
surfaceflow.SurfaceFlow(BV.geographic,
                         'outflow_drain_t('+lead_numb+').tif',
                         '_temp_outflow_drain_t(xxx).shp',
                         '_temp_trace_outflow_drain_t(xxx).tif',
                         'trace_outflow_drain_t('+lead_numb+').shp',
                         extraction_folder=
                         'D:/Users/abherve/HYDROMODPY/Canut2/results_simulations/trans_disch-0.001-19.833-50-0.014/_extraction')
"""
#%%
"""
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

x = wbt.raster_summary_stats(
    'D:/Users/abherve/HYDROMODPY/Canut2/results_simulations/trans_disch-0.001-19.833-50-0.014/_extraction/outflow_drain_t(000).tif')

x = wbt.zonal_statistics(
    'D:/Users/abherve/HYDROMODPY/Canut2/results_simulations/trans_disch-0.001-19.833-50-0.014/_extraction/outflow_drain_t(000).tif', 
    'D:/Users/abherve/HYDROMODPY/Canut2/results_simulations/trans_disch-0.001-19.833-50-0.014/_extraction/seepage_areas_t(000).tif', 
    output='D:/Users/abherve/HYDROMODPY/Canut2/results_simulations/trans_disch-0.001-19.833-50-0.014/_extraction/test_number_t(000).tif', 
    stat='total', 
    out_table=None)
"""
#%% 
"""
mask_list = os.listdir('D:/Users/abherve/RESULTS/rejets_metropole/Out/results_stable/subbasins')
mask_list = [x for x in mask_list if x.split('_')[1] == 'onde']
for mask_name in mask_list:
    print(mask_name)
    subasin_folder = os.path.join('D:/Users/abherve/RESULTS/rejets_metropole/Out/results_stable/subbasins', mask_name)
    masked_file = os.path.join('D:/Users/abherve/RESULTS/rejets_metropole/Out/results_simulations/ext_satur-0.001-29.438-50-0.017/_masked', mask_name)
    sim_path = os.path.join(masked_file, '_simulated_chronics.csv')
    sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
    sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
    sim_data = sim_data.set_index('date')
    
    sim = np.array(sim_data['seepage_areas'].values)
    fig, ax = plt.subplots(1,1, figsize=(5,3))
    ax.plot(sim)
"""
"""
from tools import tif_masks
npy = 'D:/Users/abherve/RESULTS/rejets_metropole/Out/results_simulations/ext_disch-0.001-29.438-50-0.013/_extraction/seepage_areas.npy'
n = np.load(npy, allow_pickle=True)
plot = n.item()[1]
plt.imshow(plot)
x = gdal.Open(os.path.join('D:/Users/abherve/RESULTS/rejets_metropole/Out/results_stable/subbasins/calib_onde_J7384000_la Cotardière_341706_6794353','subbasin.tif'))
x = gdal.Open(os.path.join('D:/Users/abherve/RESULTS/rejets_metropole/Out/results_stable/subbasins/calib_onde_J73-0310_la Vaunoise_338945_6793945','subbasin.tif'))
mask_data = x.GetRasterBand(1).ReadAsArray()
masked = tif_masks.mask_by_dem(plot, mask_data, '!=', 1)
cell = masked.count()
count = (masked > 0).sum()
calc = (count/cell) * 100
df.loc[key,data_process] = calc
"""
     
#%%
"""
path_h5 = "D:/Users/abherve/HYDROMODPY/Canut/results_stable/climatic/REA.h5"
variable = 'REC'
scenario = 'historic'

raw = pd.read_hdf(path_h5, variable+'/'+scenario)
raw = raw[(raw.index.year >= 2000) & (raw.index.year <= 2005)]
raw = raw.resample('M').sum()
serie = raw.mean(numeric_only=True, axis=1)
serie = serie.reset_index()
sin = serie_transf.create_sinusoidal(serie, 'monthly', 1,1,1,1)
plt.plot(serie[0],c='b')
plt.plot(sin,c='r')
"""
#%%
"""
flux = imageio.imread(drn_sim_mask) # L/T
flux = np.ma.masked_array(flux, mask=(dem.data==-99999))
cell = flux.count()
outflow = (np.nansum(flux) / (cell * geographic.resolution**2)) # M/T

        self.sim_list = glob(xxx+'*')
        if not self.sim_list:
            print('- Delete previous : '+'NO'+'\n')
        else:
            print('- Delete previous : '+'YES'+'\n')
        for folder in self.sim_list:
            shutil.rmtree(folder)
"""
#%%
"""
self.df.loc[self.compt,'Kr'] = round(self.krval, 4)
self.df.loc[self.compt,'K'] = round(self.hyd_cond, 4)
self.df.loc[self.compt,'Sflow'] = round(self.store.sim_to_obs_mean, 4)
self.df.loc[self.compt,'Oflow'] = round(self.store.obs_to_sim_mean, 4)    

print('==> Simulation : '+str(self.compt))
print('    Parameters : '+self.sim_id)
print('    KR = '+str(round(self.krval, 2)))
print('    Condition = '+str(self.condition))
"""        
#%%
"""
d = pd.date_range(start='01/01/1950', end='31/12/2099', freq='MS')
df = d.to_period('M').to_timestamp('M').to_frame() # d + pd.offsets.MonthEnd(0)
time = pd.to_datetime(raw[['year','month','day']]) # create datetime
pd.to_datetime('13000101', format='%Y%m%d',

data = np.load("D:/Users/abherve/RESULTS/rejets_metropole/Out/results_simulations/ext_satur-0.1-29.438-50-0.017/_extraction/seepage_areas.npy",
            allow_pickle=True)

d1={'key1':[5,10], 'key2':[50,100]}
np.save("d1.npy", d1)
d2=np.load("D:/Users/abherve/RESULTS/rejets_metropole/Out/results_simulations/ext_satur-0.1-29.438-50-0.017/_extraction/seepage_areas.npy", allow_pickle=True)
print (d1.get('key1'))
print (d2.item().get('key2'))

x=d2.item()
for i in x:
    print (i)
    print(x[i])
d2.item()[5]

x= pd.read_csv("D:/Users/abherve/RESULTS/rejets_metropole/Out/results_simulations/ext_disch-0.1-29.438-50-0.013/_extraction/_simulated_chronics.csv", sep=';',
               parse_dates=True, index_col=0)
"""
#%%
"""
# if ident.split('-')[0] == 'ext_disch':
# obs_data, sim_data, df_stats, mask_name = chronics.compar_discharge_chronic()
    # return obs_data, sim_data, df_stats, mask_name

# if ident.split('-')[0] == 'ext_satur':
# obs_data, sim_data, df_stats, mask_name = chronics.compar_saturation_chronic()
    # return obs_data, sim_data, df_stats, mask_name
"""
