# -*- coding: utf-8 -*-
"""
@date: 2025-04-07
@lastMod: 2025-09-23
@author: delarueo
@description: Toolbox new functions
@littleMemo: a lot - to unpack
"""
#%% 
# To be compatible with hydromodpy structure
# import os
# local_loc = os.getcwd()
# local_loc = local_loc.replace('\\','/')
# local_loc_split = local_loc.split('/')
# folder_path = local_loc_split[0:-2]
# root_path = '/'.join(folder_path) + '/'
# import sys
# sys.path.insert(0, root_path)

import os
from pathlib import Path
import sys
EXTERNAL_DIR = Path(r"D:/git/hydromodpy-waterwise")
sys.path.insert(0, str(EXTERNAL_DIR))

import shutil

# import for GEOGRAPHY TOOLS
import math
import geopandas as gpd
import numpy as np

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd

from matplotlib.lines import Line2D
from matplotlib.colors import is_color_like

# import for CERRA helper

import xarray as xr
# TODO how to include ghc or necessary part
from cerra.pywtraj import geohydroconvert as ghc # /\ to include in root folder 
import copy

from shapely.geometry import Point


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
import matplotlib.dates as mdates

import seaborn as sns

# from matplotlib.ticker import FuncFormatter
# # Visual settings
# plt.style.use('./mypythonstyle_sourcesanspro.mplstyle')

#%% DIRECTORY MANAGEMENT 
# FROM cerra_crops_alps_cerra clean_buffer_folder
def delete_folder(path):
    """
    delete_folder delete folder at [path] and its contents

    :param path: folder to delete
    :type path: str
      """
    
    if os.path.exists(path) and os.path.isdir(path):
        shutil.rmtree(path)  # Remove buffer folder and its contents

def create_folder(path):
    """
    If not exist, create a new empty folder.

    Parameters
    ----------
    path : str
        Folder path.
    """
    if not os.path.exists(path):
        os.makedirs(path)     
        
#%% PLOT MANAGEMENT
def save_plot(fig, fig_folder, fig_label, fig_formats = ['png'], verbose = False):
    """
    save_plot save plot at the given location & in the given location.

    :param fig: figure to save
    :type fig: fig object
    :param fig_folder: save location
    :type fig_folder: str
    :param fig_label: name of the figure
    :type fig_label: str
    :param fig_formats: list of the formats in which to save the figure, defaults to ['png']
    :type fig_formats: list[str], optional
    :param verbose: activate comment display, defaults to False
    :type verbose: bool, optional
    """
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
    data_ref  = self.loc[:,cRef]
    data_raw  = self.loc[:,cRaw]
    data_corr = self.loc[:,cCor]
    timeline  = self.loc[:,cTime]

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
    """
    Geo class to manage geographic calculations
    """

    # static variables
    EARTH_RADIUS = 6378137  # Earth's radius in meters (WGS84)
    # WARNING - for cerra data : 63712229 m
    DEGREES_PER_METER_LAT = 1 / 111320  # Approximate meters per degree latitude

    @staticmethod
    def meters_per_degree_longitude(latitude):
        """
        meters_per_degree_longitude compute the number of meters per degree of longitude at a given latitude.

        :param latitude: latitude in degrees
        :type latitude: float
        :return: meters per degree of longitude at a given latitude
        :rtype: float
        """               
        return (math.pi / 180) * __class__.EARTH_RADIUS * math.cos(math.radians(latitude))
    
    
#%%% GDF MANAGEMENT   

    # Functions from geoDataFrame to array coords coords[0] longitude  - coords[1]  latitude
    # TODO standardize coords manipulation
    # TODO check for fonctionality clearer name

    def file2coords(file_path, src_crs = 3035, dst_crs = 4326):
        """
        file2coords 
        Open .shp file and return the coordonates of the exterior boundary of the object in an array obj_coords.
        If dst_crs = 4326,
            obj_coords[0] : longitude of the exterior boundary
            obj_coords[1] : latitude of the exterior boundary

        :param file_path: path to the .shp file
        :type file_path: str
        :param src_crs: epsg id of the source coordonate system of the .shp file. 
            The default is 3035 (ETRS89-extend / LAEA europe).
        :type src_crs: int, optional
        :param dst_crs: epsg id of the destination coordonate system of the returned obj_coords. 
            The default is 4326 (WGS 84 - World geodetic system 1984, used in GPS).
            /!\ If not default value - obj_coords provided in description not valid.
        :type dst_crs: int, optional
        :return: Coordonates of the exterior boundary of the object in path_file.shp
        :rtype: array[rows:**, cols:2] 
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
        gdf2coords 
        Return the coordonates of the exterior boundary of the gdf object in an array obj_coords.
        If dst_crs = 4326,
            obj_coords[0] : longitude of the exterior boundary
            obj_coords[1] : latitude of the exterior boundary

        :param gdf: GeoDataFrame object countaining either a Polygon, a MultiPolygon or a LineString
        :type gdf: GeoDataFrame
        :param src_crs: epsg id of the source coordonate system of the .shp file. 
            The default is 3035 (ETRS89-extend / LAEA europe).
        :type src_crs: int, optional
        :param dst_crs: epsg id of the destination coordonate system of the returned obj_coords. 
            The default is 4326 (WGS 84 - World geodetic system 1984, used in GPS).
            /!\ If not default value - obj_coords provided in description not valid
        :type dst_crs: int, optional
        :return: Coordonates of the exterior boundary of the gdf object.
        :rtype: array[rows:**, cols:2] 
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
        plot_multiple_gdfs 
        Create a plot displaying multiple GeoDataFrames on the same axes.

        :param gdfs: list of GeoDataFrames to plot
        :type gdfs: [gdfs]
        :param colors: list of the colors to used, defaults to None
        :type colors: [str], optional
        :param color_space: color space to used, defaults to 'viridis'
            Possible color_space : 'viridis', 'plasma', 'inferno', 'magma', 'cividis', 'Greys', 'Purples', etc.
        :type color_space: str, optional
        :param markersize: list of marker size to used, defaults to [50]
        :type markersize: [int], optional
        :param markershape: list of the marker symbole to used, defaults to ['o']
            Possible markershape : 'o', 's', '^', 'D', 'v', '<', '>', 'p', '*', '+', 'x', etc.
        :type markershape: [str], optional
        :param alpha: TO_CONTINUE  , defaults to 0.5
        :type alpha: float, optional
        :param title: _description_, defaults to "Multiple GeoDataFrames"
        :type title: str, optional
        :param xlabel: _description_, defaults to "Longitude"
        :type xlabel: str, optional
        :param ylabel: _description_, defaults to "Latitude"
        :type ylabel: str, optional
        :param labels: _description_, defaults to None
        :type labels: _type_, optional
        :param src_crs: _description_, defaults to 3035
        :type src_crs: int, optional
        :param dst_crs: _description_, defaults to 4326
        :type dst_crs: int, optional
        :param save: _description_, defaults to False
        :type save: bool, optional
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
    
    # Conversions to apply for pyHelp input generation    
    PYHELP_CONVERSIONS = {
        'surface_net_solar_radiation': lambda x: x/10**6,  # from J/m2 to MJ/m2
        'surface_solar_radiation_downwards': lambda x: x/10**6  # from J/m2 to MJ/m2
        }

    
    STANDARD_VARIABLES = {
        't2m': '2m_temperature',
        'tp': 'total_precipitation',
        'sde': 'snow_depth',
        'sd': 'snow_depth_water_equivalent',
        'ssr': 'surface_net_solar_radiation',
        'ssrd': 'surface_solar_radiation_downwards'
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
        'surface_net_solar_radiation' : 'sum', # warning cumulative value        
        'surface_solar_radiation_downwards': 'sum'
        }
    
    DOWNLOAD_SPECS = {
        'dataset'   : 'reanalysis-cerra-single-levels',
        'level_type': 'surface_or_atmosphere',
        'data_type' : 'reanalysis',
        'product_type': 'fc', #forecast
        'leadtime_hour': 3,
        'time': ['00:00', '03:00', '06:00','09:00',
                 '12:00', '15:00','18:00', '21:00']
       }
    
    def __init__(self, path: str, to_standard = True) -> None:       
        self._path = path
        self.dataset = None
        self.shape_grid = None
        self._load_dataset(to_standard)

    def __close__(self):
        self.dataset.close()
        del self
        
    def __save__(self, save_path = ''):
        if save_path == '':
            save_path = self._path
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
            # print('_load_dataset> ', end = '')
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
      
   
    def to_standard(self, accum_method = None, verbose = False) -> None: 
        """
        Modify dimension, coordinate and variables names of Dataset for them to be compliant with the standard of HelperCERRA class.
        Idem for unit conversions.
        
        Returns
        -------
        None.

        """
        vprint = print if verbose else lambda *a, **k: None 
        vprint('to_standard> ', end = '\n    ')
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
                
        # Check if download specs as expected.   
        for var_name in self.dataset.data_vars:
            # TODO why this loop ? WARNING
            if self.dataset[var_name].attrs['GRIB_dataType'] != self.__class__.DOWNLOAD_SPECS['product_type']:
                vprint(f"\n WARNING - {self._path} - Unexpected dataType",
                  f" {self.dataset[var_name].attrs['GRIB_dataType']} - Download spec : ",
                  f"{self.__class__.DOWNLOAD_SPECS['product_type']}")                
                
            # Transform cumulative variable into dataset    
            vprint(self.dataset[var_name].attrs['GRIB_stepType'])
            if self.dataset[var_name].attrs['GRIB_stepType'] == 'accum' and self.dataset[var_name].attrs['GRIB_stepType'] == 'fc':                
                self.accum2instant(var_name, 
                        leadtime_hour = self.__class__.DOWNLOAD_SPECS['leadtime_hour'],
                        method = accum_method,
                        verbose = verbose)
                vprint('data step type accum')
       

    #◘ generate new files
    @staticmethod
    # TODO deal with georef verbose
    # TODO not static method ?
    def generate_gridFile(ref_path, grid_path, attrs = dict(), coord_ids = dict(), 
                          src_crs = 6258, verbose = False):     
        
        # define vprint accordingly to *verbose*
        vprint = print if verbose else lambda *a, **k: None
        
        data = xr.open_dataset(ref_path, mode='r', engine='netcdf4')
        lat = self.latitude.values
        lon = self.longitude.values
        self.close() 
        
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
    def _find_nearest_point2(self, lat, lon, work_crs=3035, direction='all', checkplot=False):
        """
        Find the nearest point to the goal Point(lon,lat) and return its characteristics.

        Parameters
        ----------
        lat : float
            Latitude goal point.
        lon : float
            Longitude goal point.
        work_crs : int, optional
            EPSG in which the distance between the points will be computed.
            The default is 3035 (ETRS89-extend / LAEA Europe).
        direction : str, optional
            Indicate the nearest point(s) will be researched.
            Options: ['se', 'sw', 'nw', 'ne', 'all', 'each']. Default is 'all'.
        checkplot : bool, optional
            Display checkplot to show selected points. Default is False.

        Raises
        ------
        ValueError
            When inputs are invalid or all distances are NA.

        Returns
        -------
        result : DataFrame
            DataFrame with main characteristics of the nearest point(s).
        """

        # Validate latitude and longitude
        if lat < -90 or lat > 90 or lon < -180 or lon > 180:
            raise ValueError("Latitude must be between -90 and 90, and longitude must be between -180 and 180.")

        # Apply direction mask            
        grid_lat = self.dataset.latitude.values
        grid_lon = self.dataset.longitude.values
        shape = grid_lat.shape

        # Create mask based on desired direction
        dictMask = {
            'sw': (grid_lat < lat) & (grid_lon < lon % 360),
            'se': (grid_lat < lat) & (grid_lon > lon % 360),
            'nw': (grid_lat > lat) & (grid_lon < lon % 360),
            'ne': (grid_lat > lat) & (grid_lon > lon % 360),
            'all': (grid_lat > -90) & (grid_lon >= 0)
        }

        if direction not in dictMask:
            raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne', 'all', 'each'.")

        # Extract dataset grid gdf             
        gdf_grid_, yx, df_yx = self._extract_gdfGrid(dst_crs=work_crs)
        gdf_grid = gdf_grid_.copy()
        
        # Apply mask
        mask = dictMask[direction]
        mask_h = [i for i, row in df_yx.iterrows() if not mask[row['y'], row['x']]]
        for idx in mask_h:
            gdf_grid.at[idx, 'geometry'] = None

        # Check if grid has valid points
        if gdf_grid.is_empty.any() or gdf_grid.shape[0] == 0:
            raise ValueError("All grid points are filtered out by the mask.")

        # Define goal point as GeoDataFrame
        gdf_point = gpd.GeoDataFrame(geometry=[Point(lon, lat)])
        gdf_point.set_crs(epsg=4326, inplace=True)
        gdf_point = gdf_point.to_crs(epsg=work_crs)
        print(gdf_point)
        print(gdf_grid)
        # Compute distance between grid points and the goal point
        distances = gdf_grid.distance(gdf_point)

        # Handle all NA values in distances
        if distances.isna().all():
            raise ValueError("All computed distances are NA. Please check input self.")

        # Find index of nearest point
        idx = distances.dropna().idxmin()

        # Extract characteristics of the nearest point
        result = pd.DataFrame(index=[direction], columns=['y', 'x', 'point', 'd_m'])
        result.at[direction, 'y'] = df_yx.at[idx, 'y']
        result.at[direction, 'x'] = df_yx.at[idx, 'x']
        result.at[direction, 'point'] = gdf_grid.to_crs(epsg=4326).geometry[idx]
        result.at[direction, 'd_m'] = distances[idx]

        # Optional check plot
        if checkplot:
            gdf_selec = gpd.GeoDataFrame(geometry=[result.at[direction, 'point']])
            gdf_selec.set_crs(epsg=4326, inplace=True)
            
            Geo.plot_multiple_gdfs([gdf_grid_, gdf_point, gdf_selec],
                                    labels=['grid', 'point', f'n_{direction}'],
                                    markersize=[50], markershape=['+', '*', 'o'],
                                    title=f'Checkplot _find_nearest_point\nDirection: {direction}',
                                    src_crs=work_crs)

        return result


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
            'all': (grid_lat > -90) & (grid_lon >= 0) 
            }
        
        # For specific direction or absolu nearest *all*
        if direction in dictMask.keys():
            # Choose mask indicating the points which should be considered depending of direction.
            mask = dictMask.get(direction)            
            
            # Extract dataset grid gdf             
            gdf_grid_, yx, df_yx = self._extract_gdfGrid(dst_crs = work_crs)
            gdf_grid = copy.deepcopy(gdf_grid_)
            mask_h = [i for i, row in df_yx.iterrows() if not mask[row['y'], row['x']]]
            for idx in mask_h:
                gdf_grid.at[idx,'geometry'] = None    

            # Define gdf goal point
            gdf_point = gpd.GeoDataFrame(geometry = [Point(lon,lat) for i in range(len(yx))])
            gdf_point = gdf_point.set_crs(epsg = 4326)          
            gdf_point = gdf_point.to_crs(epsg = work_crs)      
            
            # Compute distance between each grid point and the goal point
            distances = gdf_grid.distance(gdf_point)
            idx = distances.argmin() 
            
            # Extracte characteristics of the nearest grid point in the choosen direction
            result = pd.DataFrame(index = [direction], columns = ['y','x','point','d_m'])
            result.at[direction,'y'] = df_yx.at[idx,'y']
            result.at[direction,'x'] = df_yx.at[idx,'x']
            result.at[direction,'point'] = gdf_grid.to_crs(epsg = 4326).geometry[idx]
            result.at[direction,'d_m'] = distances.values[idx]
                        
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
                
                result.at[compass,'y'] = df_yx.at[idx,'y']
                result.at[compass,'x'] = df_yx.at[idx,'x']
                result.at[compass,'point']= gdf_grid.to_crs(epsg = 4326).geometry[idx]
                result.at[compass,'d_m'] = distances.values[idx]
            
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
    
    def accum2instant(self, name_var, leadtime_hour, method = None, verbose = False):
        """
        Converts accumulated precipitation to instantaneous values.
        
        Parameters:
            name_var (str): Name of the variable to adjust (e.g., 'total_precipitation').
            leadtime (int or float): Time to shift forward (in hours).
            method (str): Method to apply. Supported: 'cut'
        """
        vprint = print if verbose else lambda *a, **k: None
        vprint(f'>> accum2instant - {name_var} - method: {method}')

        if method == None:
            vprint("accum2instant - No method provided. Exiting without changes.")
            return True
        elif  method == "day":
            # Convert time to datetime
                timeline = pd.to_datetime(self.dataset['time'].values)
                # Keep only hours 0, 6, 12, 18
                hour_mask = timeline.hour.isin([0, 6, 12, 18])
                filtered_times = timeline[hour_mask]
    
                # Filter dataset
                self.dataset = self.dataset.sel(time=filtered_times)

                # Resample onremaining data
                self.dataset = self.dataset.resample('D').sum()
    
                # Shift timeline by leadtime (e.g., to adjust for accumulation offset)
                self.dataset['time'] = pd.to_datetime(self.dataset['time'].values) + pd.to_timedelta(f'{leadtime_hour}H')
    
                # Modify attribute accordingly
                self.dataset[name_var].attrs['GRIB_stepType'] = f'cumul_{method}'
                vprint(self.dataset[name_var].max(),self.dataset[name_var].mean(), self.dataset[name_var].min())

        elif method == "cut":
                # Convert time to datetime
                timeline = pd.to_datetime(self.dataset['time'].values)
    
                # Keep only hours 0, 6, 12, 18
                hour_mask = timeline.hour.isin([0, 6, 12, 18])
                filtered_times = timeline[hour_mask]
    
                # Filter dataset
                self.dataset = self.dataset.sel(time=filtered_times)
    
                # Shift timeline by leadtime (e.g., to adjust for accumulation offset)
                self.dataset['time'] = pd.to_datetime(self.dataset['time'].values) + pd.to_timedelta(f'{leadtime_hour}H')
    
                # Modify attribute accordingly
                self.dataset[name_var].attrs['GRIB_stepType'] = f'instant_{method}'
                
        elif method == "divise":            
                timeline = pd.to_datetime(self.dataset['time'].values)
                timestep = timeline[1]-timeline[0]
                
                divide = pd.to_timedelta(f'{leadtime_hour}H')/timestep

                # Filter dataset
                self.dataset[name_var] = (('time','y','x'), self.dataset[name_var][:,:,:].values/divide)

                # Shift timeline by leadtime (e.g., to adjust for accumulation offset)
                self.dataset['time'] = pd.to_datetime(self.dataset['time'].values) + timestep
                
                # Modify attribute accordingly
                self.dataset[name_var].attrs['GRIB_stepType'] = f'instant_{method}'   
        
        # elif method == "avg":            
        #         timeline = pd.to_datetime(self.dataset['time'].values)
        #         timestep = timeline[1]-timeline[0]
                
        #         divide = pd.to_timedelta(f'{leadtime_hour}H')/timestep

        #         # Filter dataset
        #         self.dataset[name_var] = (('time','y','x'), self.dataset[name_var][:,:,:].values/divide)
        #         self.dataset[name_var] = (('time','y','x'), self.dataset[name_var].rolling(time=divide, center=False).mean())

        #         # Shift timeline by leadtime (e.g., to adjust for accumulation offset)
        #         # self.dataset['time'] = pd.to_datetime(self.dataset['time'].values) + timestep
                
        #         # Modify attribute accordingly
        #         self.dataset[name_var].attrs['GRIB_stepType'] = f'instant_{method}' 
                
        else:
                print("accum2instant - Method not recognized. Use 'cut'.")

        return True
#%% Extract site data tools   
    # TODO check for crs consitency issue
    # TODO ddocumentation
    def do_site_mask(self, 
                    site_box_path, 
                    site_mask_path, 
                    catch_crs = 3035,
                    verbose = False, 
                    checkplot = False,  
                    save = True,
                    reset = False,
                    buffer = 0,
                    logger = False
                    ):   
        def doMaskCheckplot(mask, output_path):
            '''
            Create checkplot of the mask
            '''           
            gdf_grid,yx, df_yx  = self._extract_gdfGrid(dst_crs = 4326)
            gdf_mask = copy.deepcopy(gdf_grid)
            mask_h = [i for i, row in df_yx.iterrows() if not mask[row['y'], row['x']]]
            print(gdf_mask)
            for idx in mask_h:
                gdf_mask.at[idx,'geometry'] = None  

            Geo.plot_multiple_gdfs([gdf_grid,gdf_mask], labels=['grid','mask'],
                                title = f'Checkplot Mask',
                                markersize = [5],
                                save = f'{output_path}checkplot/mask.pdf')

        # function initialization
        vprint = print if verbose else lambda *a, **k: None
        vprint('>> < START > do_site_mask')
        if checkplot:  
            if checkplot is str:
                output_path = checkplot
            else:
                output_path = './'            
            create_folder(f'{output_path}checkplot/')
        # I. check if mask file exists
        if os.path.exists(site_mask_path) and not reset:
            if verbose and logger:
                logger.info('>> Load existing mask file {site_mask_path}')
            mask = np.load(site_mask_path)
            if checkplot:
                doMaskCheckplot(mask, output_path)
            return mask
        
        # II. if not exists - generate it
        else:   
            if verbose and logger:
                logger.info(f'>> Generate new mask for site')
            # 1. Load site box
                logger.info(f'>> load site box from {site_box_path}')
            gdf_site = gpd.read_file(site_box_path)
            if gdf_site.crs:
                gdf_site = gdf_site.to_crs(epsg=4326)
            else:
                gdf_site = gdf_site.set_crs(epsg=catch_crs)
                gdf_site = gdf_site.to_crs(epsg=4326)
                
            if checkplot:
                Geo.plot_multiple_gdfs([gdf_site], labels = ['site box'],
                                    save = f'{output_path}checkplot/catchement_box.pdf')
            # 2. Identify corner pixel in the grid
            if verbose and logger:
                logger.info(f'>> Identify data site box pixel corners')   
            [minLon,minLat,maxLon,maxLat] = gdf_site.total_bounds
            corners = pd.DataFrame(index = ['sw','se','ne','nw'], 
                                columns = ['longitude','latitude'], 
                                data =[[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat]])
                
            ## Identify corner pixels
            grid_corners = pd.DataFrame(index = ['se','sw','nw','ne'], columns = ['y','x','point','d_m'])
            for c in corners.index:
                res = self._find_nearest_point(corners['latitude'][c], corners['longitude'][c], direction = c)
                grid_corners.loc[c,:] = res.loc[c,:]        
            if verbose and logger:
                logger.info(grid_corners)            

            ## Identify grid corners indexes (y,x)
            minY, maxY = min(grid_corners['y']), max(grid_corners['y'])
            minX, maxX = min(grid_corners['x']), max(grid_corners['x'])
            
            # # 2. Adjust indexes according to buffer
            rangeY = (1+buffer)*(maxY - minY)/2
            rangeX = (1+buffer)*(maxX - minX)/2
            midY,midX = (minY+maxY)/2, (minX+maxX)/2
            minY = floor(midY - rangeY)
            maxY = ceil(midY + rangeY)
            minX = floor(midX - rangeX)
            maxX = ceil(midX + rangeX)  
            
            # 3. Generate mask
            if verbose and logger:
                logger.info(f'>> Generate mask array')
            mask = np.zeros(self.shape_grid)
            mask[minY:maxY+1, minX:maxX+1] = 1
            
            if checkplot:    
                doMaskCheckplot(mask, output_path)        
            
            # 4. Save mask
            if save:
                np.save(site_mask_path, mask)  
            if verbose and logger:
                logger.info('>>< END > generate_site_mask')          
            return mask

    def crop_and_save(self, file_id, output_folder, mask):
        
        self.dataset = copy.deepcopy(self.dataset)
        self.dataset['mask'] = (('y', 'x'), mask)  # Apply mask
        self.dataset = self.dataset.where(self.dataset.mask == 1)  # Apply the mask
        
        self.dataset = self.dataset.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
        self.dataset = self.dataset.drop(['mask'])  # Drop unnecessary variables
        if "expver" in self.dataset.coords:
            self.dataset = self.dataset.drop(['expver'])
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
        return 

    @staticmethod    
    def extract_site_data(mask, site_id, 
                          cerra_path, 
                          variables, years, 
                          output_file,
                          logger,
                          verbose = False,
                          input_data ='_alps'):
        
        vprint = print if verbose else lambda *a, **k: None
        work_folder = f'./work/'
        
        create_folder(work_folder)
        missing = []
        for var in variables:            
            vprint(f'>>> {var}\n>>> ', end = '')
            year_files = []
            
            for year in years:
                vprint(f'{year}', end = '')
                
                # Define file paths
                folder_path = cerra_path
                input_file_path = cerra_path / f'{year}/{year}{input_data}.nc' #f'{folder_path}{year}/{year}{input_data}.nc'
                
                # Check if data available for given variable and year
                if os.path.isfile(input_file_path):                
                    # Open dataset
                    data = __class__(input_file_path)
        
                    # Process and save the buffer files
                    year_files.append(data.crop_and_save(f'{year}_{site_id}', work_folder, mask))
                    data.__close__()
                    
                else:
                    missing.append(year)
                    vprint(' no data', end = '')
                vprint(' - ', end = '')
            # combine_file = output_file_structure + f'_{var}.nc' 
            __class__.combine(year_files,output_file)
            vprint('combine')        
        delete_folder(work_folder)
        return output_file, missing
    
    def extract_site_data_(mask, site_id, list_paths, output_path, combine_file, verbose = False):
        
        vprint = print if verbose else lambda *a, **k: None
        work_folder = f'{output_path}work/'
        create_folder(work_folder)

        files = []
        i = 0
        for path in list_paths:
            vprint(f'{path}', end = '')
          
            # Check if data available for given variable and year
            if os.path.isfile(path):                
                # Open dataset
                data = __class__(path, to_standard = True)    
                # Process and save the buffer files
                files.append(self.crop_and_save(f'{i}_{site_id}', work_folder, mask))
                self.__close__()
                
            else:
                vprint(' no data', end = '')
            vprint(' - ', end = '')
            i += 1
        vprint(' combine dataset ') 
        __class__.combine(files,combine_file)              
        delete_folder(work_folder)
        return combine_file
        
    def generate_local_cerra(self, cerra_path, shape_path, obs_path, output_path,
                           site_id, type_site, variables, years, buffer = 0.2,
                           verbose = False, checkplot = False):

        mask = self.generate_site_mask(site_id, 
                                       shape_path, obs_path, output_path,
                                       buffer, catch_crs = 3035, 
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
        df = pd.DataFrame({'Latitude (dd)': coordinates.T[0], 'Longitude (dd)': coordinates.T[1]})
        
        return gdf, df
    
    def generate_pyHelp_file(self, gdf_helpGrid, df_helpGrid, var, 
                            #  logger,
                             rule = 'nearest', timestep = 'D',
                            verbose = False, save = False):   

        if var in __class__.PYHELP_CONVERSIONS:
            # Apply the conversion if the variable has a corresponding function
            conversion_func = __class__.PYHELP_CONVERSIONS[var]
            self.dataset[var] = conversion_func(self.dataset[var])
        
        # define vprint accordingly to *verbose*
        vprint = print if verbose else lambda *a, **k: None
        vprint(f'> generate_pyHelp_input {var} {timestep}')
    
        timeline = self.dataset['time'].values        
        values = pd.DataFrame(columns = range(df_helpGrid.shape[0]))
        values['time'] = pd.to_datetime(timeline, format='%d-%b-%Y %H:%M:%S')
        
        vprint('> start data extraction - points ')
        i = 0         
        for point in gdf_helpGrid.geometry: 
            vprint(i, end = ' ')
            if rule == 'nearest':
                nearest = self._find_nearest_point(point.y, point.x, direction='all')
                v = self.dataset[var][:,nearest['y']['all'],nearest['x']['all']]
                
            elif rule == 'inverse_distance':
                nearest = self._find_nearest_point(point.y, point.x, direction='each')                
                v = np.zeros(len(timeline))
                for r in nearest.index:                    
                    v +=  self.dataset[var][:,nearest['y'][r],nearest['x'][r]].values/(nearest['d_m'][r])
                v = v / sum(1/(nearest['d_m']))
            elif rule == 'inverse_distance2':
                nearest = self._find_nearest_point(point.y, point.x, direction='each')                
                v = np.zeros(len(timeline))
                for r in nearest.index:                    
                    v +=  self.dataset[var][:,nearest['y'][r],nearest['x'][r]].values/(nearest['d_m'][r]**2)
                v = v / sum(1/(nearest['d_m']**2))    
            elif rule == 'linear':
                nearest = self._find_nearest_point(point.y, point.x, direction='each')                
                v = np.zeros(len(timeline))
                for r in nearest.index:                    
                    v +=  self.dataset[var][:,nearest['y'][r],nearest['x'][r]].values*(nearest['d_m'].sum()-nearest['d_m'][r])/(nearest['d_m'].sum())            
            elif rule == 'bilinear':
                nearest = self._find_nearest_point(point.y, point.x, direction='each')                
                v = np.zeros(len(timeline))
                
                d_y = nearest['d_m']['sw'] + nearest['d_m']['se'] - nearest['d_m']['nw'] - nearest['d_m']['ne']
                d_x = nearest['d_m']['sw'] + nearest['d_m']['nw'] - nearest['d_m']['se'] - nearest['d_m']['ne']
                d_xy = (nearest['d_m']['sw'] - nearest['d_m']['se'] - nearest['d_m']['nw'] + nearest['d_m']['ne'])
                
                v += self.dataset[var][:,nearest['y']['sw'],nearest['x']['sw']].values * ( (d_y + d_x + d_xy) / (4*nearest['d_m'].sum()) )
                v += self.dataset[var][:,nearest['y']['se'],nearest['x']['se']].values * ( (d_y - d_x - d_xy) / (4*nearest['d_m'].sum()) )
                v += self.dataset[var][:,nearest['y']['nw'],nearest['x']['nw']].values * ( (-d_y + d_x - d_xy) / (4*nearest['d_m'].sum()) )
                v += self.dataset[var][:,nearest['y']['ne'],nearest['x']['ne']].values * ( (-d_y - d_x + d_xy) / (4*nearest['d_m'].sum()) )
            else: 
                logger.error('> rule not available')
                           
                
            values[i] = pd.to_numeric(v, errors='coerce')  
            i += 1
    
        vprint(f'\n> resample time - new timestep :{timestep}')      
        values.set_index('time', inplace=True)
        values = values.resample(timestep).agg(__class__.AGGREGATION_RULES[var]) 
        values.reset_index(inplace = True)

        dates = pd.to_datetime(values['time'])
        values.index = dates.dt.strftime("%d/%m/%Y")
        values = pd.concat([df_helpGrid.T, values])
        
        if save:
            vprint(f'> save data at {save}')
            values.to_csv(save, 
                          date_format = "%d/%m/%Y", # follow requirement format from pyhelp
                          header = False # column id not saved
                          )
            
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

    def compute_timeserie_statistics(self, variable, logger, site_id = '', shape_path = False, 
                                     catch_crs = 3035, save = False, checkplot = False):
        ## Preporocessing
        timeseries = pd.DataFrame({'time': self.dataset.time})
        df_loc = pd.DataFrame(columns = ['lon', 'lat'], index = [f'{y}{x}' for y in self.dataset.y.values for x in self.dataset.x.values])
        latitudes = self.dataset.latitude.values
        longitudes = self.dataset.longitude.values
        for y in self.dataset.y.values:
            for x in self.dataset.x.values:
                timeseries[f'{y}.{x}'] = pd.to_numeric(self.dataset[variable].sel(y=y, x=x).to_series().values)
                df_loc.at[f'{y}.{x}', 'lon'] = longitudes[y,x]
                df_loc.at[f'{y}.{x}', 'lat'] = latitudes[y,x]

        # organise timeseries pixel timeserie      
        timeseries['time'] = pd.to_datetime(timeseries['time'])
        timeseries.set_index('time', inplace = True)
        # organise pixel localisation information
        gdf = gpd.GeoDataFrame(df_loc, geometry = [Point(row['lon'], row['lat']) for i,row in df_loc.iterrows()], crs="EPSG:4326")
        
        if shape_path:
            logger.info(f'{site_id} | load shape file')
            shp = gpd.read_file(shape_path)
            shp = gpd.GeoDataFrame(shp['geometry'])
            if catch_crs:
                shp.set_crs(epsg = catch_crs)
            else:
                shp.set_crs(epsg = 3035)
            shp.to_crs(4326, inplace = True)

            keep = gdf.clip(shp)
            pixels = list(keep.index)
            timeseries_stats = timeseries[pixels]
        else:
            pixels = list(timeseries.columns)
            timeseries_stats = timeseries.copy()    

        ## Start statistic computation
        # Build output structure
        logger.info(f'{site_id} | create pixel timeserie statistics')
        logger.info(f'{site_id} | number of pixels for statistics: {len(pixels)}')

        timeline = self.dataset['time'].values
        empty_data = np.zeros((timeline.shape[0],4))
        statics = pd.DataFrame(columns = ['time','mean','min','max'],
                               data = empty_data)
        statics['time'] = pd.to_datetime(timeline, format='%d-%b-%Y %H:%M:%S')
        
        means, mins, maxs = [], [], []
        for i,row in timeseries_stats.iterrows():
            avg, m, M = row.mean(), row.min(), row.max()
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
                logger.info(f'{site_id} | pixel timeserie statistics saved at {save}')
            except:
                logger.error(f'Invalid save path {save}')
        
        if checkplot:
            logger.info(f'{site_id} | checkplot statistics')
            fig, ax = plt.subplots(1,1,figsize = [10,5])
            statics.plot(ax = ax, y = ['max','mean','min'], color = [ '#DC267F', '#FFB000', '#648FFF'])
            ax.yaxis.set_label_text(variable)
            ax.set_title(f'CERRA local timeserie statistics\n{site_id} - {variable}')
            plt.show()
                
        return statics
    
      
       
#%% WeatherStation Class
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
            
    # def __init__(self, name, path):
    #    self._name = name        
    #    self._path = path
    #    self._infos = {}
    #    self._data = {}
    #    self._read_coordinate_infos()                    
            
    def __str__(self):
        text = f'{self._name}\n'
        for key,val in self._infos.items():
            text = f'{text}{key} {val}\n'
        return text
    
    def info2pdf(self, site = '', comments = ''):

        data = pd.DataFrame(columns = ['site', 'id', 'X', 'Y', 'crs', 
                                       'variables', 'comments'], 
                            data = np.empty((1,7)))
        data['site'] = site
        data['id'] = self._name
        data['X'] = self._infos['x']
        data['Y'] = self._infos['y']
        if 'crs' in self._infos:
            crs = f"{self._infos['crs']}"
            if 'zone' in self._infos and self._infos['zone'] != '':
                crs += f"/{self._infos['zone']}" 
        elif 'epsg':
            crs = f"{self._infos['epsg']}"
        else: 
            crs = 'nan'
            print(f">> WeatherStation.info2pdf - fail to crs to str: {self._name}")
            
        data['crs'] = crs
        str_variables = " ".join(self._self.keys())
        data['variables'] = str_variables
        data['comments'] = comments

        return data
            
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
        cols = self.columns.values

        # Format weather station data
        station_data = pd.DataFrame()
        station_data['time'] = pd.to_datetime(data[cols[0]], format= "%d/%m/%Y %H:%M") #'%d-%b-%Y %H:%M:%S')

        # Extract the year for grouping
        station_data['year'] = station_data['time'].dt.year

        # Ensure numeric columns are correctly converted
        station_data[f'{var}_{self._name}'] = pd.to_numeric(data[cols[1]], errors='coerce')
        station_self.set_index('time', inplace=True)
        
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
                    
            elif line.lower().startswith(('x','easting','long')):
                x = NUMS.search(line)
                geo_info['x'] = float(x.group(0))        
                
            elif line.lower().startswith(('y','northing','lat')):
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
                        'ref_bounds': [pd.Timestamp('1985-01-01'), pd.Timestamp('2000-12-31')]}

    VAR_ID_TO_NAME = {
        '2m_temperature': 'Air Temperature',
        'total_precipitation': 'Precipitation',
        'surface_net_solar_radiation': 'Surface net Solar Radiation'
        }
    
    VAR_ID_TO_UNIT = {
        '2m_temperature': '°C',
        'total_precipitation': 'mm/3h',
        'surface_net_solar_radiation': 'J/m²/3h'
        }
    
    RESAMPLE_UNIT = {
        'total_precipitation_sum': {'H': 'mm/hour', 'D': 'mm/day', 
                                  'M': 'mm/month','Y': 'mm/year'},
        'total_precipitation_mean': {},
        '2m_temperature_mean': {},
        'surface_net_solar_radiation_sum': {'H': 'J/m²/hour', 'D': 'J/m²/day', 
                                  'M': 'J/m²/month','Y': 'J/m²/year'},
        'surface_net_solar_radiation_mean': {}
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
        print(df.head())
        df['time'] = pd.to_datetime(df.index, format='%Y-%m-%d %H:%M:%S')
        df = df.set_index('time')
        
        self.data_origin = df
        self.data_work = copy.deepcopy(df)   
        
    def reset_data(self):
        self.data_work = copy.deepcopy(self.data_origin)
        self.unit = __class__.VAR_ID_TO_UNIT[self.variable_id]
        self.name = __class__.VAR_ID_TO_NAME[self.variable_id]
        
    def resample_data(self, timestep, method):
        # Modify unit in ClimateStats if necessary - to verify
        # TODO make better + deal with supplementary columns
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
            temp = pd.DataFrame()
            temp['mean'] = self.data_work['mean'].resample(timestep).mean()
            temp['min'] = self.data_work['min'].resample(timestep).min()
            temp['max'] = self.data_work['max'].resample(timestep).max()
            self.data_work = temp
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

    def compute_threshold(self, threshold, timestep = 'D', method = 'mean'):
        self.resample_data(timestep, method)
        years = self.data_work.index.year.unique()
        counter = pd.DataFrame(columns = [f'{key}_inf{threshold}' for key in self.data_work.columns])
        temp = pd.DataFrame()
        for key in self.data_work.columns:
            temp[f'{key}_inf{threshold}'] = self.data_work[key] < threshold
        for year in years:
            group = temp[temp.index.year == year]
            counter.loc[year] = group[[f'{key}' for key in temp.columns]].sum()
        return counter
        
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
        file_name = f'{self.variable_id}_{self.location}_stripes_{FIRST}_{LAST}'
        save_plot(fig, fig_folder, file_name, 
                  fig_formats = fig_formats, verbose = verbose)
        return file_name

    def plot_monthly_anomaly(self, fig_folder, fig_formats = ['png','pdf'], 
                             time_bounds = [], plot_settings = {}, 
                             anomaly_settings = ANOMALY_SETTINGS, 
                             display = False, verbose = False):
        
        # Plot setting
        settings = {
            'NegColor':      'blue',
            'PosColor':      'red',
            'HorizontalGrid': False
            }
        # define plot time boundaries

            
        for key, val in plot_settings.items():
            settings[key] = val
        
        # Compute data anomaly
        self.resample_data('M', anomaly_settings['method'])
        self.compute_anomaly(anomaly_settings['ref_bounds'])
             
        # Calculate the rolling 12-month average
        rolling_12m_avg = self.data_work['anomaly'].rolling(window=12, min_periods=1).mean()

        # Build plot
        fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

        # # Set background color
        # fig.patch.set_facecolor('white')

        # Plot monthly anomalies
        axes[0].bar(self.data_work.index, self.data_work['anomaly'], 
                    color = [settings['NegColor'] if anomaly <= 0 else settings['PosColor'] 
                             for anomaly in self.data_work['anomaly']],
                    width = 50)

        
        axes[0].set_ylabel(f'Anomaly [{self.unit}]', fontsize=14, labelpad=15)
        axes[0].set_title(f'Monthly {self.name} Anomalies [{self.unit}]', pad=5)
        coef = 0.03
        limits = [min(self.data_work['anomaly'].min()*(1+coef), self.data_work['anomaly'].min()*(1-coef)),
                  max(self.data_work['anomaly'].max()*(1+coef), self.data_work['anomaly'].max()*(1-coef))]
        axes[0].set_ylim(limits[0], limits[1])

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
        axes[1].set_title(f'\n12-Month Rolling Average {self.name} Anomalies [{self.unit}]', pad=5)
        limits = [min(rolling_12m_avg_trimmed.min()*(1+coef), rolling_12m_avg_trimmed.min()*(1-coef)),
                  max(rolling_12m_avg_trimmed.max()*(1+coef), rolling_12m_avg_trimmed.max()*(1-coef))]
        axes[1].set_ylim(limits[0], limits[1])
        

        if settings['HorizontalGrid']:
            axes[1].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')
            axes[0].grid(axis='y', linestyle='--', linewidth=0.5, color='gray')

        # Customize tick marks and labels
        for ax in axes:
            ax.xaxis.set_major_locator(mdates.YearLocator(2))  # tick every 2 years
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))  # Display every other year
            # ax.set_xticklabels(self.data_work.index.year.unique()[::2], rotation=45, ha='right', fontsize=8)
        # Add horizontal line at 0 for both subplots
        for ax in axes:
            ax.axhline(0, color='black', linewidth=1)

        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        fig.align_ylabels(axes)

        if display:
            plt.show()
        
        # save plot
        save_plot(fig, fig_folder, f'{self.variable_id}_{self.location}_monthly_anomaly', 
                  fig_formats = fig_formats, verbose = verbose)
        plt.close(fig)
        
    def plot_negDays(self, fig_folder, fig_formats = ['png','pdf'], 
                            time_bounds = [], plot_settings = {}, 
                            display = False, verbose = False):
        
        # Default plot settings
        settings = {
            'PlotVersion': 'simple', # 'full' or 'simple'
            'ColorPalette':  'jet_r',
            'Title': f'Number of Days per Year with {self.name} < 0 {self.unit}',
            'HorizontalGrid': False
            }
        
        # Update plot settings            
        for key, val in plot_settings.items():
            settings[key] = val
        
        # Compute negative days
        counter = self.compute_threshold(0, 'D', 'mean')    
        counter = counter.loc[counter.index>=time_bounds[0]]
        counter = counter.loc[counter.index<=time_bounds[1]]
        

        # Build plot
        if settings['PlotVersion'] == 'simple':

            # Create colormap
            cmap = plt.get_cmap(settings['ColorPalette'])
            # Generate values in the range 0 to 1
            num_colors = 16
            values = np.linspace(0.25, 1, num_colors)
            # Extract colors
            colors = [cmap(value) for value in values]
            # Assign colors based on the value in the column
            col_colors = [colors[x//25] for x in counter['mean_inf0']]


            fig, ax = plt.subplots(1, 1, figsize=(14, 5), sharex=True)
            fig.subplots_adjust(hspace=0.25)
            ax.bar(counter.index, counter['mean_inf0'], 
                            color = col_colors,
                            width = 0.8, align='center')
            yMax = counter['mean_inf0'].max() + 10
            yMin = counter['mean_inf0'].min() - 10
            print(yMin, yMax)
            ax.set_ylim(yMin, yMax)
            ax.set_xlim(time_bounds[0]-1, time_bounds[1]+1)  
            ax.set_xlabel('Year', fontsize=13)
            ax.set_ylabel('Number of Days', fontsize=14, labelpad=15)
            ax.set_title(f'Number of Days per Year with {self.name} < 0 {self.unit}', fontsize=16, pad=10)
            if settings['HorizontalGrid']:
                ax.grid(axis='y', linestyle='--', linewidth=0.5, color='gray')  
            # Customize tick marks and labels
            ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))  
            plt.xticks(fontsize=12)
            plt.yticks(fontsize=12) 
            if display:
                plt.show()
    
        elif settings['PlotVersion'] == 'full':        
            fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
            fig.subplots_adjust(hspace=0.25)

            for i,col in enumerate(counter.columns):
                #Create colormap
                cmap = plt.get_cmap(settings['ColorPalette'])
                # Generate values in the range 0 to 1
                num_colors = 37
                values = np.linspace(0, 1, num_colors)
                # Extract colors
                colors = [cmap(value) for value in values]
                # Assign colors based on the value in the column
                col_colors = [colors[x//10] for x in counter[col]]

                ax = axes[i]
                ax.bar(counter.index, counter[col], 
                            color = col_colors,
                            width = 0.5, align='edge')
                ax.set_ylim(0, 385)
                ax.set_xlim(time_bounds[0], time_bounds[1])
                ax.axhline(365, ls = ':', color='black', linewidth=1)        
                ax.set_ylabel('Number of Days', fontsize=14, labelpad=15)
            fig.suptitle(f'Number of Days per Year with {self.name} < 0 {self.unit}', fontsize=16, y=0.93)
            axes[-1].set_xlabel('Year', fontsize=13)
            if display:
                plt.show()


        # save plot 
        file_name = f'{self.variable_id}_{self.location}_negDays_perYear'
        save_plot(fig, fig_folder, file_name, 
                  fig_formats = fig_formats, verbose = verbose)        
        return file_name


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
        file_name = f'{X.variable_id}_{Y.variable_id}_{X.location}_anomaly'
        save_plot(fig, fig_folder, file_name,
                  fig_formats = fig_formats, verbose = verbose)       
        return df, file_name
    
    # Climate history plot
    VARIABLE_COLOR = {
        '2m_temperature': '#67000d',
        'total_precipitation': '#2171b5',
        'surface_net_solar_radiation': '#fcbba1'
    }
    def plot_bar_timeserie(self, fig_folder, fig_formats = ['png','pdf'], 
                            time_bounds = [], timestep = 'Y', 
                            plot_settings = {},
                            display = False, verbose = False):
        
        # plot setting
        settings = {
                'time_bounds' : [1984,2021],
                'timestep': 'Y',
                'agg_method': {
                    '2m_temperature': 'mean',
                    'total_precipitation': 'sum',
                    'surface_net_solar_radiation': 'sum'
                }
                }
        
        for key, val in plot_settings.items():
            settings[key] = val

        method = settings['agg_method'][self.variable_id]
        colorVar = __class__.VARIABLE_COLOR[self.variable_id]

        # prepare data for plotting
        self.resample_data(timestep, method)
        self.data_work['years'] = pd.to_numeric(self.data_work.index.year)
        self.data_work = self.data_work[self.data_work.years > settings['time_bounds'][0]]
        self.data_work = self.data_work[self.data_work.years < settings['time_bounds'][1]]

        # build figure
        fig, ax = plt.subplots(1,1,figsize = [10,5])  
        self.data_work.plot(ax = ax, x = 'years', y = 'mean', kind = 'bar', color = colorVar)
        ax.yaxis.set_label_text(f'{self.name} ({self.unit})')
        ax.xaxis.set_label_text(f'Years')

        # ax.tick_params(axis='x', labelrotation=45)

        ax.set_title(f'Annual Mean Value over Catchement\n{self.location}')
        ax.legend([])
        if display:
            plt.show()     

        # save plot
        file_name = f'{self.variable_id}_{self.location}_bar_timeserie'
        save_plot(fig, fig_folder, file_name, 
                    fig_formats = fig_formats, verbose = verbose)
        
        # reset data
        self.reset_data()
        return file_name
    
    def plot_interannual_seasonal_tendancy(self, fig_folder, fig_formats = ['png','pdf'], 
                            time_bounds = [], timestep = 'Y', 
                            plot_settings = {},
                            display = False, verbose = False):
        
        # plot setting
        settings = {
                'time_bounds' : [1985,2022],
                'agg_method': {
                    '2m_temperature': 'mean',
                    'total_precipitation': 'sum',
                    'surface_net_solar_radiation': 'sum'
                },
                'statistics' : {
                    'q10':  lambda x: x.quantile(q=0.1), # dispersion - low boundary
                    'mean': lambda x: x.mean(),          # main Line
                    'q90':  lambda x: x.quantile(q=0.9)  # dispersion - high boundary
                },
                'legend': {
                    'mainLine': 'Mean',
                    'dispersion': "10–90th Percentile"
                }
            }

        # 1. EXTRACT NEEDED DATA
        # Reset to data to original
        self.reset_data()
        # Resample by month
        self.resample_data('M', settings['agg_method'][self.variable_id])
        # Drop data outside of the timeline of interest
        self.data_work = self.data_work[self.data_work.index.year > settings['time_bounds'][0]]
        self.data_work = self.data_work[self.data_work.index.year < settings['time_bounds'][1]]

        # Groups data by Months & by Years 
        byMonths = self.data_work.groupby(self.data_work.index.month)
        byYears = self.data_work.groupby(self.data_work.index.year)
        # Define Dataframe for statistic computation
        interYear = pd.DataFrame(index = range(1,13), 
                                 columns = list(settings['statistics'].keys()))
        interYear['label'] = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        # Compute interannual statistics
        for month,group in byMonths:
            for stat,func in settings['statistics'].items():
                interYear.at[month,stat] = func(group['mean'])
                # interYear.at[month,stat] = group['mean'].max()
                # interYear.at[month,'mean'] = group['mean'].mean()
                # interYear.at[month,'min'] = group['mean'].min()
                # interYear.at[month,'q90'] = group['mean'].quantile(q = 0.9)
                # interYear.at[month,'q10'] = group['mean'].quantile(q = 0.1)

        # Seasonal values for each year considered
        years = []
        for year,group in byYears:
            years.append(year)
            interYear[year] = group['mean'].values

        for col in interYear.columns:
            if col != 'label':
                interYear[col] = pd.to_numeric(interYear[col])

        # display parameter
        sns.set_theme(style="whitegrid")
        plt.rcParams.update({
            "font.family": "serif",
            "font.size": 13,
            "axes.labelsize": 14,
            "axes.titlesize": 16,
            "axes.edgecolor": "0.3",
            "grid.color": "0.85",
            "grid.linestyle": "--",
            "grid.linewidth": 0.5,
            "axes.linewidth": 1.0,
            "legend.frameon": False,
        })

        colorVar = __class__.VARIABLE_COLOR[self.variable_id]
        stats = list(settings['statistics'].keys())
        fig, ax = plt.subplots(figsize=(10, 5))

        # plot every year data
        interYear.plot(
            ax=ax, x='label', y=years,
            color="0.65", alpha=0.25,
            linewidth=1,
            legend=False
        )
        # plot statistic main line
        interYear.plot(
            ax=ax, x='label', y=stats[1],
            color=colorVar, lw=2.5,
            label=settings['legend']['mainLine']
        )
        # plot statistic dispersion
        ax.fill_between(
            interYear['label'],
            interYear[stats[0]], interYear[stats[2]],
            color=colorVar, alpha=0.22,
            label=settings['legend']['dispersion']
        )

        # format axis
        ax.set_ylabel(f"{self.name} ({self.unit})")
        ax.set_xlabel("Year")
        ax.set_xticks(interYear['label'])
        ax.set_xticklabels(interYear['label'], rotation=45, ha='right')
        ax.set_xlim(['Jan','Dec'])
        ax.set_title(f"Interannual variability\n{self.location}", pad=12)
        # format legend
        legendElts = list(ax.get_legend_handles_labels())
        labels = legendElts[1]
        labels = labels[-2:]
        elts = legendElts[0]
        elts = elts[-2:]
        ax.legend(labels=labels, handles=elts)
        # ax.grid(False)

        plt.tight_layout()
        if display:
            plt.show()     

        # save plot
        file_name = f'{self.variable_id}_{self.location}_interannual_season_tendancy'
        save_plot(fig, fig_folder, file_name, 
                    fig_formats = fig_formats, verbose = verbose)
        
        # reset data
        self.reset_data()

        return interYear

    def plot_wetDays(self, fig_folder, fig_formats = ['png','pdf'], 
                            time_bounds = [1985,2020], plot_settings = {}, 
                            display = False, verbose = False, 
                            threshold = 1):
        
        # Default plot settings
        settings = {
            'PlotVersion': 'simple', # 'full' or 'simple'
            'ColorPalette':  'jet_r',
            'Title': f'Number of wet Days per Year',
            'HorizontalGrid': False
            }
        
        # Update plot settings            
        for key, val in plot_settings.items():
            settings[key] = val
        
        # Compute negative days
        counter = self.compute_threshold(threshold, 'D', 'sum')    
        counter = counter.loc[counter.index>=time_bounds[0]]
        counter = counter.loc[counter.index<=time_bounds[1]]
        print(counter.head())
        
        counter = 364 - counter
        print('after')
        print(counter.head())

        interestLabel = f'mean_inf{threshold}'


        # Create colormap
        cmap = plt.get_cmap(settings['ColorPalette'])
        # Generate values in the range 0 to 1
        num_colors = 16
        values = np.linspace(0.25, 1, num_colors)
        # Extract colors
        colors = [cmap(value) for value in values]
        # Assign colors based on the value in the column
        col_colors = [colors[x//25] for x in counter[interestLabel]]


        fig, ax = plt.subplots(1, 1, figsize=(14, 5), sharex=True)
        fig.subplots_adjust(hspace=0.25)
        ax.bar(counter.index, counter[interestLabel], 
                        color = col_colors,
                        width = 0.8, align='center')
        yMax = counter[interestLabel].max() + 10
        yMin = counter[interestLabel].min() - 10
        print(yMin, yMax)
        ax.set_ylim(yMin, yMax)
        ax.set_xlim(time_bounds[0]-1, time_bounds[1]+1)  
        ax.set_xlabel('Year', fontsize=13)
        ax.set_ylabel('Number of Days', fontsize=14, labelpad=15)
        ax.set_title(f'Number of Wet Days per Year\n{self.location}', fontsize=16, pad=10)
        if settings['HorizontalGrid']:
            ax.grid(axis='y', linestyle='--', linewidth=0.5, color='gray')  
        # Customize tick marks and labels
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))  
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12) 
        if display:
            plt.show()

        # save plot 
        file_name = f'{self.variable_id}_{self.location}_wetDays_perYear'
        save_plot(fig, fig_folder, file_name, 
                  fig_formats = fig_formats, verbose = verbose)        
        return file_name