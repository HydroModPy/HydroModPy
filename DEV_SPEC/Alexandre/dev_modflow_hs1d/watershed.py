# coding:utf-8

import os

import geopandas as gpd
from osgeo import gdal, osr
from shutil import copyfile
import numpy as np
import deepdish as dd
from IPython.core.debugger import set_trace as st
import geographic
import geology
import climatic
import piezometry
### Method 1
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
### Method 2
# from WBT.whitebox_tools import WhiteboxTools
# wbt = WhiteboxTools()

class build:
	"""
	explication fonction
	entrée
	sortie
	"""
	def __init__(self, watershed_name, dem_path, x_outlet, y_outlet, snap_dist=150, buff_dist=1000,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\', 
                 surfex_path = None, geology_path = None, load=True):

		self.name = watershed_name
		self.dem_path = dem_path
		self.x_outlet = x_outlet
		self.y_outlet = y_outlet
		self.snap_dist = snap_dist
		self.buff_dist = buff_dist
		self.out_path = out_path
		self.surfex_path = surfex_path
		self.geology_path = geology_path
		self.watershed_folder = out_path + '/' + watershed_name + '/'
		self.add_data_folder = self.watershed_folder + '/data/add_data/'

		if not os.path.exists(self.watershed_folder):
				os.makedirs(self.watershed_folder)
		if not os.path.exists(self.add_data_folder):
				os.makedirs(self.add_data_folder)

		if load==True:
			self.load_object()
		else:
			self.create_object()

	def load_object(self):
		dict_object = dd.io.load(self.watershed_folder + 'object.h5')
		if ('geographic' in dict_object) == True:
			self.geographic = dict_object['geographic']
		if ('climatic' in dict_object) == True:
			self.climatic = dict_object['climatic']
		if ('piezometry' in dict_object) == True:
			self.piezometry = dict_object['piezometry']
		if ('geology' in dict_object) == True:
			self.geology = dict_object['geology']

	def create_object(self):
		#STURCUTRE DATA
		self.geographic = geographic.extract(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet, snap_dist=self.snap_dist, buff_dist=self.buff_dist,
                 out_path=self.watershed_folder) #2D
		#self.hillslope = hillslope() #1D
		if self.geology_path != None:
			self.geology =  geology.extract(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path)

		#MODELING DATA
		if self.surfex_path != None:
			self.climatic = climatic.extract(out_path=self.watershed_folder,surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)

		#FIELD DATA
		self.piezometry = piezometry.extract(out_path=self.watershed_folder,geographic=self.geographic)
		#self.hydrometry = hydrometry()
		#self.geochemistry = geochemistry()

	def save_variables(self):
		dict_object = {}
		if ('geographic' in self.__dict__.keys()) == True:
			dict_object["geographic"] = self.geographic
		if ('climatic' in self.__dict__.keys()) == True:
			dict_object["climatic"] = self.climatic
		if ('piezometry' in self.__dict__.keys()) == True:
			dict_object["piezometry"] = self.piezometry
		if ('geology' in self.__dict__.keys()) == True:
			dict_object["geology"] = self.geology
		dd.io.save(self.watershed_folder + 'object.h5', dict_object)

	def add_piezometry_data(self):
		self.piezometry.add_data(self.add_data_folder)
