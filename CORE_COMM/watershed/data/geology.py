#coding:utf-8

# Librairies
import os
import numpy as np
from osgeo import gdal
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

class Geology:
    def __init__(self, out_path, geographic, geo_path, landsea, types_obs = 'GEO1M.shp', fields_obs = 'CODE_LEG'):
        print('Extraction des données géologiques')
        data_folder = os.path.join(out_path,'results_stable/geology/')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.geol_file =  os.path.join(geo_path, types_obs)
        self.field = fields_obs
        self.structure_dem_path =  os.path.join(data_folder,'GeoStructure.tif')
        self.structure_clip =  os.path.join(data_folder,'GeoStructure_clip.tif')
        # Be careful, column T_M_num not exist in default self.geol_file
        self.landsea = landsea
        if self.landsea != None:
                d_sea_dem_path =  os.path.join(data_folder,'Land_Sea.tif')
                land_sea_clip = os.path.join(data_folder, 'Land_Sea_clip.tif')
        watershed_shp = os.path.join(data_folder,'watershed.shp')
        self.generate_structure_dem(data_folder, geographic)
        self.geology_array(data_folder)
        
        """"""
        # Problem with this function (sizes of arrays)
        # self.geology_elevation(geographic)
        """"""
        
    def generate_structure_dem(self, data_folder, geographic):
        wbt.vector_polygons_to_raster(self.geol_file, self.structure_dem_path , field=self.field, nodata=None, base=geographic.watershed_buff_dem)
        wbt.clip_raster_to_polygon(self.structure_dem_path, geographic.watershed_shp, self.structure_clip)
        if self.landsea != None:
                wbt.vector_polygons_to_raster(self.geol_file, data_folder + 'Land_Sea.tif', field="T_M_num", nodata=None, base=geographic.watershed_buff_dem)
                wbt.clip_raster_to_polygon(data_folder + 'Land_Sea.tif', geographic.watershed_shp, data_folder + 'Land_Sea_clip.tif')
        return self

    def geology_array(self,data_folder):
        dem_geo = gdal.Open(self.structure_dem_path)
        dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
        if self.landsea != None:
                dem_T_M = gdal.Open(data_folder + 'Land_Sea.tif')
                dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
                dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
        self.geology_array = dem_data.astype(int)
        self.geology_code = np.intersect1d(self.geology_array, self.geology_array)

        dem_geo_clip = gdal.Open(self.structure_dem_path)
        dem_data_clip = dem_geo_clip.GetRasterBand(1).ReadAsArray()
        if self.landsea != None:
                dem_T_M_clip = gdal.Open(data_folder + 'Land_Sea_clip.tif')
                dem_data_T_M_clip = dem_T_M_clip.GetRasterBand(1).ReadAsArray()
                dem_data_clip[dem_data_T_M_clip==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
        dem_data_clip[dem_data_clip<0]= np.nan
        self.geology_array_clip = dem_data_clip.astype(int)

        #self.geology_array[self.geology_array<=100] = int(1)
        #self.geology_array_clip[self.geology_array_clip<=100] = int(1)

        self.geology_code_clip = np.intersect1d(self.geology_array_clip, self.geology_array_clip)
        self.geology_code = self.geology_code_clip[self.geology_code_clip>=0]

        '''
        #Double geology
        self.geology_code = [int(1),int(2)]
        for i in self.geology_code:
            if i ==1:
                self.geology_array[self.geology_array<=100] = int(i)
                self.geology_array_clip[self.geology_array_clip<=100] = int(i)

        '''
        return self

    def geology_elevation(self, geographic):
        self.geology_elevation = np.ones(len(self.geology_code))
        for i in range(0,len(self.geology_code)):
            self.geology_elevation[i]= np.min(geographic.dem_data[self.geology_array==self.geology_code[i]])
        
        #idxs = self.geology_elevation.argsort()
        #self.geology_elevation = self.geology_elevation[idxs[:]]
        #self.geology_code = self.geology_code[idxs[:]]
        return self

    def geo_to_K(self,K_geo_values):
        '''
        geology_array: 2D arrays - code of geology entities
        K_geo_values: 1D array (same size that geology code variable) - correspondence between geology codes and hydraulique conductivity values 
        '''
        self.K_array = self.geology_array
        for i in range(0,len(self.geology_code)):
            self.K_array[self.geology_array==self.geology_code[i]]=K_geo_values[i]
        return self