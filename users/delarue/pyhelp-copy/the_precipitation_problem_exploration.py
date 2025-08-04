# -*- coding: utf-8 -*-
"""
Created on Mon Jun  2 11:56:18 2025

@author: delarueo
"""
import toolbox_newFuns_ as tb
import os
import pandas as pd
import matplotlib.pyplot as plt
#%%
cerra_urse = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_urse.nc'
year = 2000
# cerra_urse = f'Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/{year}/{year}_alps.nc'
# cerra_urse = 'M:/crash_zone/2000.nc'
variable = 'total_precipitation'


print('>> Open variable local cerra')
data = tb.CERRA(cerra_urse)
#%%
# y,x = 70, 87 #Urse alps
y,x = 3,3
# y,x = 390+70, 475+88 #Robbia
print(data.dataset['latitude'][y,x].values, data.dataset['longitude'][y,x].values)
tp = data.dataset['total_precipitation'].values[:,y,x]
timeline = data.dataset['time'].values

df = pd.DataFrame()
df['time'] = pd.to_datetime(timeline)
df['tp'] = tp
df.set_index('time', inplace=True)

#%%
fig, ax = plt.subplots(1,1,figsize = [5,5])
df.plot(ax = ax,ls =':',marker = '.')

# ax.set_xlim([f'{year}-09-15',f'{year}-10-15'])

df_day = df.resample('D').sum(numeric_only=True)
df_day.plot(ax = ax, ls = '', marker = '.')

ax.set_xlim([f'{year}-09-20',f'{year}-09-22'])

#%%
df_yearly = df.resample('Y').sum(numeric_only=True)
print(df_yearly)


#%%
import pandas as pd
import matplotlib.pyplot as plt

#%% define standard
# Remplacez 'file_path' par le chemin de votre fichier CSV
file_path = 'L:\_poschiavino\_data\_meteoswiss\_ROB\order_127830_data.txt'

#%% 
output_folder = 'Z:/delarue/poschiavo_debiasing/'
output_vars = ['2m_temperature','total_precipitation']

data_ws = pd.read_csv(file_path, sep = ';')


#%% 
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
    # 'snow_height': 'max',
    'total_precipitation': 'sum'
    # 'total_precipitation_corr': 'sum'
    # 'outgoing_longwave_radiation': 'mean'
    }

#%% open data file
# f = open(file_path, "r")
# strData = f.read() 

# #%% from string to dataframe structure
# listData = strData.split('\n')
# listData2 = [x.split(';') for x in listData]
# cols,values = listData2[0], listData2[1:]
# data_beh = pd.DataFrame(values, columns = cols)

#%% format data
listVar = ['2m_temperature','total_precipitation']#,'total_precipitation_corr']
data_ws.rename(columns = meteoswiss2standards, inplace=True)
data_ = pd.DataFrame()
data_['time'] = pd.to_datetime(data_ws['time'], format='%Y%m%d%H%M')
for var in listVar:
    data_[var] = pd.to_numeric(data_ws[var], errors='coerce')
data_.set_index('time', inplace=True)

print(data_.columns)
print(data_.head(5))
# fig, ax = plt.subplots()
# data_.plot(ax=ax, y = 'total_precipitation', ) 
# ax.set_xlim(['2015-05-01','2015-07-01'])
# ax.set_title('Bernina pass weather station')
# plt.show()
#%%
data_day = data_.resample('D').agg(standardVars_agg)
data_year = data_.resample('Y').agg(standardVars_agg)

#%%
data_day.plot(y='total_precipitation')
data_.plot(y='total_precipitation')

#%%
data_filtered = data_day.loc['1991-09-15':'1991-10-15']

# Plot avec barres temporelles
fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(data_filtered.index, data_filtered['total_precipitation'], width=1.0)

ax.set_title('Robbia  weather station')
ax.set_ylabel('Total Precipitation (mm)')
ax.set_xlabel('Date')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

#%%
# 📅 Select the year
year = 2015

# 🎯 Filter data for that year
station_year = data_day[data_day.index.year == year]
model_year = df_day[df_day.index.year == year]

# 📈 Compute cumulative sums
station_cum = station_year['total_precipitation'].cumsum()
model_cum = model_year['tp'].cumsum()

# 🖼️ Plot
fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(station_cum.index.dayofyear, station_cum, label='Station', color='blue', linewidth=2)
ax.plot(model_cum.index.dayofyear, model_cum, label='Modèle CERRA', color='red', linestyle='--', linewidth=2)

# 🎨 Formatting
ax.set_title(f'Précipitations cumulées – {year} – Robbia')
ax.set_xlabel('Jour de l\'année')
ax.set_ylabel('Cumul (mm)')
ax.legend()
ax.grid(True, linestyle=':')
plt.tight_layout()
plt.show()
#%%
# Plot avec barres temporelles

fig, ax = plt.subplots(figsize=(12, 6))

# Courbe 1 : données station météo
data_day.plot(ax=ax, y='total_precipitation', label='Station', color='blue', linewidth=1.5)

# Courbe 2 : données modèle ou reanalyse
df_day.plot(ax=ax, y='tp', label='Modèle CERRA', color='red', linestyle='--', linewidth=1.5)

# Mise en forme
ax.set_title('Robbia - Précipitations journalières comparées')
ax.set_ylabel('Précipitations (mm/jour)')
ax.set_xlabel('Date')
ax.set_xlim(['2015', '2016'])  # Plage temporelle
ax.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

#%%

import matplotlib.pyplot as plt

# 📅 Année à afficher
year = 2016

# 🔍 Filtrer uniquement l'année choisie
station_year = data_day[data_day.index.year == year]
model_year = df_day[df_day.index.year == year]

# 📈 Cumul progressif par jour (cumsum)
station_year['cumul'] = station_year['total_precipitation'].cumsum()
model_year['cumul'] = model_year['tp'].cumsum()

# 🎨 Création du plot avec double axe
fig, ax1 = plt.subplots(figsize=(12, 6))

# Axe 1 : précipitations journalières
ax1.bar(station_year.index, station_year['total_precipitation'], 
        label='Station (journalier)', color='blue', width=1)
ax1.plot(model_year.index, model_year['tp'], 
         label='Modèle (journalier)', color='red', linestyle='--')
ax1.set_ylabel('Précipitations journalières (mm)')
ax1.set_xlabel('Date')
ax1.tick_params(axis='x', rotation=45)

# Axe 2 : cumul progressif
ax2 = ax1.twinx()
ax2.plot(station_year.index, station_year['cumul'], 
         label='Station (cumulé)', color='navy', linewidth=2)
ax2.plot(model_year.index, model_year['cumul'], 
         label='Modèle (cumulé)', color='darkred', linestyle='--', linewidth=2)
ax2.set_ylabel('Cumul (mm)')

# Légende combinée
lines = ax1.get_lines() + ax2.get_lines()
labels = [line.get_label() for line in lines]
ax1.legend(lines, labels, loc='upper left')

# Titre et affichage
ax1.set_title(f'Robbia – Précipitations {year} : journalières & cumulées')
ax1.grid(True, linestyle=':')
plt.tight_layout()
plt.show()

#%% Plot Bar Year

fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(data_year.index, data_year['total_precipitation'],width=150)
ax.bar(df_yearly.index,df_yearly['tp'],color = 'r',width=100)
ax.set_title('Robbia  weather station')
ax.set_ylabel('Total Precipitation (mm)')
ax.set_xlabel('Date')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
plt.xlabel('Station (mm/jour)')
plt.ylabel('Modèle (mm/jour)')

#%% Plot xy - station /cerra - loglog

combined_day = data_day[['total_precipitation']].join(
    df_day[['tp']], how='inner', lsuffix='_station', rsuffix='_model')

plt.figure(figsize=(6, 6))
plt.loglog(combined_day['total_precipitation'], combined_day['tp'], 'o', alpha=0.5)

plt.xlabel('Station (mm/jour)')
plt.ylabel('CERRA (mm/jour)')
plt.axis('equal')
plt.title('Précipitations journalières – log-log')
plt.grid(True, which='both', linestyle=':', alpha=0.6)
plt.tight_layout()
plt.show()

#%% Plot xy - station/cerra

combined_day = data_day[['total_precipitation']].join(
    df_day[['tp']], how='inner', lsuffix='_station', rsuffix='_model')

plt.figure(figsize=(6, 6))
plt.plot(combined_day['total_precipitation'], combined_day['tp'], 'o', alpha=0.5)
plt.plot([-10,150],[-10,150] ,color='k')
plt.xlabel('Station (mm/jour)')
plt.ylabel('CERRA (mm/jour)')
plt.axis('equal')
plt.title('Précipitations journalières')
plt.grid(True, which='both', linestyle=':', alpha=0.6)
plt.tight_layout()
plt.show()

# #%% Plot xy - station/cerra - zoom

# combined_day = data_day[['total_precipitation']].join(
#     df_day[['tp']], how='inner', lsuffix='_station', rsuffix='_model')

# plt.figure(figsize=(6, 6))
# plt.plot(combined_day['total_precipitation'], combined_day['tp'], 'o', alpha=0.5)

# plt.xlabel('Station (mm/jour)')
# plt.ylabel('CERRA (mm/jour)')
# plt.xlim([-5,50])
# plt.ylim([-5,100])
# plt.axis('equal')
# plt.title('Précipitations journalières')
# plt.grid(True, which='both', linestyle=':', alpha=0.6)
# plt.tight_layout()
# plt.show()