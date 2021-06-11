#coding:utf-8

# Librairies
import os
import sys
import numpy as np
import topography
from osgeo import gdal, osr
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
from IPython.core.debugger import set_trace as st

class extract:
	def __init__(self,out_path, geographic, geo_path):
		print('Extraction des données géologiques')
		data_folder = out_path + 'data/geoglogy/'
		if not os.path.exists(data_folder):
				os.makedirs(data_folder)
		geo_file = geo_path + '/GEO1M.shp'
		structure_dem_path = data_folder + 'GeoStructure.tif'
		land_sea_dem_path = data_folder + 'Land_Sea.tif'
		structure_clip = data_folder + 'GeoStructure_clip.tif'
		land_sea_clip = data_folder + 'Land_Sea_clip.tif'
		watershed_shp = data_folder + 'watershed.shp'
		self.generate_structure_dem(geo_file, data_folder, geographic)
		self.geology_array(data_folder)
		self.geology_elevation(geographic)

	def generate_structure_dem(self,geo_file, data_folder, geographic):
		wbt.vector_polygons_to_raster(geo_file, data_folder + 'GeoStructure.tif' , field="CODE_LEG", nodata=None, base=geographic.watershed_buff_dem)
		wbt.clip_raster_to_polygon(data_folder + 'GeoStructure.tif', geographic.watershed_shp, data_folder + 'GeoStructure_clip.tif')
		wbt.vector_polygons_to_raster(geo_file, data_folder + 'Land_Sea.tif', field="T_M_num", nodata=None, base=geographic.watershed_buff_dem)
		wbt.clip_raster_to_polygon(data_folder + 'Land_Sea.tif', geographic.watershed_shp, data_folder + 'Land_Sea_clip.tif')
		return self

	def geology_array(self,data_folder):
		dem_geo = gdal.Open(data_folder + 'GeoStructure.tif')
		dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
		dem_T_M = gdal.Open(data_folder + 'Land_Sea.tif')
		dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
		dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
		self.geology_array = dem_data.astype(int)
		self.geology_code = np.intersect1d(self.geology_array, self.geology_array)

		dem_geo = gdal.Open(data_folder + 'GeoStructure_clip.tif')
		dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
		dem_T_M = gdal.Open(data_folder + 'Land_Sea_clip.tif')
		dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
		dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
		self.geology_array_clip = dem_data.astype(int)
		self.geology_code_clip = np.intersect1d(self.geology_array, self.geology_array)
		return self

	def geology_elevation(self, geographic):
		self.geology_elevation = np.ones(len(self.geology_code))
		for i in range(0,len(self.geology_code)):
			self.geology_elevation[i]=np.min(geographic.dem_data[self.geology_array==self.geology_code[i]])
		
		idxs = self.geology_elevation.argsort()
		self.geology_elevation = self.geology_elevation[idxs[:]]
		self.geology_code = self.geology_code[idxs[:]]
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


class structure:
	def __init__(self, dem_path, geo_path = os.path.dirname(os.path.abspath(__file__)) +'/data/geology/GEO1M.shp',out_path = os.path.dirname(os.path.abspath(__file__))):
		self.dem_path = dem_path
		self.geo_path = geo_path
		self.dem = topography.dem(self.dem_path)
		self.structure_dem_path = out_path + '/GeoStructure.tif'
		self.land_sea_dem_path = out_path + '/Land_Sea.tif'
		self.structure_clip = out_path + '/GeoStructure_clip.tif'
		self.land_sea_clip = out_path + '/Land_Sea_clip.tif'
		self.watershed_shp = out_path + '/watershed.shp'
		self.generate_structure_dem()
		self.geology_array()
		self.geology_elevation()

	def generate_structure_dem(self):
		wbt.vector_polygons_to_raster(self.geo_path, self.structure_dem_path , field="CODE_LEG", nodata=None, base=self.dem_path)
		wbt.clip_raster_to_polygon(self.structure_dem_path, self.watershed_shp, self.structure_clip)
		wbt.vector_polygons_to_raster(self.geo_path, self.land_sea_dem_path, field="T_M_num", nodata=None, base=self.dem_path)
		wbt.clip_raster_to_polygon(self.land_sea_dem_path, self.watershed_shp, self.land_sea_clip)
		return self

	def geology_array(self):
		dem_geo = gdal.Open(self.structure_dem_path)
		dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
		dem_T_M = gdal.Open(self.land_sea_dem_path)
		dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
		dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
		self.geology_array = dem_data.astype(int)
		self.geology_code = np.intersect1d(self.geology_array, self.geology_array)

		dem_geo = gdal.Open(self.structure_clip)
		dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
		dem_T_M = gdal.Open(self.land_sea_clip)
		dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
		dem_data[dem_data_T_M==0] = 1 # Condidering that the part imerged by the sea is a superficial formation
		self.geology_array_clip = dem_data.astype(int)
		self.geology_code_clip = np.intersect1d(self.geology_array, self.geology_array)

		return self

	def geology_elevation(self):
		self.geology_elevation = np.ones(len(self.geology_code))
		for i in range(0,len(self.geology_code)):
			self.geology_elevation[i]=np.min(self.dem.data[self.geology_array==self.geology_code[i]])
		
		idxs = self.geology_elevation.argsort()
		self.geology_elevation = self.geology_elevation[idxs[:]]
		self.geology_code = self.geology_code[idxs[:]]
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
