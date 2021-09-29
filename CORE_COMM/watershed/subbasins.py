# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 20:10:52 2021

@author: Ronan Abhervé
"""

# Modules
import glob
import geopandas as gpd
import geopandas as gpd
import shapely
shapely.speedups.disable()
import imageio
import matplotlib.pyplot as plt
import numpy as np
import os
from osgeo import gdal, osr
import pandas as pd
from pyproj import Transformer
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.set_verbose_mode(False)

# HydroModPy modules
from tools import file_adds

class Subbasins:
    
    def __init__(self, geographic):
        
        self.geographic = geographic
        
        self.columns=['fonction','type','code','label','x','y','start','end']
        self.df = pd.DataFrame(columns=self.columns)
        
    def automatic_coord(self, hydrology_path, hydrology_stable):
        watershed_shp = gpd.read_file(self.geographic.watershed_shp)
        
        print('Search hydrometric stations in watershed')
        
        hydrometric_shp = gpd.read_file(os.path.join(hydrology_path, 'hydrometric.shp'))
        clip_hydrometric_shp = gpd.clip(hydrometric_shp, watershed_shp)
        clip_hydrometric_shp.to_file(os.path.join(hydrology_stable, 'hydrometric.shp'))
        
        clip_hydrometric_shp = gpd.read_file("D:/Users/abherve/RESULTS/rejets_metropole/Out/results_stable/hydrology/hydrometric.shp")
        
        df_hydro = pd.DataFrame(columns=self.columns)
        
        for i in range(len(clip_hydrometric_shp)):
            raw = clip_hydrometric_shp.iloc[0]
            to_append = ['calib',
                          'hydrometric',
                          raw['CdStatio_1'],
                          raw['LbStationH'],
                          raw['CoordXStat'],
                          raw['CoordYStat'],
                          pd.to_datetime(raw['timePositi'][0:10], format='%Y-%m-%d'),
                          pd.to_datetime(raw['DtFermetur'][0:10],format='%Y-%m-%d')]
            df_hydro.loc[i] = to_append
        
        self.df = self.df.append(df_hydro, ignore_index = True)
        self.df = self.df.reset_index(drop=True)
        
        print('Search onde stations in watershed')
        
        onde_shp = gpd.read_file(os.path.join(hydrology_path, 'onde.shp'))
        clip_onde_shp = gpd.clip(onde_shp, watershed_shp)
        clip_onde_shp.to_file(os.path.join(hydrology_stable, 'onde.shp'))
        stations = clip_onde_shp['<LbSiteHyd'].unique()
        
        df_onde = pd.DataFrame(columns=self.columns)
        
        for i in stations:
            mask = (clip_onde_shp['<LbSiteHyd'] == i)
            raw = clip_onde_shp[mask]
            to_append = ['calib',
                          'onde',
                          raw.iloc[0]['<CdTroncon'],
                          raw.iloc[0]['<NomEntite'],
                          raw.iloc[0]['<CoordXSit'],
                          raw.iloc[0]['<CoordYSit'],
                          pd.to_datetime(raw.iloc[0]['<DtRealObs'], format='%Y-%m-%d'),
                          pd.to_datetime(raw.iloc[-1]['<DtRealObs'],format='%Y-%m-%d')]
            df_onde.loc[i] = to_append

        self.df = self.df.append(df_onde, ignore_index = True)
        self.df = self.df.reset_index(drop=True)
        
        return self.df
        
    def manual_coord(self, add_data_stable, file_name,  
                              fonction_column,
                              type_data,
                              code_column,
                              label_column,
                              x_column,
                              y_column,
                              start_column,
                              end_column):
        
        print('Search manual data in watershed')
        
        coord_path = os.path.join(add_data_stable, file_name)
        coord_data = pd.read_csv(coord_path, sep=';')

        df_manual = pd.DataFrame(columns=self.columns)

        for i in range(len(coord_data)):
            raw = coord_data.iloc[i]
            to_append = [raw[fonction_column],
                         type_data,
                         raw[code_column],
                         raw[label_column],
                         raw[x_column],
                         raw[y_column],
                         raw[start_column],
                         raw[end_column]]
            df_manual.loc[i] = to_append
            
        self.df = self.df.append(df_manual, ignore_index = True)
        self.df = self.df.reset_index(drop=True)
        
        return self.df
        
    def extract_subbasins(self, snap_dist, stable_folder):
        
        self.subbasins_folder = os.path.join(stable_folder, 'subbasins')
        file_adds.create_folder(self.subbasins_folder)
        
        # Open
        dem_path = self.geographic.watershed_buff_dem
        dem = gdal.Open(dem_path)
        geodata = dem.GetGeoTransform()
        watshd_data = dem.GetRasterBand(1).ReadAsArray()
        dem_shp = gpd.read_file(self.geographic.watershed_shp)
        
        fig, ax = plt.subplots(1,1, figsize=(8,8), dpi=300)
        dem_shp.plot(ax=ax, facecolor="none", edgecolor="black", linewidth=2)
        
        for i in range(len(self.df)):
            
            print('Generate subbasin : '+str(i+1)+' / '+str(len(self.df)))
            
            raw = self.df.iloc[i]
            
            fct = raw.fonction
            typ = raw.type
            code = raw.code
            label = raw.label
            x = raw.x
            y = raw.y
            
            identity = str(fct)+'_'+str(typ)+'_'+str(code)+'_'+str(label)+'_'+str(round(x))+'_'+str(round(y))
            
            self.subbasin_folder = os.path.join(self.subbasins_folder, identity+'/')
            file_adds.create_folder(self.subbasin_folder)
            
            # Generate folder where processing files are stored
            gis_path=self.subbasin_folder
            
            """
            Raw buff watershed DEM
            """
            # Correction
            fill = gis_path + 'watershed_buff_fill.tif'
            wbt.fill_depressions(dem_path, fill) # or # wbt.breach_depressions(dem_path, fill, 2, 75*8)
            # Flow direction
            direc = gis_path + 'watershed_buff_direc.tif'
            wbt.d8_pointer(fill, direc, esri_pntr=False)
            # Flow accumulation
            acc = gis_path + 'watershed_buff_acc.tif'
            wbt.d8_flow_accumulation(fill, acc, log=True)
            """
            Extract subbasins from an outlet
            """
            # Extract the coordinate system
            # proj = osr.SpatialReference(wkt=dem.GetProjection())
            # crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
            # Create outlet shapefile from x and y coordinates
            df = pd.DataFrame({'x': [x], 'y': [y]})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']))
            outlet_shp = gis_path + 'outlet.shp'
            gdf.to_file(outlet_shp)
            # Snap the outlet shapefile from the flow accumulation
            outlet_snap_shp = gis_path + 'outlet_snap.shp'
            wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
            # Generate raster watershed
            subbasin = gis_path + 'subbasin.tif'
            wbt.watershed(direc, outlet_snap_shp, subbasin, esri_pntr=False)
            # Create shapefile polygon of the watershed
            subbasin_shp = gis_path + 'subbasin.shp'
            wbt.raster_to_vector_polygons(subbasin, subbasin_shp)
            # Create shapefile polyline of the watershed
            subbasin_contour_shp = gis_path + 'subbasin_contour.shp'    
            wbt.polygons_to_lines(subbasin_shp, subbasin_contour_shp)
            # Plot dem
            if typ == 'hydrometric':
                color='dodgerblue'
            if typ == 'onde':
                color='darkorange'
            if (typ != 'hydrometric') & (typ != 'onde'):
                color='forestgreen'
            sub = gpd.read_file(subbasin_shp)
            snp = gpd.read_file(outlet_snap_shp)
            sub.plot(ax=ax, facecolor="none", edgecolor=color, linewidth=1)
            snp.plot(ax=ax, facecolor=color, edgecolor='k', linewidth=0.5)
            
#%%
"""
        for i in range(len(clip_hydrometric_shp)):
            df.loc[i,'type'] = 'hydrometric'
            df.loc[i,'code'] = clip_hydrometric_shp['CdStatio_1'].values[0]
            df.loc[i,'label'] = clip_hydrometric_shp['LbStationH'].values[0]
            df.loc[i,'x'] = clip_hydrometric_shp['CoordXStat'].values[0]
            df.loc[i,'y'] = clip_hydrometric_shp['CoordYStat'].values[0]
            df.loc[i,'start'] = pd.to_datetime(clip_hydrometric_shp['timePositi'].values[0][0:10], format='%Y-%m-%d')
            df.loc[i,'end'] = pd.to_datetime(clip_hydrometric_shp['DtFermetur'].values[0][0:10],format='%Y-%m-%d')
"""
        
        
        
        
        