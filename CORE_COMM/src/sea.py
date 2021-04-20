import os
import sys
import numpy as np
import geopandas as gpd
from IPython.core.debugger import set_trace as st

class mean_sea_level:
	'''
	centroid: list : X and Y coordinates of the centroid of the dem
	'''
	def __init__(self,centroid):
		self.ram_path = os.path.dirname(os.getcwd())+"/data/sea/RAM_2020.shp"
		self.xcentroid = centroid[0]
		self.ycentroid = centroid[1]
		self.get_mean_sea_level()

	def get_mean_sea_level(self):
		gdf = gpd.read_file(self.ram_path)
		ports = gdf.to_crs(epsg=2154)
		ports = ports.dropna(subset=['NM', 'ZH_Ref'])
		ports = ports.reset_index()
		dist = np.sqrt((self.xcentroid-ports.geometry.x.values)**2+(self.ycentroid-ports.geometry.y.values)**2)
		index = (np.abs(dist)).argmin()
		self.port = ports.SITE[index]
		self.mean_sea_level = ports.NM[index]/100+ports.ZH_Ref[index]