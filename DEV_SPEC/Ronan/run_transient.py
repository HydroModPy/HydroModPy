# -*- coding: utf-8 -*-


# Librairies
import os
import pandas as pd
import numpy as np
from glob import glob
import threading
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
import shutil

# Modules
import sys
sys.path.insert(0, 'D:/GITHUB/HydroModPy/CORE_COMM/src/')
import climatic as clim
import dichotomy as dic
import watershed as wat
import scanning as sca
import modflow as mod

# Plots
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties

#%% Recharge

path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/congress_events/egu/analysis_model/"
outlets = pd.read_csv(path+"_data/outlets_test.txt", sep='\t', header=None, engine='python')
                
#%% Fct

def settings(k, n, e, r, outlet):
        
        type_time = 'transient'
        site = outlet.iloc[:,1].values[0]
        lay_number = 1
        thick = e
        climatic = r / 1000 # m/m
        hyd_cond = k * 3600 * 24 * 30 # m/m
        krval = hyd_cond / climatic.mean()
        porosity = n / 100
        dem_path = path + site + '/gis/' + 'watershed_buff_dem.tif'
                
        sim_id = type_time+'_'+\
                    site+'_'+\
                    str(lay_number)+'_'+\
                    str(thick)+'_'+\
                    str(round(krval, 3))+'_'+\
                    str(round(climatic.mean(), 3))+'_'+\
                    str(round(hyd_cond,3))+'_'+\
                    str(round(porosity,3))
                             
        mod.modflow_model(dem_path, 
                          watershed=site, 
                          climatic=climatic, 
                          lay_number=lay_number, 
                          thick=thick, 
                          bottom=None, 
                          hyd_cond=hyd_cond, 
                          porosity=porosity,
                          coastal_aquifer=False,
                          time_step='monthly',
                          model_name=sim_id, 
                          model_folder=path)
    
#%% Run

first = 1990
last = 1991

scenarios_list = ['historic','RCP8.5']
variables_list = ['TAS','PPT','ETP','RUN','REC']

recharge = clim.surfex('D:/LOCAL/PHD/3_analysis/surfex_plot/data/loc-ebr_mod-ips1_var-all_sce-all.h5', 
                   sim='IPS1', var='REC', sce='historic', resample='M').data
recharge = recharge.resample('M').sum()
recharge = recharge[(recharge.index.year >= first) & (recharge.index.year <= last)]


hyd_cond_list = np.geomspace(1e-6,1e-6,1) # m/s
porosity_list = np.linspace(1,1,1) # %
thick_list = np.linspace(50,50,1) # m

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet.iloc[:,1].values[0]
    
    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
    
    wat.extract_watershed(dem_path=path+"_data/Bretagne.tif",
                          outlet=outlet,
                          snap_dist=outlet[4].values[0], buff_dist=1000, save_gis=True,
                          tmp_path=path+'_tmp/',
                          out_path=path)
        
    p = os.getcwd()
    fr = 'D:/GITHUB/HydroModPy/CORE_COMM/data/surfex/' + "maille_meteo_fr_pr93.shp"
    watershed = path+site+'/gis/' + "buff.shp"
    surfex = path+site+'/gis/' + "watershed_surfex.shp"
    wbt.intersect(fr,watershed,surfex)
    shp = gpd.read_file(surfex)
    numid = list(shp.num_id.values)
    os.chdir(p)
    
    rech = recharge.loc[:,numid]
    rech = rech.mean(axis=1)
    rech = rech[rech.index.notnull()]
    
    allr = glob(path + site + '/' + 'transient*')
    for f in allr:
        shutil.rmtree(f)
        
    # allm = glob("D:/LOCAL/MODEL/" + site + '/' + 'transient*')
    # for f in allm:
    #     shutil.rmtree(f)

    for var1 in range (0, len(hyd_cond_list)): # permit to fix k
        for var2 in range (0, len(porosity_list)): # permit to fix porosity
            for var3 in range (0, len(thick_list)): # permit to fix porosity
            
                    print('k = '+str(hyd_cond_list[var1])+' - '+
                          'n = '+str(porosity_list[var2])+' - '+
                          'e = '+str(thick_list[var3]))
                    
                    settings(hyd_cond_list[var1], porosity_list[var2], thick_list[var3], rech, outlet)

#%% Parallel

# # # For each combination : parallel
# compt=0
# coeur=35
# for var1 in range (0, len(hyd_cond_list)): # permit to fix k
#     for var2 in range (0, len(porosity_list)): # permit to fix porosity
#         compt += 1
#         t = threading.Thread(target=settings, args=(hyd_cond_list[var1], porosity_list[var2]))
#         t.start()
#         if int(compt / coeur) == compt / coeur:  # Si compt est multiple de 3
#             t.join()  # alors on attend que les modèles soient terminées pour recommencer
#             print(compt)
# t.join() # On attend que les modèles soient finis pour terminer le calcul

#%% NOTES
