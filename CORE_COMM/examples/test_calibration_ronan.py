# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

# Modules
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
    # out_path = "D:/Users/abherve/HYDROMODPY"
    out_path = "D:/Users/abherve/RESULTS/rejets_metropole"
    analy_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/rejets_metropole"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = True
# watershed_name = 'Canut'
watershed_name = 'Out'
# library_path = df + '/watershed' + '/watershed_library.csv'
library_path = analy_path + '/outlets_basins.txt'

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
"""
df_auto, df_manual = BV.generate_subbasins(file_name='rejets_coord.txt',
                                           fonction_column='fonction',
                                           type_data='rejet',
                                           code_column='name', label_column='name',
                                           x_column='x_outlet', y_column='y_outlet',
                                           start_column=0, end_column=0,
                                           snap_dist=200)
"""
#%% DICHOTOMY CALIBRATION
"""
BV.calib_dichotomy(ident=None, calib=True, climatic=pd.Series(rech.mean()), lay_number=1, thick=50, bottom=None, thick_exp=1., 
                   first=1, last=10000, gap=10, porosity=0.01, sea_level=None, cond_decay=0.)
"""
#%% EXTRPOLATION CALIBRATION

dic = pd.read_csv(simulations_folder+'_dichotomy.csv', sep=';')

# Fixed
K = dic.iloc[-1]['K']
e = 50
time_step = 'monthly'

# Extrapolation
porosities = np.linspace(0.001, 0.05, 5).round(3)
# porosities = [0.001]

for i, porosity in enumerate(porosities):
    
    step = 'ext_disch'
    first = 1972
    last = 1989
    rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
    run = runof[(runof.index.year >= first) & (runof.index.year <= last)]
    print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
    ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
    # BV.run_modflow(ident=ident, calib=True,
    #                 climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
    #                 hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
    BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=True, 
                        first=first, last=last, time_step='monthly')
    obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_discharge_chronic()
    
    fig, ax = plt.subplots(1,1, figsize=(5,3))
    ax.plot(rch*1000, color='dodgerblue')
    ax.plot(obs_data['disch_norm']*1000, color='k')
    ax.plot(sim_data['outflow_drain']*1000, color='darkorange')
    ax.plot(sim_data['outflow_drain']*1000+run*1000, color='red')
    ax.set_yscale('log')
    ax.set_ylim(0.1, None)
    ax.set_title(mask_name+'\n'+ident)
    ax.grid(True)
        
    #################

    step = 'ext_satur'
    first = 2014
    last = 2019
    rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
    run = runof[(runof.index.year >= first) & (runof.index.year <= last)]
    print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
    ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
    # BV.run_modflow(ident=ident, calib=True,
    #                 climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
    #                 hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
    BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=True, 
                        first=first, last=last, time_step='monthly')
    obs_data, sim_data, df_stats, mask_name = BV.chronics.compar_saturation_chronic()
    
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