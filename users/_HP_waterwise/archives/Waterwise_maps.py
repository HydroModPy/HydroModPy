# -*- coding: utf-8 -*-
"""
Created on Tue Apr 7, 2025

@author: clement
"""


#%% LIBRARIES MODULES

# General
import os
import sys
from os.path import dirname, abspath
import tempfile

import socket
hostname = socket.gethostname()
if hostname in ['CHYN-2208-W']:
    print("Running on Ronny's computer")
    DIR = "D:/github/hydromodpy-dev-waterwise/users" #comment CR: why do we need DIR and DIR2?
    DIR2 = "D:/github/hydromodpy-dev-waterwise" 
    git_path = 'D:/github/hydromodpy-dev0.1/' #I included the data and out paths here
    data_path = "Z:/HDPY_database_forModelling/"
    out_path = 'Z:/HDPY_models/RF'           
    os.makedirs(out_path, exist_ok=True)   
elif hostname in ['CHYN-2115-W']:
    print("Running on Clement's computer")
    # DIR = "D:/_GitHub/HydroModPy-dev-waterwise/users"
    DIR = "//home/roquesc$/_travail/_GitHub/HydroModPy-dev-waterwise/users"
    # DIR2 = "D:/_GitHub/HydroModPy-dev-waterwise"
    DIR2 = "//home/roquesc$/_travail/_GitHub/HydroModPy-dev-waterwise"
    data_path = 'Y:\HDPY_database_forModelling/'
    out_path = 'Y:/HDPY_models/CR_20250409'
    os.makedirs(out_path, exist_ok=True)
    temp_path = '//home/roquesc$/_temp/'
    os.makedirs(temp_path, exist_ok=True)
    os.environ['TEMP'] = temp_path
    os.environ['TMP'] = temp_path
    tempfile.tempdir = temp_path
elif hostname in ['Computer Name ORC']:
    print("Running on Odile's computer")
    DIR = "D:/github/hydromodpy-dev-waterwise/users"
    DIR2 = "D:/github/hydromodpy-dev-waterwise"    
    git_path = 'D:/github/hydromodpy-dev0.1/' #I included the data and out paths here
    data_path = "Z:/HDPY_database_forModelling/"
    out_path = 'Z:/HDPY_models/OR'    
else:
    print("Running on HYDRA")
    DIR = "D:/Users/figueroar/Documents/HydroModPy/users"
    DIR2 = "D:/Users/figueroar/Documents/HydroModPy"   



import os


#%%Import packages    
sys.path.append(DIR2)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
from matplotlib.patches import Patch
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import flopy
import pickle
import random
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import MaxNLocator
import shutil

# Plot
# from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
# from matplotlib.colors import LightSource
# import earthpy.spatial as es
# import earthpy.plot as ep
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# Gis
from rasterio.mask import mask
from rasterio.transform import array_bounds
from shapely.geometry import box
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
#%% HYDROMODPY
import src
import importlib
importlib.reload(src)

from src import watershed_root
from src.watershed import climatic, driasclimat, driaseau, geographic, geology, hydraulic, \
                          hydrography, hydrometry, intermittency, oceanic, \
                          piezometry, safransurfex, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% Import functions from the waterwise_tools

waterwise_tools = os.path.abspath(os.path.join(DIR, '_HP_waterwise\waterwise_tools'))

if waterwise_tools not in sys.path:
    sys.path.append(waterwise_tools)

from geol_glim import process_geology_with_glim
from elevation import plot_dem_hillshade_stream
from open_street_map import open_street_map
from google_satellite_map import google_satellite_map


#%% BULK FUNCTIONS

import os
from scipy.ndimage import gaussian_filter


def clip_raster_to_square(raster_path, output_path, center_coords, side_length):  
    """
    Clip a raster file to a square region centered at given coordinates.
    
    Parameters:
    - raster_path (str): Path to the original raster file.
    - output_path (str): Path to save the clipped raster file.
    - center_coords (tuple): (x, y) coordinates of the center of the square.
    - side_length (float): Length of the square's side in meters (default is 200000, i.e., 200 km).
    """
    x_center, y_center = center_coords
    half_side = side_length / 2

    # Define the square bounding box
    square = box(
        x_center - half_side,  # left
        y_center - half_side,  # bottom
        x_center + half_side,  # right
        y_center + half_side   # top
    )

    with rasterio.open(raster_path) as src:
        geojson_geometry = [square.__geo_interface__]

        out_image, out_transform = mask(src, geojson_geometry, crop=True)

        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
            "crs": src.crs
        })       
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)

    print(f"Clipped raster saved to: {output_path}")
    

from rasterio.enums import Resampling

def resample_and_save_dem(input_path, output_path, scale_factor=0.5):
    """
    Resample a DEM to a lower resolution and save as a new file.
    
    Parameters:
    - input_path (str): Path to the original DEM file.
    - output_path (str): Path to save the resampled DEM file.
    - scale_factor (float): Factor to downscale the DEM (e.g., 0.5 for half resolution).
    """
    with rasterio.open(input_path) as src:
        # Calculate new dimensions
        new_width = int(src.width * scale_factor)
        new_height = int(src.height * scale_factor)
        
        # Define the new transform for the resampled dataset
        transform = src.transform * src.transform.scale(
            (src.width / new_width),
            (src.height / new_height)
        )

        # Read and resample the data
        data = src.read(
            1,
            out_shape=(new_height, new_width),
            resampling=Resampling.average  # You can also use Resampling.bilinear or others
        )

        # Update metadata
        profile = src.profile
        profile.update({
            'height': new_height,
            'width': new_width,
            'transform': transform
        })
        
        # Save the resampled dataset
        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(data, 1)
    
    print(f"Resampled DEM saved to: {output_path}")


################

from pyproj import CRS
def plot_dem_and_points(dem_path, points_df, x_col='x_LAEA', y_col='y_LAEA'):
    """
    Plot DEM and overlay points with EPSG:3035 coordinates.
    
    Parameters:
    - dem_path: Path to the DEM file (GeoTIFF).
    - points_df: DataFrame containing 'x_LAEA' and 'y_LAEA' columns.
    - x_col, y_col: Column names for projected coordinates.
    """
    # Open DEM
    with rasterio.open(dem_path) as src:
        # Check CRS
        if src.crs.to_epsg() != 3035:
            print(f"DEM CRS is {src.crs}. Reprojecting to EPSG:3035.")
            dem_crs = CRS.from_epsg(3035)
        else:
            dem_crs = src.crs
            print(f"DEM CRS is already EPSG:3035.")

        # Read the DEM data
        dem = src.read(1)
        dem_extent = src.bounds

        # Plot DEM
        fig, ax = plt.subplots(figsize=(10, 10))
        show(src, ax=ax, cmap='terrain', title='Digital Elevation Model (EPSG:3035)')
        
        # Plot points if they exist
        if not points_df.empty:
            # Create a GeoDataFrame from the points DataFrame
            points_gdf = gpd.GeoDataFrame(
                points_df,
                geometry=gpd.points_from_xy(points_df[x_col], points_df[y_col]),
                crs="EPSG:3035"
            )
            
            # Plot points
            points_gdf.plot(ax=ax, color='red', marker='o', markersize=50, label='Sampled Points')
        
        # Aesthetic tweaks
        ax.set_xlim(dem_extent.left, dem_extent.right)
        ax.set_ylim(dem_extent.bottom, dem_extent.top)
        ax.legend()
        plt.show()


def convert_coordinates(df, x_col='x_LAEA', y_col='y_LAEA', lat_col='latitude', lon_col='longitude'):
    """
    Iterate over each row to check if x_LAEA is NaN, then perform conversion
    from WGS84 (EPSG:4326) to LAEA (EPSG:3035).

    Parameters:
    - df: DataFrame with coordinate columns.
    - x_col, y_col: Columns for LAEA coordinates (e.g., 'x_LAEA', 'y_LAEA').
    - lat_col, lon_col: Columns for WGS84 coordinates (e.g., 'latitude', 'longitude').

    Returns:
    - DataFrame with filled 'x_LAEA' and 'y_LAEA'.
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)

    for index, row in df.iterrows():
        if pd.isna(row[x_col]):  # If x_LAEA is NaN
            try:
                lon, lat = row[lon_col], row[lat_col]
                if pd.notna(lon) and pd.notna(lat):
                    x, y = transformer.transform(lon, lat)
                    df.at[index, x_col] = x
                    df.at[index, y_col] = y
            except Exception as e:
                print(f"Error processing row {index}: {e}")

    return df


def deficiency_evaporation(dfmonth, ppt_col, etp_col, ppt_etp_col, etr_col, ru_col, de_col):
    calc = pd.DataFrame()
    calc[ppt_etp_col] = (dfmonth[ppt_col]-dfmonth[etp_col]).round(2)
    calc[ru_col] = np.nan
    calc[etp_col] = dfmonth[etp_col]
    calc[ppt_col] = dfmonth[ppt_col]
    
    long = np.array(range(0,len(calc)))
    
    for r in long:
        idx = calc.index[0]
        calc[ru_col][idx] = 125
        if r == len(calc)-1:
            break
        else:
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) >= 125:
                calc[ru_col][r+1] = 125      
            if 0 < (calc[ru_col][r] + calc[ppt_etp_col][r+1]) < 125:
                calc[ru_col][r+1] = (calc[ru_col][r]+ 
                                              calc[ppt_etp_col][r+1])
            if (calc[ru_col][r] + calc[ppt_etp_col][r+1]) <= 0:
                calc[ru_col][r+1] = 0
    
    calc[etr_col] = np.nan
    for p in calc[ppt_etp_col]:
        if p > 0:
            idx1 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx1] = calc[etp_col][idx1]
    
        else:
            idx2 = calc.index[calc[ppt_etp_col] == p]
            calc[etr_col][idx2] = (calc[ppt_col][idx2] + (
                calc[ru_col][idx2]-1) - calc[ru_col][idx2])
    
    calc[de_col] = calc[etp_col] - calc[etr_col]

    for n in long:
        if calc[de_col][n] < 0:
            calc[de_col][n] = 0
            
    calc[de_col] = calc[de_col].round(2)
    
    dfmonth[etr_col] = calc[etr_col]
    dfmonth[de_col] = calc[de_col]
    
    return(dfmonth)

def fmt_xaxes(ax, years_maj, years_min):
    yearsmaj = mdates.YearLocator(years_maj)   # every year
    yearsmin = mdates.YearLocator(years_min)
    # monthsmaj = mdates.MonthLocator(6)  # every month
    # monthsmin = mdates.MonthLocator(3)
    # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
    years_fmt = mdates.DateFormatter('%Y')
    ax.xaxis.set_major_locator(yearsmaj)
    ax.xaxis.set_minor_locator(yearsmin)
    ax.xaxis.set_major_formatter(years_fmt)

def add_subplot_axes(ax,rect,axisbg='w'):
    fig = plt.gcf()
    box = ax.get_position()
    width = box.width
    height = box.height
    inax_position  = ax.transAxes.transform(rect[0:2])
    transFigure = fig.transFigure.inverted()
    infig_position = transFigure.transform(inax_position)
    x = infig_position[0]
    y = infig_position[1]
    width *= rect[2]
    height *= rect[3]  # <= Typo was here
    # subax = fig.add_axes([x,y,width,height],facecolor=facecolor)  # matplotlib 2.0+
    subax = fig.add_axes([x,y,width,height])  # matplotlib 2.0+
    # subax = fig.add_axes([x,y,width,height],axisbg=axisbg)
    x_labelsize = subax.get_xticklabels()[0].get_size()
    y_labelsize = subax.get_yticklabels()[0].get_size()
    x_labelsize *= rect[2]**0.5
    y_labelsize *= rect[3]**0.5
    subax.xaxis.set_tick_params(labelsize=x_labelsize)
    subax.yaxis.set_tick_params(labelsize=y_labelsize)
    return subax

def colorFader(c1,c2,mix=0): #fade (linear interpolate) from color c1 (at mix=0) to c2 (mix=1)
    c1=np.array(mpl.colors.to_rgb(c1))
    c2=np.array(mpl.colors.to_rgb(c2))
    return mpl.colors.to_hex((1-mix)*c1 + mix*c2)
c1='navy' #blue
c2='deepskyblue' #green
n=500
# fig, ax = plt.subplots(figsize=(8, 5))
# for x in range(n+1):
#     ax.axvline(x, color=colorFader(c1,c2,x/n), linewidth=4) 
# plt.show()

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import AxesGrid

class MidpointNormalize(mpl.colors.Normalize):
    def __init__(self, vmin=None, vmax=None, vcenter=None, clip=False):
        self.vcenter = vcenter
        super().__init__(vmin, vmax, clip)

    def __call__(self, value, clip=None):
        # I'm ignoring ed values and all kinds of edge cases to make a
        # simple example...
        # Note also that we must extrapolate beyond vmin/vmax
        x, y = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1.]
        return np.ma.masked_array(np.interp(value, x, y,
                                            left=-np.inf, right=np.inf))

    def inverse(self, value):
        y, x = [self.vmin, self.vcenter, self.vmax], [0, 0.5, 1]
        return np.interp(value, x, y, left=-np.inf, right=np.inf)

def shiftedColorMap(cmap, start=0, midpoint=0.5, stop=1.0, name='shiftedcmap'):
    '''
    Function to offset the "center" of a colormap. Useful for
    data with a negative min and positive max and you want the
    middle of the colormap's dynamic range to be at zero.

    Input
    -----
      cmap : The matplotlib colormap to be altered
      start : Offset from lowest point in the colormap's range.
          Defaults to 0.0 (no lower offset). Should be between
          0.0 and `midpoint`.
      midpoint : The new center of the colormap. Defaults to 
          0.5 (no shift). Should be between 0.0 and 1.0. In
          general, this should be  1 - vmax / (vmax + abs(vmin))
          For example if your data range from -15.0 to +5.0 and
          you want the center of the colormap at 0.0, `midpoint`
          should be set to  1 - 5/(5 + 15)) or 0.75
      stop : Offset from highest point in the colormap's range.
          Defaults to 1.0 (no upper offset). Should be between
          `midpoint` and 1.0.
    '''
    cdict = {
        'red': [],
        'green': [],
        'blue': [],
        'alpha': []
    }

    # regular index to compute the colors
    reg_index = np.linspace(start, stop, 257)

    # shifted index to match the data
    shift_index = np.hstack([
        np.linspace(0.0, midpoint, 128, endpoint=False), 
        np.linspace(midpoint, 1.0, 129, endpoint=True)
    ])

    for ri, si in zip(reg_index, shift_index):
        r, g, b, a = cmap(ri)

        cdict['red'].append((si, r, r))
        cdict['green'].append((si, g, g))
        cdict['blue'].append((si, b, b))
        cdict['alpha'].append((si, a, a))

    newcmap = matplotlib.colors.LinearSegmentedColormap(name, cdict)
    plt.register_cmap(cmap=newcmap)

    return newcmap

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

def linregress(inx,iny):
    x=np.array(inx, dtype=float)
    y=np.array(iny, dtype=float)
    xmas = np.ma.masked_array(x,mask=np.isnan(y)).compressed()
    ymas = np.ma.masked_array(y,mask=np.isnan(y)).compressed()
    slope, intercept, r_value, p_value, std_err = sp.linregress(xmas,ymas)    
    xf = np.linspace(min(x),max(x),100)
    xf1 = xf.copy()
    xf1 = pd.to_datetime(xf1)
    yf = (slope*xf)+intercept
    center_x = xf.mean()
    center_y = yf.mean()
    lenght_reg = [[xf.min(),xf.max()],[yf.min(),yf.max()]]
    return (center_x,center_y, slope, intercept, r_value, p_value, std_err, lenght_reg)

def sklearn_linregress(inx, iny):
    from sklearn import datasets, linear_model
    from sklearn.metrics import mean_squared_error, r2_score
    regr = linear_model.LinearRegression()
    regr.fit(inx, iny)
    y_pred = regr.predict(inx)
    print("Slope: %.2f" % regr.coef_[0])
    print("Mean squared error: %.2f" % mean_squared_error(iny, y_pred))
    print("Coefficient of determination: %.2f" % r2_score(iny, y_pred))
    print("Intercept: %.2f" % regr.intercept_)
    plt.scatter(inx, iny, color="black")
    plt.plot(inx, y_pred, color="blue", linewidth=3)
    plt.xticks(())
    plt.yticks(())
    plt.show()
    
def line(x, line_point1, line_point2, get_eq=False):
    m = (line_point1[1] - line_point2[1])/(line_point1[0] - line_point2[0])
    b = line_point1[1] - m*line_point1[0]
    if get_eq:
        return m, b
    else:
        return m*x + b

def perpendicular_line(x, random_point, line_point1, line_point2, get_eq=False):
    m, b = line(0, line_point1, line_point2, True)
    m2 = -1/m
    b2 = random_point[1] - m2*random_point[0]
    if get_eq:
        return m2, b2
    else:
        return m2*x + b2
    
def cut_polygon_by_line(polygon, line):
    merged = linemerge([polygon.boundary, line])
    borders = unary_union(merged)
    polygons = polygonize(borders)
    return list(polygons)

def plot(shapely_objects, figure_path='fig.png'):
    boundary = gpd.GeoSeries(shapely_objects)
    boundary.plot(color=['red', 'green'])
    
def clip_raster_to_square(raster_path, output_path, center_coords, side_length):
    x_center, y_center = center_coords
    half_side = side_length / 2

    square = box(
        x_center - half_side,  # Extremo izquierdo
        y_center - half_side,  # Extremo inferior
        x_center + half_side,  # Extremo derecho
        y_center + half_side   # Extremo superior
    )

    with rasterio.open(raster_path) as src:
        geojson_geometry = [square.__geo_interface__]

        out_image, out_transform = mask(src, geojson_geometry, crop=True)

        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform
        })       
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(out_image)

#%% ---- CATCHMENT

#%% OPEN the files with the coordinates
sites_file = os.path.join(data_path,'_sites','Waterwise_sites_april2025.xlsx')
sites = pd.read_excel(sites_file)

sites = convert_coordinates(sites)
for col in sites.select_dtypes(include=['datetime']):
    sites[col] = sites[col].astype(str)

# Convert the DataFrame to a GeoDataFrame
from shapely.geometry import Point
geometry = [Point(xy) for xy in zip(sites['x_LAEA'], sites['y_LAEA'])]
sites_gdf = gpd.GeoDataFrame(sites, geometry=geometry, crs="EPSG:3035")

# Save the GeoDataFrame as a .shp file
output_sites_fp = os.path.join(data_path, '_sites','', 'Waterwise_sites_saved.shp')
sites_gdf.to_file(output_sites_fp)

#%% Define the paths to main files
dem_name = "gedtm30_alps_epsg3035.tif" # name of dem
# dem_name_resampled = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035_resampled0.1.tif" # name of dem
# dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
dem_path = os.path.join(data_path,'_dem/',dem_name)
# dem_path_resampled = os.path.join(data_path,'_dem/',dem_name_resampled)
# dem_path = 'G:/Mon Drive/_travail/_python/project/alps_pyr/_data/dem/eu_dem_v11_E30-40N20_EPSG3035.tif'
# reg_fold = data_path + '_regional/'
# dem_path = 'Y:/HDPY_database_forModelling/_sites/_cont/dem_cont.tif'

#%% Resample DEM
# name_dem_resampled = dem_name[:-4] + '_resampled0.1.tif'
# dem_path_resampled = os.path.join(data_path,'_dem/',name_dem_resampled)
# resample_and_save_dem(dem_path, dem_path_resampled, scale_factor=0.1)

# dem_path = dem_path_resampled

# Example DataFrame of points
points = sites.loc[:, ['x_LAEA', 'y_LAEA']]
points = pd.DataFrame(points)



#%% run the analysis
for i, j in sites.iterrows():
    if i<10:
        continue
    id_name = str(sites.loc[i,'ID_name'])
    watershed_name = str(sites.loc[i,'Name'])
    site_num = str(sites.loc[i,'ID'])
    
    print('##########################################')
    print('##### Working on '+ watershed_name.upper()+' #####')
    
    x = sites.loc[i,'x_LAEA']
    y = sites.loc[i,'y_LAEA']
    
    # Define the output path for the clipped DEM
    clipped_dem_fp = os.path.join(data_path, '_sites', id_name)
    os.makedirs(clipped_dem_fp, exist_ok=True)
    
    clipped_dem_path = os.path.join(clipped_dem_fp, f'{id_name}_clipped_dem.tif')
    
    # Clip the DEM
    clip_raster_to_square(dem_path, clipped_dem_path, (x, y), 100000)

    from_xyv = [x, y, 150, 50, 'EPSG:3035'] # [x, y, snap distance, buffer size [%], crs proj]
    
    #%% Plot the dem 
    # Extract the catchment from the clipped DEM
    BV = watershed_root.Watershed(dem_path=clipped_dem_path,
                                  out_path=out_path,
                                  load=True,
                                  watershed_name=id_name,
                                  from_lib=None, # os.path.join(root_dir,'watershed_library.csv')
                                  from_dem=None, # [path, cell size]
                                  from_shp=None, # [path, buffer size]
                                  from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                                  bottom_path=None, # path 
                                  save_object=True)
    
    # Paths necessary for the rest of the script
    stable_folder = os.path.join(out_path, id_name, 'results_stable')
    simulations_folder = os.path.join(out_path, id_name, 'results_simulations')
                      
    print('Area: ' + str(BV.geographic.area.round(2)) + 'km^2')
    print('Slope: ' + str(BV.geographic.slope.round(2)))
        
    visualization_watershed.watershed_local(clipped_dem_path, BV)
    visualization_watershed.watershed_dem(BV)
    
    #%% plot dem elevation
    plot_dem_hillshade_stream(data_path, 
                              stable_folder, 
                              clipped_dem_path, 
                              id_name, 
                              watershed_name)
    
    #%% plot the Open street map
    open_street_map(stable_folder, 
                    id_name, 
                    watershed_name)
    
    #%% plot the google earth map
    google_satellite_map(data_path, 
                         stable_folder, 
                         id_name, 
                         watershed_name)
    
    #%% GEOLOGY
    geol_path = os.path.join(data_path, '_geology')
    BV.add_geology(geol_path, types_obs='GLiM_clip_EU.shp', fields_obs='xx')
    
    process_geology_with_glim(data_path, 
                              stable_folder, 
                              clipped_dem_path, 
                              id_name, sites, 
                              site_num, 
                              watershed_name)
 
    


