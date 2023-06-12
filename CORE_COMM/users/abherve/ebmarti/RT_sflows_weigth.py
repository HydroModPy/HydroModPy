# -*- coding: utf-8 -*-
"""
Created on Tue Jul  5 11:53:39 2022

@author: emarti
"""


import os
import numpy as np
import pandas as pd
import rioxarray as rxr
import flopy
import flopy.modflow as fpm
import flopy.utils.binaryfile as bf
import flopy.utils.postprocessing as pp
import matplotlib.pyplot as plt


#%%

study_cuenca = 'Tarapaca'
dempath = 'D:/emarti/Tarapaca/out/' + study_cuenca + '/results_stable/geographic/watershed_dem.tif'
basin_dem = rxr.open_rasterio(dempath, masked=False).squeeze()


#%%Define model parameters

defKR = np.concatenate((np.logspace(-3,-1,3), np.linspace(0.2,1,5)), axis=None)

#defKR = [1.0]

k= 1e-7 * 86400 # m/s en m/j
#BV.hydrodynamic.update_hyd_cond(k) 
#recharge = 1e-7  #m/j
#BV.forcing.update_recharge(recharge, 'steady')
#defKR = np.logspace(-1,2,4)
recharge = 1e-4 
thickness = 500
deflaynb = [3]
defbc = [1825]
elapsed = []
box=True
#bottom=-1000


#%%

moments=[]

for lay_nb in deflaynb:
    for bc_left in defbc:
        for KR in defKR:   
            KR_name = round(KR,3)
            #recharge = round(k / KR_name, 7)
            save_path_WRT = 'D:/emarti/Tarapaca/out/figures/'+study_cuenca+'/residence_times/layers_nb_' + str(lay_nb) +'/bchead_'+str(bc_left)+'/'
            modeldir = 'D:/emarti/Tarapaca/out/Tarapaca/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_thickness_' + str(thickness) +'/'
            print('Performing simulation for model : KR = ' +str(KR_name)+' layer_nb='+str(lay_nb)+' bc='+str(bc_left))
            namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_thickness_' + str(thickness)
            
            data = pd.read_csv(modeldir + 'surface_flows.txt', sep=' |\t', engine='python')
            data_2D = np.reshape(data['flow'].to_numpy(), (data['rowI'].max()+1,data['colJ'].max()+1))
            ncol = data['colJ'].max()+1
            nrow = data['rowI'].max()+1
            data_head = pd.read_csv(modeldir + 'heads.txt', sep=' |\t', engine='python')
            data_head_2D = np.reshape(data_head['head_height'].to_numpy(), (data['rowI'].max()+1,data['colJ'].max()+1))
            #data_2D_plot = data_2D[0:-1,1:-1] #delete borders with no recharge for representation
            m = np.ma.masked_where(basin_dem.data < 0, basin_dem.data)
            data_2D_basin = np.ma.masked_where(np.ma.getmask(m), data_2D)
            #data_2D_basin_masked = data_2D_basin[data_2D_basin.mask == False]
            res_time = np.zeros(np.shape(basin_dem))
            endobj = flopy.utils.EndpointFile(modeldir + namepath +'.mpend')
            e = endobj.get_alldata()
            for cell in range(len(e)):
                res_time[e[cell].i0,e[cell].j0] = e[cell].time # where infiltrated
                #res_time[e[cell].i,e[cell].j] = e[cell].time # where outputed
            
            
            res_time = np.ma.masked_where(np.ma.getmask(m), res_time).compressed()
            rch = data_2D_basin.compressed()
            rch = rch[res_time > 0]
            res_time = res_time[res_time > 0]/365
            rchSum = np.sum(rch)
            rchPerc = rch / rchSum
            
            
            #tau = porosity*np.mean(data_head_2D)/np.mean(rch)
            mom1=np.average(res_time,weights=rchPerc)
            mom2=np.average((res_time - mom1)**2, weights=rchPerc)
            sigma=np.sqrt(mom2)
            mom3=np.average(((res_time - mom1)/sigma)**3,weights=rchPerc)
            mom4=np.average(((res_time - mom1)/sigma)**4,weights=rchPerc)
            #defining bin number based on dataset
            binwidth = (max(res_time) - min(res_time))/np.sqrt(len(res_time))
            bins = round((max(res_time) - min(res_time))/binwidth)
            y, binEdges = np.histogram(res_time, bins=bins, density=True, weights=rchPerc)
            x =  ((binEdges[1:] + binEdges[:-1])/2)
            x1 = np.linspace(0,max(res_time), 200)
            #Definition of analytical solution vectors
            pt = np.zeros(len(x1))
            for i in range(len(x1)):
                pt[i] = 1/mom1*np.exp(-x1[i]/mom1) #Solution for uniform recharge along x
            #break
            #x/mean and y*mean for normalization for both numerical and exponential solution
            fig, ax1 = plt.subplots(figsize=(16,9))
            p = ax1.scatter(x/mom1,y*mom1)
            ax1.plot(x1/mom1, pt*mom1, c='orange', label='analytical solution')
            plt.xlabel('t/tau')
            plt.ylabel('p(t)')
            plt.title('Normalized Weigthed Residence Times KR= %1.3f' %KR_name)
            #plt.yscale('log')
            #plt.xscale('log')
            file = 'WRT_expo_KR_'+str(KR_name)+'_rch_'+str(round(recharge,5))+'_thickness.png'
            moments.append([mom1, mom2, sigma, mom3, mom4, KR_name])

            if not os.path.isdir(save_path_WRT):
                os.makedirs(save_path_WRT)
            fig.savefig(os.path.join(save_path_WRT, file))
            #plt.show()
            #break
        #break
    #break


df = pd.DataFrame(moments,columns=['mean','variance','std', 'skewness', 'kurtosis', 'KR'])

#%%


df.to_csv('RT_moments_Tarapaca_thickness.csv')
#%%


fig, ax1 = plt.subplots(figsize=(16,9))
p = ax1.plot(defKR,df['mean'])
p2 = ax1.scatter(defKR,df['mean'])
plt.xlabel('K/R')
plt.ylabel('Distribution mean values')
plt.xscale('log')
plt.yscale('log')

#%%


fig, ax1 = plt.subplots(figsize=(16,9))
p = ax1.plot(defKR,df['kurtosis'])
p2 = ax1.scatter(defKR,df['kurtosis'])
plt.xlabel('K/R')
plt.ylabel('Distribution kurtosis values')
plt.xscale('log')
#plt.yscale('log')