# -*- coding: utf-8 -*-
"""
Created on Wed Feb  1 10:22:03 2023

@author: Martin Le Mesnil
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
from scipy.ndimage import uniform_filter1d

site_name = 'Caen-la-Mer'

site_dict = {'Saint-Germain-sur-Ay' : 'SGA',
             'Agon-Coutainville' : 'AGC',
             'Barneville-Carteret' : 'BNV',
             'Baie-du-Cotentin' : 'BDC',
             'Caen-la-Mer' : 'CLM'}
site_code = site_dict[site_name]

#%% DRIAS recharge analysis

# list_sim = os.listdir(os.path.join('E:\PostDoc\Modélisation', site_code, 'Heterogeneous\simulation_results'))    
# list_rech_path = [os.path.join('E:\PostDoc\Modélisation', site_code, 'Heterogeneous\simulation_results', s, 'recharge.csv') for s in list_sim]

# C:\Users\Martin Le Mesnil\Travail\HydroModPy\output2\Caen-la-Mer\results_simulations\recharge_DRIAS\20202100_CNRALARCP26_07022023093708

list_sim = os.listdir(os.path.join(r'C:\Users\Martin Le Mesnil\Travail\HydroModPy\output2', site_name, r'results_simulations\recharge_DRIAS'))    
list_rech_path = [os.path.join(r'C:\Users\Martin Le Mesnil\Travail\HydroModPy\output2', site_name, r'results_simulations\recharge_DRIAS', s, 'recharge.csv') for s in list_sim]
rech_list = []
drias_list = []
for r in list_rech_path:
    rech = pd.read_csv(r, sep = ";")
    rech['Date'] = pd.to_datetime(rech['Date'])
    rech.iloc[:,1] = rech.iloc[:,1].apply(lambda x: x*1000) #m to mm
    rech[rech.columns[1]+'_smooth1'] = uniform_filter1d(rech.iloc[:,1], size=365*1)
    rech[rech.columns[1]+'_smooth5'] = uniform_filter1d(rech.iloc[:,1], size=365*5)
    rech[rech.columns[1]+'_smooth10'] = uniform_filter1d(rech.iloc[:,1], size=365*10)
    rech_list.append(rech)
    drias = rech.columns[1][4:11]
    if not drias in drias_list:
        drias_list.append(drias)




#plot recharge by climatic model (2 trajectories)
for cm in drias_list:
    plt.figure(dpi=300)
    for rech in rech_list:
        if cm in rech.columns[1]:
            plt.plot(rech['Date'], rech.iloc[:,4], label = rech.columns[1][4:12]+rech.columns[1][15:])
    plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    plt.ylabel('Recharge (mm/day)')
    plt.show()

#plot recharge all climatic models (RCP8.5)
plt.figure(dpi=300)
for rech in rech_list:
    if rech.columns[1][15:] == '8.5':
        plt.plot(rech['Date'], rech.iloc[:,4], label = rech.columns[1][4:12])
plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
plt.ylabel('Recharge (mm/day)')
plt.show()

# plt.figure(dpi=300)
# for rech in rech_list:
#     plt.plot(rech['Date'], rech.iloc[:,2], label = rech.columns[1][4:12]+rech.columns[1][15:])
# plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
# plt.ylabel('Recharge (mm/day)')
# # plt.title(site_name)
# # plt.xticks(rotation=45)
# # plt.savefig('C:/Users/Martin Le Mesnil/Desktop/PZ_SGA.png')
# # plt.text(0.1,0.9,sim_name.split(sep='_')[1])
# plt.show()
    
#%% Watertable depth raster analysis

homo_rast_dir = ''
list_sim_rast = os.listdir(os.path.join('E:\PostDoc\Modélisation', site_code, 'Heterogeneous','rasters_wtd'))    
list_rast_dir = [os.path.join('E:\PostDoc\Modélisation', site_code, 'Heterogeneous','rasters_wtd', s) for s in list_sim_rast]
list_rast_types = os.listdir(list_rast_dir[0])


rast_path_dict = {}
for sim in list_rast_dir:
    # print(sim)
    list_rast_sim = os.listdir(sim)
    print(list_rast_sim)
    # rast_path_dict[sim[9:20]] = 


