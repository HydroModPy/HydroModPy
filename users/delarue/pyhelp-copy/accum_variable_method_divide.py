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

leadtime = 6

#%%
data = cerra_t2m.dataset['2m_temperature'][:,4,4].values
timeline = cerra_t2m.dataset['time'].values
df = pd.DataFrame(data = {'time': pd.to_datetime(timeline),
                          't2m': pd.to_numeric(data)})
df = df.set_index('time')

df.plot()
plt.xlim(['1985-08-20','1985-08-21'])

#%% CUT method

df_bef = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                    'tp_bef' :  cerra_tp.dataset['total_precipitation'][:,1,1].values})
df_bef.set_index('time', inplace =True)
df_bef = df_bef.copy()
print(df_bef.shape)

cerra_tp.accum2instant('total_precipitation', leadtime, 'cut')
df_af_cut = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                      'tp_af' : pd.to_numeric(cerra_tp.dataset['total_precipitation'][:,1,1].values)})
df_af_cut.set_index('time', inplace =True)
print(df_af_cut.shape)

#%% DIVIDE method
cerra_tp = tb.CERRA(path)

df_bef = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                   'tp_bef' :  cerra_tp.dataset['total_precipitation'][:,1,1].values})
df_bef.set_index('time', inplace =True)
df_bef = df_bef.copy()
print(df_bef.shape)

# Convert time to datetime

timeline = pd.to_datetime(cerra_tp.dataset['time'].values)
timestep = timeline[1]-timeline[0]
print(timestep)

divide = pd.to_timedelta(f'{leadtime}H')/timestep
print(divide)
# Filter dataset
cerra_tp.dataset['total_precipitation'] = (('time','y','x'), cerra_tp.dataset['total_precipitation'][:,:,:].values/divide)

# Shift timeline by leadtime (e.g., to adjust for accumulation offset)
cerra_tp.dataset['time'] = pd.to_datetime(cerra_tp.dataset['time'].values) + timestep

df_af_div = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                      'tp_af' : pd.to_numeric(cerra_tp.dataset['total_precipitation'][:,1,1].values)})
df_af_div.set_index('time', inplace =True)
print(df_af_div.shape)

#%% AVG method
name_var = 'total_precipitation'
timeline = pd.to_datetime(cerra_tp.dataset['time'].values)
timestep = timeline[1]-timeline[0]

divide = pd.to_timedelta(f'{leadtime}H')/timestep

# Filter dataset
cerra_tp.dataset[name_var] = (('time','y','x'), cerra_tp.dataset[name_var][:,:,:].values/divide)
cerra_tp.dataset[name_var] = cerra_tp.dataset[name_var].rolling(time = divide, center = False).mean()


# Shift timeline by leadtime (e.g., to adjust for accumulation offset)
# self.dataset['time'] = pd.to_datetime(self.dataset['time'].values) + timestep


df_af_avg = pd.DataFrame({'time': pd.to_datetime(cerra_tp.dataset['time'].values),
                         'tp_af' : pd.to_numeric(cerra_tp.dataset['total_precipitation'][:,1,1].values)})
df_af_avg.set_index('time', inplace =True)
print(df_af_avg.shape)

#%%

bef_day = df_bef.resample('D').agg('sum')
bef_year = df_bef.resample('Y').agg('sum')

af_div_day = df_af_div.resample('D').agg('sum')
af_div_year = df_af_div.resample('Y').agg('sum')

af_cut_day = df_af_cut.resample('D').agg('sum')
af_cut_year = df_af_cut.resample('Y').agg('sum')
#%%

fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(bef_year.index, bef_year['tp_bef'],  label='before')
ax.plot(df_af_cut.index, df_af_cut['tp_af'], '--', label='cut')
ax.plot(df_af_div.index, df_af_div['tp_af'], ':', label='div')

ax.set_title('Total Precipitation - accumulation 2 instant building')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()

#%%

fig, ax = plt.subplots(figsize=(10, 5))

df_bef.plot(ax=ax, label='before')
df_af_cut.plot(ax=ax, ls = '--', label='cut')
df_af_div.plot(ax=ax, ls = ':', label='div')
df_af_avg.plot(ax=ax, ls = ':', label='avg')

ax.set_title('Total Precipitation - accumulation 2 instant building')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
ax.set_xlim(['1985-08-20','1985-08-30'])
fig.tight_layout()

plt.show()

