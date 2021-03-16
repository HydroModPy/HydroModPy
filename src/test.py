import os
import sys
import numpy as np
import climatic as c
import modflow as m
import watershed as w
import extract as e
import calibration as cal

### Alexandre
#%%
# climatic =  c.surfex('C:/Users/alexa/Documents/GitHub/surfex_extract/OUT/data.h5',resample='M')
# m.modflow_model(dem_path='C:/Users/alexa/Documents/GitHub/HydroModPy/tmp/watershed_buff.tif', climatic=climatic.period_data, thick=50,  
# 		hyd_cond=0.0864, porosity=0.01)

### Ronan
#%%
w.extract_watershed(dem_path="D:/GITHUB/HydroModPy/data/watershed/bdalti75m_bzh.tif", 
                    outlet=np.loadtxt("D:/GITHUB/HydroModPy/data/watershed/outlet.txt"), 
                    snap_dist=500, buff_dist=1000)

#%%
N = 'gael'
S = 'S'
L = 1
T = 200
M = 0.025
K = 1e-6*(3600*24*30)
P = 0.01

m.modflow_model(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\' + 'watershed_buff_fill.tif',
                watershed=N, model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\",
                model_name=S+'_'+N+'_'+str(L)+'_'+str(T)+'_'+str(M)+'_'+str(K)+'_'+str(P),
                lay_number=L, thick=T, climatic=[M], hyd_cond=K, porosity=P)
    
#%%
e.extract_modflow(dem_path=os.path.dirname(os.getcwd()) + '\\tmp\\' + 'watershed_buff_fill.tif',
                  watershed='gael',
                  model_name=S+'_'+N+'_'+str(L)+'_'+str(T)+'_'+str(M)+'_'+str(K)+'_'+str(P),
                  model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\")

#%%
cal.extract_observed(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                     watershed='gael', type_obs='streams',
                     tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')

cal.generate_distances(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                       watershed='gael', sim_id=0, type_obs='streams',
                       tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')

#%%



