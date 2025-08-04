# -*- coding: utf-8 -*-
"""
Created on Thu Jun  5 16:53:20 2025

@author: delarueo
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import toolbox_newFuns_ as tb

#%% LOADING CERRA FORECAST
path ='Z:/_waterwise_data_process/_climate/_cerra_forecast/2m_temperature/2m_temperature_urse.nc'
cerra_t2m = tb.CERRA(path)

path ='Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_urse.nc'
cerra_tp = tb.CERRA(path)

#%%
data = cerra_t2m.dataset['2m_temperature'][:,4,4].values
timeline = cerra_t2m.dataset['time'].values
df = pd.DataFrame(data = {'time': pd.to_datetime(timeline),
                          't2m': pd.to_numeric(data)})
df = df.set_index('time')

df.plot()
plt.xlim(['1985-08-20','1985-08-21'])

#%%
df_bef = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                   'tp_bef' :  cerra_tp.dataset['total_precipitation'][:,1,1].values})
df_bef.set_index('time', inplace =True)
df_bef = df_bef.copy()
print(df_bef.shape)

cerra_tp.accum2instant('total_precipitation', 6, 'cut')

df_af = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                      'tp_af' : pd.to_numeric(cerra_tp.dataset['total_precipitation'][:,1,1].values)})
df_af.set_index('time', inplace =True)
print(df_af.shape)

#%%

bef_day = df_bef.resample('D').agg('sum')
bef_year = df_bef.resample('Y').agg('sum')

af_day = df_af.resample('D').agg('sum')
af_year = df_af.resample('Y').agg('sum')
#%%

fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(bef_year.index, bef_year['tp_bef'],  label='before')
ax.plot(af_year.index, af_year['tp_af'], '--', label='after')

ax.set_title('Total Precipitation - accumulation 2 instant building')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()

#%%

fig, ax = plt.subplots(figsize=(10, 5))

bef_day.plot(ax=ax, label='before')
af_day.plot(ax=ax, ls = '--', label='after')

ax.set_title('Total Precipitation - accumulation 2 instant building')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
ax.set_xlim(['1985-08-20','1985-08-30'])
fig.tight_layout()

plt.show()
