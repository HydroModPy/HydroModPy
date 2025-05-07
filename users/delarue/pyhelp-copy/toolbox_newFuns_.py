# -*- coding: utf-8 -*-
"""
Created on 15:39:33 2025-04-03
Last modification : 2025-04-03

@author: delarueo
"""
import sys
sys.path.insert(0, 'M:/GitHub/HydroModPy-dev-waterwise/')

# import for DIRECTORY MANGEMENT
from src.tools.toolbox import create_folder
import os
import shutil

# import for GEOGRAPHY TOOLS
import math
import geopandas as gpd
import numpy as np
# from shapely.geometry import Polygon, Point

import matplotlib as mpl
import matplotlib.pyplot as plt

import pandas as pd

from matplotlib.lines import Line2D
from matplotlib.colors import is_color_like

# import for CERRA helper

import xarray as xr
# TODO how to include ghc or necessary part
from pywtraj import geohydroconvert as ghc # /\ to include in root folder 
import copy

from shapely.geometry import Point
import cartopy

from math import floor,ceil,sqrt


# import for Observation
import re
import csv

# import for Debiaser
from scipy.stats import percentileofscore

# import Climate plot
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.colors import ListedColormap

from datetime import datetime

#%% DIRECTORY MANAGEMENT 

# FROM scr.tools.toolbox
# def create_folder(path): 
#     """
#     If not exist, create a new empty folder.

#     Parameters
#     ----------
#     path : str
#         Folder path.
#     """
#     if not os.path.exists(path):
#         os.makedirs(path)

# FROM cerra_crops_alps_cerra celan_buffer_folder
def delete_folder(path):
    """
    If exist, delete folder and its contents.

    Parameters
    ----------
    path : str
        Folder path.
    """
    
    if os.path.exists(path) and os.path.isdir(path):
        shutil.rmtree(path)  # Remove buffer folder and its contents
        
        
#%% PLOT MANAGEMENT

def save_plot(fig, fig_folder, fig_label, fig_formats = ['png'], verbose = False):
    os.makedirs(fig_folder, exist_ok=True)
    for f in fig_formats:
        fig_name = os.path.join(fig_folder, f'{fig_label}.{f}')
        fig.savefig(fig_name, dpi=300, bbox_inches='tight')
        if verbose:
            print(f"Plot saved to {fig_name}")
 
        
#%% DEBIASING MANAGEMENT       
    # Linear scaling x* = a + b.x
def generate_debiaser(data_ref,data_raw,method='LinearScaling'):
    """
        
    method dispo : 'LinearScaling'
    corr = a + b. mes
    a = 1/b.(ref_mean-mes_mean)
    b = ref_std
    
    """

    if method == 'LinearScaling':
        mean_ref = data_ref.mean()
        mean_raw = data_raw.mean()
        std_ref = data_ref.std()
        std_raw = data_raw.std()
        
        b = std_ref / std_raw
        a = (mean_ref - mean_raw) / b
        
        debiaser = (lambda x: a + b*x )
        
    elif method == 'QuantileMappingReplace':
        data_model = data_raw
        debiaser = (lambda x: (np.percentile(data_ref, percentileofscore(data_model, x))) )
    
    elif method == 'QuantileMappingDelta':
        data_model = data_raw
        debiaser = (lambda x, data_sim : (x + np.percentile(data_ref,   percentileofscore(data_sim, x))
                                           - np.percentile(data_model, percentileofscore(data_sim, x))) )             
    else:
        print('> debiaser generator - method asked not available')
        debiaser = (lambda x: x)
        
    return debiaser

def statistics(data, cols, stats = dict()):
    
    for var in cols:
        stats[f'{var}_mean'] = data[var].mean()
        stats[f'{var}_std'] = data[var].std()
        
    return stats

def evaluate_debias(data_ref, data_raw, data_corr, method = 'diff'):
    """
    method - diff (difference stepBystep - mean - std)

    """
    rmse = (lambda X,Y: sqrt(np.mean((X-Y)**2)))
    
    diff_raw = data_ref - data_raw
    diff_corr = data_ref - data_corr
    
    diff_raw_abs = abs(diff_raw)
    diff_raw_mean = diff_raw.mean()
    diff_raw_std = diff_raw_abs.std()
    rmse_raw = rmse(data_ref,data_raw)
    
    diff_corr_abs = abs(diff_corr)
    diff_corr_mean = diff_corr.mean()
    diff_corr_std = diff_corr_abs.std()
    rmse_corr = rmse(data_ref,data_corr)
    
    evaluation = {'diff_raw': diff_raw,
                  'diff_raw_abs': diff_raw_abs,
                  'diff_raw_mean': diff_raw_mean,
                  'diff_raw_std': diff_raw_std,
                  'rmse_raw': rmse_raw,
                  
                  'diff_corr': diff_corr,
                  'diff_corr_abs': diff_corr_abs,
                  'diff_corr_mean': diff_corr_mean,
                  'diff_corr_std': diff_corr_std,
                  'rmse_corr': rmse_corr}
    
    return evaluation

def evaluate_debias_(data, cRef, cRaw, cCor, label = 'corr', output = dict(), cTime = 'time'):
    """
    method - diff (difference stepBystep - mean - std)

    """
    # 
    rmse = (lambda X,Y: sqrt(np.mean((X-Y)**2)))
    data_ref  = data.loc[:,cRef]
    data_raw  = data.loc[:,cRaw]
    data_corr = data.loc[:,cCor]
    timeline  = data.loc[:,cTime]

    # compute indicators
    diff_raw = data_ref - data_raw
    diff_corr = data_ref - data_corr
    
    diff_raw_abs = abs(diff_raw)
    diff_raw_mean = diff_raw_abs.mean()
    diff_raw_std = diff_raw_abs.std()
    rmse_raw = rmse(data_ref,data_raw)
    
    diff_corr_abs = abs(diff_corr)
    diff_corr_mean = diff_corr.mean()
    diff_corr_std = diff_corr_abs.std()
    rmse_corr = rmse(data_ref,data_corr)
    
    diffs = pd.DataFrame({  cTime: timeline, 
                           'diff_raw':     diff_raw,
                           'diff_raw_abs': diff_raw_abs,
                          f'diff_{label}':     diff_corr,
                          f'diff_{label}_abs': diff_corr_abs})
    
    indicators = { 'diff_raw_mean': diff_raw_mean,
                   'diff_raw_std':  diff_raw_std,
                   'rmse_raw':      rmse_raw,                
                   f'diff_{label}_mean': diff_corr_mean,
                   f'diff_{label}_std':  diff_corr_std,
                   f'rmse_{label}':      rmse_corr}
    
    for key,val in indicators.items():
        output[key] = val

    return diffs, output
        
#%% GEOGRAPHY TOOLS
# TODO find better name close to src.watershed.geographic
class Geo():

    # static variables
    EARTH_RADIUS = 6378137  # Earth's radius in meters (WGS84)
    DEGREES_PER_METER_LAT = 1 / 111320  # Approximate meters per degree latitude

    @staticmethod
    def meters_per_degree_longitude(latitude):
        """
        Return meters per longitude degree at a given latitude.

        Parameters
        ----------
        latitude : float
            latitude in degree.

        Returns
        -------
        TYPE  float
            meters per degree longitude at the given latitude.

        """
        return (math.pi / 180) * __class__.EARTH_RADIUS * math.cos(math.radians(latitude))
    
    
#%%% GDF MANAGEMENT   

    # Functions from geoDataFrame to array coords coords[0] longitude  - coords[1]  latitude
    # TODO standardize coords manipulation
    # TODO check for fonctionality clearer name
    
    def file2coords(file_path, src_crs = 3035, dst_crs = 4326):
        """
        Open .shp file and return the coordonates of the exterior boundary of the object in an array obj_coords.
        If dst_crs = 4326,
            obj_coords[0] : longitude of the exterior boundary
            obj_coords[1] : latitude of the exterior boundary
        
        Parameters
        ----------
        file_path : str
            path to the .shp file.
            
        src_crs : int, optional
            epsg id of the source coordonate system of the .shp file. 
            The default is 3035 (ETRS89-extend / LAEA europe).
            
        dst_crs : int, optional
            epsg id of the destination coordonate system of the returned obj_coords. 
            The default is 4326 (WGS 84 - World geodetic system 1984, used in GPS).
            /!\ If not default value - obj_coords provided in description not valid.

        Returns
        -------
        obj_coords: array[rows:**, cols:2] 
            Coordonates of the exterior boundary of the object in path_file.shp .

        """
        try:
            obj = gpd.read_file(file_path)  
        except:
            print("> error - invalid file path") 
            return False
    
        obj = obj.set_crs(epsg=src_crs)
        obj = obj.to_crs(epsg=dst_crs)
        obj = obj.geometry[0]
        obj_type = type(obj).__name__
        
        toCoords = {
            'Polygon':  lambda obj : np.array([list(coords) for coords in obj.exterior.coords]).T,
            'MultiPolygon': lambda obj : np.array([coord for p in [list(x.exterior.coords) for x in obj.geoms] for coord in p]).T,
            'LineString': lambda obj : np.array([list(coords) for coords in list(obj.coords)]).T
        }.get(obj_type)
        
        obj_coords = toCoords(obj)
        return obj_coords
    
    def gdf2coords(gdf, src_crs = 3035, dst_crs = 4326):    
        """
        Return the coordonates of the exterior boundary of the gdf object in an array obj_coords.
        If dst_crs = 4326,
            obj_coords[0] : longitude of the exterior boundary
            obj_coords[1] : latitude of the exterior boundary
        
        Parameters
        ----------
        gdf : GeoDataFrame
            GeoDataFrame object countaining either a Polygon, a MultiPolygon or a LineString.
            
        src_crs : int, optional
            epsg id of the source coordonate system of the .shp file. 
            The default is 3035 (ETRS89-extend / LAEA europe).
            
        dst_crs : int, optional
            epsg id of the destination coordonate system of the returned obj_coords. 
            The default is 4326 (WGS 84 - World geodetic system 1984, used in GPS).
            /!\ If not default value - obj_coords provided in description not valid

        Returns
        -------
        obj_coords: array[rows:**, cols:2] 
            Coordonates of the exterior boundary of the gdf object.

        """
        if gdf.crs:
            gdf = gdf.to_crs(epsg=dst_crs)
        else:
            gdf = gdf.set_crs(epsg=src_crs)
            gdf = gdf.to_crs(epsg=dst_crs)
        obj = gdf.geometry[0]
        obj_type = type(obj).__name__
        
        toCoords = {
            'Polygon':  lambda obj : np.array([list(coords) for coords in obj.exterior.coords]).T,
            'MultiPolygon': lambda obj : np.array([coord for p in [list(x.exterior.coords) for x in obj.geoms] for coord in p]).T,
            'LineString': lambda obj : np.array([list(coords) for coords in list(obj.coords)]).T
        }.get(obj_type)
    
        if toCoords == None:
            print('> no protocole for this type of object (available - Polygon,Multipolygon,LineString')
            return False
        
        obj_coords = toCoords(obj)
        return obj_coords  

    # gdf visualize several gdf together
    def plot_multiple_gdfs(gdfs, colors = None, color_space = 'viridis', markersize=[50], markershape = ['o'], alpha=0.5, 
                                    title="Multiple GeoDataFrames", xlabel="Longitude", ylabel="Latitude", labels = None, 
                                    src_crs = 3035, dst_crs = 4326,
                                    save = False):
        """
        Plot several geodataframes (gdfs) on the same figure

        Parameters
        ----------
        gdfs : list[gdf]
            List of the gdfs to plot together.
        colors : list[color_code], optional (default: None)
            List of the colors to use on the figure for each gdf.
        color_space : str, optional (default : 'viridis')
            Name of the color space from which extract the colors. 
            Used only if *colors* parameter is None or does not comply with requirements.
        markersize : list[int], optional
            The default is [50].
        markershape : TYPE, optional
            DESCRIPTION. The default is ['o'].
        alpha : TYPE, optional
            DESCRIPTION. The default is 0.5.
        title : TYPE, optional
            DESCRIPTION. The default is "Multiple GeoDataFrames".
        xlabel : TYPE, optional
            DESCRIPTION. The default is "Longitude".
        ylabel : TYPE, optional
            DESCRIPTION. The default is "Latitude".
        labels : TYPE, optional
            DESCRIPTION. The default is None.
        src_crs : TYPE, optional
            DESCRIPTION. The default is 3035.
        dst_crs : TYPE, optional
            DESCRIPTION. The default is 4326.

        Returns
        -------
        None.

        """
        # TODO save option - display option
        # TODO complite legend
        
        # Coordonate system management
        if src_crs is not list():
            src_crs = [src_crs]
            
        if len(src_crs)<len(gdfs):
            crs = src_crs[0]
            src_crs = [crs for i in gdfs]
        
        for i, gdf in enumerate(gdfs):
            if gdf.crs:
                gdfs[i] = gdf.to_crs(dst_crs)
            else:
                gdfs[i] = gdf.set_crs(src_crs[i]).to_crs(dst_crs)
        
        # Default colors if none are provided
        if colors is None or len(colors) != len(gdfs) or colors.is_color_like() or not(all([is_color_like(c) for c in colors])) :
            colors = mpl.colormaps.get_cmap(color_space).resampled(len(gdfs)+1).colors          
            
        if labels is None or len(labels) != len(gdfs):
            labels = [f'{i}' for i in range(len(gdfs))]
        
        if len(markersize)<len(gdfs):
            ms = markersize[0]
            markersize = [ms for i in gdfs]
        
        if len(markershape)<len(gdfs):
            ms = markershape[0]
            markershape = [ms for i in gdfs]
        
        # Create a figure and axis
        fig, ax = plt.subplots(figsize=(10, 10))
              
        # Plot each GeoDataFrame in the list
        for i, gdf in enumerate(gdfs):
            if not gdf.empty: 
                gdf.plot(ax=ax, color=colors[i % len(colors)],  label = labels[i], legend=True,
                          markersize=markersize[i], marker=markershape[i], alpha=alpha)

        # Add legend
        lines = [ Line2D([0], [0], linestyle="none", marker="s",
                  markersize=10, markerfacecolor=t.get_facecolor())
                  for t in ax.collections]
        labels = [t.get_label() for t in ax.collections]
        fig.legend(lines, labels,loc='outside right')
                
        # Set title and labels
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        
        # Show the plot
        plt.show()  
        if save:
            fig.savefig(save)
        
    def calculate_internal_bounds(gdf, shrink_distance=0.1):
        """
        Function to calculate the internal bounds of a GeoDataFrame of points.
        This function computes the convex hull, shrinks it inward, and returns the bounds.

        Parameters:
        - gdf: GeoDataFrame containing points (geometry must be Point).
        - shrink_distance: Distance to shrink the convex hull (default is 0.1).

        Returns:
        - internal_bounds: A tuple (minx, miny, maxx, maxy) of the internal (shrunken) bounding box.
        """
        # Step 1: Compute the convex hull of all the points in the GeoDataFrame
        convex_hull = gdf.unary_union.convex_hull
        bounds = gdf.total_bounds
        scale = max(bounds[2]-bounds[0], bounds[3]-bounds[1])
        
        # Step 2: Shrink the convex hull by the specified shrink_distance using a negative buffer
        internal_polygon = convex_hull.buffer(-shrink_distance*scale)
        
        # Step 3: Check if the resulting polygon is valid
        if internal_polygon.is_valid:
            # Return the bounds of the internal (shrunken) polygon
            internal_bounds = internal_polygon.bounds  # (minx, miny, maxx, maxy)
        else:
            # If the internal polygon is invalid, return the original convex hull's bounds
            internal_bounds = convex_hull.bounds
        
        return internal_bounds
    
    def load_pyHelpGrid(file_path, file_type = 'base', verbose = False):
        
        # define vprint accordingly to *verbose*
        vprint = print if verbose else lambda *a, **k: None
        gdf, df = gpd.GeoDataFrame(), pd.DataFrame()
        
        if file_type == 'base':
            df_grid = pd.read_csv(file_path, sep = ',')
            vprint(df_grid)
            coordinates = []
            vprint('>> Extract grid point coordinates from csv file')
            for index, row in df_grid.iterrows():
                coordinates.append([row['lat_dd'], row['lon_dd']])
                
            # Create GeoDataFrame from coordinates
            coordinates = np.array(coordinates)
            points = [Point(lon, lat) for lat, lon in coordinates]
            gdf = gpd.GeoDataFrame(geometry=points)
            df = pd.DataFrame({'latitude': coordinates.T[0], 'longitude': coordinates.T[1]})
        
        elif file_type == 'input':
            print('>> load_pyHelpGrid - file type input to implement')
            
        else:
            print('>> load_pyHelpGrid - file type not avaliable')
        
        return gdf, df 
                
        
#%% netCDF CERRA TOOLS
### CERRA : Copernicus Europe Regional ReAnalysis
### https://climate.copernicus.eu/copernicus-regional-reanalysis-europe-cerra

class CERRA():
    
    # static variables
    # TODO check standard for each CERRA variables
    STANDARD_CONVERSIONS = {
        't2m': lambda x: x - 273.15
        }
    
    STANDARD_VARIABLES = {
        't2m': '2m_temperature',
        'tp': 'total_precipitation',
        'sde': 'snow_depth',
        'sd': 'snow_depth_water_equivalent',
        'ssr': 'surface_net_solar_radiation'
        }
    STANDARD_DIMS ={
        'valid_time': 'time'
        }
    STANDARD_COORDINATES = {
        'valid_time': 'time',
        'lon' : 'longitude',
        'lat' : 'latitude'
        }
    
    AGGREGATION_RULES = {
        '2m_temperature': 'mean',
        'total_precipitation': 'sum',
        'snow_depth': 'mean',
        'snow_depth_water_equivalent': 'mean',
        'surface_net_solar_radiation' : 'mean'
        }
    
    def __init__(self, path: str, to_standard = True) -> None:       
        self._path = path
        self.dataset = None
        self.shape_grid = None
        self._load_dataset(to_standard)

    def __close__(self):
        self.dataset.close()
        del self
        
    def __save__(self, save_path):
        try: 
            self.dataset.to_netcdf(save_path, mode='w')
        except:
            print(f'> CERRA __save__ save_path not supported : {save_path}')

        
    def _load_dataset(self, to_standard: bool) -> None:
        """
        Load dataset at self._path and apply to_standard if required

        Parameters
        ----------
        to_standard : bool
            If True, the to_standard method is applied to the dataset.

        Returns
        -------
        None.

        """
        self.dataset = xr.open_dataset(self._path, mode='r', engine='netcdf4')
        if to_standard:
            self.to_standard()
        self.shape_grid = self.dataset.latitude.shape
            
    def _extract_gdfGrid(self, src_crs = 4326, dst_crs = 4326):
        
        lat = self.dataset.latitude.values
        lon = self.dataset.longitude.values
        shape = lat.shape
        
        points = []
        yx = []
        Y = []
        X = []
        for y in range(shape[0]):
            for x in range(shape[1]):
                points.append(Point(lon[y,x], lat[y,x]))
                yx.append((y,x))
                Y.append(y)
                X.append(x)
                
        gdf = gpd.GeoDataFrame(geometry=points)        
        gdf = gdf.set_crs(f'epsg:{src_crs}')     
        gdf = gdf.to_crs(epsg = dst_crs)
        
        df_yx = pd.DataFrame({'y': Y, 'x': X})
        
        return gdf, yx, df_yx
        
    
    def to_standard(self): 
        """
        Modify dimension, coordinate and variables names of Dataset for them to be compliant with the standard of HelperCERRA class.
        Idem for unit conversions.
        
        Returns
        -------
        None.

        """
        
        # Coordinates to standard name
        for dim_name in self.dataset.dims:
            if dim_name in __class__.STANDARD_DIMS:
                new_name = __class__.STANDARD_DIMS[dim_name]
                self.dataset = self.dataset.rename({dim_name : new_name})  
        
        for coord_name in self.dataset.coords:
            if coord_name in __class__.STANDARD_COORDINATES:
                new_name = __class__.STANDARD_COORDINATES[coord_name]
                self.dataset = self.dataset.rename({coord_name : new_name})   
                
        # Variable to standard names and units            
        for var_name in self.dataset.data_vars:
            if var_name in __class__.STANDARD_CONVERSIONS:
                # Apply the conversion if the variable has a corresponding function
                conversion_func = __class__.STANDARD_CONVERSIONS[var_name]
                self.dataset[var_name] = conversion_func(self.dataset[var_name])
                
            if var_name in __class__.STANDARD_VARIABLES:
                # Apply the name changes if the variable has a standard name
                new_name = __class__.STANDARD_VARIABLES[var_name]            
                self.dataset = self.dataset.rename({var_name : new_name})


    #◘ generate new files
    @staticmethod
    # TODO deal with georef verbose
    # TODO not static method ?
    def generate_gridFile(ref_path, grid_path, attrs = dict(), coord_ids = dict(), 
                          src_crs = 6258, verbose = False):     
        
        # define vprint accordingly to *verbose*
        vprint = print if verbose else lambda *a, **k: None
        
        data = xr.open_dataset(ref_path, mode='r', engine='netcdf4')
        lat = data.latitude.values
        lon = data.longitude.values
        data.close() 
        
        extras = {'description': 'Cerra data pixel grid coordinates',
                  'grid_projection_type':  'Lambert conformal conical grid',
                  'grid_projection_name':  'ERTS89-LCC',
                  'espg': 6258}
    
        for [key, val] in attrs.items():
            extras[key] = val        
    
        grid = xr.Dataset( coords = {"latitude":  (("y", "x"), lat),
                                     "longitude": (("y", "x"), lon)},
                            attrs  = extras)
        
        grid.rename(coord_ids)  
        grid = ghc.georef(data = grid, crs = src_crs)
    
        ghc.export(grid, grid_path)
        
        vprint(f'>> generate_grid_file from {ref_path}')
        vprint(f'>> generated file at {grid_path}')
        vprint(grid)        
           
        return grid
  
  


    def _find_nearest_point(self, lat, lon, work_crs = 3035, direction = 'all',
                            checkplot = False):
        """
        Find nearest point to the goal point Point(lon,lat) and return its characteristics.

        Parameters
        ----------
        lat : float
            Latitude goal point.
        lon : float
            Longitude goal point.
        src_crs : int, optional
            EPSG of the geographic inputs. 
            The default is 4326 (WGS 84 - World geodetic system 1984, used in GPS).
            /!\ If not default value - lat,lon have to be .
            ******
            
        work_crs : int, optional
            EPSG in which the distance between the points will be computed.
            It is best to choose a projection which will express coordinates in meter.
            The default is 3035 (ETRS89-extend / LAEA europe).
        direction : str, optional
            options : ['se','sw','nw','ne','all','each']
            Indicate in each direction the nearest point(s) will be researched.
            The default is 'all'.
        checkplot : bool, optional
            Display checkplot to show which points are selected if activated. 
            The default is False.

        Raises
        ------
        ValueError
            DESCRIPTION.

        Returns
        -------
        result : DataFrame[index: direction, columns: [y,x,point,d_m]]
            DataFrame with the main characteristics of the nearest point(s).
            y,x   - coordinates of the point in the grid of the dataset
            point - Point object Point(longitude,latitude)
            d_m   - computed distance between nearest and goal point in m (if unit work_crs is meter).
        """
             
        # Apply direction mask            
        grid_lat = copy.deepcopy(self.dataset.latitude.values)
        grid_lon = copy.deepcopy(self.dataset.longitude.values)            
        shape = grid_lat.shape
        
        # Dictionnary of the mask to consider for each direction
        dictMask = {
            'sw': (grid_lat < lat) & (grid_lon < lon % 360),
            'se': (grid_lat < lat) & (grid_lon > lon % 360),
            'nw': (grid_lat > lat) & (grid_lon < lon % 360),
            'ne': (grid_lat > lat) & (grid_lon > lon % 360),
            'all': (grid_lat > -90) & (grid_lon >= 0) }
        
        # For specific direction or absolu nearest *all*
        if direction in dictMask.keys():
            # Choose mask indicating the points which should be considered depending of direction.
            mask = dictMask.get(direction)
                        
            # Mask the grid points outside the specified direction
            mask_h = [~mask[y,x] for y in range(shape[0]) for x in range(shape[1])]
            
            # Extract dataset grid gdf             
            gdf_grid_, yx, df_yx = self._extract_gdfGrid(dst_crs = work_crs)
            gdf_grid = copy.deepcopy(gdf_grid_)
            gdf_grid.geometry[mask_h] = None
            
            
            # Define gdf goal point
            gdf_point = gpd.GeoDataFrame(geometry = [Point(lon,lat) for i in range(len(yx))])
            gdf_point = gdf_point.set_crs(epsg = 4326)          
            gdf_point = gdf_point.to_crs(epsg = work_crs)      
            
            # Compute distance between each grid point and the goal point
            distances = gdf_grid.distance(gdf_point)
            idx = distances.argmin() 
            
            # Extracte characteristics of the nearest grid point in the choosen direction
            result = pd.DataFrame(index = [direction], columns = ['y','x','point','d_m'])
            result['y'][direction] = df_yx['y'][idx]
            result['x'][direction] = df_yx['x'][idx]
            result['point'][direction] = gdf_grid.to_crs(epsg = 4326).geometry[idx]
            result['d_m'][direction] = distances.values[idx]
                        
            if checkplot:
                gdf_selec = gpd.GeoDataFrame(geometry=list(result['point'][:]))
                gdf_selec = gdf_selec.set_crs(epsg = 4326)
                
                Geo.plot_multiple_gdfs([gdf_grid_, gdf_point, gdf_selec], 
                           labels=['grid','point',f'n_{direction}'],
                           markersize=[50], markershape=['+','*','o'],
                           title = f'checkplot _find_nearest_point\n       direction *{direction}*      ',
                           src_crs = work_crs)
        
        # For *each* - find the nearest point in each direction
        elif direction == 'each':
            # Extract dataset grid gdf             
            gdf_grid, yx, df_yx = self._extract_gdfGrid(dst_crs = work_crs)
            
            # Define gdf goal point
            gdf_point = gpd.GeoDataFrame(geometry = [Point(lon,lat) for i in range(len(yx))])
            gdf_point = gdf_point.set_crs(epsg = 4326)          
            gdf_point = gdf_point.to_crs(epsg = work_crs)      
            
            # Compute distance between each grid point and the goal point
            distances = gdf_grid.distance(gdf_point)
            
            # Identify nearest in each direction and extract information
            result = pd.DataFrame(index = ['se','sw','nw','ne'], columns = ['y','x','point','d_m'])
            for compass in ['se','sw','nw','ne']:
                mask = dictMask.get(compass)
                mask_h = [~mask[y,x] for y in range(shape[0]) for x in range(shape[1])]
                distances_ = copy.deepcopy(distances)
                distances_[mask_h] = None                
                idx = distances_.argmin() 
                
                result['y'][compass] = df_yx['y'][idx]
                result['x'][compass] = df_yx['x'][idx]
                result['point'][compass] = gdf_grid.to_crs(epsg = 4326).geometry[idx]
                result['d_m'][compass] = distances.values[idx]
            
            if checkplot:                
                gdf_selec = gpd.GeoDataFrame(geometry=list(result['point'][:]))
                gdf_selec = gdf_selec.set_crs(epsg = 4326)
                
                Geo.plot_multiple_gdfs([gdf_grid, gdf_point, gdf_selec], 
                           labels=['grid','point',f'n_{direction}'],
                           markersize=[50], markershape=['+','*','o'],
                           title = 'checkplot _find_nearest_point\n       direction *each*      ',
                           src_crs = work_crs)

        else :
            raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne', 'all', 'each'.")
            result = None
        
        return result
    
#%% Extract site data tools   
    # TODO check for crs consitency issue
    # TODO ddocumentation
    def generate_site_mask(self, site_id, site_shape_path, obs_paths, output_path, buffer, catch_crs = 3035,
                           verbose = False, checkplot = False, save = True):   
        
        vprint = print if verbose else lambda *a, **k: None
        vprint('>> < START > generate_site_mask')
        if checkplot:            
            create_folder(f'{output_path}checkplot/')
        # Define mask : need to cover catchement area + observation stations
        
        # I. Extract extended site area
        # 1. Extract gdf catchement
        vprint('>> Read area shape file')
        gdf_catch = gpd.read_file(site_shape_path)
        if gdf_catch.crs:
            gdf_catch = gdf_catch.to_crs(epsg=4326)
        else:
            gdf_catch = gdf_catch.set_crs(epsg=catch_crs)
            gdf_catch = gdf_catch.to_crs(epsg=4326)
            
        # 2. Extract gdf of the obersvation station   
        vprint('>> Extract location information about Observation station')
        list_points = []
        i = 0
        for path in obs_paths:
            try:
                name = f'st{i}'
                ws = WeatherStation(name, path)
                list_points.append(ws._point)
                vprint(f'>> Weather Station at {ws._point}')
                i += 1
            except:
                vprint(f'>> Nothing at {path}')
        
        # 3. Combine gdfs
        vprint('>> Combine gdfs')
        if list_points :
            gdf_obs = gpd.GeoDataFrame(geometry = list_points, crs = 4326)
            gdf_site = gdf_catch
        else:            
            gdf_obs = gpd.GeoDataFrame(geometry = list_points, crs = 4326)
            gdf_site = gpd.GeoDataFrame(pd.concat([gdf_catch, gdf_obs], ignore_index=True), crs=4326) 
              
        if checkplot:
            Geo.plot_multiple_gdfs([gdf_catch, gdf_obs], labels = ['site','observation'],
                                   save = f'{output_path}checkplot/{site_id}_catch_obs.pdf')
            
        [minLon,minLat,maxLon,maxLat] = gdf_site.total_bounds
        corners = pd.DataFrame(index = ['sw','se','ne','nw'], 
                               columns = ['longitude','latitude'], 
                               data =[[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat]])
            
        # II. Find grid corners 
        grid_corners = pd.DataFrame(index = ['se','sw','nw','ne'], columns = ['y','x','point','d_m'])
        for c in corners.index:
            res = self._find_nearest_point(corners['latitude'][c], corners['longitude'][c], direction = c)
            grid_corners.loc[c,:] = res.loc[c,:]        
        vprint(grid_corners)
        
        # III. Build mask from grid corners index
        # 1. Identify grid corners indexes (y,x)
        minY, maxY = min(grid_corners['y']), max(grid_corners['y'])
        minX, maxX = min(grid_corners['x']), max(grid_corners['x'])
        
        # 2. Adjust indexes according to buffer
        rangeY = (maxY - minY)/2*(buffer+1)
        rangeX = (maxX - minX)/2*(buffer+1) 
        midY,midX = (minY+maxY)/2, (minX+maxX)/2
        minY = floor(midY - rangeY)
        maxY = ceil(midY + rangeY)
        minX = floor(midX - rangeX)
        maxX = ceil(midX + rangeX)  
        
        mask = np.zeros(self.shape_grid)
        mask[minY:maxY+1, minX:maxX+1] = 1

        
        # CHECKPLOT
        if checkplot:            
            gdf_grid,_,_ = self._extract_gdfGrid(dst_crs = 4326)
            gdf_mask = copy.deepcopy(gdf_grid)
            mask_ = mask.astype(bool)
            mask_h = [~mask_[y,x] for y in range(self.shape_grid[0]) for x in range(self.shape_grid[1])]
            gdf_mask.geometry[mask_h] = None
            
            Geo.plot_multiple_gdfs([gdf_grid,gdf_mask], labels=['grid','mask'],
                                   title = f'Checkplot Mask {site_id}',
                                   markersize = [5],
                                   save = f'{output_path}checkplot/{site_id}_mask.pdf')
          
        # IV. save mask
        np.save(f'{output_path}{site_id}_mask.npy', mask)  
        vprint('>>< END > generate_site_mask')          
        return mask

    def crop_and_save(self, file_id, output_folder, mask):
        
        self.dataset = copy.deepcopy(self.dataset)
        self.dataset['mask'] = (('y', 'x'), mask)  # Apply mask
        self.dataset = self.dataset.where(self.dataset.mask == 1)  # Apply the mask
        
        self.dataset = self.dataset.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
        self.dataset = self.dataset.drop(['mask'])  # Drop unnecessary variables
        
        output = f'{output_folder}{file_id}.nc'
        self.dataset.to_netcdf(output, mode='w') 
        
        return output
    
    def crop(self, mask):
        self.dataset = copy.deepcopy(self.dataset)
        self.dataset['mask'] = (('y', 'x'), mask)  # Apply mask
        self.dataset = self.dataset.where(self.dataset.mask == 1)  # Apply the mask        
        self.dataset = self.dataset.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
        self.dataset = self.dataset.drop(['mask'])
        
      
    @staticmethod  
    def combine(list_path, output_path):
        """
        Combines multiple netcdf files into one netCDF file.
    
        Parameters:
        -----------
        list_path : list
            List of file paths to the individual buffer files.
        output_path : str
            Path to save the combined netCDF file.
    
        Returns:
        --------
        None
        """
        # Combine the separated buffer files into one large dataset
        data = xr.open_dataset(list_path[0])
        for f in list_path[1:]:
            buffer = xr.open_dataset(f)
            data = xr.concat([data, buffer], dim='time')
    
        data.to_netcdf(output_path, mode='w')  # Save combined data
        data.close()  # Close the dataset   
        return output_path

    @staticmethod    
    def extract_site_data(mask, site_id, cerra_path, variables, years, output_path, verbose = False,
                          input_data ='_alps'):
        
        vprint = print if verbose else lambda *a, **k: None
        work_folder = f'{output_path}work/'
        create_folder(work_folder)
        
        for var in variables:            
            vprint(f'>>> {var}\n>>> ', end = '')
            year_files = []
            for year in years:
                vprint(f'{year}', end = '')
                
                # Define file paths
                folder_path = f'{cerra_path}{var}/'
                input_file_path = f'{folder_path}{year}/{year}{input_data}.nc'
                
                # Check if data available for given variable and year
                if os.path.isfile(input_file_path):                
                    # Open dataset
                    data = __class__(input_file_path)
        
                    # Process and save the buffer files
                    year_files.append(data.crop_and_save(f'{year}_{site_id}', work_folder, mask))
                    data.__close__()
                    
                else:
                    vprint(' no data', end = '')
                vprint(' - ', end = '')
            combine_file = f'{cerra_path}{var}/{var}_{site_id}.nc'
            __class__.combine(year_files,combine_file)
            vprint('combine')        
        delete_folder(work_folder)
        return combine_file
        
    def generate_local_cerra(self, cerra_path, shape_path, obs_path, output_path,
                           site_id, type_site, variables, years, buffer = 0.2,
                           verbose = False, checkplot = False):

        mask = self.generate_site_mask(site_id, 
                                       shape_path, obs_path, output_path,
                                       buffer, catch_crs = 3035,
                                       obs_variables = ['air_temperature'], 
                                       checkplot = checkplot)
        self.__close__() 
        output_file = __class__.extract_site_data(mask, site_id, cerra_path, variables, 
                                    years, output_path, verbose = True)
        return output_file

#%% Cerra data to Help input    
    def create_pyHelpGrid(self, bounds, step_meters):
        """
        Generate a grid of coordinates within a bounding box with a specific step size in meters.

        Parameters
        ----------
        bounds : A tuple (min_lon, min_lat, max_lon, max_lat) defining the bounding box.
            DESCRIPTION.
        step_meters : int
            Step size in meters for the grid..

        Returns
        -------
        gdf : TYPE
            DESCRIPTION.
        df : TYPE
            DESCRIPTION.
            A GeoDataFrame containing the grid of points and a corresponding DataFrame
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Convert step in meters to step in degrees for latitude
        step_deg_lat = step_meters * Geo.DEGREES_PER_METER_LAT
        
        # Generate latitudes within the bounding box
        latitudes = np.arange(min_lat, max_lat, step_deg_lat)
        
        # Generate longitudes for each latitude
        coordinates = []
        for lat in latitudes:
            meters_per_deg_lon = Geo.meters_per_degree_longitude(lat)
            step_deg_lon = step_meters / meters_per_deg_lon
            longitudes = np.arange(min_lon, max_lon, step_deg_lon)
            
            # Add the latitudes and longitudes to coordinates
            for lon in longitudes:
                coordinates.append([lat, lon])
        
        # Create GeoDataFrame from coordinates
        coordinates = np.array(coordinates)
        points = [Point(lon, lat) for lat, lon in coordinates]
        gdf = gpd.GeoDataFrame(geometry=points)
        df = pd.DataFrame({'latitude': coordinates.T[0], 'longitude': coordinates.T[1]})
        
        return gdf, df
    
    def generate_pyHelp_file(self, gdf_helpGrid, df_helpGrid, var, rule = 'nearest', timestep = 'D',
                              verbose = False, save = False):   
        """
        
        Parameters
        ----------
        gdf_helpGrid : TYPE
            DESCRIPTION.
        df_helpGrid : TYPE
            DESCRIPTION.
        var : TYPE
            DESCRIPTION.
        rule : TYPE, optional
            DESCRIPTION. The default is 'nearest'.
        timestep : TYPE, optional
            DESCRIPTION. The default is 'D'.
        verbose : TYPE, optional
            DESCRIPTION. The default is False.
        save : TYPE, optional
            DESCRIPTION. The default is False.

        Returns
        -------
        values : TYPE
            DESCRIPTION.

        """
        
        vprint = print if verbose else lambda *a, **k: None
        vprint(f'> generate_pyHelp_input {var} {timestep}')
    
        timeline = self.dataset['time'].values        
        values = pd.DataFrame(columns = range(df_helpGrid.shape[0]))
        values['time'] = pd.to_datetime(timeline, format='%d-%b-%Y %H:%M:%S')
        
        vprint('> start data extraction - points ', end = '')
        i = 0         
        for point in gdf_helpGrid.geometry: 
            vprint(i, end = ' ')
            if rule == 'nearest':
                nearest = self._find_nearest_point(point.y, point.x, direction='all')
                v = self.dataset[var][:,nearest['y']['all'],nearest['x']['all']]
    
            elif rule == 'linear':
                nearest = self._find_nearest_point(point.y, point.x, direction='each')                
                v = np.zeros(len(timeline))
                for r in nearest.index:                    
                    v +=  self.dataset[var][:,nearest['y'][r],nearest['x'][r]].values*nearest['d_m'][r]/nearest['d_m'].sum()
                    
            else: 
                print('> rule not available')
                           
                
            values[i] = pd.to_numeric(v, errors='coerce')  
            i += 1
    
        vprint(f'\n> resample time - new timestep :{timestep}')
        values.set_index('time', inplace=True)
        values = values.resample(timestep).agg(__class__.AGGREGATION_RULES[var])       
        values = pd.concat([df_helpGrid.T, values])
        
        if save:
            vprint(f'> save data at {save}')
            values.to_csv(save)
            
        return values
    

#%% Debaising tools
# TODO altitude correcteur

    def apply_debiaser(self, debiaser, variable, save = False, inplace = False, verbose = False):
        vprint = print if verbose else lambda *a, **k: None
        debias_dataset = copy.deepcopy(self.dataset)
        for y in range(self.shape_grid[0]):
            for x in range(self.shape_grid[1]):
                vprint(f'{y} {x}', end = ' | ')
                df_pixel = pd.DataFrame({variable : self.dataset[variable][:,y,x].values})
                df_pixel[f'{variable}_debias'] = df_pixel[variable].apply(debiaser)                
                debias_dataset[variable][:,y,x] = copy.deepcopy(df_pixel[f'{variable}_debias'])
        if inplace:
            self.dataset = debias_dataset   
            if save:
                self.__save__(save) 
        else:
            if save:
                try:
                    debias_dataset.to_netcdf(save, mode='w')
                except:
                    print(f'> save path not supported : {save}')
        vprint('apply_debiaser END')

        
#%% Timeserie statistics

    def compute_timeserie_statistics(self, shape_path, var,
                                     catch_crs = 3035, save = False):
        # Build output structure
        timeline = self.dataset['time'].values
        empty_data = np.zeros((timeline.shape[0],4))
        statics = pd.DataFrame(columns = ['time','mean','min','max'],
                               data = empty_data)
        statics['time'] = pd.to_datetime(timeline, format='%d-%b-%Y %H:%M:%S')
        
        # Identify pixel to consider
        mask = self.generate_site_mask('site_id', shape_path, [], '', 0, catch_crs = catch_crs,
                               verbose = False, checkplot = False, save = False)        
        self.crop(mask)   
        
        means, mins, maxs = [], [], []
        for t in range(len(timeline)):
            timestep = np.array(self.dataset[var][t,:,:].values)
            avg, m, M = timestep.mean(), timestep.min(), timestep.max()
            means.append(avg)
            mins.append(m)
            maxs.append(M)

        statics['mean'] = pd.to_numeric(means, errors='coerce')  
        statics['min'] = pd.to_numeric(mins, errors='coerce') 
        statics['max'] = pd.to_numeric(maxs, errors='coerce') 
        statics = statics.set_index('time')

        if save:
            try:
                statics.to_csv(save)
            except:
                print(f'>> compute_timeserie_statistics - {save} not a valid path')
                
        return statics
    
        












        
#%% weather station
class WeatherStation():
    
    """
    Choose - data as a dictionnary with each variable with its own dataframe 
    Easier handle of variable time resolution and installation datae of the instrument
    
    """
    
    WEATHER_STATION_FILES = {
        '2m_temperature' : 'T.degC',
        'total_precipitation': 'p.mm'
        }
        
    def __init__(self, name, path, variables = []):
        self._name = name        
        self._path = path
        self._infos = {}
        self._data = {}
        self._read_coordinate_infos()
        for var in variables:
            self._load_data(var)
    def __init__(self, name, path):
       self._name = name        
       self._path = path
       self._infos = {}
       self._data = {}
       self._read_coordinate_infos()                    
            
    def __str__(self):
        text = f'{self.name}\n'
        for key,val in self._infos.items():
            text = f'{text}{key} {val}\n'
        return text
    
    def _load_data(self, var):
        DELIMITER = re.compile(r'(,|;)')
        def csv_read(path):            
            with open(path, 'r', newline='') as f1:
                sample = f1.read(5000)
                delimiter = DELIMITER.search(sample).group(0)
            data = pd.read_csv(path, sep=delimiter)
            return data

        # Open data file
        var_ws = __class__.WEATHER_STATION_FILES[var]
        path_data = f'{self._path}{var_ws}.csv'                 
        data = csv_read(path_data)
        cols = data.columns.values

        # Format weather station data
        station_data = pd.DataFrame()
        station_data['time'] = pd.to_datetime(data[cols[0]], format= 'mixed') #'%d-%b-%Y %H:%M:%S')

        # Extract the year for grouping
        station_data['year'] = station_data['time'].dt.year

        # Ensure numeric columns are correctly converted
        station_data[f'{var}_{self._name}'] = pd.to_numeric(data[cols[1]], errors='coerce')
        station_data.set_index('time', inplace=True)
        
        self._data[var] = station_data
        
    def _read_coordinate_infos(self):
        
        # Open the text file and read the content
        NUMS = re.compile(r"[+-]?\d+(?:\.\d+)?")
        WGS = re.compile(r"WGS\s*\d*", re.IGNORECASE)
        UTM = re.compile(r"UTM", re.IGNORECASE)
        EPSG = re.compile(r"epsg[;:]\s*(\d+)",re.IGNORECASE)
        ZONE = re.compile(r"zone\s*[:;]?(\d{1,3}[A-Za-z])",re.IGNORECASE)
        
        CRS_TO_EPSG = {'WGS84': {''   : 4326, 
                                 '32T': 32632},
                       'UTM': {'32N': 32632},
                       'LV95': {'' : 2056}}
        
        # TODO generalize path 
        path = f'{self._path}infos/coordinates.txt'
        
        with open(path, 'r') as file:
            lines = file.readlines()
        
        # Extract the relevant data from the file content
        geo_info = {}
        for line in lines: 
            
            # Coordinate system
            if line.lower().startswith(('ref','crs')):
                wgs = WGS.search(line)
                utm = UTM.search(line)
                epsg = EPSG.search(line)
                if wgs:
                    geo_info['crs'] = wgs.group(0).replace(" ", "")
                    geo_info['zone'] = ''
                if utm: 
                   geo_info['crs'] = 'UTM'
                   geo_info['zone'] = '' 
                if epsg: 
                    geo_info['epsg'] = int(epsg.group(1)) 
                    
            elif line.lower().startswith('zone'):
                zone = ZONE.search(line)
                geo_info['zone'] = zone.group(1)
                    
            elif line.lower().startswith(('x','easting')):
                x = NUMS.search(line)
                geo_info['x'] = float(x.group(0))        
                
            elif line.lower().startswith(('y','northing')):
                y = NUMS.search(line)
                geo_info['y'] = float(y.group(0))    
            
            elif line.lower().startswith(('z','alt')):
                alt = NUMS.search(line)
                geo_info['alt'] = float(alt.group(0)) 
                
        if 'epsg' not in geo_info and 'crs' in geo_info:
            geo_info['epsg'] = CRS_TO_EPSG[geo_info['crs']][geo_info['zone']]  
        
        if 'x' in geo_info and 'y' in geo_info:
            point = Point(geo_info['x'], geo_info['y'])
            gdf = gpd.GeoDataFrame(geometry=[point])
            gdf = gdf.set_crs(epsg = geo_info['epsg'])
        else:
            raise ValueError("Unable to parse geographic information.")
            
        try:
            self._infos = {**self._infos, **geo_info}
            self._gdf = gdf.to_crs(epsg = 4326)
            self._point = Point(self._gdf.geometry[0].x, self._gdf.geometry[0].y)
        except:
            raise ValueError(f"Coordinates not readable")


#%% Climate statistics and visualization
# From Clement Roques -- Code

class ClimateStats():
    
    ANOMALY_SETTINGS = {'timestep': 'Y', 
                        'method': 'mean',
                        'ref_bounds': [pd.Timestamp('1984-01-01'), pd.Timestamp('2000-12-31')]}

    VAR_ID_TO_NAME = {
        '2m_temperature': 'Air Temperature',
        'total_precipitation': 'Precipitation'
        }
    
    VAR_ID_TO_UNIT = {
        '2m_temperature': '°C',
        'total_precipitation': 'mm/3h'
        }
    
    RESAMPLE_UNIT = {
        'total_precipition_sum': {'H': 'mm/hour', 'D': 'mm/day', 
                                  'M': 'mm/month','Y': 'mm/year'},
        'total_precipitation_mean': {},
        '2m_temperature_mean': {}
        }
    
    
        
    def __init__(self, path, var_id, location = 'Neverland'):
        
        self.path = path
        self.variable_id = var_id
        self.name = __class__.VAR_ID_TO_NAME[self.variable_id]
        self.unit = __class__.VAR_ID_TO_UNIT[self.variable_id]
        self.anomaly_unit = False
        self.location = location
        
        self.data_origin = pd.DataFrame()
        self.data_work = pd.DataFrame()
        self.load_data()
   
    
    def load_data(self):
        df = pd.read_csv(self.path, index_col=0)
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time')
        
        self.data_origin = df
        self.data_work = copy.deepcopy(df)   
        
    def reset_data(self):
        self.data_work = copy.deepcopy(self.data_origin)
        self.unit = __class__.VAR_ID_TO_UNIT[self.variable_id]
        self.name = __class__.VAR_ID_TO_NAME[self.variable_id]
        
    def resample_data(self, timestep, method):
        # Modify unit in ClimateStats if necessary
        try:
            new_unit = __class__.RESAMPLE_UNIT[f'{self.variable_id}_{method}']  
            if new_unit:
                new_unit = new_unit[timestep]
            else:
                new_unit = self.unit
            self.unit = new_unit
                
        except:
            print('>> WARNING Not information in RESAMPLE_UNIT for the provided parameters')
        
        # Resample data
        if method == 'mean':
            self.data_work = self.data_work.resample(timestep).mean()
            
        elif method == 'sum':
            self.data_work = self.data_work.resample(timestep).sum()
            
        else:
            print('>> WARNING method asked not avaliable')
            
          
    def long_name(self):
        names = {}
        for key in self.data_work.columns:
            names[key] = f'{self.variable_id}_{key}'
        self.data_work.rename(columns = names, inplace = True)
        
    @staticmethod   
    def combine_data(X,Y):          
        X.long_name()
        Y.long_name()         
        
        combo = X.data_work.join(Y.data_work)   
        combo.dropna(axis = 0, how = 'any', inplace = True)
        
        return combo

    def compute_anomaly(self, ref_bounds, method = 'diff'):
        [start_ref, end_ref] = ref_bounds
        mean_ref = self.data_work['mean'][(self.data_work.index >= start_ref) & (self.data_work.index <= end_ref)].mean()
        if method == 'diff':
            self.data_work['anomaly'] = self.data_work['mean'] - mean_ref
            self.anomaly_unit = self.unit
        elif method == 'relative':
            self.data_work['anomaly'] = (self.data_work['mean'] - mean_ref)/mean_ref*100
            self.anomaly_unit = '%'
        else:
            print('>> WARNING compute_anomaly - methode [{method}] not avaliable')
        
    # Visualisation methods        
    def plot_climate_stripes(self, fig_folder, fig_formats = ['png','pdf'], 
                             time_bounds = [], plot_settings = {}, 
                             anomaly_settings = ANOMALY_SETTINGS, 
                             display = False, verbose = False):
        # plot setting
        settings = {'LIM' : 2.5,
                    'cmap' : ListedColormap([
                        '#08306b', '#08519c', '#2171b5', '#4292c6',
                        '#6baed6', '#9ecae1', '#c6dbef', '#deebf7',
                        '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a',
                        '#ef3b2c', '#cb181d', '#a50f15', '#67000d',
                        ])
                    }
        
        for key, val in plot_settings.items():
            settings['key'] = val
        
        # compute data anomaly
        self.resample_data(anomaly_settings['timestep'], anomaly_settings['method'])
        self.compute_anomaly(anomaly_settings['ref_bounds'])
        
        # define plot time boundaries
        if time_bounds:
            [FIRST,LAST] = time_bounds
        else:
            FIRST, LAST = self.data_work.index.year.min(), self.data_work.index.year.max()
            
        # build plot    
        fig = plt.figure(figsize=(10, 1))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        col = PatchCollection([
            Rectangle((y, 0), 1, 1) for y in range(FIRST, LAST + 1)
        ])
        
        col.set_array(self.data_work['anomaly'].values)
        col.set_cmap(settings['cmap'])
        col.set_clim(-settings['LIM'], settings['LIM'])
        
        ax.add_collection(col)

        ax.set_ylim(0, 1)
        ax.set_xlim(FIRST, LAST + 1)
        if display:
            plt.show()
        
        # save plot
        save_plot(fig, fig_folder, f'{self.variable_id}_{self.location}_stripes', 
                  fig_formats = fig_formats, verbose = verbose)

    def plot_monthly_anomaly(self, fig_folder, fig_formats = ['png','pdf'], 
                             time_bounds = [], plot_settings = {}, 
                             anomaly_settings = ANOMALY_SETTINGS, 
                             display = False, verbose = False):
        
        # Plot setting
        settings = {
            'NegColor':      'red',
            'PosColor':      'blue',
            'HorizontalGrid': False
            }
        # define plot time boundaries

            
        for key, val in plot_settings.items():
            settings[key] = val
        
        # Compute data anomaly
        self.compute_anomaly(anomaly_settings['ref_bounds'])        
        self.resample_data('M', 'mean')
        
        # Calculate the rolling 12-month average
        rolling_12m_avg = self.data_work['anomaly'].rolling(window=12, min_periods=1).mean()

        # Build plot
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # # Set background color
        # fig.patch.set_facecolor('white')

        # Plot monthly anomalies
        axes[0].bar(self.data_work.index, self.data_work['anomaly'], 
                    color = [settings['NegColor'] if anomaly <= 0 else settings['PosColor'] 
                             for anomaly in self.data_work['anomaly']],
                    width = 50)

        
        axes[0].set_ylabel(f'Anomaly [{self.unit}]', fontsize=14, labelpad=15)
        axes[0].set_title(f'Monthly {self.name} Anomalies [{self.unit}]', fontsize=12, pad=10)
        axes[0].set_ylim(self.data_work['anomaly'].min() - 0.01, self.data_work['anomaly'].max() + 0.01)

        # Plot rolling 12-month average excluding first and last 12 months
        rolling_12m_avg_trimmed = rolling_12m_avg.iloc[12:-12]
        axes[1].plot(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed, color='black')
        axes[1].fill_between(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed, 
                             0, where = rolling_12m_avg_trimmed >= 0, 
                             facecolor = settings['PosColor'], interpolate=True)
        axes[1].fill_between(rolling_12m_avg_trimmed.index, rolling_12m_avg_trimmed,
                             0, where=rolling_12m_avg_trimmed <= 0, 
                             facecolor = settings['NegColor'], interpolate=True)
        
        axes[1].set_ylabel(f'Anomaly [{self.unit}]', fontsize=14, labelpad=15)
        axes[1].set_title(f'\n12-Month Rolling Average {self.name} Anomalies [{self.unit}]', fontsize=12, pad=10)
        axes[1].set_ylim(rolling_12m_avg_trimmed.min() - 0.01, rolling_12m_avg_trimmed.max() + 0.01)

        if settings['HorizontalGrid']:
            axes[1].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')
            axes[0].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')

        # Customize tick marks and labels
        for ax in axes:
            ax.set_xticks(self.data_work.index[::24])  # Display every other year
            ax.set_xticklabels(self.data_work.index.year.unique()[::2], rotation=45, ha='right', fontsize=8)
        # Add horizontal line at 0 for both subplots
        for ax in axes:
            ax.axhline(0, color='black', linewidth=1)

        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)

        if display:
            plt.show()
        
        # save plot
        save_plot(fig, fig_folder, f'{self.variable_id}_{self.location}_monthly_anomaly', 
                  fig_formats = fig_formats, verbose = verbose)

    @staticmethod
    def plot_XY_anomaly(X, Y, fig_folder, fig_formats = ['png','pdf'], 
                        plot_settings = {}, 
                        anomaly_settings = ANOMALY_SETTINGS, 
                        display = False, verbose = False):
        
        # Apply verbose command
        vprint = print if verbose else lambda *a, **k: None
        
        # Plot setting default and provided
        settings = {
            'months_X':      range(1, 5),
            'months_Y':      range(6, 9),
            'timestep':      'Y',
            'anomaly_method_X': 'relative',
            'anomaly_method_Y': 'diff'
            }
        for key, val in plot_settings.items():
            settings['key'] = val
        
        # Dict for plot label
        MONTHS_SHORT = {
            1: 'Jan', 2: 'Feb', 3: 'Mar' ,  4: 'Apr',  5: 'May',  6: 'Jun',
            7: 'Jul', 8: 'Aug', 9: 'Sept', 10: 'Oct', 11: 'Nov', 12: 'Dec'
            }
        
            
        # Define the months to include
        X.data_work = X.data_work[X.data_work.index.month.isin(settings['months_X'])]
        Y.data_work = Y.data_work[Y.data_work.index.month.isin(settings['months_Y'])]
        vprint('time period OKAY')
        
        # Group the temperature data by year to create yearly anomalies
        X.resample_data(settings['timestep'], 'mean')
        Y.resample_data(settings['timestep'], 'mean')
        vprint('resample OKAY')
        
        # Compute anomaly on relevant months
        X.compute_anomaly(anomaly_settings['ref_bounds'], settings['anomaly_method_X'])
        Y.compute_anomaly(anomaly_settings['ref_bounds'], settings['anomaly_method_Y'])
        vprint('compute anomaly OKAY')
        
        
        # Crop data to commun area
        df = __class__.combine_data(X,Y)
        vprint(df)
        aX = f'{X.variable_id}_anomaly'
        aY = f'{Y.variable_id}_anomaly'

        # Create the scatter plot
        # Build plot
        fig, ax = plt.subplots(1, 1, figsize=(10, 8), sharex=True)
        sc = ax.scatter(df[aX], df[aY], c = df.index.year, cmap='jet', marker="o", s=400, zorder=1, lw=1, alpha=1)

        # Add labels and title
        X_months = f"{MONTHS_SHORT[settings['months_X'][0]]}-{MONTHS_SHORT[settings['months_X'][-1]]}"
        Y_months = f"{MONTHS_SHORT[settings['months_Y'][0]]}-{MONTHS_SHORT[settings['months_Y'][-1]]}"
        
        ax.set_xlabel(f'{X.name} Anomaly {X_months} [{X.anomaly_unit}]', fontsize=14)
        ax.set_ylabel(f'{Y.name} Anomaly {Y_months} [{Y.anomaly_unit}]', fontsize=14)

        # Add colorbar
        cbar = plt.colorbar(sc)
        cbar.ax.tick_params(labelsize=14)  # Increase font size of colorbar ticks

        # Add horizontal and vertical lines at x=0 and y=0 with lower zorder
        ax.axhline(0, color='black', linewidth=1, zorder=0)
        ax.axvline(0, color='black', linewidth=1, zorder=0)

        for i, txt in enumerate(df.index.year):
            ax.annotate(txt, (df[aX][i], df[aY][i]), color='black', fontsize=10, ha='right')

        # Increase font size of tick labels
        ax.tick_params(axis='both', labelsize=12)

        if display:
            plt.show()
        
        # save plot
        save_plot(fig, fig_folder, f'{X.variable_id}_{Y.variable_id}_{X.location}_anomaly', 
                  fig_formats = fig_formats, verbose = verbose)

        
        return df
    
    
    