import os
import numpy as np
import climatic as c
import modflow as m
import watershed as w
import extract as e
import calibration as cal
import pandas as pd
from glob import glob
import shutil
import matplotlib.pyplot as plt

#%%
climatic =  c.surfex("D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+'data\\'+'climate.h5',
                     sim='ACC1', var='REC', sce='historic', resample='M')

#%%
w.extract_watershed(dem_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+'data\\'+"bdalti75m_bzh.tif", 
                    outlet=np.loadtxt("D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+'data\\'+"outlets.tif"), 
                    snap_dist=500, buff_dist=1000)

#%%

def dichotomy(krval, compt):
    
    krval = krval
    hydcond = krval * recharge
    
    simulation = time+'_'+\
                 basin+'_'+\
                 str(lay)+'_'+\
                 str(thick)+'_'+\
                 str(round(krval,3))+'_'+\
                 str(round(recharge,3))+'_'+\
                 str(round(hydcond,3))+'_'+\
                 str(porosity)
                 
    m.modflow_model(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\' + 'watershed_buff_fill.tif',
                    model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\",
                    watershed=basin, model_name=simulation,
                    lay_number=lay, thick=thick, climatic=[recharge], hyd_cond=hydcond, porosity=porosity)
        
    e.extract_modflow(dem_path=os.path.dirname(os.getcwd()) + '\\tmp\\' + 'watershed_buff_fill.tif',
                      watershed='gael',
                      model_name=simulation,
                      model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\")

    ext = cal.extract_observed(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                         watershed='gael', type_obs='streams',
                         tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')
    
    gener = cal.generate_distances(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                           watershed='gael', sim_id=simulation,  type_time='s', type_obs='streams',
                           tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')
    
    store = cal.store_dataframe(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                           watershed='gael', sim_id=simulation, type_time='s',
                           tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')
    
    df.loc[compt,'Kr'] = round(krval, 4)
    df.loc[compt,'K'] = round(hydcond/30/24/3600, 4)
    df.loc[compt,'Sflow'] = round(store.sim_to_obs_mean, 4)
    df.loc[compt,'Oflow'] = round(store.obs_to_sim_mean, 4)
    df.loc[compt,'Qflow'] = round(store.outflow,4)
    
    # Condition
    cond = round(store.sim_to_obs_mean / store.obs_to_sim_mean, 2)
    print('*** Simulation '+str(compt)+' ***')
    print('Parameters : '+simulation)
    print('KR = '+str(round(krval, 2)))
    print('Condition = '+str(cond))
    
    return cond

#%%

time = 's'
basin = 'gael'
lay = 1
thick = 100
porosity = 0.01
recharge = climatic.period_data.mean() * 30 / 1000

debut = 1
fin = 5000
ecart = fin - debut

interv = 10

df = pd.DataFrame()

todel = '_'+basin+'_'+'1'+'_'+'100'
sim_list = glob("D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+basin+'\\'+time+todel+'*')
for folder in sim_list:
    shutil.rmtree(folder)

compt = 0
while ecart > interv:
    mid = (debut+fin) / 2
    cond = dichotomy(mid, compt)
    if cond > 1:
        debut = mid
    else:
        fin = mid
    ecart = fin - debut
    print('Ecart = '+str(round(ecart,2)))
    compt += 1
    
df.to_csv("D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+basin+'\\'+basin+'_calibration.csv', sep='\t', index=True)

plt.scatter(df.Kr, df.Oflow)
plt.scatter(df.Kr, df.Sflow)

