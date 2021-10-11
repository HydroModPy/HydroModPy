# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé, modified Clement Roques
"""

# Modules
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from osgeo import gdal
import rasterio as rio
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.set_verbose_mode(False)

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
user = "Clement"

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
elif user=="Clement":
    root_path= "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_data/"
    out_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/"
    #analy_path = "D:/Google Drive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_process/"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = False
# watershed_name = 'Canut'
watershed_name = 'Lasset'
library_path = df + '/watershed' + '/watershed_library.csv'
#library_path = analy_path + '/outlets_basins.txt'

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

dem_path = root_path + "/DEM/" + "BDALTI_25M_09_MERGED.tif"
#dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

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


#%% RUN MODFLOW
"""
rch = 1e-3
e=25;
K=rch*200;
porosity = 0.1
ident = str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch,3))

BV.run_modflow(ident=ident,
               climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
               hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
"""

#%% RUN MODFLOW
#Merger les points shp
pt_streams = stable_folder + 'hydrology/' + 'stream_digit_pt.shp'
pt_zh = stable_folder + 'hydrology/' + 'zh_digit_pt.shp'
merge_path = pt_streams+';'+pt_zh
pt_zhstreams = stable_folder + 'hydrology/' + 'zhstreams_pt.shp'
wbt.merge_vectors(merge_path, pt_zhstreams)

#Merger les tifs
tif_streams = stable_folder + 'hydrology/' + 'stream_digit.tif'
tif_zh = stable_folder + 'hydrology/' + 'zh_digit.tif'
merge_path = tif_streams+';'+tif_zh
tif_zhstreams = stable_folder + 'hydrology/' + 'zhstreams.tif'
wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")


#%% EXTRACT RECHARGE FROM SURFEX
rech_path = stable_folder+'climatic/'+'REA.h5'
rech = pd.read_hdf(rech_path,'REC/'+'historic')
first = 2000
last = 2019
rech = rech[(rech.index.year >= first) & (rech.index.year <= last)]
rech = rech.MEAN
rech = rech.resample('D').sum()
rech = rech / 1000 #mm to m

fig1 = plt.figure(1)
ax1 = fig1.add_subplot(1,1,1)
ax1.set_xlabel("time, [-]")
ax1.set_ylabel("recharge [m/d]")
#ax.set_xscale("log")
ax1.plot(rech)
fig1.show()


#%% DICHOTOMY CALIBRATION

e = 50
porosities = np.linspace(1, 1, 1).round(2)

#types_river = ['streams','zhstreams']
types_river = ['zhstreams']
for type_river in types_river:
    BV.calib_dichotomy(ident=None, calib=True, type_river=type_river, climatic=rech.mean(), 
                       lay_number=1, thick=e, bottom=None, thick_exp=1., 
                       first=1, last=500, gap=1, porosity=0.01, 
                       sea_level=None, cond_decay=0.)


#%% Transient simulations

dic = pd.read_csv(simulations_folder+'_dichotomy.csv', sep=';')

# Fixed
K = dic.iloc[-1]['K']
#K = K #
time_step = 'daily'

for i, porosity in enumerate(porosities):
    
    step = '_transient_daily'
    first = 2000
    last = 2019
    rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
    print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
    ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
    BV.run_modflow(ident=ident,
                    climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
                    hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
    BV.chronics_modflow(ident=ident, first=first, last=last, time_step=time_step)
    
    # step = 'ext_satur'
    # first = 2014
    # last = 2019
    # rch = rech[(rech.index.year >= first) & (rech.index.year <= last)]
    # print('==> Simulation ' + step + ' ' + str(i+1) + ' / ' + str(len(porosities)))
    # ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rch.mean(),3))
    # BV.run_modflow(ident=ident,
    #                 climatic=rch, lay_number=1, thick=e, bottom=None, thick_exp=1., 
    #                 hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
    # BV.chronics_modflow(ident=ident, first=first, last=last, time_step='monthly')
    
#Questions for Ronan and Alexandre: 
    #how transient simulation are initiated?



#%% GENERATE CHRONICS



#%% CALIBRATED MODEL



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