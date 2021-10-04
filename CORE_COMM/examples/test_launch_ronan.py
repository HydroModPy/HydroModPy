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
    out_path = "D:/Users/abherve/RESULTS/rejets_metropole"
    analy_path = "D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/rejets_metropole"
else:
    print("Define a well-validated name of user")

# Inputs initialize
watershed_name = 'Forecast'
library_path = analy_path + '/outlets_basins.txt'
# out_path = "D:/Users/abherve/HYDROMODPY"
# library_path = df + '/watershed' + '/watershed_library.csv'

# Data paths
dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"
surfex_path =  root_path + 'SURFEX'
geology_path = root_path + 'GEOLOGY'
hydrology_path = root_path + 'HYDROLOGY'
modflow_path = root_path + 'MODFLOW'
piezometry_path = None
oceanic_path = None

# Output paths
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% GENERATE BV

load = True
subbasin = False

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

if subbasin == True:
    df_auto, df_manual = BV.generate_subbasins(file_name='rejets_coord.txt',
                                               fonction_column='fonction',
                                               type_data='rejet',
                                               code_column='name', label_column='name',
                                               x_column='x_outlet', y_column='y_outlet',
                                               start_column=0, end_column=0,
                                               snap_dist=200)

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
        rec = pd.read_hdf(h5_path,'REC/'+scenario)
        rec = rec[(rec.index.year >= first) & (rec.index.year <= last)]
        rec = rec.MEAN
        rec = rec.resample('M').sum()
        rec = rec / 1000
    except:
        rec = np.nan
    
    return tas, ppt, etp, run, rec
    
#%% DICHOTOMY CALIBRATION

tas, ppt, etp, run, rec = extract_surfex_variables(stable_folder + 'climatic/', 
                                                   'REA', 'historic', 1960, 2019)
rec = rec.mean()

BV.calib_dichotomy(ident=None, calib=True, type_river='streams', climatic=pd.Series(rec.mean()), 
                   lay_number=1, thick=50, bottom=None, thick_exp=1., 
                   first=1, last=10000, gap=10, porosity=0.01, sea_level=None, cond_decay=0.)

#%%  LAUNCH MODELS

#################### PARAMETERS ####################

dic = pd.read_csv(simulations_folder+'_dichotomy_streams.csv', sep=';')
K = dic.iloc[-1]['K']
e = 50
porosity = 0.001
time_step = 'monthly'

#%%

#################### PAST ####################

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
print('==> Simulation ' + step)
ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rec.mean(),3))

# Model modflow
BV.run_modflow(ident=ident, calib=False, climatic=rec, 
               lay_number=1, thick=e, bottom=None, thick_exp=1., 
               hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)

# Chronics modflow
BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=False, 
                    first=first, last=last, time_step='monthly')

#%%

#################### FUTURE ####################

models = ['IPS1', 'CAN1', 'ACC1']
scenarios = ['RCP4.5', 'RCP8.5']
first = 2020
last = 2099

for model in models:
    for scenario in scenarios:
        
        if (model!='IPS1') or (scenario!='RCP4.5'):
            print(model+'_'+scenario)
        
            # Recharge modflow
            tas, ppt, etp, run, rec = extract_surfex_variables(stable_folder + 'climatic/', 
                                                                model, scenario, first, last)
            df = pd.DataFrame()
            df.index = rec.index
            df['tas'] = tas
            df['ppt'] = ppt
            df['etp'] = etp
            df['run'] = run
            df['rec'] = rec
            
            # Name modflow
            step = model+'_'+scenario
            df.to_csv(stable_folder + 'climatic/' + step + '.csv', sep=';')
            print('==> Simulation ' + step)
            ident = str(step)+'-'+str(round(porosity,3))+'-'+str(round(K,3))+'-'+str(round(e,3))+'-'+str(round(rec.mean(),3))
            
            # Model modflow
            BV.run_modflow(ident=ident, calib=False, climatic=rec, 
                           lay_number=1, thick=e, bottom=None, thick_exp=1., 
                           hyd_cond=K, porosity=porosity, sea_level=None, cond_decay=0.)
            
            # Chronics modflow
            BV.chronics_modflow(ident=ident, mask=True, outlet_type=None, calib_only=False, 
                                first=first, last=last, time_step='monthly')
        
#%% 
