# -*- coding: utf-8 -*-
"""
Created on Wed Jun  4 10:58:46 2025

@author: delarueo
"""

# -*- coding: utf-8 -*-
"""
Created on Tue Jun  3 09:34:31 2025

@author: delarueo
--------------------------------------------------
Solving the preicpitation mystery 



"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import toolbox_newFuns_ as tb

print('>< START ><')
#%% LOADING CERRA LAND DATA 
cerra_path = 'D:/_cerra_land_tp/tp_land_posch.nc'
# Location reference Weather Station
lat,lon = 46.347212,10.063031

#%%
print('>> Loading CERRA LAND data')
cerra = tb.CERRA(cerra_path)
result = cerra._find_nearest_point(lat, lon, checkplot = True)
print(cerra.dataset)
print(result)


#%%
print('>> From xarray to pixel dataframe')
y,x = result['y']['all'], result['x']['all']
timeline = cerra.dataset['time'].values
data = cerra.dataset['total_precipitation'][:,y,x]
df_cerra = pd.DataFrame({'time': pd.to_datetime(timeline), 'tp_land': pd.to_numeric(data.values)}).set_index('time')
print(df_cerra.head(10))
cerra.__close__()

#%% Checkplot - CERRA Land
print('>> Checkplot \n ')
fig, ax = plt.subplots(figsize=(10, 5))

ax.bar(df_cerra.index, df_cerra['tp_land'], width=0.4, label='CERRA', align='center')
ax.set_title('Total Precipitation - CERRA Land')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()

#%% LOADING CERRA FORECAST
cerra_forecast_path ='Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_urse.nc'

print('>> Loading CERRA forescast data - urse sample')
cerra_forecast = tb.CERRA(cerra_forecast_path)
result = cerra_forecast._find_nearest_point(lat, lon, checkplot = True)
y,x = result['y']['all'], result['x']['all']

print('>> From xarray to pixel dataframe')
timeline = cerra_forecast.dataset['time'].values
data = cerra_forecast.dataset['total_precipitation'][:,y,x]
df_cerra_forecast = pd.DataFrame({'time': pd.to_datetime(timeline), 'tp_forecast': pd.to_numeric(data.values)}).set_index('time')
print(df_cerra_forecast.head(10))
cerra_forecast.__close__()

#%% Checkplot - CERRA Land
print('>> Checkplot \n ')
fig, ax = plt.subplots(figsize=(10, 5))

ax.bar(df_cerra_forecast.index, df_cerra_forecast['tp_forecast'], width=0.4, label='CERRA forecast', align='center')
ax.set_title('Total Precipitation - CERRA Forecast')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()

#%% LOADING WEATHER STATION DATA
print('>> Loading Weather Station data')
station_path = 'L:/_poschiavino/_data/_meteoswiss/_ROB/order_127830_data.txt'
output_vars = ['2m_temperature', 'total_precipitation']

data_ws = pd.read_csv(station_path, sep = ';')

meteoswiss_variables = pd.DataFrame({
    'tre200h0'  : {'unit':'°C', 'info': "température de l'air à 2 m du sol; moyenne horaire", 'standard_name':'2m_temperature'},
    'qtre200h0' : {'unit':'Code', 'info': "fr/legend.parameter.dq", 'standard_name':'qtre200h0'},
    'mtre200h0' : {'unit':'Code', 'info': "Information de modification pour tre200h0", 'standard_name':'mtre200h0'},
    'hns000hs'  : {'unit':'cm', 'info': "Épaisseur de neige; valeur instantanée horaire", 'standard_name':'snow_height'},
    'qhns000hs' : {'unit':'Code', 'info': "fr/legend.parameter.dq", 'standard_name':'qhns000hs'},
    'mhns000hs' : {'unit':'Code', 'info': "Information de modification pour hns000hs", 'standard_name':'mhns000hs'},
    'rre150h0'  : {'unit':'mm', 'info': "Précipitations; somme horaire", 'standard_name':'total_precipitation'},
    'qrre150h0' : {'unit':'Code', 'info': "fr/legend.parameter.dq", 'standard_name':'qrre150h0'},
    'mrre150h0' : {'unit':'Code', 'info': "Information de modification pour rre150h0", 'standard_name':'mrre150h0'},
    'rretnth0'  : {'unit':'mm', 'info': "précipitations; somme horaire, corrigé avec fonction de transfert pour pluviomètre à auget basculant, sans paravent, mesure du vent à 10 m", 'standard_name':'total_precipitation_corr'},                                 
    'qrretnth0' : {'unit':'Code', 'info': "fr/legend.parameter.dq", 'standard_name':'qrretnth0'},
    'mrretnth0' : {'unit':'Code', 'info': "Information de modification pour rretnth0", 'standard_name':'mrretnth0'}, 
    'oli000h0'  : {'unit':'W/m²', 'info': "irradiation par onde longue; moyenne horaire", 'standard_name':'outgoing_longwave_radiation'},
    'qoli000h0' : {'unit':'Code', 'info': "fr/legend.parameter.dq", 'standard_name':'qoli000h0'},
    'moli000h0' : {'unit':'Code', 'info': "Information de modification pour oli000h0", 'standard_name':'moli000h0'}}).T

meteoswiss2standards = dict(meteoswiss_variables['standard_name'].T)
standardVars = ['2m_temperature','snow_height','total_precipitation','total_precipitation_corr','outgoing_longwave_radiation']
standardVars_agg = {
    '2m_temperature': 'mean',
    'total_precipitation': 'sum'
    }

listVar = ['2m_temperature','total_precipitation']
data_ws.rename(columns = meteoswiss2standards, inplace=True)
#%%

df_ws = pd.DataFrame()
df_ws['time'] = pd.to_datetime(data_ws['time'], format='%Y%m%d%H%M')
df_ws['tp_ws'] = pd.to_numeric(data_ws['total_precipitation'], errors='coerce')
df_ws.set_index('time', inplace=True)
print(df_ws.head(10))

print('>> Resampling WS data - day')
df_ws_day = df_ws.resample('D').agg('sum')

print('>> Resampling WS data - year')
df_ws_year = df_ws.resample('Y').agg('sum')
#%% Checkplot - Weather Station
print('>> Checkplot WS data day')
fig, ax = plt.subplots(figsize=(10, 5))

ax.bar(df_ws_day.index, df_ws_day['tp_ws'], width=0.4, label='Robbia', align='center')
ax.set_title('Total Precipitation - Weather station Robbia')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()


#%% Plot data together
df_ws_day_light = df_ws_day[df_ws_day.index < '1990']

fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(df_ws_day_light.index, df_ws_day_light['tp_ws'], color = 'purple', label='Robbia')
ax.plot(df_cerra.index, df_cerra['tp_land'], ls = ':', color = 'cyan', label='CERRA Land')

ax.set_title('Total Precipitation - Robbia and CERRA Land')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.set_xlim([df_cerra.index[0],df_cerra.index[-1]])
ax.legend()

fig.tight_layout()

plt.show()

#%% XY plot

df_cerra_day = df_cerra.groupby(df_cerra.index.normalize()).sum() 
print(df_cerra_day.head(5))

#%%
df_cerra_month = df_cerra.resample('M').agg('sum')
df_ws_month = df_ws.resample('M').agg('sum')
df_cerra_fr_month = df_cerra_forecast.resample('M').agg('sum')

combined = pd.merge(df_cerra_month, df_ws_month, left_index=True, right_index=True, how='left')
combined_ = pd.merge(combined, df_cerra_fr_month, left_index=True, right_index=True, how='left')
print(combined_.head(5))

#%% CERRA LAnd vs WeatherStation
fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined['tp_ws'], combined['tp_land'], 'o', alpha=0.5, label ='CERRA Land')

ax.plot([-20, 300], [-20, 300], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title(f'Monthly Precipitation Comparison (Aug 1984 - Dec 1986)')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')

fig.tight_layout()
plt.show()
#%% CERRA land - CERRA forecast vs Weather Station

fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined_['tp_ws'], combined_['tp_land'], 'o', alpha=0.5, label ='CERRA Land')
ax.plot(combined_['tp_ws'], combined_['tp_forecast'], 'o', alpha=0.5, label ='CERRA Forecast')

ax.plot([-10,850],[-10,850], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title('Monthly Precipitation Comparison (Aug 1984 - Dec 1986)')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')
ax.set_xlim([-20,850])

fig.tight_layout()
plt.show()

#%% Plot data together - monthly

fig, ax = plt.subplots(figsize=(10, 5))

ax.bar(combined_.index, combined_['tp_forecast'], color = 'orange', label='CERRA Forecast', width=20, align = 'edge')
ax.bar(combined_.index, combined_['tp_land'], color = 'cyan', label='CERRA Land', width=15, align ='edge')
ax.bar(combined_.index, combined_['tp_ws'], color = 'purple', label='Robbia', width=10, align = 'edge')

ax.set_title('Monthly Total Precipitation - Robbia, CERRA Land, CERRA forecast')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.set_xlim([df_cerra.index[0],df_cerra.index[-1]])
ax.legend()

fig.tight_layout()
plt.show()

#%% Plot data together

df_cerra_fr_day = df_cerra_forecast.resample('D').agg('sum')

combined_day = pd.merge(df_cerra_day, df_ws_day, left_index=True, right_index=True, how='left')
combined_day = pd.merge(combined_day, df_cerra_fr_day, left_index=True, right_index=True, how='left')
print(combined_day.head(5))

#%% TIMESERIE - CERRA land, CERRA forecast, Weather Station (Robbia) 
fig, ax = plt.subplots(figsize=(15, 5))
ax.bar(combined_day.index, combined_day['tp_forecast'], color = 'orange', label='CERRA Forecast', width=0.8, align = 'edge')
ax.bar(combined_day.index, combined_day['tp_land'], color = 'cyan', label='CERRA Land', width=0.6, align ='edge')
ax.bar(combined_day.index, combined_day['tp_ws'], color = 'purple', label='Robbia', width=0.4, align = 'edge')

ax.set_title('Daily Total Precipitation - Robbia, CERRA Land, CERRA forecast')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.set_xlim([df_cerra.index[30],df_cerra.index[60]])
ax.legend()

fig.tight_layout()
plt.show()

#%% CERRA land - CERRA forecast vs Weather Station - Compare aggregation periods
step = '30D'
combined_step = combined_day.resample(step).agg('sum')

fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined_step['tp_ws'], combined_step['tp_land'], 'o', alpha=0.5, label ='CERRA Land')
ax.plot(combined_step['tp_ws'], combined_step['tp_forecast'], 'o', alpha=0.5, label ='CERRA Forecast')

ax.plot([-10,200],[-10,200], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title(f'{step} Precipitation Comparison (Aug 1984 - Dec 1986)')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')
ax.set_xlim([-10,200])

fig.tight_layout()
plt.show()

#%% CERRA land - CERRA forecast vs Weather Station - Compare forecast aggregation method
method = 'max'
df_cerra_fr_day_mean = df_cerra_forecast.resample('D').agg(method)

combined_day = pd.merge(df_cerra_day, df_ws_day, left_index=True, right_index=True, how='left')
combined_day_mean = pd.merge(combined_day, df_cerra_fr_day_mean, left_index=True, right_index=True, how='left')
print(combined_day_mean.head(5))

step = '30D'
combined_step_mean = combined_day_mean.resample(step).agg('sum')

fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined_step_mean['tp_ws'], combined_step_mean['tp_land'], 'o', alpha=0.5, label ='CERRA Land')
ax.plot(combined_step_mean['tp_ws'], combined_step_mean['tp_forecast'], 'o', alpha=0.5, label ='CERRA Forecast')

ax.plot([-10,200],[-10,200], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title(f'{step} Precipitation Comparison (Aug 1984 - Dec 1986)\n Forecast agg : {method}')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')
ax.set_xlim([-10,200])

fig.tight_layout()
plt.show()

# TODO implement russell index for comparaison

