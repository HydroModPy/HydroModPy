# -*- coding: utf-8 -*-
"""
Created on Thu May 16 10:11:52 2024

@author: ronan
"""


# WORKFLOW:
import os
import SIM2_tools as smt
# sim_folder = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\SIM2"
sim_folder = r"C:\Users\ronan\GitHub\HydroModPy-dev0.1\users\acoche\SIM2_climate\data_ronan"
# <1> Pour traiter les données par paquets, adapter la variable batch_var au 
# début de la fonction to_netcdf()
smt.folder_to_netcdf(os.path.join(sim_folder, "csv"))
smt.merge_folder(os.path.join(sim_folder, "netcdf"))
# Supprimer si besoin les fichiers dans \netcdf\
smt.compress_folder(os.path.join(sim_folder, "merged"))
smt.clip_folder(os.path.join(sim_folder, "compressed"), 
                os.path.join(sim_folder, "watershed.shp"))
# Déplacer les clipped dans \Bretagne\
smt.clip_folder(os.path.join(sim_folder, "merged"), 
                os.path.join(sim_folder, "EBR_rectangle.shp"))
# Déplacer les clipped dans \EBR\
# Déplacer les compressed dans done
# Déplacer les merged sur le DDext
