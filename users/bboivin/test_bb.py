#%% CHARGEMENT DES BIBLIOTHEQUES ET MODULES

# Filtrer les avertissements (avant les imports)
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import pkg_resources # A placer après DeprecationWarning car elle même obselète...
warnings.filterwarnings('ignore', message='.*pkg_resources.*')
warnings.filterwarnings('ignore', message='.*declare_namespace.*')

# Bibliothèques installées par défaut
import sys
import os
import requests
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
# print(f"Le répertoire courant est : {cwd}")
if cwd != root_dir:
    os.chdir(root_dir)
    # print(f"Répertoire racine défini : {root_dir}")

#% Modules HydroModPy
import src
import importlib
importlib.reload(src)
from src import watershed_root
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

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
    
