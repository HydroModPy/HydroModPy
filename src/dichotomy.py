'''Ronan'''


# Import libraries
import os
import pandas as pd
import numpy as np
import shutil
import matplotlib.pyplot as plt

# Import modules
from glob import glob
import climatic as clim
import modflow as mod
import watershed as wat
import extract as ext
import calibration as cal

# Import outlets of watersheds
outlets = pd.read_csv("D:/PHD/4_model/MFLOW3D/github_calibration/data/outlets.txt", sep='\t', header=None)

# If necessary import climate
climat = clim.surfex("D:/PHD/4_model/MFLOW3D/github_calibration/data/climate.h5",
					 sim='ACC1', var='REC', sce='historic', resample='M')
rch_mean = climat.period_data.mean() * 30 / 1000

#%%

# Loop for some sites
def delimit_site(target, idx, site):
    wat.extract_watershed(dem_path="D:/PHD/4_model/MFLOW3D/github_calibration/data/bdalti75m_bzh.tif",
    							  out_path="D:/PHD/4_model/MFLOW3D/github_calibration/",
    							  outlet=target,
    							  snap_dist=500, buff_dist=1000,
    							  tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
    							  save_dem=True)
    		
    cal.extract_observed(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
    							 watershed=site, type_obs='streams',
    							 tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')

# Launch models and calibration
def run_calibration(krval, compt):	
    
    hydcond = krval * recharge
    simulation = time+'_'+\
                 site+'_'+\
                 str(lay)+'_'+\
                 str(thick)+'_'+\
                 str(round(krval,3))+'_'+\
                 str(round(recharge,3))+'_'+\
                 str(round(hydcond,3))+'_'+\
                 str(porosity)
                 
    mod.modflow_model(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\'+'watershed_buff_fill.tif',
                      model_folder="D:/PHD/4_model/MFLOW3D/github_calibration/",
                      watershed=site, model_name=simulation,
                      lay_number=lay, thick=thick, climatic=[recharge], hyd_cond=hydcond, porosity=porosity)
        
    ext.extract_modflow(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\'+'watershed_buff_fill.tif',
                      watershed=site,
                      model_name=simulation,
                      model_folder="D:/PHD/4_model/MFLOW3D/github_calibration/")
    
    cal.generate_distances(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
                           watershed=site, sim_id=simulation,  type_time='s', type_obs='streams',
                           tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')
    
    store = cal.store_dataframe(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
                                watershed=site, sim_id=simulation, type_time='s',
                                tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')   
    
    df.loc[compt,'Kr'] = round(krval, 4)
    df.loc[compt,'K'] = round(hydcond/30/24/3600, 4)
    df.loc[compt,'Sflow'] = round(store.sim_to_obs_mean, 4)
    df.loc[compt,'Oflow'] = round(store.obs_to_sim_mean, 4)
    df.loc[compt,'Qflow'] = round(store.outflow,4)   
    
    condition = round(store.sim_to_obs_mean / store.obs_to_sim_mean, 2)
    
    print('==> Simulation : '+str(compt))
    print('    Parameters : '+simulation)
    print('    KR = '+str(round(krval, 2)))
    print('    Condition = '+str(condition))
    
    return condition

# Lauch dichotomy on K/R values
def dichotomy_loop(df, site, time, first, last, gap, lay, thick, recharge, porosity):

    difference = last - first
        
    compt = 0
    while difference > gap:
        half = (first + last) / 2
        condition = run_calibration(half, compt)
        if condition > 1:
            first = half
        else:
            last = half
        difference = last - first
        print('    Ecart = '+str(round(difference,2))+'\n')
        compt += 1
    
    save_name = site+'\\'+site+'_calibration.csv'
    df.to_csv("D:/PHD/4_model/MFLOW3D/github_calibration/"+save_name, sep='\t', index=True)
    
    # plt.scatter(df.Kr, df.Oflow)
    # plt.scatter(df.Kr, df.Sflow)

#%%

# Loop for each site modelized
for idx, serie in outlets.iterrows():
    
    # General parameters
    target = outlets.loc[[idx]]
    site = target[[0]].values[0][0]
    
    # Modflow parameters
    time = 's'
    lay = 1
    thick = 100
    recharge = 0.025
    porosity = 0.01
    
    # Dochotomy parameters
    first = 1
    last = 5000
    gap = 100
    
    # Generate site
    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
    delimit_site(target, idx, site)
    
    # Delete previous simulations
    sim_list = glob("D:/PHD/4_model/MFLOW3D/github_calibration/"+site+'\\'+'s*')
    if not sim_list:
        print('- Delete previous : '+'YES'+'\n')
    else:
        print('- Delete previous : '+'NO'+'\n')
    for folder in sim_list:
        shutil.rmtree(folder)
        
    # Run model and calibration with dichotomy
    df = pd.DataFrame()
    dichotomy_loop(df, site, time, first, last, gap, lay, thick, recharge, porosity)
    

