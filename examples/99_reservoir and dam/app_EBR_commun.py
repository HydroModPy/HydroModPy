# -*- coding: utf-8 -*-
"""
Created on Wed Dec  6 22:19:57 2023

Launch code for HydroModPy simulation of Cheze reservoir for EBR
@author: Alexnadre Coche

HydroModPy:
    * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
    *
    * This program and the accompanying materials are made available under the
    * terms of the Eclipse Public License 2.0 which is available at
    * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
    * which is available at https://www.apache.org/licenses/LICENSE-2.0.
    *
    * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""


#%% CHARGEMENT DES BIBLIOTHEQUES ET MODULES

#% PYTHON
# Bibliothèques installées par défaut
import sys
import os
import requests
import datetime
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Bibliothèques additionnelles installées dans l'environnement
import numpy as np
import pandas as pd
import flopy
import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import deepdish as dd
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import xarray as xr
xr.set_options(keep_attrs = True)

#% DOSSIER RACINE
from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)

cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    # print("Root path directory is: {0}".format(cwd))


#% Modules HydroModPy
import src
import importlib
importlib.reload(src)
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large


#%% DOSSIERS UTILISATEUR
out_path = folder_root.root_folder_results()
# Pour modifier ce chemin : out_path = folder_root.update_root_folder_results()

print(f"Les résultats des simulations seront stockés dans le dossier {out_path}\n")

data_path = os.path.join(out_path, 'data_Cheze')
if not os.path.exists(data_path):
    os.makedirs(data_path)
if len(os.listdir(data_path)) == 0:
    print(f"Warning : Le dossier {data_path} est vide. Avant toute utilisation, il est nécessaire de télécharger vers ce dossier les données d'entrée du modèle (voir lien fourni)\n")

#%% BASSIN VERSANT 
##%%% Options: Charger MNT
dem_path = os.path.join(data_path, 
                        "MNT",
                        "MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif")
load = False
watershed_name = '_'.join(['barrage_Cheze', pd.to_datetime("today").strftime("%Y-%m-%d")])
# outlet after the dam ("pont romain")
from_xyv = [331315, 6781273, 200, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
# Station de débit à Plélan-le-Grand : [x, y] = [324472, 6779605]
save_object = True

#%%% Créer GEOGRAPHIC
print('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load, # load = False
                              watershed_name=watershed_name,
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              save_object=save_object)

#%%% Recharger GEOGRAPHIC
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              watershed_name=watershed_name,
                              load=True)

#%% SOUS-BASSINS
hydrometry_path = os.path.join(data_path,
                               "Stations jaugeage")
BV.add_hydrometry(hydrometry_path, 'france hydrometric stations.shp')

intermittency_path= os.path.join(data_path,
                                 "Stations ONDE")
BV.add_intermittency(intermittency_path, 'regional onde stations.shp')

# =============================================================================
# BV.add_subbasin(os.path.join(root_dir, 'examples', 
#                              '99_reservoir and dam', 'data', 'additional'), 200)
# =============================================================================
# Normalement pas besoin car c'est déjà un point d'intérêt

#%% (VISUALISATIONS DU SITE D'ETUDE)
# Clip specific data at the catchment scale
geol_path = os.path.join(data_path,
                         "Geologie")
BV.add_geology(geol_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
hydrography_path = os.path.join(data_path,
                                r"Hydrographie")
BV.add_hydrography(hydrography_path, types_obs=['CoursEau_FXX'], fields_obs=['fid'])

# =============================================================================
# BV.add_piezometry()
# =============================================================================
# Erreur en cours

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% RECHARGE et RUISSELLEMENT DE SURFACE (données d'entrée)
BV.add_climatic()
sim_state = 'transient' # transitoire
freq_input = 'W' # hebdomadaire

##%%% Reanalyse
BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 
                                              'evt', 'etp', 'precip', 'temp'],
                                       nc_data_path=os.path.join(
                                           data_path,
                                           r"Meteo"),
                                       first_year=pd.to_datetime('today').year-15,
                                       # last_year=2021,
                                       time_step=freq_input,
                                       sim_state=sim_state,
                                       spatial_mean=True,
                                       geographic=BV.geographic,
                                       disk_clip='watershed') # for clipping the netcdf files saved on disk
                                                                # can be a shapefile path or a flag: 'watershed' or False

# Units
BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
BV.climatic.temp = BV.climatic.temp / 1000 # from mm to m
BV.climatic.update_recharge(BV.climatic.recharge / 1000, sim_state=sim_state) # from mm to m
BV.climatic.update_runoff(BV.climatic.runoff / 1000, sim_state=sim_state) # from mm to m


### Figures des chroniques
if isinstance(BV.climatic.recharge, float):
    print(f"Recharge moyenne = {BV.climatic.recharge} m")
    print(f"Ruissellement de surface moyen = {BV.climatic.runoff} m")
else:
    # Yearly (matplotlib)
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    # =============================================================================
    # R = recharge.resample('Y').sum()*1000 # [m] -> [mm]
    # r = runoff.resample('Y').sum()*1000 # [m] -> [mm]
    # =============================================================================
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        R = R.resample('Y').sum()*1000 # [m] -> [mm]
        r = r.resample('Y').sum()*1000 # [m] -> [mm]
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):
        R = BV.climatic.recharge.resample('Y').sum()*1000 # [m] -> [mm]
        r = BV.climatic.runoff.resample('Y').sum()*1000 # [m] -> [mm]
    ax.plot(R, label='recharge (réanalyse)', c='dodgerblue', lw=1)
    ax.plot(r, label='ruissellement de surface (réanalyse)', c='navy', lw=1)
    ax.set_xlabel('Temps')
    ax.set_ylabel('[mm/an]')
    ax.legend()
    
    # Daily (or weekly) (matplotlib)
    fig, ax = plt.subplots(1,1, figsize=(6,3))
    if isinstance(BV.climatic.recharge, xr.core.dataset.Dataset):
        R = BV.climatic.recharge.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        r = BV.climatic.runoff.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas().iloc[:,0]
        R = R*1000 # [m] -> [mm]
        r = r*1000 # [m] -> [mm]
    elif isinstance(BV.climatic.recharge, pd.core.series.Series):
        R = BV.climatic.recharge*1000 # [m] -> [mm]
        r = BV.climatic.runoff*1000 # [m] -> [mm]
    
    # =============================================================================
    # R = recharge*1000 # [m] -> [mm]
    # r = runoff*1000 # [m] -> [mm]
    # =============================================================================
    ax.plot(R, label='recharge (réanalyse)', c='dodgerblue', lw=1)
    ax.plot(r, label='ruissellement de surface (réanalyse)', c='navy', lw=1)
    ax.set_xlabel('Temps')
    ax.set_ylabel('[mm/j]')
    ax.legend()

#%% BARRAGE
# In this version, the lake is defined in a new modflow layer added on top of the modeL

# ---- Activer le module lac/réservoir
BV.add_lakeres()


# Ajouter un nouveau réservoir
# ----------------------
lake_id = 'reservoir_cheze'

print("\n-----------" + "-"*len(lake_id))
print(f"Ajout de '{lake_id}'")
print("-----------" + "-"*len(lake_id))
print("   . Définition de la géographie du réservoir :")

maskmx = os.path.join(data_path,"Reservoir", "Masque", "Cheze_lake_75m_larger.tif")
# maskmx = os.path.join(data_path,"Reservoir", "Masque", "Cheze_polygon_larger.shp")

BV.lakeres.new_lakeres(maskmx, lake_id)

# Géométrie et propriétés physiques
# ---------------------------------
# BV.lakeres.update_stageinit(lake_id, 85) # [m] # initialisé plus tard
BV.lakeres.update_stagemax(lake_id, 87.3) # [m]
# BV.lakeres.update_volumemax(lake_id, 14e6) # [m3]
BV.lakeres.update_lakebed_leakance(lake_id, 1e-6 * 24 * 3600) # débit de fuite du lit du réservoir [m/day]
                                                              # ici équiv. à 1e-6 m/s
bathymetry_raster = os.path.join(data_path, "Reservoir", "Bathymetrie",
                             "Cheze_bathy_1m_NGF-elevation_v2enlarged.nc")
                             # "bathymetry_25m_NGF-elevation.tif")
BV.lakeres.update_bathymetry(lake_id, bathymetry_raster)
# =============================================================================
# BV.lakeres.update_bathymetry(lake_id, bathymetry_raster, mode = 'elevation')
# # mode can be 'elevation', 'depth', 'height' (= -depth)
# =============================================================================

# Definition of the lake outlet (if not, the outlet will be automatically 
# determined)
outlet_file = os.path.join(data_path, "Reservoir", 
                           "Exutoire", "lakeres_outlets.shp")
BV.lakeres.update_outlet(lake_id, outlet_file)

# ---- Chargement des flux d'entrée à partir des données mensuelles
print("   . Chargement des flux d'entrée mensuels")

dam_data_path = os.path.join(data_path, "Reservoir", 
                             "Donnees mensuelles base historique",
                             r"dam_cheze_volume_raw_2000-2022.csv")

dam_input_df = pd.read_csv(dam_data_path,
                           sep = ";",
                           header = 0,
                           skiprows = 0,
                           index_col = 'time',
                           parse_dates = True)

# Conversion des valeurs (sommes mensuelles) en flux journaliers
days_in_month = pd.DataFrame( 
    index = dam_input_df.index,
    data = dam_input_df.index.days_in_month)
days_in_month.rename(columns = {'time':'n_days'}, inplace = True)
# dam_input_df = dam_input_df.divide(days_in_month.n_days, axis="index")
sum_col = dam_input_df.columns != 'cheze'
dam_input_df.loc[:, sum_col] = dam_input_df.loc[:, sum_col].divide(
    days_in_month.n_days, axis="index")

# Sous-échantillonage des données d'entrée selon la temporalité de la recharge
# =============================================================================
# # interpolation method
# dam_input_df = dam_input_df.shift(periods = -15, freq = 'D') # 15 should be replaced with a more accurate value
# dam_input_df = dam_input_df.resample('D').mean()
# dam_input_df.interpolate(method = "time", limit_direction = 'backward', inplace = True)
# =============================================================================
# d'abord en journalier
daily_index = pd.date_range(start = BV.climatic.recharge.index[0], 
                             periods = (BV.climatic.recharge.index[-1] \
                                 - BV.climatic.recharge.index[0]).days + 1,
                                 freq = 'D') 
dam_input_df = dam_input_df.reindex(index = daily_index)
# =============================================================================
# # other (partial) method
# dam_input_df = dam_input_df.resample('D').mean()
# =============================================================================
dam_input_df.fillna(method = 'bfill', inplace = True) # backward fill
dam_input_df.fillna(0, inplace = True) # replace remaining NaN with 0
# puis en hebdomadaire
rules = {
    'cheze': 'mean',
    'canut':'mean',
    'meu':'mean',
    'usine':'mean',
    'resti':'mean',
    'stream':'mean',
    'ppt_surf':'mean',
    'ae_oudin':'mean',
    }
dam_input_df = dam_input_df.resample(freq_input).agg(rules)

# ---- Raffinage des débits de la Chèze
print("   . Raffinage des débits de la Chèze à partir de eaufrance.fr")

code_station = 'J736422001' # La Chèze à Plélan-le-Grand - L'Enlevrier
# Details sur la station:
# -----------------------
url = r"https://hubeau.eaufrance.fr/api/v1/hydrometrie/referentiel/stations"
params = {
    # 'code_region': ['44'],
    # "code_site": "J7364220", 
    "code_station": code_station,
    "size": 10000,
    }
res = requests.get(url, params)
# =============================================================================
# with open(os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits",
#                        "stations_liste.csv"), "w",
#           encoding = res.encoding, ) as f:
#     f.write(res.text)
# 
# stations_list = pd.read_csv(
#     os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits",
#                  "stations_liste.csv"),
#     sep = ";",
#     quotechar = '"',
#     parse_dates = ['date_ouverture_station', 'date_fermeture_station'],
#     # date_format = "%d/%m/%Y",
#     )
# =============================================================================
if 'data' in res.json().keys():
    stations_info = pd.DataFrame.from_dict(res.json()['data'])
else:
# elif ('code' in res.json().keys()) or (res.json()['code'] == 'Internal server error'):
    stations_info = pd.read_csv(os.path.join(data_path, "Debits", "stations_list.csv"),
        sep = ";",
        header = 0,
        index_col = 0)
    print("        Erreur sur la mise-à-jour des infos des stations de jaugeage")
# Mise à jour des fichiers
stations_info.to_csv(os.path.join(data_path, "Debits", "stations_list.csv"), 
    sep = ";")

# Valeurs de flux journaliers :
# -----------------------------
url = r"https://hubeau.eaufrance.fr/api/v1/hydrometrie/obs_elab"
# idx = stations_info.index[stations_info['code_station'] == code_station][0]
# date_ini = stations_info.loc[idx, 'date_ouverture_station']
date_ini = stations_info.loc[0, 'date_ouverture_station']
date_today = pd.to_datetime('today').strftime("%Y-%m-%d")
# As it is possible only to extract 10000 values, only the most recent values
# will be retrieved
date_start = max(pd.to_datetime(date_ini).replace(tzinfo = None), 
                 pd.to_datetime(date_today) - pd.Timedelta(10000, 'D')
                 ).strftime("%Y-%m-%d")

quantity = 'QmJ' # [l/s]

params = {
    "size": 10000, # max
    "code_entite": code_station,
    "date_debut_obs_elab": date_start,
    "date_fin_obs_elab": date_today, # NB: la dernière semaine est généralement manquante
    "grandeur_hydro_elab": quantity,
          }
res = requests.get(url, 
                    params = params
                   )
if 'data' in res.json().keys():
    discharge = pd.DataFrame.from_dict(res.json()['data'])
else:
    discharge = pd.read_csv(os.path.join(data_path, "Debits",
        "J736422001_QmnJ(n=1_non-glissant) debit_cheze_plelan-le-grand.csv"),
        sep = ";",
        header = 0,
        index_col = 0)
    print("        Erreur sur la mise-à-jour du débit")
# Update file:
discharge.to_csv(os.path.join(data_path, "Debits",
    "J736422001_QmnJ(n=1_non-glissant) debit_cheze_plelan-le-grand.csv"),
    sep = ";")    

discharge = discharge.loc[:, ['date_obs_elab', 'resultat_obs_elab']]
discharge.columns = ['time', 'val']
discharge['val'] = discharge['val']*1e-3*60*60*24 # convertit [l/s] -> [m3/d]
discharge['time'] = pd.to_datetime(discharge['time'])
discharge.index = discharge.time
discharge = discharge.reindex(index = daily_index)
# discharge.fillna(0, inplace = True) # replace NaN with 0
discharge = discharge.resample(freq_input).mean()

# Set the first value (used for steady initialization) as the average value
discharge.iloc[0] = toolbox.hydrological_mean(discharge, 4)

dam_input_df['stream'].update(discharge.val)


# ---- Raffinage du niveau initial
print("   . Raffinage du niveau initial de la retenue avec l'abaque")

abaque = pd.read_csv(os.path.join(data_path, "Reservoir", "Abaque",
    "abaque_cheze_2020.csv"),
                     sep = "\t",
                     header = 0,
                     names = ['level', 'volume'],
                     )

# Monthly data
# ------------
# dam_data_path = os.path.join(
#     os.path.split(data_path)[0], 
#     r"1- Biblio locale\14- Barrage\Documents_travail_Ronan\dam_data",
#     "dam_cheze_volume_raw_2000-2022.csv")
# data = pd.read_csv(dam_data_path,
#                    sep = ";",
#                    header = 0,
#                    skiprows = 0,
#                    index_col = 'time',
#                    # usecols = ['time', 'cheze'],
#                    parse_dates = True)

# data_volumes = data[['cheze']].copy()
data_volumes = dam_input_df[['cheze']].copy()

# Données hebdomadaires
# ---------------------
Stock_Cheze_xls_folder = os.path.join(data_path, "Reservoir", 
                                      "Donnees journalieres EBR", "Niveaux")
try:
    Stock_Cheze_xls_path = os.path.join(
        Stock_Cheze_xls_folder,
        f"Villejean_Stock_Cheze_{datetime.datetime.now().year}_val.xlsx")
except:
    Stock_Cheze_xls_path = os.path.join(
        Stock_Cheze_xls_folder,
        f"Villejean_Stock_Cheze_{datetime.datetime.now().year-1}_val.xlsx")
        
# =============================================================================
# # methode 2 (debut)
# Stock_Cheze_xls_list = [f for f in os.listdir(
#     os.path.join(os.path.split(data_path)[0],
#                  r"1- Biblio locale\14- Barrage\Donnees journalieres Cheze\Niveaux")) \
#         if os.path.isfile(os.path.join(
#                 os.path.split(data_path)[0],
#                 r"1- Biblio locale\14- Barrage\Donnees journalieres Cheze\Niveaux", 
#                 f))]
# =============================================================================
        
data = pd.read_excel(
    Stock_Cheze_xls_path,
    sheet_name = "Histos",
    header = 3, 
    # index_col = 0,
    # skiprows = 3,
    )
data = data.iloc[:, 3:-2]
if data.iloc[:, -1].count() == 0:
    print(f"        Warning: Les dernières valeurs ({data.columns[-1]}) n'ont pas été correctement récupérées.")
    print("        Aller sur la feuille 'Histos', puis effectuer Ctrl+A, Ctrl+C, Maj+F10+V, et enregistrer sous un nouveau fichier <nom>_val.xlsx")

# Pivot from wide-format to long-format
data_volumes = pd.lreshape(data, 
                           groups = {'vol':data.columns},
                           dropna = False)

weekly_index = pd.date_range(start = pd.to_datetime(f'{data.columns[0]}:01_1', format = '%Y:%W_%w'),
                             periods = data_volumes.size*1.05, # extended
                             freq = 'W')

data_volumes.set_index(weekly_index[weekly_index.week != 53][0:data_volumes.size], 
                          inplace = True)
data_volumes = data_volumes.reindex(
    weekly_index[weekly_index <= data_volumes[data_volumes.notna().vol].index[-1]])

data_volumes.interpolate(method = 'time', inplace = True)

# Mise à jour des données d'entrées (optionnel)
# ---------------------------------------------
data_volumes = data_volumes.resample(freq_input).mean()
data_volumes.fillna(method = 'bfill', inplace = True) # backward fill
data_volumes.fillna(0, inplace = True) # replace remaining NaN with 0
dam_input_df['cheze'].update(data_volumes.vol)

# Conversion des volumes en stages
# --------------------------------
data_levels = data_volumes.copy()
data_levels.rename(columns = {'vol': 'lvl'}, inplace = True)
for t in data_levels.index:
    if not abaque[abaque.volume <= data_volumes.loc[t].item()].empty:
        data_levels.loc[t] = abaque[abaque.volume <= data_volumes.loc[t].item()].iloc[-1].level
    else:
        if data_volumes.loc[t].item() > abaque.volume.max():
            slope = (abaque.volume.iloc[-1] - abaque.volume.iloc[-2]) / (abaque.level.iloc[-1] - abaque.level.iloc[-2])
            add_level = abaque.level.iloc[-1] + (data_volumes.loc[t].item() - abaque.volume.iloc[-1])/slope
            abaque_interp = abaque.append({'level':add_level, 'volume':data_volumes.loc[t].item()}, 
                                          ignore_index = True)
        elif data_volumes.loc[t].item() < abaque.volume.min():
            slope = (abaque.volume.iloc[1] - abaque.volume.iloc[0]) / (abaque.level.iloc[1] - abaque.level.iloc[0])
            add_level = abaque.level.iloc[0] + (data_volumes.loc[t].item() - abaque.volume.iloc[0])/slope
            abaque_interp = pd.DataFrame(data = {'level':add_level, 'volume':data_volumes.loc[t].item()}, index = [0]).append(abaque, ignore_index = True)
        data_levels.loc[t] = abaque_interp[abaque_interp.volume <= data_volumes.loc[t].item()].iloc[-1].level

if BV.climatic.recharge.index[0] in data_levels.index:
    level_init = data_levels.loc[BV.climatic.recharge.index[0]].item()
else:
# =============================================================================
#     # Method 'nearest'
#     level_init = float(data_levels.iloc[
#         data_levels.index.get_indexer([BV.climatic.recharge.index[0]], 'nearest')[0]])
# =============================================================================
    
    # Method 'interpolated'
    idx = data_levels.index.get_indexer([BV.climatic.recharge.index[0]], 'pad').item()
    
    data_levels_interp = data_levels.reindex(index = [data_levels.index[idx],
                                                      BV.climatic.recharge.index[0],
                                                      data_levels.index[idx+1]])
    data_levels_interp.interpolate(method = "time", inplace = True)
    level_init = data_levels_interp.loc[BV.climatic.recharge.index[0]].item()


BV.lakeres.update_stageinit(
    lake_id,
    level_init) # [m]


# ---- Raffinage des flux d'entrée récents à partir des données journalières
print("   . Raffinage des flux d'entrée avec les données journalières :")

Flux_Cheze_xls_folder = os.path.join(data_path, "Reservoir",
                                     "Donnees journalieres EBR", "Flux")

for path, folders, files in os.walk(Flux_Cheze_xls_folder):
    if len(files) > 0:
        print(f"        mise-à-jour {os.path.split(path)[-1]}")
        for f in files:
            if (f[0] != '~') & (f[-8:-5].casefold() != 'old'):
                if f[-11:-5] in ['1_2020', '2_2020', '3_2020',
                                 '4_2020', '5_2020']: # ancien format
                    data = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 9, 11, 13, 14],
                        names = ['time', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                    data['radar'] = data['cheze']
                else:
                    data = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 9, 10, 12, 14, 15],
                        names = ['time', 'radar', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                data = data[data.index.notna()] # remove the rows with no date
                # data.dropna(axis = 0, how = 'all', inplace = True) # remove the last rows if empty
                data.index = pd.to_datetime(data.index, format = '%d/%m/%Y')
                # Use radar values to fill in missing piezo values:
                data.cheze[data.cheze.isna()] = data.radar[data.cheze.isna()] 
                data = data.loc[:, data.columns != 'radar']
                data.interpolate(method = 'time', inplace = True)
                
                data = data.resample(freq_input).agg({var:rules[var] for var in data.columns})

                # Conversion des niveaux en volumes
                # ---------------------------------
                for t in data.index:
                    if not abaque[abaque.level <= data.cheze.loc[t].item()].empty:
                        data.cheze.loc[t] = abaque[abaque.level <= data.cheze.loc[t].item()].iloc[-1].volume
                    else:
                        if data.cheze.loc[t].item() > abaque.level.max():
                            slope = (abaque.level.iloc[-1] - abaque.level.iloc[-2]) / (abaque.volume.iloc[-1] - abaque.volume.iloc[-2])
                            add_volume = abaque.volume.iloc[-1] + (data.cheze.loc[t].item() - abaque.level.iloc[-1])/slope
                            abaque_interp = abaque.append({'volume':add_volume, 'level':data.cheze.loc[t].item()}, 
                                                          ignore_index = True)
                        elif data.cheze.loc[t].item() < abaque.level.min():
                            slope = (abaque.level.iloc[1] - abaque.level.iloc[0]) / (abaque.volume.iloc[1] - abaque.volume.iloc[0])
                            add_volume = abaque.volume.iloc[0] + (data.cheze.loc[t].item() - abaque.level.iloc[0])/slope
                            abaque_interp = pd.DataFrame(data = {'volume':add_volume, 'level':data.cheze.loc[t].item()}, index = [0]).append(abaque, ignore_index = True)
                        data.cheze.loc[t] = abaque_interp[abaque_interp.level <= data.cheze.loc[t].item()].iloc[-1].volume


                for col in ['cheze', 'resti', 'meu', 'usine']:
                    dam_input_df[col].update(data[col])
                # dam_input_df[['cheze', 'resti', 'meu', 'usine']].update(data)


# ---- Mise-à-jour des données d'entrée du réservoir
print("   . Mise à jour des paramètres du réservoir")

# Set the first value (used for steady initialization) as the average value
dam_input_df.iloc[0] = toolbox.hydrological_mean(dam_input_df, 4)

##%%% Mise-à-jour des flux

# Environmental fluxes (by default, fluxes are set to 0) 
# User can update these fluxes with float, file path, or "from_climatic" mode
# BV.lakeres.update_precip(lake_id, dam_input_df['ppt_surf']/1.73e6) # because Ronan's values were summed over 1.73 km² area
# BV.lakeres.update_precip(lake_id, 'from_climatic')
BV.lakeres.update_precip(lake_id, BV.climatic.precip)
# BV.lakeres.update_evap(lake_id, dam_input_df['ae_oudin']/1.73e6)
# BV.lakeres.update_evap(lake_id, 'from_climatic')
BV.lakeres.update_evap(lake_id, BV.climatic.evt)
# BV.lakeres.update_runoff(lake_id, BV.climatic.runoff * (30-3.31)*1e6) # because runoff has to be a volume (summed over the area runing off towards the lake)

# Anthropic fluxes
# Convert into cumsum with the same time resolution as recharge
withdraw_fill_ts = dam_input_df['usine'] - dam_input_df['canut'] - dam_input_df['meu'] 
# For now we can add here the upstream flow and substract the return flux
withdraw_fill_ts = withdraw_fill_ts + dam_input_df['resti'] - 3*dam_input_df['stream'] # the x3 factor is added to account for lateral streams
BV.lakeres.update_withdraw_fill(lake_id, withdraw_fill_ts)
# if values are daily rates, then user should indicate daily = True

# Otherwise, the Cheze river discharge (en amont) can be found here:
    # D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits\J736422001_QmnJ(n=1_non-glissant) raw_cheze_plelan-le-grand.csv


######################
### --- others --- ###
######################
# =============================================================================
# BV.lakeres.update_definition(lake_id, new_lake_id, new_mask_path)
# =============================================================================

# =============================================================================
# BV.lakeres.remove(lake_id)
# =============================================================================


BV.save_object()


#%%% (Input flow)
# (used here to force a return flow)
# Return flow time series
return_flow_series = dam_input_df['resti']
# return_flow_series can also be a .txt file

# Coordinates of the cell where the return flow is mesured
return_flow_coords = (331500, 6781425) # tuple or list of tuples 
# =============================================================================
# fixed_flow_coords = os.path.join(root_dir, 'examples', '99_reservoir and dam',
#                                  'data', 'additional', 'coords_forcedflow.txt')
# =============================================================================
                    # the coords can also be indicated as a .txt file

bound_id = 0 # identifier for the cell (or cells) where the return flow will be forced
snap_dist = 200
BV.settings.add_inputflow(bound_id, return_flow_coords, snap_dist,
                          return_flow_series)

# To remove a forced-flow cell or group of cells:
# BV.lakeres.remove_flowbound(bound_id)


#%% PARAMETRISATION

##%%% Définitions :
# Paramètres cadres
box = True # or False
sink_fill = False # or True
plot_cross = True

# Paramètres climatiques
first_clim = BV.climatic.recharge[0] # 'mean' # or 'first or value

# Paramètres hydrauliques
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 20 # if bottom is None, aquifer thickness
hyd_cond = 1.4e-4 * 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 0.1 / 100 # [%]
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Conditions aux limites
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Paramètres de suivi des particules
zone_partic = 'watershed' # or 'domain''

# "Split temp" : à supprimer à terme (split_temp -> dis_perlen, = 'days' par défaut)
split_temp = True

##%%% Mise à jour :
BV.add_settings()

# Nom du modèle
model_name = 'base'
BV.settings.update_model_name(model_name)

BV.add_geometric() # soon
BV.add_hydraulic()

# Paramètres cadre
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Paramètres climatiques
# BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Paramètres hydrauliques
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / n'intervient pas si bottom != None
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Conditions aux limites
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

# Paramètres du suivi des particules
BV.settings.update_input_particules(zone_partic=zone_partic)

# Lacs/reservoirs
try:
    BV.lakeres
except AttributeError:
    BV.lakeres = None
    
# "Split temp" : à supprimer à terme (split_temp -> dis_perlen, = 'days' par défaut)
BV.settings.update_split_temporal(split_temp)

BV.save_object()

#%% VISUALISATION DU MAILLAGE

mf = flopy.modflow.Modflow.load(os.path.join(
    BV.simulations_folder, model_name, model_name+'.nam'))
gridname = os.path.join(BV.simulations_folder+model_name, model_name+'.dis')
grid_model = mf.modelgrid
hk_grid = mf.upw.hk
sy_grid = mf.upw.sy

fig, axs = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
axs = axs.ravel()

ax = axs[0]
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Row': int((grid_model.shape[1])/2)})
val = hk_grid.array/24/3600 # m/s
try:
    for i in range(val.shape[0]):
        val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
except:
    pass
cb = modelxsect.plot_array(val, ax=ax, cmap='viridis', lw=0.5, norm=mpl.colors.LogNorm(vmin=1e-3,vmax=1e-8))
ax.set_title('Hydraulic conductivity [m/s] - Meshgrid West to East', fontsize=12)
ax.set_xlim(0, 9000)
ax.set_ylim(40, 150)
ax.set_xticks([0,2000,4000,6000,8000])
ax.set_yticks([50,75,100,125,150])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
fig.suptitle(model_name.upper(), x=0.22, y=1.05, fontsize=8)
fig.colorbar(cb)
plt.tight_layout()

ax = axs[1]
modelxsect = flopy.plot.PlotCrossSection(model=mf, line={'Column': int((grid_model.shape[2])/2)})
cb = modelxsect.plot_array(sy_grid.array*100, ax=ax, cmap='viridis', lw=0.5,
                            # vmin=0, vmax=30,
                            norm=mpl.colors.LogNorm(vmin=0.1, 
                                                    vmax=10))
ax.set_title('Specific yield [%] - Meshgrid South to North', fontsize=12)
ax.set_xlim(0, 5500)
ax.set_ylim(40, 150)
ax.set_xticks([0,1000,2000,3000,4000,5000])
ax.set_yticks([50,75,100,125,150])
ax.set_xlabel('Distance [m]')
fig.suptitle(model_name.upper(), x=0.5, y=1.0, fontsize=8)
fig.colorbar(cb)
plt.tight_layout()

#%% SIMULATION DU MODELE (Modflow)
model_name = BV.settings.model_name
sim_state = BV.settings.sim_state

# model_modflow = BV.preprocessing_modflow(BV.simulations_folder)
model_modflow = BV.preprocessing_modflow()
BV.save_object() # because self.lakeres.lake_by_num_id has been updated

success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

h5file = os.path.join(BV.simulations_folder,
                      'results_listing_' + model_name)

##%%% Save
mdflw_dict = {}
mdflw_dict['model_name'] = model_name
mdflw_dict['success_modflow'] = success_modflow
mdflw_dict['model_modflow'] = model_modflow

dd.io.save(h5file, mdflw_dict)

#%%% Rechargement des résultats du modèle Modflow
model_name = 'base'

h5file = os.path.join(BV.simulations_folder,
                      'results_listing_' + model_name)

mdflw_dict = dd.io.load(h5file)
model_name = mdflw_dict['model_name']
success_modflow = mdflw_dict['success_modflow']
model_modflow = mdflw_dict['model_modflow']

#%% POST-PROCESSING
start_time = datetime.datetime.now()
print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
##%%% Netcdf
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = True,
                              # lake_seepage = True,
                              export_all_tif = False,)


##%%% Timeseries
model_modpath = None # because transient
timeseries_results = BV.postprocessing_timeseries(model_modflow,
                                                  model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True) # or None

##%%% NetCDF
netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                          actual_date=True)

now = datetime.datetime.now()
print("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
print("Total time:", now - start_time)