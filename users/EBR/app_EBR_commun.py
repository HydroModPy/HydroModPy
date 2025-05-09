#%%
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

#%% CHARGEMENT DES BIBLIOTHEQUES, MODULES ET DU DOSSIER RACINE

# Filtrer les avertissements (avant les imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # A placer après DeprecationWarning car elle même obsolète...
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Bibliothèques installées par défaut
import sys
import os
import datetime
import logging

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
try:
    from os.path import abspath, dirname
    root_dir = dirname(dirname(dirname(abspath(__file__))))
except NameError:
    root_dir = os.path.dirname(os.path.dirname(os.getcwd()))  # Pour les notebooks

sys.path.append(root_dir)

cwd = os.getcwd()
logging.info(f"Le répertoire courant est : {cwd}")
if cwd != root_dir:
    os.chdir(root_dir)
    logging.info(f"Répertoire racine défini : {root_dir}")

#% Modules HydroModPy
import src
import importlib
importlib.reload(src)
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root
from matplotlib.dates import DateFormatter

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% Initialiser le gestionnaire de logs en mode développement
log_manager = toolbox.LogManager(mode="dev", # Utiliser mode="verbose" pour afficher les logs INFO et supérieur et mode="quiet" pour afficher les logs WARNING et supérieur
                                    #  log_dir="", # Utiliser log_dir pour spécifier le répertoire des logs
                                    # overwrite=False # Utiliser overwrite=True pour écraser les fichiers de logs existants
                                    # verbose_libraries=True # Utiliser verbose_libraries=True pour afficher les logs des bibliothèques (waring et supérieur)
                                     )

#%% DOSSIERS UTILISATEUR
# out_path = folder_root.root_folder_results()
out_path = "/home/bb/Documents/02_Output_HydroModPy" # Voir pourquoi ça ne fonctionne pas sous Linux
# Pour modifier ce chemin : out_path = folder_root.update_root_folder_results()
logging.info(f"Les résultats des simulations seront stockés dans le dossier {out_path}")

data_path = os.path.join(out_path, 'LakeRes')
os.makedirs(data_path, exist_ok=True)

if os.listdir(data_path):
    logging.info(f"Les données d'entrée du modèle sont stockées dans le dossier {data_path}")
else:
    logging.critical(f"Le dossier {data_path} est vide. Avant toute utilisation, il est nécessaire de télécharger vers ce dossier les données d'entrée du modèle (voir lien fourni)")
    sys.exit()

#==============================================================================
#%% PARAMETRISATION DU MODELE

# Paramètres généraux
first_year = 2023
last_year = 2023
sim_state = 'transient' # transitoire
freq_input = 'D' # hebdomadaire

subbassin = False
load_geographic = False
save_object = True # Pour geographic
dis_perlen = True # "Split temp" : à supprimer à terme (split_temp -> dis_perlen, = 'days' par défaut)
model_name = 'base'
visual_plot = False

# outlet after the dam ("pont romain")
from_xyv = [331315, 6781273, 200, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
# Station de débit à Plélan-le-Grand : [x, y] = [324472, 6779605]

# Paramètres cadres
box = False # or False
sink_fill = False # or True
plot_cross = True

# Paramètres hydrauliques
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 24.86968801 # if bottom is None, aquifer thickness
hk = 0.000114826* 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
hk_vertical = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
sy = 0.003807997
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Conditions aux limites
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Paramètres de suivi des particules
zone_partic = 'watershed' # or 'domain'

#==============================================================================
#%% BASSIN VERSANT
dem_path = os.path.join(data_path, 
                        "MNT",
                        f"MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif")

hk_str = f"{hk / (24 * 3600):.1e}"

watershed_name = '_'.join([
    'barrage_Cheze_SFR_LAK',
    pd.to_datetime("today").strftime("%Y-%m-%d"),
    timestamp := datetime.datetime.now().strftime("%H-%M"),
    # f"thick_{thick}",
    # f"hk_{hk_str}",
    # f"sy_{sy*100:.1f}",
    f"{freq_input}"
])

logging.info('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load_geographic,
                              watershed_name=watershed_name,
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              save_object=save_object)

#%% DONNEES PONCTUELLES
if subbassin is True:
    hydrometry_path = os.path.join(data_path,
                                "Stations jaugeage")
    BV.add_hydrometry(hydrometry_path, 'france hydrometric stations.shp')

    intermittency_path= os.path.join(data_path,
                                    "Stations ONDE")
    BV.add_intermittency(intermittency_path, 'regional onde stations.shp')

    BV.add_subbasin(sub_snap_dist=200)
#%% SOUS-BASSINS
geol_path = os.path.join(data_path,
                        "Geologie")
BV.add_geology(geol_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
hydrography_path = os.path.join(data_path,
                                r"Hydrographie")

# Utilisation d'un clip sur la bretagne pour éviter de charger trop de données
BV.add_hydrography(hydrography_path, types_obs=['CoursEau_FXX_clip_bre'], fields_obs=['fid'])

#%% (VISUALISATIONS DU SITE D'ETUDE)
if visual_plot is True :
    # General plot of the study site
    visualization_watershed.watershed_local(dem_path, BV)
    visualization_watershed.watershed_geology(BV)
    visualization_watershed.watershed_dem(BV)

#%% RECHARGE et RUISSELLEMENT DE SURFACE DIRECT (données d'entrée)
BV.add_climatic()

# # Reanalyse
# BV.climatic.update_sim2_reanalysis(var_list=['recharge', 'runoff', 'precip',
#                                              'evt', 'etp', 't',
#                                               ],
#                                        nc_data_path=os.path.join(
#                                            data_path,
#                                            r"Meteo\Historiques SIM2"),
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state,
#                                        spatial_mean=True,
#                                        geographic=BV.geographic,
#                                        disk_clip='watershed') # for clipping the netcdf files saved on disk
#                                                                 # can be a shapefile path or a flag: 'watershed' or False
# # Units
# BV.climatic.evt = BV.climatic.evt / 1000 # from mm to m
# BV.climatic.etp = BV.climatic.etp / 1000 # from mm to m
# BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m
# BV.climatic.t = BV.climatic.t / 1000 # from mm to m
# #%% Reanalyse Surfex
# # Besoin de le mettre à jour qu'une fois par an.
# # BV.add_safransurfex("C:\\Users\\basti\\Documents\\Output_HydroModPy\\LakeRes\\Meteo\\REA")

# BV.climatic.update_recharge_reanalysis(path_file=os.path.join(data_path, 'Meteo', 'REA', 'climatic_historic_to_2024', '_REC_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# BV.climatic.update_runoff_reanalysis(path_file=os.path.join(data_path, 'Meteo', 'REA', 'climatic_historic_to_2024', '_RUN_D.csv'),
#                                        clim_mod='REA',
#                                        clim_sce='historic',
#                                        first_year=first_year,
#                                        last_year=last_year,
#                                        time_step=freq_input,
#                                        sim_state=sim_state)

# BV.climatic.update_recharge(BV.climatic.recharge / 1000, sim_state=sim_state) # from mm to m
# BV.climatic.update_runoff(BV.climatic.runoff / 1000, sim_state=sim_state) # from mm to m

# =============================================================================
# Exportation des données climatiques
# =============================================================================
# df_climatic = pd.DataFrame({
#     'recharge': BV.climatic.recharge,
#     'runoff': BV.climatic.runoff,
#     'precip': BV.climatic.precip,
#     'evt': BV.climatic.evt,
#     'etp': BV.climatic.etp,
#     't': BV.climatic.t,
#     })
# df_climatic.to_csv(os.path.join(data_path,'Meteo', 'Historiques SIM2', 'climatic_data.csv'))

# =============================================================================
# Lecture des données climatiques
# =============================================================================
df_climatic = pd.read_csv(os.path.join(data_path,'Meteo', 'Historiques SIM2', 'climatic_data.csv'), index_col=0, parse_dates=True)
df_climatic.index = pd.to_datetime(df_climatic.index)
df_climatic = df_climatic.loc[(df_climatic.index >= pd.Timestamp("01/01/{}".format(first_year))) &
                              (df_climatic.index <= pd.Timestamp("31/12/{}".format(last_year)))]

agg_dict = {'recharge': 'sum',
            'runoff': 'sum',
            'precip': 'sum',
            'evt': 'sum',
            'etp': 'sum',
            't': 'mean'}
df_climatic = df_climatic.resample(freq_input).agg(agg_dict)

# =============================================================================
# Chargement des données climatiques
# =============================================================================
BV.climatic.recharge = df_climatic['recharge']
BV.climatic.runoff = df_climatic['runoff']
BV.climatic.precip = df_climatic['precip']
BV.climatic.evt = df_climatic['evt']
BV.climatic.etp = df_climatic['etp']
BV.climatic.t = df_climatic['t']

# Paramètres climatiques
first_clim = BV.climatic.recharge[0] # 'mean' # or 'first or value
# BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

#%% Figures des chroniques climatiques
if visual_plot is True :
    if isinstance(BV.climatic.recharge, float):
        logging.info(f"Recharge moyenne = {BV.climatic.recharge} m")
        logging.info(f"Ruissellement de surface moyen = {BV.climatic.runoff} m")
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

logging.info("\n-----------" + "-"*len(lake_id))
logging.info(f"Ajout de '{lake_id}'")
logging.info("-----------" + "-"*len(lake_id))
logging.info("   . Définition de la géographie du réservoir :")

# maskmx = os.path.join(data_path,"Reservoir", "Masque", "Cheze_lake_75m_larger.tif")
maskmx = os.path.join(data_path,"Reservoir", "Masque", "Cheze_polygon_larger.shp")

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
# =============================================================================
# outlet_file = os.path.join(data_path, "Reservoir", 
#                            "Exutoire alternatif", "lakeres_outlets.shp")
# BV.lakeres.update_outlet(lake_id, outlet_file)
# =============================================================================


# ---- Chargement des flux d'entrée à partir des données mensuelles
logging.info("   . Chargement des flux d'entrée journaliés du réservoir")

dam_input_path = os.path.join(data_path, "Reservoir", 
                             "Donnees journalieres EBR",
                             r"dam_input_2004_2024.csv")

dam_input_df = pd.read_csv(
    dam_input_path,
    sep = ";",
    header = 0,
    skiprows = 0,
    index_col = 'time',
    parse_dates = True,
    dayfirst = True,
    )

rules = {
    'cheze_lvl': 'mean',
    'cheze_vol': 'mean',
    'canut':'mean',
    'meu':'mean',
    'usine':'mean',
    'resti':'mean',
    }

dam_input_df = dam_input_df.resample(freq_input).agg(rules)

dam_input_df = dam_input_df.loc[
    (dam_input_df.index >= pd.Timestamp("01/01/{}".format(first_year))) &
    (dam_input_df.index <= pd.Timestamp("31/12/{}".format(last_year)))
    ]

level_init = dam_input_df['cheze_lvl'].loc[BV.climatic.recharge.index[0]].item()

BV.lakeres.update_stageinit(
    lake_id,
    level_init) # [m]

# ---- Mise-à-jour des données d'entrée du réservoir
logging.info("   . Mise à jour des paramètres du réservoir")

# Set the first value (used for steady initialization) as the average value
dam_input_df.iloc[0] = toolbox.hydrological_mean(dam_input_df, 4)

##%%% Mise-à-jour des flux

# Environmental fluxes (by default, fluxes are set to 0) 
# ------------------------------------------------------
# User can update these fluxes with float, file path, or "from_climatic" mode
# BV.lakeres.update_precip(lake_id, dam_input_df['ppt_surf']/1.73e6) # because Ronan's values were summed over 1.73 km² area
# BV.lakeres.update_precip(lake_id, 'from_climatic')
BV.lakeres.update_precip(lake_id, BV.climatic.precip)
# BV.lakeres.update_evap(lake_id, dam_input_df['ae_oudin']/1.73e6)
# BV.lakeres.update_evap(lake_id, 'from_climatic')
BV.lakeres.update_evap(lake_id, BV.climatic.evt)
# Note: runoff has to be a volume
# BV.lakeres.update_runoff(lake_id, BV.climatic.runoff * (30-3.31)*1e6) # because runoff has to be a volume (summed over the area runing off towards the lake)
BV.lakeres.update_runoff(lake_id, BV.climatic.runoff * (BV.geographic.resolution**2), runoff_accumulation = True)

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


BV.save_object()


#%% ECOULEMENTS DE SURFACE avec StreamFlow Routing
BV.add_streamflow_seepage(icalc = 1)
# icalc = 0: instant routing (default)
# icalc = 1: rectangular Manning

# ---- Generate reach and segment inputs
# Note: segment and reach data are first defined as pandas.DataFrames.
# They are converted into numpy.recarrays in modflow.py

# Load data from files
# =============================================================================
# temp_data_folder = r"D:\2- Postdoc\2- Travaux\8_Dam_EBR\dev_perso\couplage lac-riviere\SFR"
# BV.streamflow_seepage.load_data(
#     reach_data = os.path.join(temp_data_folder, r"ex3_test1_reach_data.csv"),
#     segment_data = os.path.join(temp_data_folder, r"ex3_test1_segment_data.csv"))
# =============================================================================

# ---- Update data
### These values can also be passed as arguments in the 'add_streamflow_seepage' call

# Area where the SFR seepage will be applied:
# BV.streamflow_seepage.update_area('watershed')
BV.streamflow_seepage.update_area('watershed', 0.7)
# Standard values for segment_data:
depth = 0 # 0.1 # self.thick # 1 # arbitrary
hcond_max = 0.08 # 3e-5 # self.hyd_cond[0, 0] # 864000
# width = 1 # self.resolution # 1.5  # arbitrary
thickm = 0.1 # Modflow does not run if thickm = 0
# Update segment data
BV.streamflow_seepage.update_segment_data('thickm', thickm)
BV.streamflow_seepage.update_segment_data('depth', depth)
BV.streamflow_seepage.update_segment_data('hcond', hcond_max)
BV.streamflow_seepage.update_segment_data('roughch', 0.03)
# BV.streamflow_seepage.update_segment_data('width', width)

# The following option drastically increases the loading time of Modflow processing
# Instead, here, the runoff is added directly to the lake.
# It should not be forgotten to sum it as well to the accumulation_flux in post-processing
# =============================================================================
# BV.streamflow_seepage.update_segment_data('runoff', BV.climatic.runoff)
# =============================================================================

# Update reach data
# =============================================================================
# BV.streamflow_seepage.update_reach_data(<name>, <val>)
# =============================================================================

# ---- Correct cells critical for convergence
# =============================================================================
# hcond_min = 0.000100
# # critical_area_path = r"file.tif"
# BV.streamflow_seepage.critical_cells(hcond = hcond_min, area = 'sinks', 
#                                      sink_threshold = 300)
# =============================================================================

# ---- Activate input corrections
BV.streamflow_seepage.correct('multiple_reaches', False)
BV.streamflow_seepage.correct('elevations', True)

BV.save_object()


#%% UPDATE PARAMETRISATION

##%%% Mise à jour :
BV.add_settings()

### Update
BV.settings.update_model_name(model_name)

#BV.add_geometric() # soon
BV.add_hydraulic()

# Paramètres cadre
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

# Paramètres hydrauliques
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / n'intervient pas si bottom != None
BV.hydraulic.update_hk(hk) # Ancient hyd_cond
BV.hydraulic.update_sy(sy) # Ancient porosity
BV.hydraulic.update_hk_vertical(hk_vertical)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Conditions aux limites
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

# Paramètres du suivi des particules
# =============================================================================
# BV.settings.update_input_particules(zone_partic=zone_partic)
# =============================================================================
    
# "Split temp" : à supprimer à terme (split_temp -> dis_perlen, = 'days' par défaut)
BV.settings.update_dis_perlen(dis_perlen)

BV.save_object()

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
# =============================================================================
# model_name = 'base'
# 
# h5file = os.path.join(BV.simulations_folder,
#                       'results_listing_' + model_name)
# 
# mdflw_dict = dd.io.load(h5file)
# model_name = mdflw_dict['model_name']
# success_modflow = mdflw_dict['success_modflow']
# model_modflow = mdflw_dict['model_modflow']
# =============================================================================

#%% POST-PROCESSING
start_time = datetime.datetime.now()
logging.info("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
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
                              lake_leakage = True,
                              export_all_tif = False,)

#%%
##%%% Timeseries
model_modpath = None # because transient
timeseries_results = BV.postprocessing_timeseries(model_modflow,
                                                  model_modpath,
                                                  datetime_format=True, 
                                                  subbasin_results=True) # or None

##%%% NetCDF
netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                          datetime_format=True)

now = datetime.datetime.now()
logging.info("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
logging.info("Total time:", now - start_time)

#%% VISUALISATION DU MAILLAGE
if visual_plot is True :
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
# %%
#%% COMPARAISON DES VOLUMES OBSERVÉS ET SIMULÉS
# Récupération des données de volume observé
observed_volume = dam_input_df['cheze_lvl']

# Récupération des données de volume simulé
lake_id = 'reservoir_cheze'
volume_column = f'{lake_id}_level'
timeseries_results = timeseries_results.mfdata
# Vérification que la colonne existe dans les résultats
if volume_column in timeseries_results.columns:

    simulated_volume = timeseries_results[volume_column]
    
    common_dates = observed_volume.index.intersection(simulated_volume.index)
    if len(common_dates) > 0:
        observed_volume = observed_volume.loc[common_dates]
        simulated_volume = simulated_volume.loc[common_dates]

        plt.figure(figsize=(12, 6))
        plt.plot(observed_volume.index, observed_volume, 'b-', linewidth=2, label='Volume observé')
        plt.plot(simulated_volume.index, simulated_volume, 'r--', linewidth=2, label='Volume simulé')
        
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Volume (m³)', fontsize=12)
        plt.title('Comparaison des volumes observés et simulés du réservoir Cheze', fontsize=14)
        plt.legend(fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.7)
        
        if freq_input == 'D':
            plt.gcf().autofmt_xdate()
            plt.gca().xaxis.set_major_formatter(DateFormatter('%d-%m-%Y'))
        elif freq_input == 'W':
            plt.gca().xaxis.set_major_formatter(DateFormatter('%d-%m-%Y'))
        else:
            plt.gcf().autofmt_xdate()
        
        # Annotations
        plt.text(0.01, 0.01, f'Modèle: {model_name}', transform=plt.gca().transAxes, 
                    fontsize=8, verticalalignment='bottom')
        
        plt.tight_layout()
        
        output_dir = os.path.join(BV.simulations_folder, model_name, '_figures')
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, 'volume_comparison.png'), dpi=300)
        plt.show()
    else:
        logging.warning("Aucune date commune entre les données observées et simulées.")
else:
    logging.warning(f"La colonne '{volume_column}' n'existe pas dans les résultats des séries temporelles.")
    logging.warning("Colonnes disponibles: " + ", ".join(timeseries_results.columns))
# %%
