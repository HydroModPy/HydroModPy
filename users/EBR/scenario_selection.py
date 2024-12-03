# -*- coding: utf-8 -*-
"""
Created on Tue Dec  3 17:25:08 2024

@author: Alexandre Coche

Ce script :
    1. Vide le dossier <data_path>\Reservoir\Scenarios de gestion\Selection
    2. Lit le fichier settings.py (dans <data_path>) pour en extraire la liste 
    des scénarios à tester
    3. Copie-colle les fichiers .csv correspondants depuis le dossier
    <data_path>\Reservoir\Scenarios de gestion vers le dossier
    <data_path>\Reservoir\Scenarios de gestion\Selection

"""

import os
import yaml
import shutil

from src.tools import folder_root

#%% CHARGEMENT DU FICHIER DE PARAMETRES
data_path = os.path.join(folder_root.root_folder_results(), 'data_Cheze')

with open(os.path.join(data_path, 'settings.yaml'), 'r') as file_object:
    settings = yaml.load(file_object, Loader = yaml.SafeLoader)

# Corrections
if 'scenarios' in settings:
    # Les scenarios doivent etre sous forme de liste (meme s'il y en qu'un)
    if not isinstance(settings['scenarios'], list):
        settings['scenarios'] = [settings['scenarios']]
    # Les extensions doivent etre rajoutees aux noms des fichiers (si nécessaire)
    for s in range(0, len(settings['scenarios'])):
        if os.path.splitext(settings['scenarios'][s])[-1] == '':
            settings['scenarios'][s] += '.csv'


#%% COPIER-COLLER LES SCENARIOS SELECTIONNES
scenario_folder = os.path.join(data_path, "Reservoir", "Scenarios de gestion")
selected_folder = os.path.join(scenario_folder, "Selection")
shutil.rmtree(selected_folder)
os.makedirs(selected_folder)

for sce in settings['scenarios']:   
    shutil.copyfile(os.path.join(scenario_folder, sce), 
                    os.path.join(selected_folder, sce))    


