# -*- coding: utf-8 -*-
"""
Created on Thu Aug 31 12:40:43 2023

@author: emarti
"""

#%% LIBRAIRIES

import geopandas as gpd
import numpy as np
import rioxarray as rxr
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False


#%%PATHS

user_path = "Etienne"
data_path = "D:/emarti/Chile/data/"
out_path = "D:/emarti/Chile/out/"
shp_path = data_path+'HYDROATLAS_SHP/individual/'


#%%Read larger DEM and HydroAtlas file once 
north_chile_dem=data_path+'DEM/study_area_DEM_UTM.tif'
dem_data =  rxr.open_rasterio(north_chile_dem, masked=True).squeeze()
dem_res = int(dem_data.x[2] - dem_data.x[1])
#%%
HydroAtlas_shp = data_path+'HYDROATLAS_SHP/BasinATLAS_v10_lev08_inside_chile_UTM.shp'
#Import shapefile
cuencas = gpd.read_file(HydroAtlas_shp)
cuencas['PFAF_ID_RSTRIP'] = [int(str(s).rstrip("0")) for s in cuencas['PFAF_ID']]

cuencas_final = cuencas[(cuencas.PFAF_ID_RSTRIP % 2==0) & (cuencas['SUB_AREA'] >=500) & (cuencas['SUB_AREA'] <=1500)]

watersheds = [x for x in cuencas_final.HYBAS_ID]

#%%RIVERS for whole study zone
rivers_shp=data_path+'RIVERS/rivers.shp'
rivers = gpd.read_file(rivers_shp,crs=32719)

#%%
for watershed_name in watersheds:
    
    print(watershed_name)
    BV = gpd.read_file(shp_path+str(watershed_name)+'.shp')
    BV = BV.set_crs(crs=32719)
    river_red = rivers.clip(BV)
    L_river = np.sum(river_red.length)
    dd = L_river/float(BV.area)
    LC = int(1/(2*dd))
    print('LC='+str(LC)+'')
    stable_folder = out_path+str(watershed_name)+'/'+'results_stable/'
    geographic = stable_folder+'geographic/'
    dem_path = geographic+'watershed_dem.tif'
    search=int(LC/dem_res)
    print('search='+str(search)+'')
    wbt.geomorphons(dem_path,geographic+'geomorphons.tif',search=search,threshold=5,skip=2)
    
    


#%%

for watershed_name in watersheds:  

    stable_folder = out_path+str(watershed_name) + \
        '/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path + \
        str(watershed_name)+'/'+'results_simulations/'  # necessary for plots
    geographic = stable_folder+'geographic/'
    dem_path = geographic+'watershed_box_buff_dem.tif'
    shp_mask = geographic+'watershed.shp'
    dem_data = rxr.open_rasterio(dem_path, masked=True).squeeze()
    bottom = np.nanmin(dem_data.values)-0.5 * \
        ((np.nanmax(dem_data.values)-np.nanmin(dem_data.values)))
    cuenca = gpd.read_file(shp_mask)
    dem_cuenca_clipped = dem_data.rio.clip(cuenca.geometry, drop=False)
    area = float(cuenca.area)
    dx = float(dem_data.x[2] - dem_data.x[1])
    dy = float(dem_data.y[1] - dem_data.y[2])

    wbt.ruggedness_index(dem_path,geographic+'watershed_ruggedness_index.tif')
    ruggedness_index_path = geographic+'watershed_ruggedness_index.tif'
    ruggedness_index_data = rxr.open_rasterio(ruggedness_index_path, masked=True).squeeze()
    mean_ruggedness_index = float(np.nanmean(ruggedness_index_data.values))
    slope_path = geographic+'watershed_slope.tif'
    slope_data = rxr.open_rasterio(slope_path, masked=True).squeeze()
    mean_slope = float(np.nanmean(slope_data.values))