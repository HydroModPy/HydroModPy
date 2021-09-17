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
import matplotlib.pyplot as plt
import pandas as pd

import warnings

warnings.filterwarnings("ignore", 
                        message=".*An exception was ignored while fetching the attribute.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*`np.object` is a deprecated alias for the builtin `object`.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*is deprecated. Use tobytes().*",
                        category=DeprecationWarning)

warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                                            
# HydroModPy modules
from watershed import watershed_root
from tools import tif_adds

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
library_path = df + '/watershed' + '/watershed_library.csv'

dem_path = root_path + "/DEM/" + "BDALTI_bzh_75m.tif"

surfex_path =  root_path + 'SURFEX'
geology_path = None
hydrology_path = None
modflow_path = root_path + 'MODFLOW'
piezometric_path = None
oceanic_path = None

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              library_path=library_path,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path,
                              geology_path=geology_path,
                              hydrology_path=hydrology_path,
                              piezometric_path=piezometric_path,
                              oceanic_path=oceanic_path, 
                              modflow_path=modflow_path,
                              load=load)

rech = pd.Series([0.02,0.025,0.032,0.027,0.018])

BV.run_modflow(ident='temporary', climatic=rech, lay_number=1, thick=100, bottom=None, thick_exp=1., 
               hyd_cond=21, porosity=0.01, sea_level=None, cond_decay=0.)

#%%
# read_dictionary = np.load('D:/Users/abherve/HYDROMODPY/Canut/simulations/watertable_elevation.h5.npy', allow_pickle='TRUE').item()

# climatic ==> pd.Series([8e-4,7.5e-4,7.0e-4])
