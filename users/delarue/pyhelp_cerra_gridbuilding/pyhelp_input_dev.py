# -*- coding: utf-8 -*-
"""
Created on Mon Mar 24 11:59:54 2025

@author: delarueo

pyHelp input generator dev

"""
import geopandas as gpd
from shapely.geometry import Point
import math

#%%



def load_grid_from_csv(path_togrid):
    """
    Load the csv that contains the pixel point information.
    
    adapted from pyhelp
    """
    grid = pd.read_csv(path_togrid, dtype={'cid': 'str'})

    fname = osp.basename(path_togrid)
    req_keys = ['cid', 'lat_dd', 'lon_dd', 'run', 'context']
    for key in req_keys:
        if key not in grid.keys():
            raise KeyError("No attribute '{}' found in {}".format(key, fname))

    # Set 'cid' as the index of the dataframe.
    grid.set_index(['cid'], drop=False, inplace=True)

    return grid

#%%
workdir = 'M:/GitHub/HydroModPy-dev-waterwise/users/delarue/dev_pyhelp/'

help_grid = f'{workdir}grid_urse.csv'
cerra_grid = f'{workdir}cerra_alps.csv'

