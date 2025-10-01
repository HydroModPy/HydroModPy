# -*- coding: utf-8 -*-
"""
Created on Thu Jun  5 13:24:26 2025

@author: delarueo
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import toolbox_newFuns_ as tb
from scipy.stats import linregress

print('>< START ><')
#%% LOADING CERRA LAND DATA 
cerra_path = 'M:/crash_zone/total_precipitation_cerra_land.nc'
# Location reference Weather Station
lat,lon = 46.347212,10.063031

#%% load cerra land
print('>> Loading CERRA LAND data')
cerra_land = tb.CERRA(cerra_path)
result = cerra_land._find_nearest_point(lat, lon, checkplot = True)
print(cerra_land.dataset)
print(result)


#%% build cerra lan df
print('>> From xarray to pixel dataframe')
y,x = result['y']['all'], result['x']['all']
timeline = cerra_land.dataset['time'].values
data = cerra_land.dataset['total_precipitation'][:,y,x]
df_land = pd.DataFrame({'time': pd.to_datetime(timeline), 'tp_land': pd.to_numeric(data.values)}).set_index('time')
print(df_land.head(10))
cerra_land.__close__()

#%% LOADING CERRA Forecast
cerra_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_urse.nc'

print('>> Loading CERRA Forecast data')
cerra = tb.CERRA(cerra_path)
result = cerra._find_nearest_point(lat, lon, checkplot = True)
print(cerra.dataset)
print(result)

#%% Extract timeline info
leadtime = '6H'
timeline = cerra.dataset['time'].values
data = pd.DataFrame({'forecast_time': pd.to_datetime(timeline)})
# data['real_time'] = pd.to_datetime(timeline) + pd.to_timedelta(leadtime)
data['tp'] = cerra.dataset['total_precipitation'][:, result['y']['all'], result['x']['all']].values
data = data.set_index('forecast_time')

#%% Splite data
data_00 = data[(data.index.hour.isin([0,6,12,18]))].copy()
data_03 = data[(data.index.hour.isin([3,9,15,21]))].copy()

#%% Checkplot
fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(data_00.index, data_00['tp'],  label='00')
ax.plot(data_03.index, data_03['tp'],  label='03')

ax.set_title('Total Precipitation (accumulation: T -> T+6h')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()

#%% Resample data
print('>> CERRA forecast splite')
data_00_day = data_00.resample('D').agg('sum')
data_03_day = data_03.resample('D').agg('sum')
diff = pd.DataFrame(index = data_00_day.index, data = {'tp_diff': data_00_day['tp']-data_03_day['tp'],
                                                       'tp_diff_abs': abs(data_00_day['tp']-data_03_day['tp'])})
fig, ax = plt.subplots(3,1,figsize=(10, 5))

ax[0].plot(data_00.index, data_00['tp'],  label='00')
ax[1].plot(data_03.index, data_03['tp'],  label='03')
ax[2].plot(diff.index, diff['tp_diff'],  label='00-03')
ax[2].plot(diff.index, diff['tp_diff_abs'],  label='abs')

ax[0].set_title('Total Precipitation (accumulation: T -> T+6h')  
ax[1].set_xlabel('Time')
ax[0].set_ylabel('00 - Precipitation (mm)')
ax[1].set_ylabel('03 - Precipitation (mm)')
ax[2].set_ylabel('Difference (mm)')
ax[2].legend()

fig.tight_layout()

plt.show()
print('>> CERRA forecast data splite')



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
#%% Build weather station df
df_ws = pd.DataFrame()
df_ws['time'] = pd.to_datetime(data_ws['time'], format='%Y%m%d%H%M')
df_ws['tp_ws'] = pd.to_numeric(data_ws['total_precipitation'], errors='coerce')
df_ws.set_index('time', inplace=True)
print(df_ws.head(10))

print('>> Resampling WS data - day')
df_ws_day = df_ws.resample('D').agg('sum')
df_ws_month = df_ws.resample('M').agg('sum')

print('>> Resampling WS data - year')
df_ws_year = df_ws.resample('Y').agg('sum')
#%% Checkplot - Weather Station
print('>> Checkplot WS data day')
fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(df_ws_day.index, df_ws_day['tp_ws'], label='Robbia')
ax.set_title('Total Precipitation - Weather station Robbia')  
ax.set_xlabel('Time')
ax.set_ylabel('Precipitation (mm)')
ax.legend()
fig.tight_layout()

plt.show()


#%% INITIAL EXPLORATION & VISUAL
# Build combine
data_00.rename(columns={'tp': 'tp_00'}, inplace = True)
data_03.rename(columns={'tp': 'tp_03'}, inplace = True)

#%% RECONSTRUCTION TIMESERIE
print('>> avg rebuild')

data['half'] = data['tp']/2
data['avg_rebuild'] = data['half'].rolling(window=2).mean()
data['min_rebuild'] = data['half'].rolling(window=2).min()
data.plot()

print(data.head(5))

#%% Month comparison
data00_month = data_00.resample('M').agg('sum')
data03_month = data_03.resample('M').agg('sum')
data_month = data.resample('M').agg('sum')
land_month = df_land.resample('M').agg('sum')
land_month = land_month[land_month.index>'1984-08-31']

combined_month = pd.merge(df_ws_month, data00_month, left_index=True, right_index=True, how='right')
combined_month = pd.merge(combined_month, data03_month, left_index=True, right_index=True, how='right')
combined_month = pd.merge(combined_month, data_month, left_index=True, right_index=True, how='right')
combined_month = pd.merge(combined_month, land_month, left_index=True, right_index=True, how='right')
print(combined_month.head(5))

#%% Plot - month comparison
fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined_month['tp_ws'], combined_month['tp_00'], 'o', alpha=0.5, label ='00')
ax.plot(combined_month['tp_ws'], combined_month['tp_03'], 'o', alpha=0.5, label ='03')
ax.plot(combined_month['tp_ws'], combined_month['avg_rebuild'], 'o', alpha=0.5, label ='avg rb')
ax.plot(combined_month['tp_ws'], combined_month['min_rebuild'], 'o', alpha=0.5, label ='min rb')
ax.plot(combined_month['tp_ws'], combined_month['tp_land'], 'o', alpha=0.5, label ='land')
ax.plot(combined_month['tp_ws'], combined_month['half'], 'o', alpha=0.5, label ='half')

ax.plot([-10,600],[-10,600], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title('Monthly Precipitation Comparison')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')
ax.set_xlim([-20,600])

fig.tight_layout()
plt.show()

#%% Annual comparison
data00_year = data_00.resample('Y').agg('sum')
data03_year= data_03.resample('Y').agg('sum')
data_year = data.resample('Y').agg('sum')
# land_year = df_land.resample('Y').agg('sum')

combined_year = pd.merge(df_ws_year, data00_year, left_index=True, right_index=True, how='right')
combined_year = pd.merge(combined_year, data03_year, left_index=True, right_index=True, how='right')
combined_year = pd.merge(combined_year, data_year, left_index=True, right_index=True, how='right')
# combined_year = pd.merge(combined_year, land_year, left_index=True, right_index=True, how='right')
print(combined_year.head(5))

combined_year = combined_year[(combined_year.index.year>1984)]
combined_year = combined_year[(combined_year.index.year<2021)]

#%% Plot - annual comparison
fig, ax = plt.subplots(figsize=(6, 6))

ax.plot(combined_year['tp_ws'], combined_year['tp_00'], 'o', alpha=0.5, label ='00')
ax.plot(combined_year['tp_ws'], combined_year['tp_03'], 'o', alpha=0.5, label ='03')
ax.plot(combined_year['tp_ws'], combined_year['avg_rebuild'], 'o', alpha=0.5, label ='avg rb')
ax.plot(combined_year['tp_ws'], combined_year['min_rebuild'], 'o', alpha=0.5, label ='min rb')
ax.plot(combined_year['tp_ws'], combined_year['half'], 'o', alpha=0.5, label ='half')

ax.plot([-10,2500],[-10,2500], ls = ':', color = 'grey')  # 1:1 reference line
ax.set_title('Annual Precipitation Comparison')

# Axis labels
ax.set_xlabel('Station (mm)')
ax.set_ylabel('CERRA (mm)')

# Equal axis[ ratio and grid
ax.axis('equal')
ax.grid(True, which='both', linestyle=':')
ax.legend(loc='lower right')
ax.set_xlim([-20,2500])

fig.tight_layout()
plt.show()

#%% With LinReg - month
dataset = combined_month
lim_axe = [-10,600] # month | [-10,2600] # year
list_var = ['half','avg_rebuild','min_rebuild','tp_land']
colors = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    # "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
]

fig, axes = plt.subplots(2, 2, figsize=(12, 12)) 

for ax, var, color in zip(axes.flat, list_var, colors[:len(list_var)]):
    slope, intercept, r_value, p_value, std_err = linregress(dataset['tp_ws'], dataset[var])
    line = slope * pd.Series(dataset['tp_ws']) + intercept
    label = f'y = {slope:.2f} x + {intercept:.2f}\nR = {r_value:.5f}\nstdErr = {std_err:.5f}'
    ax.plot(dataset['tp_ws'], dataset[var], 'o', color = color, alpha = 0.3, label='Data')
    ax.plot(dataset['tp_ws'], line, color= color, label = label)
    ax.plot(lim_axe,lim_axe, ls = ':', color = 'black') 
    
    ax.set_title(f"{var}")
    ax.set_xlabel("Station (mm)")
    ax.set_ylabel(f"CERRA {var} (mm)")
    ax.legend(loc = 'lower right')
    ax.grid(True, linestyle=':')
    ax.axis('equal')
    ax.set_xlim(lim_axe)
    
fig.suptitle("Monthly Comparison \n Robbia Weather Station - CERRA forecast", fontsize=14)

plt.tight_layout()
plt.show()

#%% With LinReg - Year
dataset = combined_year
lim_axe = [-10,2600] # year
list_var = ['tp_00','tp_03','avg_rebuild','min_rebuild']
colors = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple
    "#D55E00",  # vermillion    
]

fig, axes = plt.subplots(2, 2, figsize=(12, 12)) 

for ax, var, color in zip(axes.flat, list_var, colors[:len(list_var)]):
    slope, intercept, r_value, p_value, std_err = linregress(dataset['tp_ws'], dataset[var])
    line = slope * pd.Series(dataset['tp_ws']) + intercept
    label = f'y = {slope:.2f} x + {intercept:.2f}\nR = {r_value:.5f}\nstdErr = {std_err:.5f}'
    ax.plot(dataset['tp_ws'], dataset[var], 'o', color = color, alpha = 0.3, label='Data')
    ax.plot(dataset['tp_ws'], line, color= color, label = label)
    ax.plot(lim_axe,lim_axe, ls = ':', color = 'black') 
    
    ax.set_title(f"{var}")
    ax.set_xlabel("Station (mm)")
    ax.set_ylabel(f"CERRA {var} (mm)")
    ax.legend(loc = 'lower right')
    ax.grid(True, linestyle=':')
    ax.axis('equal')
    ax.set_xlim(lim_axe)
    
fig.suptitle("Yearly Comparison \n Robbia Weather Station - CERRA forecast", fontsize=14)

plt.tight_layout()
plt.show()

