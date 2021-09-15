# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 20:10:52 2021

@author: Alexandre Gauvain
"""
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from watershed import watershed_root

# Users
user_path = "Alexandre"

if user_path=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user_path=="Jean-Raynald":
    root_path= "C:/DATA/codes-gitlab-public/HydroModPy_data/"
    out_path = "C:/DATA/results/HydroModPy"
elif user_path=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
else:
    print("Define a well-validated name of user")

# test of watershed class
load = False
watershed_name = 'Agon-Coutainville'

dem_path = root_path + "MNT_TOPO_BATH_75m_corr.tif"
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path,surfex_path=surfex_path, geology_path = geology_path, 
                              hydrology_path=hydrology_path, oceanic_path=oceanic_path, 
                              modflow_path=modflow_path , load=load)