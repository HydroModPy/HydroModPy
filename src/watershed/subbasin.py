# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import sys
import os
import numpy as np
import pandas as pd
import geopandas as gpd
import glob
import shutil
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Subbasin:
    
    #%% INIT
    
    def __init__(self, geographic, hydrometry, intermittency,
                 add_path, sub_snap_dist,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):        
        print('Extract subbasin from generated and added data')
        
        self.sub_snap_dist = sub_snap_dist
        
        self.subbasin_path = os.path.join(out_path, 'results_stable/subbasin/')
        if not os.path.exists(self.subbasin_path):
            toolbox.create_folder(self.subbasin_path)
                
        self.adddata_path = os.path.join(out_path, 'results_stable/add_data/')
        if not os.path.exists(self.adddata_path):
            toolbox.create_folder(self.adddata_path)
        
        try:
            code_bh = hydrometry.code_bh
            x_coord = hydrometry.x_coord
            y_coord = hydrometry.y_coord
            for i in range(len(code_bh)):
                sub_path = os.path.join(self.subbasin_path, 'hydrometry_'+code_bh[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            print('     No hydrometry subbasin or problem')
            pass
        
        try:
            code_onde = intermittency.code_onde
            x_coord = intermittency.x_coord
            y_coord = intermittency.y_coord
            for i in range(len(code_onde)):
                sub_path = os.path.join(self.subbasin_path, 'intermittency_'+code_onde[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            print('     No intermittency subbasin or problem')
            pass
        
        # try:
        code_sub, x_coord, y_coord = self.add_coord_manual(add_path)
        for i in range(len(code_sub)):
            sub_path = os.path.join(self.subbasin_path, 'subbasin_'+code_sub[i])
            self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path, sub_snap_dist)            
        # except:
        #     print('     No personnal subbasins or problem')
        #     pass
    
    #%% SUB-CATCHMENT FROM STATIONS
    
    # Extract sub-catchment from existing stations : hydrometry or intermittency
    
    def extract_interest_zones(self, geographic, X, Y, outpath, sub_snap_dist):
        # Path of subbasin
        if os.path.exists(outpath):
            shutil.rmtree(outpath)
        toolbox.create_folder(outpath)        
        # Coordinates
        outpath = outpath + '/'
        df = pd.DataFrame({'x': [X], 'y': [Y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=geographic.crs_proj)
        outlet_shp = outpath + 'outlet.shp'
        gdf.to_file(outlet_shp)
        # Snap the outlet shapefile from the flow accumulation
        outlet_snap_shp = outpath + 'outlet_snap.shp'
        wbt.snap_pour_points(outlet_shp,
                             os.path.join(geographic.reg_path, 'region_acc.tif'),
                             outlet_snap_shp,
                             sub_snap_dist
                             # geographic.snap_dist
                             )
        # Generate raster watershed
        watershed = outpath + 'watershed.tif'
        wbt.watershed(os.path.join(geographic.reg_path, 'region_direc.tif'), outlet_snap_shp, watershed, esri_pntr=False)
        # Create shapefile polygon of the watershed
        watershed_shp = outpath + 'watershed.shp'
        wbt.raster_to_vector_polygons(watershed, watershed_shp)
        shp = gpd.read_file(watershed_shp)
        shp.set_crs(geographic.crs_proj, inplace=True, allow_override=True)
        shp.to_file(watershed_shp)
        wbt.polygon_area(watershed_shp)
        area = gpd.read_file(watershed_shp).AREA[0]/1000000
        area = np.abs(area)
        # Create shapefile polyline of the watershed
        watershed_contour_shp = outpath + 'watershed_contour.shp'
        wbt.polygons_to_lines(watershed_shp, watershed_contour_shp)
        # Clip buffer watershed DEM from watershed shapefile polygon
        watershed_dem = outpath + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(geographic.watershed_buff_dem, watershed_shp, watershed_dem, maintain_dimensions=True)        
    
    #%% SUB-CATCHMENT FROM XY POINT
    
    # From a .csv file with x, y coordinates representing the outlet desired sub-catchments
    
    def add_coord_manual(self, add_path):
        path_coord = glob.glob(add_path+'/'+'*')[0]
        print(path_coord)
        sub_list = pd.read_csv(path_coord, sep=';')
        code_sub = sub_list['code_sub'].to_list()
        x_coord = sub_list['x_outlet'].to_list()
        y_coord = sub_list['y_outlet'].to_list()
        return code_sub, x_coord, y_coord
        
#%% NOTES
