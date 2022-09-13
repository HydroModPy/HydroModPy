# -*- coding: utf-8 -*-
"""
Created on Tue Sep 21 15:23:44 2021

@author: 33650
"""

# Import Module
import watershed_root as WS
#import watershed as WS
#import geology as GE
#import region as RE

# Import Library
import pandas as pd
import sys
import os


# Define all paths
src_path = os.getcwd()

dem_path = src_path + '/data/DEM/' + 'MNT.tif'
geology_path = src_path + '/data/Geology/' + 'GEO001M_CART_FR_S_FGEOL_2154.shp'
#out_path = src_path + '/OUTPUTS/gis_results/'

# Catchment name
watershed_name = 'Nancon'

Watershed = WS.Watershed(watershed_name, dem_path, load=True)

sys.exit()

# Outlet
#x = [389357.60]
#y = [6816630.18]
#outlet = pd.DataFrame(x, columns=['x'])
#outlet['y'] = y

# Critical drainage area
#critical_drainage_area = 400
#snap_dist=150










Region = RE.Region(dem_path)
Watershed = WS.Watershed(Region, dem_path, gis_path, outlet, critical_drainage_area, snap_dist)


sys.exit()

# Build Classes

Geology = GE.Geology(geology_path)
MetaGeology = GE.MetaGeology(geology_path)

# Extract watershed

# Build Hillslope Class
Hillslope = WS.Hillslope(dem_path, gis_path, outlet, critical_drainage_area, snap_dist)

# 1D HILLSLOPE
Hillslope.hs1D = Hillslope.compute_hillslopes1D(Region.dem.Z, Region.dem.cellsize)





