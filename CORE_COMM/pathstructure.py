# -*- coding: utf-8 -*-
"""
Created on Sat Jan  7 16:08:40 2023

@author: jdedreuz
"""

# -*- coding: utf-8 -*-
"""


"""

import sys
import os
from os.path import dirname, abspath


def results_folder(): 
    
    # user = 'Martin'
    user = 'Jean-Raynald'

    # Path where the results will be stored (SHOULD BE SPECIFIED BY THE USER)
    if user == 'Jean-Raynald':
        out_path = os.getenv("HYDROMODPY_RESULTS")
    if user == 'Alexandre':
        out_path = "C:/Users/alexa/Dropbox/HydroModPy/"
    if user == 'Martin':
        out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
    if user == 'Ronan':
        out_path = 'D:/Users/abherve/TESTS/'

    return out_path        


def path_classical(DIR):

    # Path to the git repositoty home page
    git_path = DIR
    # Path to the test folder
    test_path = os.path.join(git_path, "examples", "a_given/")
    
    # We suggest that data be stored in the following suite of specific folders
    # 1 folder for each of the type of data and "process" to be simulated
    dems_path = os.path.join(test_path, 'dem/')
    hydrology_path = os.path.join(test_path, 'hydrology/')   # add hydrographic shapefiles
    modflow_path = os.path.join(test_path, 'modflow/')       # add bin/ folder with necessary .exe
    climate_path = os.path.join(test_path, 'climate/')
    intermittency_path = os.path.join(test_path, 'intermittency/')
    hydrometry_path = os.path.join(test_path,'hydrometry/')
    piezometry_path = None                      # add piezometry data or nothing for automatic download
    geology_path = None                         # add geologic layers
    oceanic_path = 'None'                         # add specific sea level files
    
    # Specifically designed to process SURFEX data (France scale)
    surfex_path =  None # add surfex models in .h5 format    
    library_path = os.path.join(test_path, 'watershed_library.csv') # each row is a study site

    return dems_path, hydrology_path, modflow_path, climate_path, intermittency_path, \
            hydrometry_path, piezometry_path, geology_path, oceanic_path, surfex_path, library_path

