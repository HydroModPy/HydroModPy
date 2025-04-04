# -*- coding: utf-8 -*-
"""
Created on Mon Mar 17 13:25:44 2025

@author: delarueo

opening data from meteoswiss weather station
"""

import pandas as pd
import matplotlib.pyplot as plt

#%% define standard
# Remplacez 'file_path' par le chemin de votre fichier CSV
file_path = 'L:\_poschiavino\_data\_meteoswiss\_BEH\order_127829_data.csv'

#%% 
output_folder = 'Z:/delarue/poschiavo_debiasing/'
output_vars = ['2m_temperature','total_precipitation']


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
    'snow_height': 'max',
    'total_precipitation': 'sum',
    'total_precipitation_corr': 'sum',
    'outgoing_longwave_radiation': 'mean'
    }
#%% open data file
f = open(file_path, "r")
strData = f.read() 

#%% from string to dataframe structure
listData = strData.split('\n')
listData2 = [x.split(';') for x in listData]
cols,values = listData2[0], listData2[1:]
data_beh = pd.DataFrame(values, columns = cols)

#%% format data
data_beh.rename(columns = meteoswiss2standards, inplace=True)
standardVars_ = [var for var in standardVars if var in data_beh.columns]
standardVars_agg_ = {key: standardVars_agg[key] for key in standardVars_}
#%%
data = pd.DataFrame({'snow_height':data_beh['snow_height']})
data_beh['time'] = pd.to_datetime(data_beh['time'], format='%Y%m%d%H%M')
for var in standardVars_:
    data_beh[var] = pd.to_numeric(data_beh[var], errors='coerce')
data_beh.set_index('time', inplace=True)

#%% display data
fig, ax = plt.subplots()

data_beh.plot(ax=ax,y = 'total_precipitation')  

ax.set_xlim(['2015-05-01','2015-07-01'])
ax.set_title('Bernina pass weather station')
plt.show()
 
#%% resample 
beh_data_3h = data_beh.resample('3H').agg(standardVars_agg_)
toDrop = [var for col in beh_data_3h if (col in output_vars) == False]
beh_data_3h.drop( columns = toDrop, inplace=True)
#%% snow height data 
# fig, ax = plt.subplots()

# data_beh.plot(ax=ax,y = 'snow_height')  

# ax.set_xlim(['2014-01-01','2025-01-01'])
# ax.set_title('Bernina pass weather station')
# plt.show()
 


# #%%
# data = pd.DataFrame({'snow_height':data_beh['snow_height']})
# fig, ax = plt.subplots()

# data.plot(ax=ax,y = 'snow_height', ls = '', marker = '+')  

# ax.set_xlim(['2014-01-01','2014-04-01'])
# ax.set_title('Bernina pass weather station')
# plt.show()