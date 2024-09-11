# -*- coding: utf-8 -*-
"""
Created on Mon Jan 15 16:26:46 2024

@author: roquesc
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import mapping

#%% define the working directories
# Path to the data folder
data_path = "G:/Mon Drive/_travail/_projects/_current/_massif/_gis/_global_databases/"
# Path where the results will be stored
out_path = "D:/_projects/_massif/_out/"
# pathe toward the geological database
geol_path = 'G:/Mon Drive/_travail/_gis/geology/GLiM/EU/'
GLiM = gpd.read_file(geol_path+'GLiM_clip_EU.shp')

# path toward the geological database
dtb_path = 'G:/Mon Drive/_travail/_gis/depth_to_bedrock/EU/'
#dtb = gpd.read_file(dtb_path + 'BDTICM_M_1km_ll_clip_EU.tif')

path_catch = data_path + '/HYDROATLAS/hybas_eu_lev01-12_v1c/hybas_eu_lev09_v1c.shp'
catch = gpd.read_file(path_catch)
catch = catch.set_crs('epsg:4326')
catch = catch.to_crs(epsg = 3035)
catch.head()

# if path.exists(out_path + 'results.shp')==False:
results = catch
em = np.empty(len(results))
em[:]=np.nan   

results.loc[:,'su'] = em
results.loc[:,'ss'] = em
results.loc[:,'ev'] = em
results.loc[:,'sc'] = em
results.loc[:,'sm'] = em
results.loc[:,'mt'] = em
results.loc[:,'ig'] = em
results.loc[:,'nd'] = em
results.loc[:,'wb'] = em
results.loc[:,'pa'] = em
results.loc[:,'pb'] = em
results.loc[:,'pi'] = em
results.loc[:,'py'] = em
results.loc[:,'va'] = em
results.loc[:,'vb'] = em
results.loc[:,'vi'] = em
# else:
#     results = gpd.read_file(out_path + 'results.shp')
    
#define if you save the data
save = 0

for i, row in catch.iterrows():
    catch_ID = str(row['HYBAS_ID'])
    print(f'Working on catchment #{i}/{len(catch)}, HYBAS_ID={catch_ID}')
    
    out_path_catch = os.path.join(out_path, catch_ID)
    os.makedirs(out_path_catch, exist_ok=True)
    
    catch_bnd = gpd.GeoDataFrame(index=[0], crs='epsg:3035', geometry=[row['geometry']])
    
    out_path_bnd = os.path.join(out_path_catch, '_boundaries')
    os.makedirs(out_path_bnd, exist_ok=True)
    
    catch_bnd.to_file(os.path.join(out_path_bnd, 'catchment_boundary.shp'))
    
    # Extract the geology for GLiM
    print('Extracting geology')
    
    geol_path_out = os.path.join(out_path_catch, '_geology')
    os.makedirs(geol_path_out, exist_ok=True)
    
    geol_clip = gpd.clip(GLiM, catch_bnd)
    
    if save == 1:
        geol_clip.to_file(os.path.join(geol_path_out, 'GLiM_clip_catch.shp'))
    
    geol_clip = geol_clip.dissolve(by='xx')
    geol_clip['area'] = geol_clip['geometry'].area
    geol_clip = geol_clip.sort_values(by=['area'])
    
    for index, subrow in geol_clip.iterrows():
        cover = subrow['area'] / catch_bnd.area * 100
        results.at[i, str(index)] = cover.values[0]
    
    print('Extracting depth to bedrock')
    
    # Extract the depth to bedrock stat
    dtb_path_out = os.path.join(out_path_catch, '_depth_to_bedrock')
    
    with rasterio.open(os.path.join(dtb_path, 'BDTICM_M_1km_ll_clip_EU.tif')) as src:
        out_dtb, out_transform = rasterio.mask.mask(src, [mapping(row['geometry'])], crop=True)
        out_meta = src.meta.copy()
        
    if save == 1:
        os.makedirs(dtb_path_out, exist_ok=True)
        with rasterio.open(os.path.join(dtb_path_out, 'dtb.tif'), 'w', **out_meta) as dest:
            dest.write(out_dtb)
    
    out_dtb = out_dtb.astype(float)
    out_dtb[out_dtb < 0] = np.nan
    
    results.at[i, 'bdticm_me'] = np.nanmean(out_dtb) / 100
    results.at[i, 'bdticm_std'] = np.nanstd(out_dtb) / 100

# Save results
results.to_file(os.path.join(out_path, 'results.shp'))