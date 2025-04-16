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
import requests
import datetime
import logging
import shutil

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
from scipy.optimize import minimize  # Pour l'optimisation Simplex
from matplotlib import patches       # Pour les visualisations
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

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% Initialiser le gestionnaire de logs en mode développement
log_manager = toolbox.LogManager(mode="dev", # Utiliser mode="verbose" pour afficher les logs INFO et supérieur et mode="quiet" pour afficher les logs WARNING et supérieur
                                    #  log_dir="", # Utiliser log_dir pour spécifier le répertoire des logs
                                    # overwrite=False # Utiliser overwrite=True pour écraser les fichiers de logs existants
                                    # verbose_libraries=True # Utiliser verbose_libraries=True pour afficher les logs des bibliothèques (waring et supérieur)
                                     )

#%% DOSSIERS UTILISATEUR
out_path = folder_root.root_folder_results()
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
first_year = 2012
last_year = 2022
sim_state = 'transient' # transitoire
freq_input = 'W' # hebdomadaire

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
thick = 26 # if bottom is None, aquifer thickness
hk = 2.55e-5* 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
hk_vertical = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
sy = 0.005 # [%]
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Conditions aux limites
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Paramètres de suivi des particules
zone_partic = 'watershed' # or 'domain''

#==============================================================================
#%% BASSIN VERSANT
dem_path = os.path.join(data_path, 
                        "MNT",
                        f"MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif")

hk_str = f"{hk / (24 * 3600):.1e}"

watershed_name = '_'.join([
    'barrage_Cheze_SFR_LAK',
    pd.to_datetime("today").strftime("%Y-%m-%d"),
    f"calib_V1_lvl"
])

logging.info('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load_geographic,
                              watershed_name=watershed_name,
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              save_object=save_object)

#%% SOUS-BASSINS
if subbassin is True:
    hydrometry_path = os.path.join(data_path,
                                "Stations jaugeage")
    BV.add_hydrometry(hydrometry_path, 'france hydrometric stations.shp')

    intermittency_path= os.path.join(data_path,
                                    "Stations ONDE")
    BV.add_intermittency(intermittency_path, 'regional onde stations.shp')
    
    BV.add_subbasin(sub_snap_dist=200)

#%% DONNEES AUXILIAIRES
geol_path = os.path.join(data_path,
                        "Geologie")
BV.add_geology(geol_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
hydrography_path = os.path.join(data_path,
                                r"Hydrographie")
BV.add_hydrography(hydrography_path, types_obs=['CoursEau_FXX_clip_bre'], fields_obs=['fid'])

#%% RECHARGE et RUISSELLEMENT DE SURFACE DIRECT (données d'entrée)
BV.add_climatic()

# =============================================================================
# Lecture des données climatiques
# =============================================================================
df_climatic = pd.read_csv(os.path.join(data_path,'Meteo', 'Historiques SIM2', 'climatic_data.csv'), index_col=0, parse_dates=True)
df_climatic.index = pd.to_datetime(df_climatic.index)
df_climatic = df_climatic.loc[(df_climatic.index >= pd.Timestamp("01/01/{}".format(first_year))) &
                              (df_climatic.index <= pd.Timestamp("31/12/{}".format(last_year)))]

agg_dict = {'recharge': 'mean',
            'runoff': 'mean',
            'precip': 'mean',
            'evt': 'mean',
            'etp': 'mean',
            't': 'mean'}
df_climatic = df_climatic.resample(freq_input).agg(agg_dict)

# =============================================================================
# Chargement des données climatiques (à implémenter dans la class directement...)
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

#%% OPTIMISATION DES PARAMÈTRES PAR MÉTHODE SIMPLEX
run_optimization = True

if run_optimization:
    optim_folder = os.path.join(BV.simulations_folder, 'optimization_results')
    os.makedirs(optim_folder, exist_ok=True)

    all_simulations_results = []

    use_time_filter = True
    
    calib_start_date = "2013-01-01"
    calib_end_date = "2022-12-31"
    
    use_seasonal_filter = False
    season_start_month = 7
    season_start_day = 1
    season_end_month = 12
    season_end_day = 31

    def filter_dates(dates):
        """Filter dates based on time and seasonal criteria"""
        if not isinstance(dates, pd.DatetimeIndex):
            dates = pd.DatetimeIndex(dates)
        mask = pd.Series(True, index=dates)
        
        if use_time_filter:
            mask = mask & (dates >= calib_start_date) & (dates <= calib_end_date)
        
            if use_seasonal_filter:
                def is_in_season(date):
                    start = pd.Timestamp(date.year, season_start_month, season_start_day)
                    # Adjust end date if season ends in the next year
                    if season_end_month < season_start_month:
                        end = pd.Timestamp(date.year + 1, season_end_month, season_end_day)
                    else:
                        end = pd.Timestamp(date.year, season_end_month, season_end_day)
                    
                    return (date >= start) & (date <= end)
                
                seasonal_mask = dates.map(is_in_season)
                mask = mask & seasonal_mask

        return mask
    
    """
    L'algorithme Simplex fonctionne mieux quand tous les paramètres sont à la même échelle
    Permet d'avoir des pas similaires dans toutes les directions de l'espace des paramètres
    Évite que des paramètres avec de grandes valeurs dominent des paramètres avec de petites valeurs
    Pour hk qui varie sur plusieurs ordres de grandeur, on utilisera une échelle logarithmique
    """
    def normalize(x, xmin, xmax):
        """Normalize a value x according to the bounds xmin and xmax"""
        return (x - xmin) / (xmax - xmin)

    def denormalize(x_norm, xmin, xmax):
        """Denormalize a value x_norm according to the bounds xmin and xmax"""
        return x_norm * (xmax - xmin) + xmin

    # Global variables for optimization
    optimization_results = {"model_name": None, "model_modflow": None, "best_error": np.inf}
    compt = 0

    # Function to run the optimization
    def erreur_modele_norm(params_norm):
        global compt, BV, dam_input_df, optimization_results, all_simulations_results
        
        # Conversion de la valeur normalisée en valeur log(hk), puis en hk
        log_hk_value = denormalize(params_norm[0], log_hk_min, log_hk_max)
        hk_value = 10**log_hk_value  # Convertir de log à valeur réelle
        
        sy_value = denormalize(params_norm[1], sy_min, sy_max)
        thick_value = denormalize(params_norm[2], thick_min, thick_max)
        
        BV.hydraulic.update_hk(hk_value)
        BV.hydraulic.update_sy(sy_value)
        BV.hydraulic.update_thick(thick_value)
        
        # Model name
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        model_name = f"optim_{compt}_{timestamp}_hk{hk_value/24/3600:.2e}_sy{sy_value*100:.2f}%_th{thick_value:.1f}"
        logging.info(f"\nSimulation {compt}: hk={hk_value/24/3600:.2e}m/s, sy={sy_value*100:.2f}%, thick={thick_value:.1f}m")
        BV.settings.update_model_name(model_name)
        
        model_modflow = BV.preprocessing_modflow()
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
        
        if not success_modflow:
            logging.error("Échec de la simulation!")
            return 1e6
        
        BV.postprocessing_modflow(model_modflow,
                                watertable_elevation=True,
                                watertable_depth=False,
                                seepage_areas=False,
                                outflow_drain=False,
                                lake_leakage=True,
                                accumulation_flux=True)
        
        BV.postprocessing_timeseries(model_modflow, 
                                    model_modpath=None, 
                                    datetime_format=True)
        
        csv_path = os.path.join(BV.simulations_folder, model_name, '_postprocess/_timeseries/_simulated_timeseries.csv')
        if not os.path.exists(csv_path):
            logging.error(f"Fichier de résultats non trouvé: {csv_path}")
            return 1e6
        
        sim_series = pd.read_csv(csv_path, sep=';', index_col=0, parse_dates=True)
        
        if "reservoir_cheze_level" not in sim_series.columns:
            logging.error("Colonne 'reservoir_cheze_level' manquante dans le fichier de résultats!")
            logging.error("Colonnes disponibles: %s", sim_series.columns.tolist())
            return 1e6
        
        simulated_series = sim_series['reservoir_cheze_level']
        if simulated_series.empty:
            logging.error("Série temporelle vide!")
            return 1e6
        
        # ---- Filtrage des dates ----
        sim_dates = simulated_series.index
        date_mask = filter_dates(sim_dates)
        filtered_dates = sim_dates[date_mask]
        simulated_volumes = simulated_series[date_mask].values
        
        if len(filtered_dates) == 0:
            logging.warning("Aucune date ne correspond aux critères de filtrage!")
            return 1e6
        
        logging.info(f"Utilisation de {len(filtered_dates)} dates sur {len(sim_dates)} pour la calibration")
        
        observed_volumes = []
        for date in filtered_dates:
            if date in dam_input_df.index:
                observed_volumes.append(dam_input_df.loc[date, 'cheze_lvl'])
            else:
                closest_date = dam_input_df.index[abs(dam_input_df.index - date).argmin()]
                observed_volumes.append(dam_input_df.loc[closest_date, 'cheze_lvl'])
        
        n = len(simulated_volumes)
        if n == 0:
            return 1e6
        
        # RMSE
        squared_errors = [(simulated_volumes[i] - observed_volumes[i])**2 for i in range(n)]
        rmse = np.sqrt(np.mean(squared_errors))
        
        # Nash-Sutcliffe Efficiency (NSE)
        mean_observed = np.mean(observed_volumes)
        numerator = sum(squared_errors)
        denominator = sum([(observed_volumes[i] - mean_observed)**2 for i in range(n)])
        if denominator == 0:
            nse = -np.inf
        else:
            nse = 1 - (numerator / denominator)
        
        # (R^2) Coefficient of determination
        mean_sim = np.mean(simulated_volumes)
        r_numerator = sum((observed_volumes[i] - mean_observed) * (simulated_volumes[i] - mean_sim) for i in range(n))
        r_denominator = np.sqrt(sum((observed_volumes[i] - mean_observed)**2 for i in range(n)) * 
                              sum((simulated_volumes[i] - mean_sim)**2 for i in range(n)))
        r_squared = (r_numerator / r_denominator)**2 if r_denominator != 0 else 0
        
        # Use the error as the objective function
        error = 1 - nse  # NSE is maximized, so we minimize 1 - NSE
        
        logging.info(f"NSE: {nse:.4f}, R²: {r_squared:.4f}, RMSE: {rmse:.2f} m³ (sur période filtrée)")
        
        # Save the results
        current_simulation = {
            "iteration": compt,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model_name": model_name,
            "hk": hk_value,
            "hk_ms": hk_value/24/3600,
            "log_hk": log_hk_value,  # Ajout du log(hk) dans les résultats
            "sy": sy_value,
            "thick": thick_value,
            "nse": nse,
            "r_squared": r_squared,
            "rmse": rmse,
            "error": error,
            "filtered_points": len(filtered_dates),
            "total_points": len(sim_dates)
        }
        
        # Append the results to the list
        all_simulations_results.append(current_simulation)
        
        pd.DataFrame(all_simulations_results).to_csv(
            os.path.join(optim_folder, 'all_simulations_results.csv'), 
            index=False
        )
        
        # Save if the error is the best so far
        if error < optimization_results["best_error"]:
            optimization_results["model_name"] = model_name
            optimization_results["model_modflow"] = model_modflow
            optimization_results["best_error"] = error
            optimization_results["best_nse"] = nse
            optimization_results["best_rmse"] = rmse
            optimization_results["best_r_squared"] = r_squared
            optimization_results["best_params"] = {
                "hk": hk_value,
                "log_hk": log_hk_value,  # Ajout du log(hk) dans les meilleurs paramètres
                "sy": sy_value,
                "thick": thick_value
            }
            optimization_results["filtered_dates"] = filtered_dates
            logging.info("► Meilleure simulation jusqu'à présent ◄")
        
        compt += 1
        return error

    # Run the optimization
    logging.info("\n=== DÉMARRAGE DE L'OPTIMISATION SIMPLEX ===")
    start_time = datetime.datetime.now()
    logging.info(f"Démarrage: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if use_time_filter:
        filter_info = f"Période de calibration: {calib_start_date} à {calib_end_date}"
        if use_seasonal_filter:
            filter_info += f", saison: {season_start_day}/{season_start_month} à {season_end_day}/{season_end_month}"
        logging.info(filter_info)
    
    # Define the bounds for the parameters using log scale for hk
    hk_min_mday, hk_max_mday = 1e-6 * 24 * 3600, 1e-3 * 24 * 3600  # m/day
    log_hk_min = np.log10(hk_min_mday)  # log10 de la valeur en m/jour
    log_hk_max = np.log10(hk_max_mday)  # log10 de la valeur en m/jour
    
    sy_min, sy_max = 0.001, 0.1  # 0.1% to 5%
    thick_min, thick_max = 20, 40  # meters
    
    # Initial values
    hk_init = hk
    sy_init = sy
    thick_init = thick
    
    # Convertir hk_init en log(hk_init) pour la normalisation
    log_hk_init = np.log10(hk_init)
    
    # Normalize the initial values with hk in log scale
    x0_norm = [
        normalize(log_hk_init, log_hk_min, log_hk_max),
        normalize(sy_init, sy_min, sy_max),
        normalize(thick_init, thick_min, thick_max)
    ]
    
    # Log des bornes et valeurs initiales pour vérification
    logging.info(f"Valeur initiale hk: {hk_init:.2e} m/jour ({hk_init/24/3600:.2e} m/s), log(hk): {log_hk_init:.4f}")
    logging.info(f"Bornes hk: [{hk_min_mday:.2e}, {hk_max_mday:.2e}] m/jour, log(hk): [{log_hk_min:.4f}, {log_hk_max:.4f}]")
    
    # Run the optimization using the Nelder-Mead method (Simplex)
    result = minimize(
        erreur_modele_norm, 
        x0_norm, 
        method='Nelder-Mead',
        options={
            'xatol': 0.01,
            'fatol': 0.01,
            'maxiter': 200,
            'disp': True
        }
    )
    
    # Conversion des résultats optimaux du log(hk) vers hk
    best_log_hk = denormalize(result.x[0], log_hk_min, log_hk_max)
    best_hk = 10**best_log_hk
    
    best_sy = denormalize(result.x[1], sy_min, sy_max)
    best_thick = denormalize(result.x[2], thick_min, thick_max)
    
    end_time = datetime.datetime.now()
    duration = end_time - start_time
    
    logging.info("\n=== RÉSULTATS DE L'OPTIMISATION ===")
    logging.info(f"Conductivité hydraulique optimale: {best_hk/24/3600:.2e} m/s ({best_hk:.2e} m/jour)")
    logging.info(f"Log(hk) optimal: {best_log_hk:.4f}")
    logging.info(f"Porosité efficace optimale: {best_sy:.4f}")
    logging.info(f"Épaisseur optimale: {best_thick:.2f} m")
    logging.info(f"NSE: {optimization_results.get('best_nse', 'N/A')}")
    logging.info(f"R²: {optimization_results.get('best_r_squared', 'N/A')}")
    logging.info(f"RMSE: {optimization_results.get('best_rmse', 'N/A')} m³")
    logging.info(f"Meilleur modèle: {optimization_results['model_name']}")
    logging.info(f"Nombre de simulations: {compt}")
    logging.info(f"Durée totale: {duration}")
    
    # Use the best parameters for the final run
    BV.hydraulic.update_hk(best_hk)
    BV.hydraulic.update_sy(best_sy)
    BV.hydraulic.update_thick(best_thick)
    
    # Update the model name with the best parameters
    model_name = f"final_optimized_hk{best_hk/24/3600:.2e}_sy{best_sy:.4f}_th{best_thick:.1f}"
    BV.settings.update_model_name(model_name)
    
    # Save the optimization results
    optim_results = {
        "best_hk": best_hk,
        "best_hk_ms": best_hk/24/3600,
        "best_log_hk": best_log_hk,  # Ajout du log(hk) dans les résultats
        "best_sy": best_sy,
        "best_thick": best_thick,
        "best_nse": optimization_results.get('best_nse'),
        "best_r_squared": optimization_results.get('best_r_squared'),
        "best_rmse": optimization_results.get('best_rmse'),
        "iterations": compt,
        "duration_seconds": duration.total_seconds(),
        "optimization_start": start_time.strftime('%Y-%m-%d %H:%M:%S'),
        "optimization_end": end_time.strftime('%Y-%m-%d %H:%M:%S'),
        "best_model": optimization_results['model_name'],
        "time_filter": {
            "enabled": use_time_filter,
            "global_start": calib_start_date,
            "global_end": calib_end_date,
            "seasonal_filter": use_seasonal_filter,
            "season_start": f"{season_start_day}/{season_start_month}",
            "season_end": f"{season_end_day}/{season_end_month}"
        }
    }
    
    # Create optimization results folder if it doesn't exist
    optim_df = pd.DataFrame([optim_results])
    optim_df.to_csv(os.path.join(optim_folder, f'optimization_results_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'), index=False)
    
    logging.info(f"Résultats d'optimisation sauvegardés dans {optim_folder}")
else:
    logging.info("Optimisation désactivée, utilisation des paramètres définis manuellement.")

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