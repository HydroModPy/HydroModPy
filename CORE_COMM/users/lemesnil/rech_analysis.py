# -*- coding: utf-8 -*-
"""
Created on Thu Mar 23 09:09:43 2023

@author: Martin Le Mesnil
"""

import pandas as pd
import matplotlib.pyplot as plt

#%% RECHARGE
rech_MF = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\rech_CLM_2000_2019_MF.csv', sep=';', index_col='Date')
rech_REA = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\rech_CLM_2000_2019_REA.csv', index_col='date')
rech_DRIAS = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\rech_CLM_2019_2050_DRIAS.csv', index_col=0)

rech_MF.index = pd.to_datetime(rech_MF.index, dayfirst=True)
rech_REA.index = pd.to_datetime(rech_REA.index, dayfirst=True)
rech_DRIAS.index = pd.to_datetime(rech_DRIAS.index)

for k in rech_DRIAS.keys():
    rech_DRIAS[k] = rech_DRIAS[k].apply(lambda x: x*1000)

plt.plot(rech_MF['Recharge'])
plt.plot(rech_REA['MEAN'])
plt.plot(rech_DRIAS['REC_MPI-CCL_RCP8.5'])
plt.ylabel('Recharge (mm/d)')
plt.legend(['MeteoFrance','Surfex','DRIAS'])
plt.show()

sum_rech_MF = rech_MF.sum()
sum_rech_REA = rech_REA.sum()
sum_rech_DRIAS = rech_DRIAS.sum()

yr_rech_MF = sum_rech_MF/20
yr_rech_REA = sum_rech_REA/20
yr_rech_DRIAS = sum_rech_DRIAS/32

std_rech_MF = rech_MF.std()
std_rech_REA = rech_REA.std()
std_rech_DRIAS = rech_DRIAS.std()

#%% Recharge Caen modified

clim_MF_Caen = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\rech_CLM_2022.csv', sep=';', index_col='Date')

sum_rech_MFC = clim_MF_Caen['Recharge'].sum()
rech_MFC =  clim_MF_Caen['Recharge']
rech_MFC.std()

#%% PRECIPITATION
# ppt_MF = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\ppt_CLM_2000_2019_MF.csv', sep=';', index_col='Date')
# ppt_REA = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\ppt_CLM_2000_2019_REA.csv', index_col='date')
# ppt_DRIAS = pd.read_csv(r'C:\Users\Martin Le Mesnil\Travail\data\estim_ET\CLM\recharge_analysis\ppt_CLM_2019_2050_DRIAS.csv', index_col=0)

# ppt_MF.index = pd.to_datetime(ppt_MF.index, dayfirst=True)
# ppt_REA.index = pd.to_datetime(ppt_REA.index, dayfirst=True)
# ppt_DRIAS.index = pd.to_datetime(ppt_DRIAS.index)

# for k in ppt_DRIAS.keys():
#     ppt_DRIAS[k] = ppt_DRIAS[k].apply(lambda x: x*1000)


# plt.plot(ppt_MF['Recharge'])
# plt.plot(ppt_REA['MEAN'])
# plt.plot(ppt_DRIAS['REC_MPI-CCL_RCP8.5'])
# plt.ylabel('Recharge (mm/d)')
# plt.legend(['MeteoFrance','Surfex','DRIAS'])
# plt.show()

# sum_rech_MF = rech_MF.sum()
# sum_rech_REA = rech_REA.sum()
# sum_rech_DRIAS = rech_DRIAS.sum()

# yr_rech_MF = sum_rech_MF/20
# yr_rech_REA = sum_rech_REA/20
# yr_rech_DRIAS = sum_rech_DRIAS/32

# std_rech_MF = rech_MF.std()
# std_rech_REA = rech_REA.std()
# std_rech_DRIAS = rech_DRIAS.std()

