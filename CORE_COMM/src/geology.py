#coding:utf-8

# Librairies
import os
import sys
import numpy as np
from osgeo import gdal, osr
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
from IPython.core.debugger import set_trace as st

class structure:
	def __init__(self, dem_path, geo_path = os.path.dirname(os.getcwd())+'/data/geology/GEO1M.shp',out_path = os.path.dirname(os.getcwd())):
		self.dem_path = dem_path
		self.geo_path = geo_path
		self.structure_dem_path = out_path + '/GeoStructure.tif'
		self.land_sea_dem_path = out_path + '/Land_Sea.tif'
		self.structure_clip = out_path + '/GeoStructure_clip.tif'
		self.land_sea_clip = out_path + '/Land_Sea_clip.tif'
		self.watershed_shp = out_path + '/watershed.shp'
		self.generate_structure_dem()
		self.geology_array()

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

	def geo_to_K(self,K_geo_values):
		'''
		geology_array: 2D arrays - code of geology entities
		K_geo_values: 1D array (same size that geology code variable) - correspondence between geology codes and hydraulique conductivity values 
		'''
		self.K_array = self.geology_array
		for i in range(0,len(self.geology_code)):
			self.K_array[self.geology_array==self.geology_code[i]]=K_geo_values[i]
		return self
