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
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
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

#%% PARAMETERS PLOT

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

#%% PATHS LOAD

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
    # root_path= "D:/HYDROMODPY/_data/"
    # out_path = "D:/HYDROMODPY"    
    # out_path = "D:/Users/abherve/RESULTS/rejets_metropole"
    # analy_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/rejets_metropole"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = True
watershed_name = 'RejetVaunoise'
# watershed_name = 'Out'
library_path = df + '/watershed' + '/watershed_library.csv'
# library_path = analy_path + '/outlets_basins.txt'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

surfex_path =  root_path + 'SURFEX'
geology_path = None
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

#%% RECHARGE FUNCTION

def extract_surfex_variables(h5_folder, model_name, scenario, first, last):
    h5_path = h5_folder + model_name +'.h5'
    
    try:
        tas = pd.read_hdf(h5_path,'TAS/'+scenario)
        tas = tas[(tas.index.year >= first) & (tas.index.year <= last)]
        tas = tas.MEAN
        tas = tas.resample('M').mean()
    except:
        tas = np.nan
        
    try:
        ppt = pd.read_hdf(h5_path,'PPT/'+scenario)
        ppt = ppt[(ppt.index.year >= first) & (ppt.index.year <= last)]
        ppt = ppt.MEAN
        ppt = ppt.resample('M').sum()
        ppt = ppt / 1000
    except:
        ppt = np.nan
    
    try:
        etp = pd.read_hdf(h5_path,'ETP/'+scenario)
        etp = etp[(etp.index.year >= first) & (etp.index.year <= last)]
        etp = etp.MEAN
        etp = etp.resample('M').sum()
        etp = etp / 1000    
    except:
        etp = np.nan
    
    try:
        run = pd.read_hdf(h5_path,'RUN/'+scenario)
        run = run[(run.index.year >= first) & (run.index.year <= last)]
        run = run.MEAN
        run = run.resample('M').sum()
        run = run / 1000
    except:
        run = np.nan
    
    try:
        rec = pd.read_hdf("D:/HYDROMODPY/Canut/results_stable/climatic/REA.h5",'REC/'+scenario)
        rec = rec[(rec.index.year >= first) & (rec.index.year <= last)]
        rec = rec.MEAN
        rec = rec.resample('M').sum()
        rec = rec / 1000
    except:
        rec = np.nan
    
    return tas, ppt, etp, run, rec

#%% CALL RECHARGE

model = 'REA'
scenario = 'historic'
first = 1960
last = 2019

# Recharge modflow
tas, ppt, etp, run, rec = extract_surfex_variables(stable_folder + 'climatic/', 
                                                   model, scenario, first, last)
df = pd.DataFrame()
df.index = rec.index
df['tas'] = tas.values
df['ppt'] = ppt.values
df['etp'] = etp.values
df['run'] = run.values
df['rec'] = rec.values

# Name modflow
step = model+'_'+scenario
df.to_csv(stable_folder + 'climatic/' + step + '.csv', sep=';')

# Sinus
raw = pd.read_csv(stable_folder + 'climatic/' + step + '.csv', sep=';', 
                  index_col='date', parse_dates=True)
raw = raw[(raw.index.year >= 2000) & (raw.index.year <= 2005)]
raw = raw.resample('M').sum()
serie = raw.mean(numeric_only=True, axis=1)
serie = serie.reset_index()
sin = serie_transf.create_sinusoidal(serie, 'monthly', 1,1,1,1)
plt.plot(serie[0],c='b')
plt.plot(sin,c='r')

#%% IMPORT REHCARGE

time_step = 'Y'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS']
scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']

sce_colors=["k","dodgerblue","forestgreen","darkorange","red"]
color_dict = dict(zip(scenarios, sce_colors))

for var in variables:
    df = pd.read_csv(stable_folder+'climatic/'+'_'+var+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
    fig, ax = plt.subplots(1,1, figsize=(7,3))
    for sce in scenarios:
        try:
            dfb = df.filter(regex=sce)
            if sce == 'historic':
                dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2009)]
            else:
                dfb = dfb[(dfb.index.year >= 2009) & (dfb.index.year <= 2099)]
            dfs = pd.DataFrame(index=dfb.index)
            # ax.plot(dfb, lw=0.2, color=color_dict[sce])
            dfs['MEAN'] = dfb.mean(axis=1)
            dfs['MIN'] = dfb.min(axis=1)
            dfs['MAX'] = dfb.max(axis=1)
            dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
            dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
            dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
            ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'], color=color_dict[sce], alpha=0.2, edgecolor='none')
            ax.plot(dfs['MEAN'], lw=1, color=color_dict[sce], label=sce)
            ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
            ax.set_title(var)
            ax.legend(loc='upper left')
            ax.axvline(pd.to_datetime('2010'), color='k', ls='--')
            from datetime import date
            ax.axvline(date.today(), color='k', ls='-')
        except:
            pass
    fig.savefig(stable_folder+'climatic/'+'_'+var+'_'+time_step+'.png', dpi=300, bbox_inches='tight')
        
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

#%% LAUNCH MODELS

# Parameters
type_river='streams'
dic = pd.read_csv(simulations_folder+'_dichotomy_'+type_river+'.csv', sep=';')
K = dic.iloc[-1]['K']
e = 50
porosity = 0.001
time_step = 'monthly'

BV.hydrodynamic.update_hyd_cond(K)
BV.hydrodynamic.update_porosity(porosity)
BV.hydrodynamic.update_thickness(e)

# Past
mod = 'REA'
sce = 'historic'
step = mod+'_'+sce+'_'
first = 1990
last = 2019
BV.forcing.update_recharge(mod, sce, first, last, 'M', 'transient')
BV.forcing.update_runoff(mod, sce, first, last, 'M', 'transient')
rch = BV.forcing.recharge / 1000 # m/m
run = BV.forcing.runoff / 1000 # m/m

print('==> Simulation ' + step + ' ' + ' / ' + str((porosity)))
param_ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))
clim_ident = str(round(rch.mean(),3))+'-'+str(first)+'-'+str(last)
ident = param_ident+'-'+clim_ident

BV.run_modflow(ident=ident, modpath_sim=False, calib=False, sink_fill=False, climatic=rch,
                lay_number=1, bottom=None, thick_exp=1., 
                sea_level=None, cond_decay=0., verbose=True)
BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=False, 
                    first=first, last=last, time_step='monthly')

# Future
mod = 'IPS1'
scenarios = ['RCP4.5', 'RCP8.5']

for sce in scenarios:
    step = mod+'_'+sce+'_'
    first = 2020
    last = 2049
    BV.forcing.update_recharge(mod, sce, first, last, 'M', 'transient')
    BV.forcing.update_runoff(mod, sce, first, last, 'M', 'transient')
    rch = BV.forcing.recharge / 1000
    run = BV.forcing.runoff / 1000
    
    print('==> Simulation ' + step + ' ' + ' / ' + str((porosity)))
    param_ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))
    clim_ident = str(round(rch.mean(),3))+'-'+str(first)+'-'+str(last)
    ident = param_ident+'-'+clim_ident
    
    BV.run_modflow(ident=ident, modpath_sim=False, calib=False, sink_fill=False, climatic=rch,
                    lay_number=1, bottom=None, thick_exp=1., 
                    sea_level=None, cond_decay=0., verbose=True)
    BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=False, 
                        first=first, last=last, time_step='monthly')

#%% COMPARE DISCHSATUR

obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_discharge_chronic()

first_year = sim_data.first_valid_index().year
last_year = sim_data.last_valid_index().year
obs_data = obs_data[(obs_data.index.year >= first_year) & (obs_data.index.year <= last_year)]

fig = plt.figure(figsize=(10,4))
gs = fig.add_gridspec(1,3)
ax1 = fig.add_subplot(gs[:, :-1])
ax2 = fig.add_subplot(gs[:, -1])

ax = ax1
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

ax = ax2
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

plt.tight_layout()

def calc_rmse(predictions, targets):
    rmse = np.sqrt(((predictions - targets) ** 2).mean())
    nrmse = rmse / targets.mean() * 100
    return rmse, nrmse
rmse, nrmspe = calc_rmse(sim_data['outflow_drain']*1000+run*1000, obs_data['disch_norm']*1000)

obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_saturation_chronic()

#%% GIFS RESULTS

mod = 'IPS1'
sce = 'RCP8.5'

step = mod+'_'+sce+'_'
first = 2020
last = 2049
BV.forcing.update_recharge(mod, sce, first, last, 'M', 'transient')
BV.forcing.update_runoff(mod, sce, first, last, 'M', 'transient')
rch = BV.forcing.recharge / 1000
run = BV.forcing.runoff / 1000

print('==> Simulation ' + step + ' ' + ' / ' + str((porosity)))
param_ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))
clim_ident = str(round(rch.mean(),3))+'-'+str(first)+'-'+str(last)
ident = param_ident+'-'+clim_ident

site= 'RejetVaunoise'

### PATH ###

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
    print('Detect intermittency : '+str(compt))
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
    
    streams = gpd.read_file(stable_folder+'/hydrology/'+'streams.shp')
    sections = gpd.read_file(stable_folder+'/hydrology/'+'sections.shp')
    sections[sections.Persistanc=='3'].plot(ax=ax, lw=1, color='grey', ls='-', zorder=7)
    sections[sections.Persistanc=='4'].plot(ax=ax, lw=1, color='k', ls='-', zorder=7)
    
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(site+'  '+str(rch.index[compt])[:10], fontproperties=fontprop)
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
imageio.mimsave(gifdir+'/'+'interm_outflow.gif', images, duration=1, loop=1)


# from matplotlib.gridspec import GridSpec
# fig = plt.figure(figsize=(12, 6))
# gs = GridSpec(nrows=2, ncols=2, width_ratios=[3, 1], height_ratios=[1, 2])
# ax1 = fig.add_subplot(gs[0, 0])
# ax2 = fig.add_subplot(gs[0, 1])
# ax3 = fig.add_subplot(gs[1, 0])
# ax4 = fig.add_subplot(gs[1, 1])

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

time_tot = rch.index

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
    
    t_temp = rch.index[key]
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
    cf=ax.imshow(outflow / 75**2, cmap='jet_r', alpha=1, vmin=0, vmax=int(round(rch.mean()*1000)))
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
    ticks = np.arange(0, int(round(rch.mean()*1000))+5, 5)
    cbar.set_ticks(ticks)
    cbar.set_ticklabels(ticks)
    cbar.set_label('Cumulated upstream discharge [mm/M]')
    plt.tight_layout()
    
    ax = ax2
    xlim = [pd.to_datetime(str(first-1)), pd.to_datetime(str(last+2))]
    rechs = rch[key]
    rch_for_gif.append(rechs)
    ax.set_title("Recharge, [mm/M]")
    ax.plot(time_tot, rch*1000, color='magenta', lw=2)
    ax.axvline(x=t_temp, color='k', lw=2)
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.set_xlim(xlim)
    ax.set_ylim(rch.min()*1000, rch.max()*1000)
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
    ax.plot(time_tot, np.array(flow_rate) * 1000,'dodgerblue', lw=2)
    ax.axvline(x=t_temp, color='k', lw=2)
    # ax.set_yscale("log")
    ax.invert_yaxis()
    ax.set_xlim(xlim)
    ax.set_ylim(np.array(flow_rate).min()* 1000, np.array(flow_rate).max()* 1000)
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
    images.append(imageio.imread(filename))
imageio.mimsave(gifdir+'/'+'dyn_outflow.gif', images, duration=1, loop=1)

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

#%% CLIMATIC MODEL

variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
variables = ['REC']
scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']
# simulations = ['IPS1']

colors = {'historic':'k',
          'RCP2.6':'forestgreen',
          'RCP4.5':'dodgerblue',
          'RCP6.0':'darkorange',
          'RCP8.5':'darkred'}

# for var in variables:

clim_path = stable_folder+'climatic/'

periods = [[2006,2009],
           [2021,2050]]
# historic and other scenarios
# other scenarios 

# var = 'REC'

for per in periods:
    
    df = pd.DataFrame(simulations, columns=['sim'])
    df = df.set_index('sim')
    df[scenarios] = np.nan

    df25 = pd.DataFrame(simulations, columns=['sim'])
    df25 = df25.set_index('sim')
    df25[scenarios] = np.nan

    df50 = pd.DataFrame(simulations, columns=['sim'])
    df50 = df50.set_index('sim')
    df50[scenarios] = np.nan

    df75= pd.DataFrame(simulations, columns=['sim'])
    df75 = df75.set_index('sim')
    df75[scenarios] = np.nan
    
    for var in variables:

    # fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
    # ax.set_ylabel(var)
    # ax.set_xlabel('Date')
    # ax.set_title(per)
    
        for sce in scenarios:
            for sim in simulations:
            
                try:
                    raw = pd.read_hdf(clim_path + sim +'.h5',var+'/'+sce)
                    raw = raw[(raw.index.year >= per[0]) & (raw.index.year <= per[1])]
                    raw = raw.MEAN
                                       
                    if var=='TAS':
                        chro = raw.resample('Y').mean()
                        # q75 = raw.resample('Y').quantile(0.75)
                        # q25 = raw.resample('Y').quantile(0.50)
                        raw = chro.mean()
                        q25 = chro.quantile(0.25)
                        # q50 = chro.quantile(0.50)
                        q75 = chro.quantile(0.75)
                    else:
                        chro = raw.resample('Y').sum()
                        # q75 = raw.resample('Y').quantile(0.75) * 1000
                        # q25 = raw.resample('Y').quantile(0.50) * 1000
                        raw = chro.mean()
                        q25 = chro.quantile(0.25)
                        # q50 = chro.quantile(0.50)
                        q75 = chro.quantile(0.75)
                    
                    # ax.plot(chro, color=colors[sce], label=sce)
                    # ax.fill_between(chro.index, q25, q75, color=colors[sce], alpha=0.5)
                    df.loc[sim, sce] = raw
                    df25.loc[sim, sce] = q25
                    # df50.loc[sim, sce] = q50
                    df75.loc[sim, sce] = q75
                    
                except:
                    df.loc[sim, sce] = np.nan
                    pass
                
        fig, ax = plt.subplots(figsize=(5, 5), dpi=300)    
        df.plot.barh(ax=ax, color=['k','forestgreen','dodgerblue','darkorange','darkred'])
        # df25.plot(ax=ax, marker='o', color=['k','royalblue','skyblue','darkorange','darkred'])
        ax.axvline(x=df.loc['REA','historic'], ls='--', color='k')
        ax.invert_yaxis()
        ax.set_xlabel(var)
        ax.set_ylabel('Climatic models')
        ax.set_title(per)
        ax.legend(bbox_to_anchor=(1.25, 1))

#%% ADD GEOMORPHOLOGY

site='Lasset'
dem = stable_folder + 'geographic/'+'watershed_dem.tif'
d8_pntr = stable_folder + 'geographic/'+'watershed_direc.tif'

wbt.find_ridges(
    dem, 
    stable_folder + 'geographic/'+'find_ridges.tif', 
    line_thin=True)

wbt.flow_length_diff(
    d8_pntr,
    stable_folder + 'geographic/''flow_length_diff.tif')
    
wbt.max_branch_length(
    dem, 
    stable_folder + 'geographic/''max_branch_length.tif', 
    log=False)

fill_path = stable_folder + 'geographic/'+'watershed_fill.tif'
dinf_path = stable_folder + 'geographic/''d_inf.tif'
slope_path = stable_folder + 'geographic/''slope.tif'
wbt.d_inf_flow_accumulation(fill_path, dinf_path, out_type="Specific Contributing Area", 
                            threshold=None, log=False, clip=False, pntr=False)
wbt.slope(fill_path, slope_path)
wti_path = stable_folder + 'geographic/''wti.tif'
wbt.wetness_index(dinf_path, slope_path, wti_path)

# x = wbt.raster_summary_stats()
# x = wbt.zonal_statistics(X, Y, output=Z, stat='total', out_table=None)

#%% MERGE STREAMS ZH

#Merger les points shp
pt_streams = stable_folder + 'hydrology/' + 'stream_digit_pt.shp'
pt_zh = stable_folder + 'hydrology/' + 'zh_digit_pt.shp'
merge_path = pt_streams+';'+pt_zh
pt_zhstreams = stable_folder + 'hydrology/' + 'zhstream_digit_pt.shp'
wbt.merge_vectors(merge_path, pt_zhstreams)

#Merger les tifs
tif_streams = stable_folder + 'hydrology/' + 'stream_digit.tif'
tif_zh = stable_folder + 'hydrology/' + 'zh_digit.tif'
merge_path = tif_streams+';'+tif_zh
tif_zhstreams = stable_folder + 'hydrology/' + 'zhstream_digit.tif'
wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")

types_river = ['stream_digit','zh_digit','zhstream_digit']
for type_river in types_river:
    BV.calib_dichotomy(ident=None, calib=True, type_river=type_river, climatic=pd.Series(1e-3), 
                       lay_number=1, thick=50, bottom=None, thick_exp=1., 
                       first=1, last=500, gap=10, porosity=0.01, 
                       sea_level=None, cond_decay=0.)

#%% STICKY TIME

d = pd.date_range(start='01/01/1950', end='31/12/2099', freq='MS')
df = d.to_period('M').to_timestamp('M').to_frame() # d + pd.offsets.MonthEnd(0)
# time = pd.to_datetime(raw[['year','month','day']]) # create datetime
# pd.to_datetime('13000101', format='%Y%m%d')

#%% CREATE HYDROCLIMAT

# Users
user = "Ronan"
root_path = "D:/HYDROMODPY/_data/"
out_path = "D:/HYDROMODPY/_HYSTERESIS/"    

dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"
surfex_path =  root_path + 'SURFEX' + '/bzh'
geology_path = None
hydrology_path = None
modflow_path = None
piezometry_path = None
oceanic_path = None
save_object = None

data_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/BANQUEHYDRO/bretagne/"

import chardet
with open(data_path+'coord/'+'all_stations.csv', 'rb') as f:
    result = chardet.detect(f.read())  # or readline if the file is large
coord = pd.read_csv(data_path+'coord/'+'all_stations.csv', sep=';', encoding=result['encoding'])
df_coord = pd.DataFrame(columns=['name','x_outlet','y_outlet','snap_dist','buff_dist','user'])
df_coord['name'] = coord['STATION_NAME']
df_coord['x_outlet'] = coord['X']
df_coord['y_outlet'] = coord['Y']
df_coord['snap_dist'] = 300
df_coord['buff_dist'] = 1000
df_coord['user'] = 'R.Abherve'
df_coord['name'] = df_coord['name'].str.lower()

df_coord.to_csv(data_path+'coord/'+'hydromodpy_stations.csv', sep=';')

load = False
library_path = data_path+'coord/'+'hydromodpy_stations.csv'

library = pd.read_csv(library_path, sep=';', index_col=0)

for idx, watershed_name in enumerate(library['name'][:]):
    x=2
    try:
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
        simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
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
        #                               load=load,
        #                               save_object=save_object)
        
        model = 'REA'
        scenario = 'historic'
        first = 1960
        last = 2019
        
        # Recharge modflow
        tas, ppt, etp, run, rec = extract_surfex_variables(stable_folder + 'climatic/', 
                                                            model, scenario, first, last)
        
        df = pd.DataFrame()
        df.index = rec.index
        df['ppt'] = ppt.values *1000 # mm/m
        df['etp'] = etp.values *1000 # mm/m
        df['run'] = run.values *1000 # mm/m
        df['rec'] = rec.values *1000 # mm/m
        df['eff'] = df['ppt'] - df['etp']
        
        area = coord[coord['STATION_NAME'].str.lower()==watershed_name].AREA_BANQUE.values[0] * 1000000
        # basin_area = tif_features.basin_area(stable_folder+'geogrpahic/waterhed_dem.tfi',
        #                                      stable_folder+'geogrpahic/waterhed_dem.tfi', '==',
        #                                      -99999,
        #                                      75)
        
        if watershed_name=='canut_nord' or watershed_name=='cheze_plelan':
            q = pd.read_csv(data_path + 'raw/' + watershed_name.lower() + '.txt', sep='\t', index_col='time', parse_dates=True)
        else:
            q = pd.read_csv(data_path + 'raw/' + watershed_name.lower() + '.csv', sep='\t', index_col='time', parse_dates=True)
        q = q * 3600 * 24 # m3/J
        q = q.resample('M').sum() # m3/m
        
        df['deb'] = q # m3/m
        df['spe'] = q / area * 1000 # mm/m
        
        # Name modflow
        df.to_csv(data_path+'hydroclimat/'+watershed_name+'.csv', sep=';')
        
        print('OK - ' + str(idx) + ' - ' + watershed_name)
        
    except:
        print('NO - ' + str(idx) + ' - ' + watershed_name)
        continue
            
#%% HYSTERESIS TOTAL

def hysteresis_total(station, index, xm, ym, out, first, last):
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
    ax.set_xlim(-100,150)
    ax.set_ylim(0.3,200)
    ax.set_xticks(np.linspace(-150, 150, 5))
    # Parameter title 
    ax.set_title(station+' '+str(first)+'-'+str(last)) 
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
    fig.savefig("D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/intermhysteresis_bzh/hysteres/"+
                station+' '+str(first)+'-'+str(last)+'.png', dpi=300, bbox_inches='tight')
    plt.close()
    
user = "Ronan"
root_path = "D:/HYDROMODPY/_data/"
out_path = "D:/HYDROMODPY/_HYSTERESIS/"    
data_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/BANQUEHYDRO/bretagne/"
import chardet
with open(data_path+'coord/'+'all_stations.csv', 'rb') as f:
    result = chardet.detect(f.read())  # or readline if the file is large
coord = pd.read_csv(data_path+'coord/'+'all_stations_ronan.csv', sep=';', encoding=result['encoding'])
stations = coord['STATION_NAME'].unique()

for idx, station in enumerate(stations[:]):
    print(str(idx) + ' - ' + station)
    stable_folder = out_path+'/'+station.lower()+'/'+'results_stable/'
    try:
        df = pd.read_csv(data_path+'hydroclimat/'+station+'.csv', sep=';', index_col='date', parse_dates=True)
        first = df.spe.first_valid_index().year
        last = df.spe.last_valid_index().year
        hysteresis_total(station, df.index, df.eff, df.spe, stable_folder, first, last)
    except:
        continue

#%% HYSTERESIS SUPERPOSE

# coord.loc[coord['STATION_NAME'].str.lower()=='aff_paimpont', 'MAIN_LITHOLOGY'] = 'Schistes et gres du Primaire '
# coord.loc[coord['STATION_NAME'].str.lower()=='cheze_plelan', 'MAIN_LITHOLOGY'] = 'Schistes et gres du Primaire '
# couleurs = ["red", "forestgreen", "hotpink", "grey", 'turquoise', 'darkorange', 'navy']

user = "Ronan"
root_path = "D:/HYDROMODPY/_data/"
out_path = "D:/HYDROMODPY/_HYSTERESIS/"    
data_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/BANQUEHYDRO/bretagne/"
import chardet
with open(data_path+'coord/'+'all_stations.csv', 'rb') as f:
    result = chardet.detect(f.read())  # or readline if the file is large
coord = pd.read_csv(data_path+'coord/'+'all_stations_ronan.csv', sep=';', encoding=result['encoding'])
stations = coord['STATION_NAME'].unique()

litho = coord['MAIN_LITHOLOGY'].unique()
couleurs = ["red", "forestgreen", "hotpink", "grey"]
diclitho = dict(zip(litho, couleurs))

for case in litho:
    print(case)
    cp = 0
    
    fig, ax = plt.subplots(1,1,figsize=(5.5, 4.5))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
    plt.xlabel("P - E [mm.m$^-$$^1$]", labelpad=+15)
    plt.ylabel("Q / A [mm.m$^-$$^1$]", labelpad=+25)

    stations = coord.loc[coord['MAIN_LITHOLOGY']==case, 'STATION_NAME'].unique()
    
    for idx, station in enumerate(stations[:]):
        print(str(idx) + ' - ' + station)
        geol = coord.loc[coord['STATION_NAME'].str.lower()==station.lower(), 'MAIN_LITHOLOGY'].values[0]
        couleur = diclitho[geol] 
        
        try:
            df_concat = pd.read_csv(data_path+'hydroclimat/'+station+'.csv', sep=';', index_col='date', parse_dates=True)
        except:
            continue
    
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
        ax.plot(xline, yline, linestyle = '-', lw=1, color=couleur, zorder=2+cp)    
        # Plot error bars
        # ax.errorbar(xintm, yintm, 
        #                     yerr=np.vstack([yintm-yerr.q25, yerr.q75-yintm]),
        #                     xerr=np.vstack([xintm-xerr.q25, xerr.q75-xintm]),
        #                     ecolor = couleur, fmt = 'none', capsize = 1, elinewidth=0.5, 
        #                     capthick=0.5, zorder=1+cp)        
        # Parameter log
        ax.set_yscale('log')        
        # Parameter lim   
        minx = -100
        maxx = 150
        ax.set_xlim(minx,maxx)
        ax.set_ylim(0.3,200)
        # Plot 1:1 line
        x = np.linspace(*ax.get_xlim())
        ax.plot(x, x, linestyle='-',color='k', linewidth=2, zorder=0)
        # Parameter title 
        ax.set_title(case)
        ax.grid(True)
        # Tidy
        plt.tight_layout()
        cp += 3
        
    fig.savefig("D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/intermhysteresis_bzh/"+
                'corrected_hysteresis_' + str(case) + '.png',
                dpi=300, bbox_inches='tight')

#%% HYSTERESIS DESCRIBE

import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math

def linregress(inx,iny,ax):
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

def hysteresis_parameters(station, index, xm, ym, out):
            
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
        reg = linregress(data.inx,data.iny,ax)
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

user = "Ronan"
root_path = "D:/HYDROMODPY/_data/"
out_path = "D:/HYDROMODPY/_HYSTERESIS/"    
data_path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/2_data/Hydrology/BANQUEHYDRO/bretagne/"
import chardet
with open(data_path+'coord/'+'all_stations.csv', 'rb') as f:
    result = chardet.detect(f.read())  # or readline if the file is large
coord = pd.read_csv(data_path+'coord/'+'all_stations_ronan.csv', sep=';', encoding=result['encoding'])
stations = coord['STATION_NAME'].unique()

litho = coord['MAIN_LITHOLOGY'].unique()
couleurs = ["red", "forestgreen", "hotpink", "grey"]
diclitho = dict(zip(litho, couleurs))

# fig, ax = plt.subplots(1,1,figsize=(5.5, 4.5))
# fig.add_subplot(111, frameon=False)
# plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False) # hide tick and tick label of the big axis
# plt.xlabel("P - E [mm.m$^-$$^1$]", labelpad=+15)
# plt.ylabel("Q / A [mm.m$^-$$^1$]", labelpad=+25)

recap = pd.DataFrame()
compt = 0

for idx, station in enumerate(stations[:]):
    print(str(idx) + ' - ' + station)
    geol = coord.loc[coord['STATION_NAME'].str.lower()==station.lower(), 'MAIN_LITHOLOGY'].values[0]
    couleur = diclitho[geol]

    stable_folder = out_path+'/'+station.lower()+'/'+'results_stable/'
    
    try:
        df = pd.read_csv(data_path+'hydroclimat/'+station+'.csv', sep=';', index_col='date', parse_dates=True)
        qmax, qmin, q0, qmid, qsep, hi, reg_stat, ortho, intersection, ecart_center = hysteresis_parameters(station, df.index, df.eff, df.spe, stable_folder)
    except:
        continue
    
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
    plt.xlabel("P - E [mm]", labelpad=+15)
    plt.ylabel("Q / A [mm]", labelpad=+25)
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
    ax.set_xlim(-150,150)
    ax.set_ylim(-75,75)
    ax.set_title(station+' '+str(first)+'-'+str(last))
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
    recap.loc[compt,'geol'] = geol
    
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
    plt.close()
    compt += 1
    
    # Save
    recap.to_csv("D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/intermhysteresis_bzh/describe/"+
                 '_recap_describe'+'.csv', sep=';')   
    fig.savefig("D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/intermhysteresis_bzh/describe/"+
                station+' '+str(first)+'-'+str(last)+'.png', dpi=300, bbox_inches='tight')

#%% HYSTERESIS BOXPLOT

import seaborn as sns

geol = recap.geol.unique().tolist()
geol_colors=["red","forestgreen","hotpink","grey"]
color_dict = dict(zip(geol, geol_colors))

fig, axs = plt.subplots(5,5,figsize=(15, 15))
axs = axs.ravel()

cols = recap.columns[1:-1]

for idx, to_look in enumerate(cols):

    ax=axs[idx]

    bplot=sns.boxplot(ax=ax, y=to_look, x='geol', 
                      data=recap, 
                      width=0.5)                  
    
    for i in range(0,3):
        mybox = bplot.artists[i]
        mybox.set_facecolor(color_dict[geol[i]])
    
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
fig.savefig("D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/intermhysteresis_bzh/describe/"+
            '_recap_figure'+'.png', dpi=300, bbox_inches='tight')

#%% CLIMAT SEASON

time_step = 'M'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS']
# variables = ['REC']
scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
scenarios = ['historic','RCP4.5','RCP8.5']
scenarios = ['historic','RCP2.6','RCP8.5']
simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']
simulations = ['ACC1','BCC1','BNU1','CAN1','CSI1','IPS1','MIR1','NOR1']
simulations = ['BCC1','CAN1','IPS1','NOR1']
simulations = 'BCC1|CAN1|IPS1|NOR1'

sce_colors=["k","dodgerblue","forestgreen","darkorange","red"]
sce_colors=["k","dodgerblue","red"]
color_dict = dict(zip(scenarios, sce_colors))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

space = 5

for var in variables:
    df = pd.read_csv(stable_folder+'climatic/'+'_'+var+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
    df = df.filter(regex=simulations)
    fig, axs = plt.subplots(2,2, figsize=(10,5))
    axs = axs.ravel()
    for i, sea in enumerate(seasons):
        ax = axs[i]
        for sce in scenarios:
            try:
                dfb = df.filter(regex=sce)
                # if sce == 'historic':
                    # dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2009)]
                    
                    # rea = dfb['REA_historic']
                    # rea = rea.groupby([(rea.index.year),(rea.index.month)]).mean()
                    # rea = rea.rename_axis(["year", "month"]).to_frame()
                    # rea = rea.query("month == "+"["+sea+"]")
                    # rea = rea.groupby('year').sum()
                    # rea.index =  pd.to_datetime(rea.index, format='%Y')
                    
                # else:
                dfb = dfb[(dfb.index.year >= 1960) & (dfb.index.year <= 2099)]
                
                dfb = dfb.groupby([(dfb.index.year),(dfb.index.month)]).mean()
                dfb = dfb.rename_axis(["year", "month"])
                
                dfb = dfb.query("month == "+"["+sea+"]")
                dfb = dfb.dropna()
                dfb = dfb.groupby('year').sum()
                dfb.index =  pd.to_datetime(dfb.index, format='%Y')
                
                dfs = pd.DataFrame(index=dfb.index)
                # ax.plot(dfb, lw=0.1, color=color_dict[sce])
                dfs['MEAN'] = dfb.mean(axis=1)
                dfs['MIN'] = dfb.min(axis=1)
                dfs['MAX'] = dfb.max(axis=1)
                dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
                dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
                dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
                dfs['STD'] = dfb.std(axis=1)
                dfs = dfs.iloc[1:-1]
                
                dfs = dfs.rolling(window=space).mean().shift(-space)
                
                # ax.plot(rea, ls='-', color='k', lw=0.25)
                ax.fill_between(dfs.index, dfs['Q25'], dfs['Q75'], color=color_dict[sce], alpha=0.2, edgecolor='none')
                # ax.plot(dfs['Q50'], lw=1, color=color_dict[sce], label=sce)
                # ax.fill_between(dfs.index, dfs.MEAN-dfs['STD'], dfs.MEAN+dfs['STD'], color=color_dict[sce], alpha=0.2, edgecolor='none')
                ax.plot(dfs['MEAN'], lw=1, color=color_dict[sce], label=sce)
                ax.set_xlim(pd.to_datetime('1960'), pd.to_datetime('2100'))
                ax.set_title(seas_dict[sea])
                # ax.legend(loc='upper left')
                # ax.axvline(pd.to_datetime('2010'), color='k', ls='--')
                from datetime import date
                ax.axvline(date.today(), color='k', ls='-')
                
                ax.axvline(dfs.first_valid_index(), color='grey', ls='-', lw=0.1)
                ax.axvline(dfs.last_valid_index(), color='grey', ls='-', lw=0.1)
                # ax.text(dfs.first_valid_index(),0.8, str(dfs.first_valid_index().year), rotation=90,
                #         transform=ax.get_xaxis_transform())
                
            except:
                pass
    fig.suptitle(var)
    plt.tight_layout()
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/surfex_plot/fig/SEASON_ROLLING/'
                    +str(space)+'_'+var+'_'+time_step+'_'+'.png', dpi=300, bbox_inches='tight')

#%% CLIMAT FREQ

time_step = 'M'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS']
# variables = ['REC']
scenarios = ['historic','RCP2.6','RCP8.5']
simulations = 'BCC1|CAN1|IPS1|NOR1'

sce_colors=["k","dodgerblue","forestgreen","darkorange","red"]
sce_colors=["k","dodgerblue","red"]
color_dict = dict(zip(scenarios, sce_colors))

seasons = ['9,10,11',
           '12,1,2',
           '3,4,5',
           '6,7,8']
string = ['SON','DJF','MAM','JJA']
seas_dict = dict(zip(seasons, string))

for var in variables:
    df = pd.read_csv(stable_folder+'climatic/'+'_'+var+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
    df = df.filter(regex=simulations)
    fig, axs = plt.subplots(1,4, figsize=(10.5,2.5))
    axs = axs.ravel()
    for i, sea in enumerate(seasons):
        ax = axs[i]
        for sce in scenarios:
            try:
                dfb = df.filter(regex=sce)
                if sce == 'historic':
                    dfb = dfb[(dfb.index.year >= 1990) & (dfb.index.year <= 2009)]
                else:
                    dfb = dfb[(dfb.index.year >= 2010) & (dfb.index.year <= 2049)]
        
                dfb = dfb.groupby([(dfb.index.year),(dfb.index.month)]).mean()
                dfb = dfb.rename_axis(["year", "month"])
                
                dfb = dfb.query("month == "+"["+sea+"]")
                dfb = dfb.dropna()
                dfb = dfb.groupby('year').sum()
                dfb.index =  pd.to_datetime(dfb.index, format='%Y')
        
                dfs = pd.DataFrame(index=dfb.index)
                dfs['MEAN'] = dfb.mean(axis=1).round(1)
                dfs['MIN'] = dfb.min(axis=1)
                dfs['MAX'] = dfb.max(axis=1)
                dfs['Q25'] = dfb.quantile(q=0.25, axis=1)
                dfs['Q50'] = dfb.quantile(q=0.50, axis=1)
                dfs['Q75'] = dfb.quantile(q=0.75, axis=1)
                dfs['STD'] = dfb.std(axis=1)
                
                freq = dfs.groupby(by='MEAN').size().reset_index(name='counts')
                freq['frequency'] = freq.counts/freq.counts.sum() #freq
                freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
                
                ax.plot(freq.cumulative_frequency, freq.MEAN, color=color_dict[sce])
                ax.set_yscale('log')
                ax.set_xticks(np.linspace(0,1,3))
                ax.set_title(seas_dict[sea])
                ax.set_xlabel('Frequency')
                ax.set_ylabel(var + ' [mm]')
                ax.plot(0.10, dfs['MEAN'].quantile(0.10), 'o',markersize=5, color=color_dict[sce], markeredgecolor='none')
                ax.plot(0.50, dfs['MEAN'].quantile(0.50), 'o',markersize=5, color=color_dict[sce], markeredgecolor='none')
                ax.plot(0.90, dfs['MEAN'].quantile(0.90), 'o',markersize=5, color=color_dict[sce], markeredgecolor='none')
                ax.set_xlim(0,1)
                
            except:
                pass
    plt.tight_layout()
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/surfex_plot/fig/ANO_FREQ/'
                +'FREQ_'+'_'+var+'_'+time_step+'_'+'.png', dpi=300, bbox_inches='tight')

#%% CLIMAT ANOMALY

time_step = 'M'

variables = ['REC', 'RUN', 'ETP', 'PPT', 'TAS']
# variables = ['REC']
scenarios = ['RCP2.6','RCP8.5']
simulations = 'BCC1|CAN1|IPS1|NOR1'

sce_colors=["k","dodgerblue","forestgreen","darkorange","red"]
sce_colors=["dodgerblue","red"]
color_dict = dict(zip(scenarios, sce_colors))

periods = [[2020,2030],
           [2030,2040],
           [2040,2050],
           [2050,2060]]

for var in variables:
    df = pd.read_csv(stable_folder+'climatic/'+'_'+var+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
    dfh = df.filter(regex=simulations)
    dfh = df.filter(regex='historic')
    hist = dfh[(dfh.index.year >= 1960) & (dfh.index.year <= 2009)]
    hist = hist.groupby([lambda x: x.month]).mean()
    hist = hist.mean(axis=1)
    
    fig, axs = plt.subplots(1,4, figsize=(12,2.5))
    axs = axs.ravel()
    for i, per in enumerate(periods):
        ax = axs[i]
        for j, sce in enumerate(scenarios):
            try:
                dfb = df.filter(regex=sce)
                dfb = dfb[(dfb.index.year >= per[0]) & (dfb.index.year <= per[1])]
                dfb = dfb.groupby([lambda x: x.month]).mean()
                dfb = dfb.mean(axis=1)

                ano = ( (dfb - hist) / hist.mean() ) * 100
                
                if sce == 'RCP2.6':
                    space=-0.1
                if sce == 'RCP8.5':
                    space=+0.1
                    
                ax.bar(ano.index+(space), ano.values, width=0.2, align='center',
                       color=color_dict[sce], edgecolor='k', lw=0.1, label=sce, alpha=1)
                ax.axhline(y=0, linewidth=0.2, color='k')
            
                x1 = [1,2,3,4,5,6,7,8,9,10,11,12]
                squad = ['J','F','M','A','M','J','J','A','S','O','N','D']
                ax.set_xticks(x1)
                ax.set_xticklabels(squad, minor=False, rotation='horizontal')
                plt.xticks(rotation='horizontal')
                ax.set_xlim(0.5,12.5)
                ax.set_ylim(-50, +50)
                import matplotlib.ticker as ticker
                minorXlocator = ticker.MultipleLocator(0.5)
                ax.xaxis.set_minor_locator(minorXlocator)
                ax.grid(True, which='minor')
                ax.set_title(str(per[0])+'-'+str(per[1]))                
                ax.set_xlabel('Months')
                if i == 0:
                    ax.set_ylabel(var + ' [%]' + '\n' + '1960-2010')
                
            except:
                pass
    plt.tight_layout()
    fig.savefig('D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/surfex_plot/fig/ANO_FREQ/'
                +'ANO_'+'_'+var+'_'+time_step+'_'+'.png', dpi=300, bbox_inches='tight')

#%% NOTES

# globals()[station] = pd.DataFrame()
# recap = globals()[station]
# ax.yaxis.set_major_formatter(ScalarFormatter())
# (ax1,ax2,ax3),(ax4,ax5,ax6),(ax7,ax8,ax9) = axs1
# axs = axs.ravel()
# yerr=yerr.T.to_numpy()
# xerr=xerr.T.to_numpy()   
