# -*- coding: utf-8 -*-
"""
Created on 

@author: Ronan Abhervé
"""

import rasterio as rio
import geopandas as gpd
from osgeo import gdal, osr
from pyproj import Proj
from pyproj import CRS
from pyproj import Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info

def export_tif(base_dem_path, data_to_tif, data_nodata_val, data_tif_path):
    # Open base dem
    with rio.open(base_dem_path) as src:
        ras_data = src.read()
        ras_nodata = src.nodatavals
        ras_dtype = src.dtypes
        ras_meta = src.profile
    # Type of data
    data_dtype = data_to_tif.dtype
    # Change base dem from data
    ras_meta['dtype'] = data_dtype
    ras_meta['nodata'] = data_nodata_val
    # Create new data raster with base dem size
    with rio.open(data_tif_path, 'w', **ras_meta) as dst:
        dst.write(data_to_tif, 1)
      
def reproject_tif(raw_dem_path, wgs_dem_path, utm_dem_path):
    raw_dem = gdal.Open(raw_dem_path)    
    warp = gdal.Warp(wgs_dem_path,raw_dem,dstSRS='EPSG:4326')
    warp = None
    
    wgs_dem = gdal.Open(wgs_dem_path)

    wgs_dem_data = wgs_dem.GetRasterBand(1).ReadAsArray()
    geodata = wgs_dem.GetGeoTransform()
    x_pixel = wgs_dem_data.shape[1] # columns
    y_pixel = wgs_dem_data.shape[0] # rows
    resolution_x = geodata[1] # pixelWidth: positive
    resolution_y = geodata[5] # pixelHeight: negative
    resolution = resolution_x
    xmin = geodata[0] # originX
    ymax = geodata[3] # originY
    xmax = xmin + x_pixel * resolution_x
    ymin = ymax + y_pixel * resolution_y
    centroid = [xmin+((xmax-xmin)/2),ymin+((ymax-ymin)/2)]
    
    lon = centroid[0]
    lat = centroid[1]
    utm_crs_list = query_utm_crs_info(datum_name="WGS 84",area_of_interest=AreaOfInterest(
                                                            west_lon_degree=lon,
                                                            south_lat_degree=lat,
                                                            east_lon_degree=lon,
                                                            north_lat_degree=lat,),)
    utm_crs = CRS.from_epsg(utm_crs_list[0].code).srs
    
    warp = gdal.Warp(utm_dem_path,wgs_dem,dstSRS=utm_crs.upper())
    warp = None
    
    return utm_crs

def reproject_coord(x_wgs, y_wgs):
    # x_wgs=-2
    # y_wgs=48
    lon = x_wgs
    lat = y_wgs
    utm_crs_list = query_utm_crs_info(datum_name="WGS 84",area_of_interest=AreaOfInterest(
                                                            west_lon_degree=lon,
                                                            south_lat_degree=lat,
                                                            east_lon_degree=lon,
                                                            north_lat_degree=lat,),)
    utm_crs = CRS.from_epsg(utm_crs_list[0].code).srs
    transformer = Transformer.from_crs("epsg:4326", utm_crs)
    x_utm, y_utm = transformer.transform(lat, lon)
    return utm_crs, x_utm, y_utm

def reproject_shp(raw_shp_path, out_shp_path, utm_crs):
    crs_code = utm_crs[5:]
    shp = gpd.read_file(raw_shp_path)
    shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
    # shp.to_crs(utm_crs)
    shp.to_file(out_shp_path)

#%%

# proj = osr.SpatialReference(wkt=dem.GetProjection())
# self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))

