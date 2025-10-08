# -*- coding: utf-8 -*-
"""
Created on Mon Jan 15 10:51:23 2024

@author: roquesc

"""

#%% Import some libraries

# General
# import sys
# from os.path import dirname, abspath
# DIR = dirname(dirname(dirname(abspath(__file__))))
# sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
# import time
import os
import os.path
# from os import path
import rasterio
from rasterio.features import geometry_mask
from rasterio import mask
from shapely.geometry import mapping

# Gis
import imageio
# import whitebox
# wbt = whitebox.WhiteboxTools()
# wbt.verbose = False

# # Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")

# for extraction ERA5
import geopandas as gpd
# import xarray as xr 
# import rioxarray

#%% define the working directories and open the databases
print('I open all the stuff')
# Path to the data folder
data_path = "G:/Mon Drive/_travail/_projects/_current/_massif/_gis/_global_databases/"
# Path where the results will be stored
out_path = "D:/_projects/_massif/_out/"

# OPEN the geological database
geol_path = 'G:/Mon Drive/_travail/_gis/geology/GLiM/EU/'
GLiM = gpd.read_file(geol_path+'GLiM_clip_EU.shp')

# OPEN the depth to bedrock dataset
dtb_path = 'G:/Mon Drive/_travail/_gis/depth_to_bedrock/EU/'
src = rasterio.open(dtb_path + 'BDTICM_M_1km_ll_clip_EU.tif')
#dtb = gpd.read_file(dtb_path + 'BDTICM_M_1km_ll_clip_EU.tif')

# OPEN the hydroatlas dataset and reset the crs
path_catch = data_path + '/HYDROATLAS/hybas_eu_lev01-12_v1c/hybas_eu_lev09_v1c.shp'
catch = gpd.read_file(path_catch)
catch = catch.set_crs('epsg:4326')
catch = catch.to_crs(epsg = 3035)
# catch.head()

# OPEN the DEM dataset
path_dem = 'F:/data/dem/dem_EU_30m_openTopograhies.tif'
dem = rasterio.open(path_dem)

# OPEN the GRDC dataset
path_grdc_point = 'G:/Mon Drive/_travail/_projects/_current/_massif/_gis/_global_databases/GRDC/GRDC_export_jan24.shp'
grdc_point = gpd.read_file(path_grdc_point)
catch = catch.set_crs('epsg:3035')

#%% Prepare the resukts file
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
results.loc[:,'nd'] = em
results.loc[:,'dtb_me'] = em
results.loc[:,'dtb_std'] = em
results.loc[:,'elevation_me'] = em
results.loc[:,'elevation_std'] = em
results.loc[:,'any_grdc'] = em
results.loc[:,'nb_grdc'] = em
results.loc[:,'dominant_litho'] = em
# else:
#     results = gpd.read_file(out_path + 'results.shp')
    
#define if you save the data
save = 0

#%%
for i, j in catch.iterrows():
    if i>=0:
        
        catch_ID = str(catch.loc[i,'HYBAS_ID'])
        print('###################################################################################')
        print('I am now working on catchment #' + str(i) + '/' + str(len(catch)) + ', HYBAS_ID=' + catch_ID)

        if save == 1:
            out_path_catch = out_path+str(catch_ID)
            os.makedirs(out_path_catch, exist_ok=True)      
        
        catch_bnd = catch.loc[i,'geometry']
        catch_bnd = gpd.GeoDataFrame(index=[0], crs='epsg:3035', geometry=[catch_bnd])
        
        if save == 1:
            out_path_bnd = out_path_catch+'/_boundaries/'
            os.makedirs(out_path_bnd, exist_ok=True)    
            catch_bnd.to_file(out_path_bnd + 'catchment_boundary.shp')
        
        ############################################################################
        #% Extract the geology for GLiM
        print('I extract the geology')

        if save == 1:
            geol_path_out = out_path_catch + '/_geology/'
            os.makedirs(geol_path_out, exist_ok=True)  
        
        # Extract percent of lithology cover
        geol_clip = gpd.clip(GLiM,catch_bnd)
        
        if save == 1:
            geol_clip.to_file(geol_path_out + 'GLiM_clip_catch.shp')
        
        # geol=gpd.read_file(geol_path_out+'/catchment_geology.shp')
        # geol_clip = geol_clip[['xx', 'geometry']]
        geol_clip = geol_clip.dissolve(by='xx')
        geol_clip['area'] = geol_clip['geometry'].area
        geol_clip = geol_clip.sort_values(by=['area'])
        
        for index, row in geol_clip.iterrows():
            cover = row['area']/catch_bnd.area*100
            cover = cover.to_frame(name="vals")
            results.loc[i,str(index)] = cover.loc[0,'vals']

        ############################################################################        
        print('I extract the depth to bedrock')
        try:
            #% Extract the depth to bedrock stat
            # Mask the raster based on the catchment boundary
            out_dtb, out_transform = rasterio.mask.mask(src, [mapping(catch_bnd.geometry.iloc[0])], crop=True)
            # Update metadata
            out_meta = src.meta
            out_meta.update({
                "driver": "GTiff",
                "height": out_dtb.shape[1],
                "width": out_dtb.shape[2],
                "transform": out_transform
            })
                
            if save == 1:
                dtb_path_out = out_path_catch + '/_depth_to_bedrock/'
                os.makedirs(dtb_path_out, exist_ok=True)  
                with rasterio.open(dtb_path_out + 'dtb.tif', "w", **out_meta) as dest:
                    dest.write(out_dtb)
                
            out_dtb = out_dtb.astype(float)
            out_dtb[out_dtb<0] = np.nan
            
            results.loc[i,'dtb_me'] = (np.nanmean(out_dtb)).astype(int)/100
            results.loc[i,'dtb_std'] = (np.nanstd(out_dtb)).astype(int)/100
        except:
            print('arf, it did not work')
            pass
            
        ############################################################################        
        print('I extract the elevation stats')
        
        try:
            #% Extract the depth to bedrock stat
            # Mask the raster based on the catchment boundary
            out_dem, out_transform_dem = rasterio.mask.mask(dem, [mapping(catch_bnd.geometry.iloc[0])], crop=True)
            # Update metadata
            out_meta = dem.meta
            out_meta.update({
                "driver": "GTiff",
                "height": out_dem.shape[1],
                "width": out_dem.shape[2],
                "transform": out_transform_dem
            })
                
            if save == 1:
                dem_path_out = out_path_catch + '/_dem/'
                os.makedirs(dem_path_out, exist_ok=True)  
                with rasterio.open(dem_path_out + 'dem.tif', "w", **out_meta) as dest:
                    dest.write(out_dem)
                
            out_dem = out_dem.astype(float)
            out_dem[out_dem<0] = np.nan
           
            results.loc[i,'elevation_me'] = (np.nanmean(out_dem)).astype(int)
            results.loc[i,'elevation_std'] = (np.nanstd(out_dem)).astype(int)
        except:
            print('')
            print('arf, it did not work!')
            pass
        
        ############################################################################        
        print('I check if there is any grdc station in the catchment')
        grdc_point_clip = gpd.clip(grdc_point,catch_bnd)
        if not grdc_point_clip.empty:
            nb_station = len(grdc_point_clip)
            print('yes, we have ' + str(nb_station) + ' station(s)')
            results.loc[i,'any_grdc'] = 1
            results.loc[i,'nb_grdc'] = nb_station
        else:
            results.loc[i,'any_grdc'] = 0
            results.loc[i,'nb_grdc'] = 0
        
############################################################################
print('I save the results to the output file')
results.to_file(out_path + 'results.shp')

#%% Compute the dominant lithology for all the catchments
results = gpd.read_file(out_path + 'results.shp')


metapluto = results[['mt', 'pa', 'pb', 'pi']]
metapluto = metapluto.fillna(0)
metapluto = metapluto.sum(axis=1)
results.loc[:,'metapluto'] = metapluto

volcanic = results[['va', 'vb', 'vi']]
volcanic = volcanic.fillna(0)
volcanic = volcanic.sum(axis=1)
results.loc[:,'volcanic'] = volcanic

unconsolidated = results[['su','py']]
unconsolidated = unconsolidated.fillna(0)
unconsolidated = unconsolidated.sum(axis=1)
results.loc[:,'uncons_sed'] = unconsolidated

consolidated = results[['ss']]
consolidated = consolidated.fillna(0)
consolidated = consolidated.sum(axis=1)
results.loc[:,'Siliciclastic_sedimentary_rocks'] = consolidated

# Carbonate = df_temp[['ev',  'sc',  'sm']]
carbonate = results[['sc','sm','ev']]
carbonate = carbonate.fillna(0)
carbonate = carbonate.sum(axis=1)
results.loc[:,'carbonate'] = carbonate

glacier_water = results[['ig','wb']]
glacier_water = glacier_water.fillna(0)
glacier_water = glacier_water.sum(axis=1)
results.loc[:,'glacier_water'] = glacier_water

lithos = pd.DataFrame({'Plutonic_and_metamorphic': metapluto, 
                       'Volcanics': volcanic, 
                       'Unconsolidated_sediments': unconsolidated,
                       'Siliciclastic_sedimentary_rocks': consolidated,
                       'Carbonates': carbonate,
                       'Galcier_and_water_bodies': glacier_water})

#get the dominant lithology for every catchment
dominant_litho = pd.DataFrame({'litho': lithos.idxmax(axis=1)})
for idx, row in lithos.iterrows():
    if sum(lithos.loc[idx,:]) == 0:
        dominant_litho.loc[idx] = np.nan
    
results.loc[:,'dominant_litho'] = dominant_litho
dups = dominant_litho.pivot_table(columns = ['litho'], aggfunc ='size')
dups

print('I save the results to the output file')
results.to_file(out_path + 'results.shp')

#%% Select the catchments of interest
results[results.dtb_me < 0] = np.nan
results[results.dtb_std < 0] = np.nan

massif_catch = results[(results['ORDER'] < 4) & (results['dtb_me'] < 25) & (results["dominant_litho"].str.contains("Carbonate") == False) & (results["dominant_litho"].str.contains("Unconsolidated_sediments") == False) & (results["dominant_litho"].str.contains("Galcier_and_water_bodies") == False)]

print('I save the selected catchments')
massif_catch.to_file(out_path + 'massif_catch.shp')

#%% OPEN the massif catch and work on the processing
out_path = "D:/_projects/_massif/_out/"
massif_catch = gpd.read_file(out_path + 'massif_catch.shp')

massif_catch_withGRDC = massif_catch[(massif_catch['any_grdc']==1)]

print('I save the selected catchments with GRDC stations')
massif_catch_withGRDC.to_file(out_path + 'massif_catch_withGRDC.shp')

# #%% Agregate the nearby polygons to identify the regions
# from shapely.geometry import MultiPolygon, JOIN_STYLE
# import itertools
# eps=5 # width for dilating and eroding (buffer)
# dist = 2  # threshold distance

# # create new result shapefile
# col = ['geometry']
# massif_catch_reg = gpd.GeoDataFrame(columns=col)
# # iterate over pairs of polygons in the GeoDataFrame 
# for ii, jj in list(itertools.combinations(massif_catch.index, 2)):
#     distance = massif_catch.geometry[ii].distance(massif_catch.geometry[jj]) # distance between polygons ii and jj in the shapefile
    
#     print('ii=' + str(ii) + ', jj=' + str(jj))
#     if distance < dist: 
#         e = MultiPolygon([massif_catch.geometry[ii],massif_catch.geometry[jj]])
#         fx = e.buffer(eps, 1, join_style=JOIN_STYLE.mitre).buffer(-eps, 1, join_style=JOIN_STYLE.mitre)
#         massif_catch_reg = massif_catch_reg.append({'geometry':fx},ignore_index=True)
        
# # save the resulting shapefile   
# massif_catch_reg.to_file(out_path + "massif_catch_reg.shp")