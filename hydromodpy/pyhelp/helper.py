# -*- coding: utf-8 -*-
"""
Created on Mon Feb 24 13:21:05 2025

@author: mathi
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point
from pyproj import Transformer
import xarray as xr

def load_csv(file_path: str) -> pd.DataFrame:
    """
    Load a CSV file into a dataframe.   
    """
    try:
        return pd.read_csv(file_path)
    except Exception as e:
        print(f"Error loading CSV file: {e}")
        return pd.DataFrame()

def load_shapefile(shapefile_path: str) -> gpd.GeoDataFrame:
    """
    Load a shapefile into a GeoDataFrame.
  
    Return a geodataframe containing the shapefile geometry
    """   
    try:
        return gpd.read_file(shapefile_path)
    except Exception as e:
        print(f"Error loading shapefile: {e}")
        return None

def get_centroid_coordinates(gdf: gpd.GeoDataFrame) -> tuple:
    """
    Calculate the centroid of the geometry contained in the given geodataframe file. 

    Return --> (float, float)
    tuple (longitude, latitude) of the centroid
    """ 
    if gdf is None:
        print("Error: GeoDataFrame is None")
        return None, None
    
    if gdf.empty:
        print("Error: GeoDataFrame is empty")
        return None, None
    
    if gdf.crs is None:
        print("Error: Shapefile has no CRS")
        return None, None
    
    try:
        gdf = gdf.to_crs("EPSG:2056")
        gdf["geometry"] = gdf.geometry.centroid 
        gdf = gdf.to_crs("EPSG:4326")  
        point = gdf.geometry.iloc[0]
        return point.x, point.y
    except Exception as e:
        print(f"Error processing centroid: {e}")
        return None, None

def transform_coordinates(dem_file_path: str, from_crs: str, to_crs: str) -> list:
    """
    Read a DEM file, iterate through its pixels and 
    convert the coordinates from  a crs to another

    return --> list of (float, float)
    list of tuples (longitude, latitude)
    """
    try:
        dem_dataset = rasterio.open(dem_file_path)
        transform = dem_dataset.transform
        width, height = dem_dataset.width, dem_dataset.height
        transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)
        
        coordinates = []
        for row in range(height):
            for col in range(width):
                x, y = transform * (col, row)
                lon, lat = transformer.transform(x, y)
                coordinates.append((lon, lat))
        return coordinates
    except Exception as e:
        print(f"Error processing DEM file: {e}")
        return []
    
def filter_coordinates_by_shape(coordinates: list, shapefile_path: str, target_crs: str) -> list:
    """
    Filter the DEM coordinates according to the watershed shapefile polygon.
    
    return --> list of (float, float)
    """
    try:
        gdf = load_shapefile(shapefile_path)
        if gdf is None:
            return []

        polygon = gdf.to_crs(target_crs).unary_union
        filtered = [pt for pt in coordinates if polygon.covers(Point(pt))]
        return filtered
    except Exception as e:
        print(f"Error filtering coordinates by shapefile: {e}")
        return []

def select_nearest_point(ds: xr.Dataset, lon: float, lat: float) -> xr.Dataset:
    """
    select the nearest point in a xr.dataset from the given longitude and latitude.
     
    return --> a cropped dataset corresponding to the nearest point 
    """ 
    if lon is not None and lat is not None:
        return ds.sel(longitude=lon, latitude=lat, method="nearest")
    return None

def select_within_polygon_points(ds: xr.Dataset, gdf: gpd.GeoDataFrame) -> xr.Dataset:
    """
    select and filter the points in a xr.dataset which coordinates 
    are within the perimeter of the given geodataframe.
    
    return --> a cropped dataset corresponding to the filtered points
    """
    
    try:
        polygon = gdf.unary_union

        lons = ds.longitude.values
        lats = ds.latitude.values

        LON, LAT = np.meshgrid(lons, lats)

        mask = np.zeros(LON.shape, dtype=bool)
        for i in range(LON.shape[0]):
            for j in range(LON.shape[1]):
                pt = Point(LON[i, j], LAT[i, j])
                mask[i, j] = polygon.contains(pt)

        ds_filtered = ds.where(mask, drop=True)
        return ds_filtered
    
    except Exception as e:
        print(f"Error in select_within_polygon_points: {e}")
        return ds


def convert_units(df: pd.DataFrame, var_key: str) -> pd.DataFrame:
    """
    Convert precipitation to mm 
    temperature to Fahrenheit 
    and change the unit of the radiation 
    """   
    if var_key == "precipitation":
        df = df * 1000.0
        pass
    elif var_key == "temperature":
        df = df - 273.15
    elif var_key == "radiation":
        df = df * 1e-6
    return df


