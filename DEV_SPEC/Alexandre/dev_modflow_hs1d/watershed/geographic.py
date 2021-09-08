# coding:utf-8

import os
import pandas as pd
import geopandas as gpd
from osgeo import gdal, osr
from shutil import copyfile
import numpy as np
from IPython.core.debugger import set_trace as st
import whitebox
from pyproj import Transformer
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
def my_callback(value):
    my_callback = 0
wbt.set_default_callback(my_callback)

class extract:
    def __init__(self, dem_path, x, y, snap_dist=150, buff_dist=1000,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):
        print('Extraction des données géographiques')
        self.generate_files(dem_path, x, y, snap_dist, buff_dist, out_path)
        self.load_files(dem_path)

    def generate_files(self,dem_path, x, y, snap_dist, buff_dist, out_path):
        gis_path = out_path + '/data/geographic/'
        fill = gis_path + 'region_fill.tif'
        direc = gis_path + 'region_direc.tif'
        acc = gis_path + 'region_acc.tif'
        outlet_shp = gis_path + 'outlet.shp'
        outlet_snap_shp = gis_path + 'outlet_snap.shp'
        watershed = gis_path + 'watershed.tif'
        self.watershed_shp = gis_path + 'watershed.shp'
        self.watershed_box_shp = gis_path + 'watershed_box.shp'
        watershed_contour_shp = gis_path + 'watershed_contour.shp'        
        watershed_dem = gis_path + 'watershed_dem.tif'
        self.watershed_fill = gis_path + 'watershed_fill.tif'
        self.watershed_direc = gis_path + 'watershed_direc.tif'
        buffer = gis_path + 'buff.shp'
        self.watershed_buff_dem = gis_path + 'watershed_buff_dem.tif'
        watershed_buff_fill = gis_path + 'watershed_buff_fill.tif'
        watershed_buff_direc = gis_path + 'watershed_buff_direc.tif'

        self.watershed_box_buff_dem = gis_path + 'watershed_box_buff_dem.tif'
        watershed_box_buff_fill = gis_path + 'watershed_box_buff_fill.tif'
        watershed_box_buff_direc = gis_path + 'watershed_box_buff_direc.tif'

        if not os.path.exists(gis_path):
                os.makedirs(gis_path)

        dem = gdal.Open(dem_path)
        proj = osr.SpatialReference(wkt=dem.GetProjection())
        geodata = dem.GetGeoTransform()
        dist = np.linspace(0,buff_dist,buff_dist+1)*np.abs(geodata[1])
        buff_dist = dist[np.abs(dist-buff_dist).argmin()]
        crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
        #wbt.breach_depressions(dem_path,fill,2,75*8)
        wbt.fill_depressions(dem_path, fill)
        wbt.d8_pointer(fill, direc, esri_pntr=False)
        wbt.d8_flow_accumulation(fill, acc, log=True)
        df = pd.DataFrame({'x': [x], 'y': [y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=crs)
        gdf.to_file(outlet_shp)
        wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
        wbt.watershed(direc, outlet_snap_shp, watershed, esri_pntr=False)
        wbt.raster_to_vector_polygons(watershed, self.watershed_shp)
        wbt.polygons_to_lines(self.watershed_shp, watershed_contour_shp)
        site_polyg = gpd.read_file(self.watershed_shp)
        site_polyg.to_file(self.watershed_shp)

        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        site_polyg.to_file(buffer)
        wbt.clip_raster_to_polygon(dem_path,buffer,self.watershed_buff_dem)
        wbt.clip_raster_to_polygon(fill,buffer,watershed_buff_fill)
        wbt.clip_raster_to_polygon(direc,buffer,watershed_buff_direc)
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp, watershed_dem,
                                   maintain_dimensions=True)
        wbt.clip_raster_to_polygon(fill,self.watershed_shp,self.watershed_fill)
        wbt.clip_raster_to_polygon(direc,self.watershed_shp,self.watershed_direc)

        wbt.minimum_bounding_envelope(self.watershed_shp,self.watershed_box_shp, features=False)
        site_polyg = gpd.read_file(self.watershed_box_shp)
        site_polyg.to_file(self.watershed_box_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        site_polyg.to_file(buffer)
        wbt.minimum_bounding_envelope(buffer,buffer, features=False)
        site_polyg = gpd.read_file(buffer)
        site_polyg.to_file(buffer)
        wbt.clip_raster_to_polygon(dem_path,buffer,self.watershed_box_buff_dem)
        wbt.clip_raster_to_polygon(fill,buffer,watershed_box_buff_fill)
        wbt.clip_raster_to_polygon(direc,buffer,watershed_box_buff_direc)
        return self

    def load_files(self, dem_path):
        dem = gdal.Open(self.watershed_buff_dem)
        self.dem_data = dem.GetRasterBand(1).ReadAsArray()
        dem = gdal.Open(self.watershed_box_buff_dem)
        self.dem_box_data = dem.GetRasterBand(1).ReadAsArray()
        self.geodata = dem.GetGeoTransform()
        self.resolution = abs(self.geodata[1])
        self.x_pixel = self.dem_data.shape[1]
        self.y_pixel = self.dem_data.shape[0]

        proj = osr.SpatialReference(wkt=dem.GetProjection())
        self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
        self.xmin = self.geodata[0]
        self.xmax = self.geodata[0] + self.dem_data.shape[1] * self.geodata[1]
        self.ymin = self.geodata[3] + self.dem_data.shape[0] * self.geodata[5]
        self.ymax = self.geodata[3]

        self.x_coord = np.linspace(1,self.x_pixel, self.x_pixel)*(self.resolution) + self.xmin
        self.y_coord = self.ymax - np.linspace(1,self.y_pixel, self.y_pixel)*(self.resolution)

        self.centroid = [self.xmin+((self.xmax-self.xmin)/2),self.ymin+((self.ymax-self.ymin)/2)]
        transformer = Transformer.from_crs("epsg:2154", "epsg:4326")
        self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
        self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
        if self.centroid_long_lat_Greenwich[1]<0:
            self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
