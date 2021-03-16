import os
import numpy as np
import climatic as c
import modflow as m
import watershed as w
import extract as e
import calibration as cal
import matplotlib.pyplot as plt

#%%
climatic =  c.surfex("D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\"+'data\\'+'climate.h5',
                     sim='ACC1', var='REC', sce='historic', resample='M')

#%%
w.extract_watershed(dem_path="D:/GITHUB/HydroModPy/data/watershed/bdalti75m_bzh.tif", 
                    outlet=np.loadtxt("D:/GITHUB/HydroModPy/data/watershed/outlet.txt"), 
                    snap_dist=500, buff_dist=1000)

#%%
time = 'S'
basin = 'gael'
lay = 1
thick = 100
porosity = 0.01
recharge = round(climatic.period_data.mean() * 30 / 1000, 3)
hydcond = round(1e-6*(3600*24*30), 3)
ratio = round(hydcond/recharge, 1)

simulation = time+'_'+basin+'_'+str(lay)+str(thick)+'_'+str(ratio)+'_'+str(recharge)+'_'+str(hydcond)+'_'+str(porosity)

m.modflow_model(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\' + 'watershed_buff_fill.tif',
                model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\",
                watershed=basin, model_name=simulation,
                lay_number=lay, thick=thick, climatic=recharge, hyd_cond=hydcond, porosity=porosity)
    
#%%
e.extract_modflow(dem_path=os.path.dirname(os.getcwd()) + '\\tmp\\' + 'watershed_buff_fill.tif',
                  watershed='gael',
                  model_name=simulation,
                  model_folder="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\")

#%%
cal.extract_observed(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                     watershed='gael', type_obs='streams',
                     tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')

x = cal.generate_distances(dir_path="D:/PHD/4_model/MFLOW3D/"+"\\github_calibration\\", 
                       watershed='gael', sim_id=0, type_obs='streams',
                       tmp_path=os.path.dirname(os.getcwd()) + '\\tmp\\')

#%%



