# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

# Modules
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy modules
from watershed import watershed_root

# Users
user = "Ronan"

if user=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user=="Jean-Raynald":
    root_path= "C:/DATA/codes-gitlab-public/HydroModPy_data/"
    out_path = "C:/DATA/results/HydroModPy"
elif user=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = False
watershed_name = 'Canut'
library_path = df + '/watershed.csv'

dem_path = root_path + "Bretagne.tif"

# surfex_path =  root_path + 'SURFEX/EBR_REA_h5'
# geology_path = root_path + 'GEOLOGY'
# oceanic_path = root_path + 'OCEAN'
# modflow_path = root_path + 'MODFLOW'
# hydrology_path = root_path + 'HYDROLOGY'

surfex_path =  None
geology_path = None
oceanic_path = None
modflow_path = None
hydrology_path = None

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              library_path=library_path,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path,
                              geology_path=geology_path,
                              hydrology_path=hydrology_path,
                              oceanic_path=oceanic_path, 
                              modflow_path=modflow_path,
                              load=load)
