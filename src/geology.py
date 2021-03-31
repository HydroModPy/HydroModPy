#coding:utf-8

# Librairies
import os
import sys
from osgeo import gdal, osr
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)

class structure:
    def __init__(self, dem_path, geo_path = os.path.dirname(os.getcwd())+'/data/geology/GEO1M.shp', out_path = os.path.dirname(os.getcwd())+'/output/'):
        self.dem_path = dem_path
        self.geo_path = geo_path
        self.structure_dem_path = out_path + 'GeoStructure.tif'
        self.land_sea_dem = out_path + 'Land_Sea.tif'
        self.generate_structure_dem()
        
    def generate_strucutre_dem(self):
        wbt.vector_polygons_to_raster(self.geo_path, self.structure_dem_path , field="CODE_LEG", nodata=None, base=self.dem_path)
        wbt.vector_polygons_to_raster(self.geo_path, self.r_terre_mer, field="T_M_num", nodata=None, base=self.dem_path)
        dem_geo = gdal.Open(self.r_geo)
        dem_data = dem_geo.GetRasterBand(1).ReadAsArray()
        dem_T_M = gdal.Open(self.r_terre_mer)
        dem_data_T_M = dem_T_M.GetRasterBand(1).ReadAsArray()
        
        return self
        