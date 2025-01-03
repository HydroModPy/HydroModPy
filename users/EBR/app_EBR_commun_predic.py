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
# =============================================================================
# if os.getenv('PROJ_LIB') is not None:
#     os.environ.pop('PROJ_LIB')
# =============================================================================
import xarray as xr
xr.set_options(keep_attrs = True)
import yaml

# Pour recharger les résultats de l'historique
import flopy.utils.binaryfile as fpu

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

#% Personal toolbox to handle NetCDF
import trajectoire_toolbox as ttbox
import geoconvert as gc

#%% ARGUMENTS D'ENTREE
try:
    scenario = sys.argv[1]
except:
    print("Le scenario est normalement défini lors du lancement du script dans la console.")
    scenario = input("Comme ce n'est pas le cas ici, il est nécessaire d'indiquer manuellement le scenario choisi : ")
    # Correction extension :
    if os.path.splitext(scenario)[-1] == '': scenario += '.csv'

#%% DOSSIERS UTILISATEUR
out_path = folder_root.root_folder_results()
# Pour modifier ce chemin : out_path = folder_root.update_root_folder_results()

print(f"Les résultats des simulations seront stockés dans le dossier {out_path}\n")

data_path = os.path.join(out_path, 'LakeRes')
if not os.path.exists(data_path):
    os.makedirs(data_path)
if len(os.listdir(data_path)) == 0:
    print(f"Warning : Le dossier {data_path} est vide. Avant toute utilisation, il est nécessaire de télécharger vers ce dossier les données d'entrée du modèle (voir lien fourni)\n")

#%% CHARGEMENT DU FICHIER DE PARAMETRES
with open(os.path.join(data_path, 'settings.yaml'), 'r') as file_object:
    settings = yaml.load(file_object, Loader = yaml.SafeLoader)
            
# Raffinage de la startdate
if ('startdate' not in settings) | (settings['startdate'] in ["aujourd'hui", "today"]):
    settings['startdate'] = pd.to_datetime("today")   


#%% BASSIN VERSANT 
##%%% Options: Charger MNT
dem_path = os.path.join(data_path, 
                        "MNT",
                        "MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif")
watershed_name = '_'.join(['barrage_Cheze_SFR_LAK', settings['startdate'].strftime("%Y-%m-%d")])
# outlet after the dam ("pont romain")
from_xyv = [331315, 6781273, 200, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
# Station de débit à Plélan-le-Grand : [x, y] = [324472, 6779605]
save_object = True

#%%% Recharger GEOGRAPHIC
print('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              watershed_name=watershed_name,
                              load=True)


#%% RECHARGE et RUISSELLEMENT DE SURFACE DIRECT (données d'entrée)
freq_input = 'W' # hebdomadaire

#%% RECHARGEMENT DES CHARGES PRECEDENTES
model_name = 'historique'
head_fpu = fpu.HeadFile(os.path.join(BV.simulations_folder,
                                     model_name,
                                     f'{model_name}.hds'))

# sim_times = head_fpu.get_times()
# prev_end_time = sim_times[list(sim_times.keys())[-1]]
prev_end_time = head_fpu.get_times()[0]

# Retrieve head_fpu and call modflow with these previous heads
prev_head_3D = head_fpu.get_data(totim = prev_end_time) # recharge les dernières charges hydrauliques de l'historique
                                                        # 3 dim = layer, y, x

head_fpu.close()

#%% BARRAGE
lake_id = 'reservoir_cheze' 
# A terme il faudrait adapter le script et le settings.yaml pour pouvoir gérer 
# des réservoirs multiples

# ---- Mise à jour du niveau initial
print("   . Mise à jour du niveau initial de la retenue avec les résultats de la simulation historique")

# Récupération du niveau final du réservoir
# -----------------------------------------
### Conserve only the first positive value from the top to bottom layer:
# Negative values will be considered as nodata
prev_head_3D[prev_head_3D < 0] = np.nan 
# Squish (flatten) the 4D array into a single-layer array
head_2D = prev_head_3D[0, :, :].copy() # 2 dim = y, x
# Browse all the layers, from the top to the bottom, and keep the first 
# encountered postive (or null) values
for layer in range(0, prev_head_3D.shape[0]):
    head_2D[np.isnan(head_2D)] = prev_head_3D[layer, :, :][np.isnan(head_2D)]
# =============================================================================
# # Apply the mask
# head_2D[self.dem_mask] = np.nan
# =============================================================================

outlet_mask = head_2D.copy()*0
i, j = BV.lakeres.ij_outlet_by_lake[lake_id]
outlet_mask[i, j] = 1
np.nan_to_num(outlet_mask, nan = 0, copy = False)
outlet_mask = outlet_mask.astype(bool)

level_init = head_2D[outlet_mask][0]

BV.lakeres.update_stageinit(
    lake_id,
    level_init) # [m]


# ---- Mise à jour des flux d'entrée 
print(f"   . Mise à jour des flux d'entrée avec le scénarios de gestion : {os.path.splitext(scenario)[0]}")

dam_data_path = os.path.join(data_path, "Reservoir", 
                             "Scenarios de gestion", scenario)

dam_input_df = pd.read_csv(dam_data_path,
                           sep = ";",
                           header = 0,
                           skiprows = 0,
                           index_col = 0,
                           parse_dates = True)

# Aligne les dates avec les dates de la simulation
old_year = dam_input_df.index[
    dam_input_df.index.month == settings['startdate'].month
    ].year[0] # Trouve l'année du scénario du mois qui correspond au mois de départ de la simulation prédictive
dam_input_df.index = dam_input_df.index + pd.DateOffset(years = settings['startdate'].year - old_year) # corrige les années du scénario en fonction

# Acolle 2 répétitions de l'année de dam_input_df, étant donné qu'on simule 6 mois et qu'ils sont parfois à cheval sur 2 ans
dam_input_df_2 = dam_input_df.copy()
dam_input_df_2.index = dam_input_df_2.index + pd.DateOffset(years = 1)
dam_input_df = pd.concat([dam_input_df, dam_input_df_2], axis = 0)
# Puis découpe cette chronique sur la période d'intérêt (date de départ + 6 mois)
dam_input_df = dam_input_df[slice(settings['startdate'], settings['startdate'] + pd.DateOffset(months = 6))]

# ---- Mise-à-jour des données d'entrée du réservoir
print("   . Mise à jour des paramètres du réservoir")

# Anthropic fluxes (including withdrawing return flow)
# ----------------
# Convert into cumsum with the same time resolution as recharge
withdraw_fill_ts = dam_input_df['usine'] - dam_input_df['canut'] - dam_input_df['meu'] 
# Then substract the return flux
withdraw_fill_ts = withdraw_fill_ts + dam_input_df['resti']
BV.lakeres.update_withdraw_fill(lake_id, withdraw_fill_ts)
# if values are daily rates, then user should indicate daily = True

# Inject return flow to the surface streamflow
# --------------------------------------------
# Injecter le débit de restitution dans la rivière à l'exutoire du réservoir 
# (procédure liée au module SFR suivant)
# =============================================================================
# BV.lakeres.connect_returnflow(lake_id, dam_input_df['resti'])
# =============================================================================
# 1. This option drastically increases the loading time of Modflow processing
# Therefore, here, it is not added to the streamflow routing.
# It should not be forgottent to sum it to the accumulation_flux in post-processing

# 2. Alternative option: shortened version of 'resti' timeseries
resti1 = dam_input_df.iloc[0]['resti']
date_idx = []
resti_mean = []
for d in dam_input_df.index[:-1]:
    resti2 = dam_input_df.loc[d, 'resti']
    if abs(resti1 - resti2)/resti2 > 0.10:
        date_idx += [d]
    resti1 = resti2
date_idx = [dam_input_df.index[0]] + date_idx + [dam_input_df.index[-1]]
resti_short = pd.Series(index = date_idx, name = 'resti')
for i in range(0, resti_short.size - 1):
    id1 = resti_short.index[i]
    id2 = resti_short.index[i+1]
    resti_short.loc[id1] = dam_input_df[id1:id2][0:-1]['resti'].mean()
resti_short = resti_short[0:-1]
BV.lakeres.connect_returnflow(lake_id, resti_short)


######################
### --- others --- ###
######################
# =============================================================================
# BV.lakeres.update_definition(lake_id, new_lake_id, new_mask_path)
# =============================================================================

# =============================================================================
# BV.lakeres.remove(lake_id)
# =============================================================================


# =============================================================================
# BV.save_object()
# =============================================================================

#%% SIMULATION DU MODELE (Modflow)
sim_state = BV.settings.sim_state

#%%% Récupération des résultats de la simulation historique
h5file = os.path.join(BV.simulations_folder,
                      'results_listing_' + model_name)
mdflw_dict = dd.io.load(h5file)
success_modflow = mdflw_dict['success_modflow']
model_modflow = mdflw_dict['model_modflow']
# =============================================================================
# model_modflow = BV.preprocessing_modflow(model_modflow)
# =============================================================================

#%%% Lancement des simulations prédictives (et mise à jour du modèle)
# ---- Créer un dossier par scénario de gestion
# =============================================================================
# if not os.path.exists(os.path.join(out_path, 
#                       BV.simulations_folder, 
#                       os.path.splitext(scenario)[0])):
#     os.makedirs(os.path.join(out_path, 
#                              BV.simulations_folder, 
#                              os.path.splitext(scenario)[0]))
# =============================================================================

list_model_name = []
list_success_modflow = []
list_model_modflow = []

# ---- Extraction des variables climatiques
forecast_path = os.path.join(data_path, "Meteo", "Previsions 6 mois C3S")
# =============================================================================
# clim_ds = ttbox.ouvrir(
#     os.path.join(forecast_path, f"C3S_{settings['startdate'].strftime('%Y-%m')}.nc"), # 'C3S_2024-10.nc'),
#     decode_times = True, decode_coords = 'all')
# =============================================================================
clim_ds = ttbox.convertir_cwatm(
    os.path.join(forecast_path, f"C3S_{settings['startdate'].strftime('%Y-%m')}.nc"), 
    'C3S',
    )

clim_ds = ttbox.georeferencer(
    data = clim_ds,
    dst_crs = 4326, include_crs = True)

# Période
clim_ds = clim_ds.loc[{'time': slice(settings['startdate'], None)}]

# Frequence
"""
Toute cette gestion devrait à terme pouvoir être faite dans un script dédié,
de la même manière que pour sim2 :
    BV.climatic.update_c3s_previsions(....)
Ce script téléchargerait automatiquement les données via l'API.

NB : A terme il faudrait aussi pouvoir utiliser directement des donnees spatio-temporelles
Pour l'instant on convertit ca en chroniques (pandas).
"""
# clim_ds = clim_ds.resample(freq_input).mean()

# ---- Boucle sur chaque run disponible dans les données
for i in range(0, 51):    
    model_name = f'predic{i}'
    BV.settings.update_model_name(model_name)
    print('\n--------\n' + model_name + '\n--------\n')
    
    clim_ds_i = clim_ds.loc[{'number': i}]

# =============================================================================
#     clipped_ds = ttbox.reprojeter(clim_ds_i, mask = BV.geographic.watershed_shp,
#                                   resolution = (BV.geographic.resolution_x,
#                                                 BV.geographic.resolution_y),
#                                   dst_crs = BV.geographic.crs_proj)
#     
#     clim_df = clipped_ds.drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas()
#     clim_df = clim_df.resample(freq_input).mean()
# =============================================================================
    
    clim_df = gc.time_series(
        input_file = clim_ds_i,
        coords = BV.geographic.watershed_shp, epsg_coords = BV.geographic.crs_proj, 
        )
    
    recharge = clim_df['ssro']
    runoff = clim_df['sro']
    precip = clim_df['tp']
    evap = clim_df['e']
    
    # ---- Mise à jour des flux naturels sur le réservoir
    BV.lakeres.update_precip(lake_id, BV.climatic.precip)
    BV.lakeres.update_evap(lake_id, BV.climatic.evt)
    BV.lakeres.update_runoff(lake_id, BV.climatic.runoff * (BV.geographic.resolution**2), runoff_accumulation = True)
    
    # ---- Mise à jour du modèle modflow
    # model_modflow = BV.preprocessing_modflow(for_calib=False)
    BV.update_modflow(
        model_modflow, 
        {'model_name': model_name,
         'full_path': os.path.join(
             os.path.split(model_modflow.full_path)[0], 
             os.path.splitext(scenario)[0],
             model_name),
         'heads': prev_head_3D, 
         'recharge': recharge,
         'lakeres': BV.lakeres,
         # 'sim_state': 'steady' si on veut
         })
    
    # ---- Simulation
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
    
    list_model_name.append(model_name)
    list_success_modflow.append(success_modflow)
    list_model_modflow.append(model_modflow)

mdflw_dict = {}
mdflw_dict['list_model_name'] = list_model_name
mdflw_dict['list_success_modflow'] = list_success_modflow
mdflw_dict['list_model_modflow'] = list_model_modflow
h5file = os.path.join(BV.simulations_folder, 'results_listing_predic')
    
dd.io.save(h5file, mdflw_dict)

#%%% Rechargement des résultats du modèle Modflow
# =============================================================================
# h5file = os.path.join(BV.simulations_folder,
#                       'results_listing_predic')
# 
# mdflw_dict = dd.io.load(h5file)
# list_model_name = mdflw_dict['model_name']
# list_success_modflow = mdflw_dict['success_modflow']
# list_model_modflow = mdflw_dict['model_modflow']
# =============================================================================

#%% POST-PROCESSING
start_time = datetime.datetime.now()
print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    ##%%% General
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
