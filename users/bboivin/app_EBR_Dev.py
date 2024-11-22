# -*- coding: utf-8 -*-
"""
Created on Wed Dec  6 22:19:57 2023

Launch code for HydroModPy simulation of Cheze reservoir for EBR
@author: Alexandre Coche & Bastien Boivin

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
warnings.filterwarnings("ignore", category=DeprecationWarning)

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
root_dir = os.path.dirname(os.path.dirname(os.getcwd())) # Utilisation de os.getcwd() car notebook prend pas en compte __file__
sys.path.append(root_dir)

cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    # print("Le répertoire racine est : {0}".format(cwd))

#% Modules HydroModPy
import importlib
import src
importlib.reload(src)
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large


#%% DOSSIERS UTILISATEUR
out_path = folder_root.root_folder_results()
# out_path = folder_root.update_root_folder_results()
# Pour modifier ce chemin : out_path = folder_root.update_root_folder_results()

print(f"Les résultats des simulations seront stockés dans le dossier {out_path}\n")

data_path = os.path.join(os.path.dirname(out_path), 'LakeRes')
print(f"Les données d'entrée du modèle sont stockées dans le dossier {data_path}\n")
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
watershed_name = '_'.join(['barrage_Cheze_SFR_LAK', pd.to_datetime("today").strftime("%Y-%m-%d")])
# outlet after the dam ("pont romain")
from_xyv = [331315, 6781273, 200, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
# Station de débit à Plélan-le-Grand : [x, y] = [324472, 6779605]
save_object = True
# %%
