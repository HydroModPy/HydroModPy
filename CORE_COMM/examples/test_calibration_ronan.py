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
watershed_name = 'Canut1'
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

#%% CLIMATIC ANALYSIS

variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
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

periods = [[1961,2009],
           [2021,2069]]

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

#%%

variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
variables = ['REC']
scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']
simulations = ['REA','IPS1']

colors = {'historic':'k',
          'RCP2.6':'forestgreen',
          'RCP4.5':'dodgerblue',
          'RCP6.0':'darkorange',
          'RCP8.5':'darkred'}

# for var in variables:

clim_path = stable_folder+'climatic/'

# periods = [[1961,2009],
#            [2021,2069]]

periods = [[1961,2009]]

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
                        
                        mens = raw.resample('M').sum()
                        qmna = mens.groupby(mens.index.year).min().round(1)
                        qmna = qmna.to_frame(['MEAN'])
                        qmna_sort = qmna.sort_values()
                        freq = qmna_sort.groupby(['MEAN']).size().reset_index(name='counts') 
                        freq['frequency'] = freq.counts/freq.counts.sum() #freq
                        freq['cumulative_frequency'] = freq['frequency'].cumsum() #freq cumulated
                        freq['retour'] = 1/freq['cumulative_frequency']
                        freq['target'] = 5
                        Mean = raw.outflow_drain.mean()
                        Min = raw.outflow_drain.min()
                        Q10 = raw.outflow_drain.quantile(0.10)
                        Q50 = raw.outflow_drain.quantile(0.5)
                        Q90 = raw.outflow_drain.quantile(0.90)
                        Max = raw.outflow_drain.max()
                        
                    
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
        
#%% TEST CLIMATE

sim = 'REA'
var = 'TAS'
sce = 'historic'
x = pd.read_hdf(clim_path + sim +'.h5',var+'/'+sce)
# x = x[(x.index.year >= per[0]) & (x.index.year <= per[1])]  
       
#%% GENERATE SUBBASINS
"""
df_auto, df_manual = BV.generate_subbasins(file_name='station_x.txt',
                                           fonction_column='fonction',
                                           type_data='intermittent',
                                           code_column='name', label_column='name',
                                           x_column='x_outlet', y_column='y_outlet',
                                           start_column=0, end_column=0,
                                           snap_dist=200)
"""
#%% DICHOTOMY CALIBRATION
"""
BV.calib_dichotomy(ident=None, calib=True, type_river='streams',
                   climatic=pd.Series(rech.mean()), lay_number=1, thick=50, bottom=None, thick_exp=1., 
                   first=1, last=10000, gap=10, porosity=0.01, sea_level=None, cond_decay=0.)
"""
#%% EXTRPOLATION CALIBRATION
"""
type_river='streams'
dic = pd.read_csv(simulations_folder+'_dichotomy_'+type_river+'.csv', sep=';')

# Fixed
K = dic.iloc[-1]['K']
# K = 20
e = 50
time_step = 'monthly'

# Extrapolation
porosities = np.linspace(0.001, 0.05, 5).round(3)
porosities = [0.001]

periods = range(1990, 2000+1)
periods = [[1990,1994],
           [1995,1999],
           [2005,2009],
           [2010,2014],
           [2015,2019]]

for period in periods:
    first = period[0]
    last = period[1]
    
    for i, porosity in enumerate(porosities):
        
        step = 'ext_disch'

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
        
        obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_saturation_chronic()
"""        
        #################
    """
        step = 'ext_satur'
        first = 2015
        last = 2019
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
