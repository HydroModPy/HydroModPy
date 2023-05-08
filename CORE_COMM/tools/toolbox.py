# -*- coding: utf-8 -*-
"""

"""

#%% Librairies

import os
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import rasterio as rio
import geopandas as gpd
from osgeo import gdal, osr
from pyproj import Proj
from pyproj import CRS
from pyproj import Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from hydroeval import *
import pandas as pd
import numpy as np

#%% Directory management

def create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)
        
#%% Raster processing

def clip_tif(tif_path, shp_path, out_path, maintain_dimensions):
    wbt.clip_raster_to_polygon(tif_path, shp_path, out_path, maintain_dimensions=maintain_dimensions)

def mask_by_dem(target_data, mask_data, cond_symb, value_masked):
    if cond_symb == '==':
        masked = np.ma.masked_array(target_data, mask=mask_data==value_masked)
    if cond_symb == '!=':
        masked = np.ma.masked_array(target_data, mask=mask_data!=value_masked)
    if cond_symb == '<=':
        masked = np.ma.masked_array(target_data, mask=mask_data<=value_masked)
    if cond_symb == '>=':
        masked = np.ma.masked_array(target_data, mask=mask_data>=value_masked)
    if cond_symb == '>':
        masked = np.ma.masked_array(target_data, mask=mask_data>value_masked)
    if cond_symb == '<':
        masked = np.ma.masked_array(target_data, mask=mask_data<value_masked)
    return masked

#%% Extract features

def basin_area(target_data, mask_data, cond_symb, value_masked, resolution):
    masked = mask_by_dem(target_data, mask_data, cond_symb, value_masked)
    cell = masked.count()
    area = (cell * resolution**2) / 1000000
    return area

def efficiency_criteria(sim, obs):
    RMSE = evaluator(rmse, sim, obs)
    nRMSE = RMSE[0] / obs.mean() # %
    NSE = evaluator(nse, sim, obs)
    NSElog = evaluator(nse, sim, obs, transform='log')
    BAL = (np.sum(sim)/np.sum(obs))
    MARE = evaluator(mare, sim, obs)
    KGEcomp = evaluator(kge, sim, obs) # and its three components (r, α, β)
    KGE = KGEcomp[0]
    return [RMSE[0], nRMSE, NSE[0], NSElog[0], BAL, MARE[0], KGE[0]]

def date_range(start, periods, freq):
    time = pd.date_range(str(start), periods=periods, freq=freq)
    return time

#%% Plot parameters

def plot_params(small,interm,medium,large):
    
    small = small
    interm = interm
    medium = medium
    large = large
    
    # mpl.rcParams['backend'] = 'wxAgg'
    mpl.style.use('classic')
    mpl.rcParams["figure.facecolor"] = 'white'
    mpl.rcParams['grid.color'] = 'darkgrey'
    mpl.rcParams['grid.linestyle'] = '-'
    mpl.rcParams['grid.alpha'] = 0.8
    mpl.rcParams['axes.axisbelow'] = True
    mpl.rcParams['axes.linewidth'] = 1.5
    mpl.rcParams['figure.dpi'] = 300
    mpl.rcParams['savefig.dpi'] = 300
    mpl.rcParams['patch.force_edgecolor'] = True
    mpl.rcParams['image.interpolation'] = 'nearest'
    mpl.rcParams['image.resample'] = True
    mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
    mpl.rcParams['axes.xmargin'] = 0.05
    mpl.rcParams['axes.ymargin'] = 0.05
    mpl.rcParams['xtick.direction'] = 'in'
    mpl.rcParams['ytick.direction'] = 'in'
    mpl.rcParams['xtick.major.size'] = 5
    mpl.rcParams['xtick.minor.size'] = 3
    mpl.rcParams['xtick.major.width'] = 1.5
    mpl.rcParams['xtick.minor.width'] = 1
    mpl.rcParams['ytick.major.size'] = 5
    mpl.rcParams['ytick.minor.size'] = 1.5
    mpl.rcParams['ytick.major.width'] = 1.5
    mpl.rcParams['ytick.minor.width'] = 1
    mpl.rcParams['xtick.top'] = True
    mpl.rcParams['ytick.right'] = True
    mpl.rcParams['legend.numpoints'] = 1
    mpl.rcParams['legend.scatterpoints'] = 1
    mpl.rcParams['legend.edgecolor'] = 'grey'
    mpl.rcParams['date.autoformatter.year'] = '%Y'
    mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
    mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
    mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
    mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
    mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'
    mpl.rcParams.update({'mathtext.default': 'regular' })
    
    plt.rc('font', size=small)                         # controls default text sizes **font
    plt.rc('figure', titlesize=large)                   # fontsize of the figure title
    plt.rc('legend', fontsize=small)                     # legend fontsize
    plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
    plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
    plt.rc('xtick', labelsize=interm)                   # fontsize of the tick labels
    plt.rc('ytick', labelsize=interm)                   # fontsize of the tick labels
    plt.rc('font', family='arial')
    
    fontprop = FontProperties()
    fontprop.set_family('arial') # for x and y label
    fontdic = {'family' : 'arial', 'weight' : 'bold'} # for legend  

    return fontprop      

#%% Reproject data

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
    warp = gdal.Warp(wgs_dem_path, raw_dem, dstSRS='EPSG:4326')
    warp = None
    
    wgs_dem = gdal.Open(wgs_dem_path)
    # proj = osr.SpatialReference(wkt=dem.GetProjection())
    # self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))

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
    
#%% Notes

    