# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

import os
import re
import math
import datetime
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
import rasterio as rio
import rasterio.features # necessary to avoid a bug
import geopandas as gpd
import xarray as xr
xr.set_options(keep_attrs = True)
# import rioxarray as rio #Not necessary, the rio module from xarray is enough
from osgeo import gdal, osr
from pyproj import CRS
from pyproj import Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from hydroeval import *
import pandas as pd
from affine import Affine
import numpy as np
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% DIRECTORY MANAGEMENT

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
        
#%% RASTER PROCESSING

def clip_tif(tif_path, shp_path, out_path, maintain_dimensions):
    """
    Clip a raster from a shapefile polygon.

    Parameters
    ----------
    tif_path : str
        Raster path.
    shp_path : str
        Shapefile path.
    out_path : str
        Ouput result path.
    maintain_dimensions : bool
        Maintain the raster dimension or not.
    """
    wbt.clip_raster_to_polygon(tif_path, shp_path, out_path, maintain_dimensions=maintain_dimensions)

def mask_by_dem(target_data, mask_data, cond_symb, value_masked):
    """
    Mask raster from different conditions

    Parameters
    ----------
    target_data : 2D matrix
        Raster data to mask.
    mask_data : 2D matrix
        Raster reference for mask.
    cond_symb : str
        Select the mask consition: '==','!=','<=','>=','>','<'.
    value_masked : float
        Value to mask.

    Returns
    -------
    masked : 2D matrix
        Masked raster.
    """
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

def load_to_numpy(file_path, src_crs=None,
                  base_path:str=None, dst_crs=None, out_path:str=None):
    """
    Generate a numpy array from a source file (vector or raster) and a base
    raster. The numpy array profile (shape, resolution, extent...) matches 
    with the base one.
    If the base raster is not specified (base_path), then the generated numpy
    array has the same profile as the source file.
    
    When the source CRS is not embeded in the source file, it can be specified
    with src_crs.
    When the destination CRS is not embeded in the base file, it can also be
    specified with dst_crs.
    
    out_path gives the possibility to export the result as a .tif file.
    

    Parameters
    ----------
    file_path : str
        Path to the input file to process.
    src_crs : int or str, optional (The default is None)
        If the CRS is not embeded in the input file, it is possible to 
        specify it here, as an integer (EPSG), or a str 'EPSG:<int>'
    base_path : str, optional (The default is None)
        Path to the file that will serve as the base for dimensions, resolution,
        extent... 
    dst_crs : int or str, optional (The default is None)
        If the CRS is not embeded in the base file, it is possible to 
        specify it here, as an integer (EPSG), or a str 'EPSG:<int>'
    out_path : str, optional (The default is None)
        If specified, the numpy array will be saved as a .tif file, using the
        profile from the base file.

    Returns
    -------
    val : numpy.ndarray

    """
    # Initializations:
    if base_path:
        with rio.open(base_path, 'r') as base: base_profile = base.profile
    else:
        base_profile = None
    if isinstance(src_crs, str): src_crs = rio.crs.CRS.from_string(src_crs)
    elif isinstance(src_crs, int): src_crs = rio.crs.CRS.from_epsg(src_crs)
    if isinstance(dst_crs, str): dst_crs = rio.crs.CRS.from_string(dst_crs)
    elif isinstance(dst_crs, int): dst_crs = rio.crs.CRS.from_epsg(dst_crs)
    
    
    if os.path.splitext(file_path)[-1] in ['.shp', '.dbf', '.shx']: # shapefile
        if base_profile:
            file_vect = gpd.read_file(file_path)
            # CRS initialization
            if not file_vect.crs: # if not file_vect.crs.is_geographic nor file_vect.crs.is_projected:
                if src_crs: 
                    file_vect.set_crs(crs = src_crs, allow_override = True)
                else: 
                    print("\nError: Source CRS (src_crs) is required to rasterize.")
                    return
                    
            if not base_profile['crs'].is_valid:
                if dst_crs: base_profile['crs'] = dst_crs
                else: 
                    print("\nError; Destination CRS (dst_crs) is required to rasterize.")
                    return
                    
            # The vector needs to be in the same CRS as the base raster:
            print(f"\n Before rasterization, the vector will be converted from 'EPSG:{file_vect.crs.to_epsg()}' into 'EPSG:{base_profile['crs'].to_epsg()}'")            
            file_vect.to_crs(crs = base_profile['crs'].to_epsg(), inplace = True)
            # Rasterize:
            val = rio.features.rasterize(
                [(val.geometry, 1) for _, val in file_vect.iterrows()],
                out_shape = (base_profile['height'], base_profile['width']),
                transform = base_profile['transform'],
                fill = base_profile['nodata'],
                all_touched = False)
            # update profile
            data_profile = base_profile
        else: # if there is no base_profile
            print('\nRasterizeError: A rasterio profile is required to convert vectoriel data into raster')
            return
            
    else: # input file is a raster
        with rio.open(file_path, 'r') as data:
            data_profile = data.profile
            if src_crs and not data_profile['crs'].is_valid:
                data_profile['crs'] = src_crs
                print(f"\n The CRS of input data has been set to 'EPSG:{data_profile['crs']}'")
            # data_crs = data.crs
            val = data.read()[0] # extract the first layer
    
    # Reprojection:
    # if (crs_proj and (str(data_crs) != crs_proj)) or (base_profile and (data_profile != base_profile)):    
    if base_profile:
        # CRS initialization
        if dst_crs and not base_profile['crs'].is_valid:
            base_profile['crs'] = dst_crs
                
        if data_profile != base_profile:
            if not data_profile['crs'].is_valid:
                print('\nError: Source CRS (src_crs) is required to reproject.')
                return
            if not base_profile['crs'].is_valid:
                print('\nError: Destination CRS (dst_crs) is required to reproject.')
                return
            rio.warp.reproject(source = val, 
                                        destination = val, 
                                        src_transform = data_profile['transform'],
                                        src_crs = data_profile['crs'],
                                        src_nodata = data_profile['nodata'],
                                        dst_transform = base_profile['transform'],
                                        dst_crs = base_profile['crs'],
                                        dst_nodata = base_profile['nodata'],
                                        resampling = rio.enums.Resampling(0),
                                        # resampling = rasterio.enums.Resampling(5),
                                        )
            # update_profile
            data_profile = base_profile
        
    
    
    # Ne fonctionne pas encore
# =============================================================================
#     # Drop nodata margins:
#     J, I = np.where(val == 1)
#     imin = I.min()
#     imax = I.max()
#     jmin = J.min()
#     jmax = J.max()
#     xmin = data_profile['transform'][2] + imin*data_profile['transform'][0]
#     ymax = data_profile['transform'][5] + (data_profile['height']-jmax)*data_profile['transform'][5]
#     data_profile['transform'] = Affine(data_profile['transform'][0],
#                                        data_profile['transform'][1],
#                                        xmin,
#                                        data_profile['transform'][3],
#                                        data_profile['transform'][4],
#                                        ymax)
#     data_profile['width'] = imax - imin
#     data_profile['height'] = jmax - jmin
# =============================================================================

    if out_path: # to export as a .tif file (optional)
        with rio.open(out_path, 'w', **data_profile) as dst: 
            dst.write_band(1, val)
    
    if base_profile: 
        print(f" destination CRS = {base_profile['crs']}")
        print(f" no data value = {base_profile['nodata']}")
    
    return val


def read_with_xarray(file_path, src_crs=None, main_var=None):
    if os.path.splitext(file_path)[-1].casefold() in ['.tif', '.tiff']:
        with xr.open_dataset(file_path) as ds:
            ds.load() # to unlock the resource
        ds = ds.squeeze('band')
        ds = ds.drop('band')
        if main_var:
            ds = ds.rename(dict(band_data = main_var))
        
    elif os.path.splitext(file_path)[-1].casefold() == '.nc':
        try:
            with xr.open_dataset(file_path, decode_coords = 'all') as ds:
                ds.load() # to unlock the resource
                
        except ValueError: 
            # Usually this error appears when unable to decode 
            # time units 'Months since 1901-01-01' with 
            # "calendar 'proleptic_gregorian'"
            print("\nWarning: Unable to decode time units")
            with xr.open_dataset(file_path, decode_coords = 'all', 
                                 decode_times = False) as ds:
                ds.load()
                
            try: ds.time.attrs['units']
            except: 
                print("Err: No information on time units in attributes")
                return
            # Build back time scale:
            print(f"Time axis will be inferred from 'time' attributes: \"{ds.time.attrs['units']}\"...")
            timeunit = ds.time.attrs['units'].split()[0].casefold()
            if timeunit in ['month', 'months', 'mois']:
                freq = 'MS'
                freq_info = 'monthly'
            elif timeunit in ['day', 'days', 'jour', 'jours']:
                freq = '1D'
                freq_info = 'daily'
            
            print("   | Note that The format of the origin date is expected to be either")
            print("   | YYYY MM DD or DD MM YYYY (with any separator). The american format")
            print("   | MM DD YYYY will not be considered.")
            # The format of the origin date is expected to be either 
            # YYYY MM DD or DD MM YYYY (with any separator)
            # The american format MM DD YYYY is not considered
            initdate_pattern = re.compile("\d{2,4}.*\d{2,4}")
            initdate = initdate_pattern.search(ds.time.attrs['units']).group()
            
            if initdate[2].isnumeric():
                sep = initdate[4]
                initdate = datetime.datetime.strptime(initdate, f"%Y{sep}%m{sep}%d")
            else:
                sep = initdate[2]
                initdate = datetime.datetime.strptime(initdate, f"%d{sep}%m{sep}%Y")
            
            start_date = pd.Series(pd.date_range(
                initdate, periods = int(ds.time[0]) + 1, freq = freq)).iloc[-1]
            date_index = pd.date_range(start = start_date, 
                                         periods = len(ds.time), freq = freq) 
            print(f"Time axis from {date_index[0]} to {date_index[-1]} ({freq_info})")
            ds['time'] = date_index  
    
    else:
        print(f"\nErr: Extension {os.path.splitext(file_path)[-1]} is not recognized by xarray")
        return
    
    # Format spatial attributes for compatibility with QGIS
    if 'units' in ds.x.attrs.keys() and ds.x.attrs['units'].casefold() in ['m', 'meter', 'meters', 'metre', 'metres']:
        ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                      'long_name': 'x coordinate of projection',
                      'units': 'Meter'}
        ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                      'long_name': 'y coordinate of projection',
                      'units': 'Meter'}
    elif 'units' in ds.x.attrs.keys() and 'deg' in ds.x.attrs['units']:
        ds.longitude.attrs = {'long_name': 'longitude',
                              'units': 'degrees_east'}
        ds.latitude.attrs = {'long_name': 'latitude',
                             'units': 'degrees_north'}
            
    # Add Coordinate Reference System if needed
    if 'spatial_ref' not in list(ds.coords) and src_crs:
        ds.rio.write_crs(src_crs, inplace = True)
    
    return ds

        
#%% EXTRACTING FEATURES

def basin_area(target_data, mask_data, cond_symb, value_masked, resolution):
    """
    Calculate the area of a masked raster.

    Parameters
    ----------
    target_data : 2D matrix
        Raster data to mask.
    mask_data : 2D matrix
        Raster reference for mask.
    cond_symb : str
        Select the mask consition: '==','!=','<=','>=','>','<'.
    value_masked : float
        Value to mask.
    resolution : float
        Cell resolution of the raster.

    Returns
    -------
    area : float
        Area in [km²] if resolution is in [m].
    """
    masked = mask_by_dem(target_data, mask_data, cond_symb, value_masked)
    cell = masked.count()
    area = (cell * resolution**2) / 1000000
    return area

def efficiency_criteria(sim, obs):
    """
    Calculate successful criteria.

    Parameters
    ----------
    sim : list
        Timeseries of simulated results.
    obs : list
        Timeseries of observed results.

    Returns
    -------
    list
        Float values results.
    """
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
    """
    Generate timestamp from datetime.

    Parameters
    ----------
    start : int
        Starting year.
    periods : int
        Number of periods.
    freq : str
        Frequency of the datetime: 'D','W','M','Y'.

    Returns
    -------
    time : datetime
        Datetime generated.
    """
    time = pd.date_range(str(start), periods=periods, freq=freq)
    return time

#%% PLOT SETTINGS

def plot_params(small,interm,medium,large):
    """
    Change options for plots.
    
    Parameters
    ----------
    small : float
        Small size.
    interm : float
        Intermediate size.
    medium : float
        Medium size.
    large : float
        Large size.

    Returns
    -------
    fontprop : dict
        Properties of font.
    """
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
    plt.rc('font', family='sans serif')
    
    fontprop = FontProperties()
    fontprop.set_family('sans serif') # for x and y label
    fontdic = {'family' : 'sans serif', 'weight' : 'bold'} # for legend  

    return fontprop      

#%% REPROJECT DATA

def export_tif(base_dem_path, data_to_tif, data_nodata_val, data_tif_path):
    """
    Export tif from 2D matrix data following raster reference.

    Parameters
    ----------
    base_dem_path : str
        Path of raster reference.
    data_to_tif : 2D matrix
        Data to export in raster.
    data_nodata_val : float
        Value defined as no data.
    data_tif_path : TYPE
        Output path of the exported raster.
    """
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
    """
    Reproject raster from WGS to UTM projection.
    """
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
    """
    Reproject coordinate points WGS to UTM.
    """
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
    """
    Reproject shapefile with defined UTM crs.
    For example: 'EPSG:2154'
    """
    crs_code = utm_crs[5:]
    shp = gpd.read_file(raw_shp_path)
    shp.set_crs(epsg=crs_code, inplace=True, allow_override=True)
    # shp.to_crs(utm_crs)
    shp.to_file(out_shp_path)

def select_period(df, first, last):
    """
    Clip a timeseries from two boundary years.

    Parameters
    ----------
    df : DataFrame or Series
        DataFrame or Series with datetime index.
    first : int
        Starting year.
    last : int
        Ending year.

    Returns
    -------
    df : DataFrame or Series
        Clipped variable.
    """
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

def export_netcdf(data, base_path:str, out_path:str, base_crs=None,
                  times=None, y=None, x=None):
    # Librairies
    import rioxarray # intended to be moved to the # LIBRAIRIES section
    
    # Metadata
    if isinstance(base_crs, str): base_crs = rio.crs.CRS.from_string(base_crs)
    elif isinstance(base_crs, int): base_crs = rio.crs.CRS.from_epsg(base_crs)
    with rio.open(base_path, 'r') as base:
        base_profile = base.profile
        if base_crs and not base_profile['crs'].is_valid:
            base_profile['crs'] = base_crs
        val_for_mask = base.read()[0]
    [reso_x, _, x_min, _, reso_y, y_max, _, _, _] = list(base_profile['transform'])
    if not x:
        x_val = [x for x in np.arange(x_min + reso_x/2, x_min + reso_x*base_profile['width'] + reso_x/2, reso_x)]
    if not y:
        y_val = [y for y in np.arange(y_max + reso_y/2, y_max + reso_y*base_profile['height'] + reso_y/2, reso_y)]
    
    # Create xarray Dataset
    M = np.array([data[item] for item in data.keys()])
# =============================================================================
#     M = np.ma.array(M, 
#                     mask = M==base_profile['nodata'],
#                     fill_value = base_profile['nodata'],
#                     )
# =============================================================================
    da = xr.DataArray(M, dims = ('time', 'y', 'x'))
    da = da.assign_coords({"time": ("time", times), 
                           "y": ("y", y_val), 
                           "x": ("x", x_val)})
    da = da.where(val_for_mask != base_profile['nodata'])
    ds = xr.Dataset()
    main_var = os.path.splitext(os.path.split(out_path)[-1])[0]
    ds[main_var] = da
    
    # Attributes
# =============================================================================
#     ds = ds.transpose('time', 'y', 'x')
# =============================================================================
    ds.x.attrs = {'standard_name': 'projection_x_coordinate',
              'long_name': 'x coordinate of projection',
              'units': 'Meter'}
    ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                  'long_name': 'y coordinate of projection',
                  'units': 'Meter'}
    ds.rio.write_crs(base_crs, inplace = True)
    # Gzip compression (not lossy):
# =============================================================================
#     ds[main_var].encoding['zlib'] = True
#     ds[main_var].encoding['complevel'] = 4
#     ds[main_var].encoding['contiguous'] = False
#     ds[main_var].encoding['shuffle'] = True
#     ds[main_var].encoding['_FillValue'] = base_profile['nodata']
#     # Very efficient, but QGIS struggles to open these files as Mesh
# =============================================================================
    # Discretization compression (lossy):
    scale_factor, add_offset = compute_scale_and_offset(ds[main_var].min(), 
                                                        ds[main_var].max(), 
                                                        16)
    ds[main_var].encoding['scale_factor'] = scale_factor
    ds[main_var].encoding['add_offset'] = add_offset
    ds[main_var].encoding['dtype'] = 'int16'
    ds[main_var].encoding['_FillValue'] = -9999 # should be inside the packed range
    
    # Export
    ds.to_netcdf(out_path)
    
#%% Packing netcdf
"""
Created on Wed Aug 24 16:48:29 2022

@author: script based on James Hiebert's work (2015):
    http://james.hiebert.name/blog/work/2015/04/18/NetCDF-Scale-Factors.html

dtypes reminder:
    uint8 (unsigned int.)       0 to 255
    uint16 (unsigned int.)      0 to 65535
    uint32 (unsigned int.)      0 to 4294967295
    uint64 (unsigned int.)      0 to 18446744073709551615
    
    int8    (Bytes)             -128 to 127
    int16   (short integer)     -32768 to 32767
    int32   (integer)           -2147483648 to 2147483647
    int64   (integer)           -9223372036854775808 to 9223372036854775807 
    
    float16 (half precision float)      10 bits mantissa, 5 bits exponent (~ 4 cs ?)
    float32 (single precision float)    23 bits mantissa, 8 bits exponent (~ 8 cs ?)
    float64 (double precision float)    52 bits mantissa, 11 bits exponent (~ 16 cs ?)
"""

def compute_scale_and_offset(min, max, n):
    """
    Computes scale and offset necessary to pack a float32 or float64 set of values
    into a int16 or int8 set of values.
    
    Parameters
    ----------
    min : float
        Minimum value from the data
    max : float
        Maximum value from the data
    n : int
        Number of bits into which we wish to pack (8 or 16)

    Returns
    -------
    scale_factor : float
        Parameter for netCDF's encoding
    add_offset : float
        Parameter for netCDF's encoding
    """
    
    # stretch/compress data to the available packed range
    scale_factor = (max - min) / (2 ** n - 1)
    
    # translate the range to be symmetric about zero
    add_offset = min + 2 ** (n - 1) * scale_factor
    
    return (scale_factor, add_offset)


def pack_value(unpacked_value, scale_factor, add_offset):
    print(f'math.floor: {math.floor((unpacked_value - add_offset) / scale_factor)}')
    return (unpacked_value - add_offset) / scale_factor


def unpack_value(packed_value, scale_factor, add_offset):
    return packed_value * scale_factor + add_offset    
    

#%% DISPLAY 

def print_hydromodpy():
    print(r'      __  __          __           __  ____          ________     ') 
    print(r'     / / / /         / /          /  \/   /         / / __  /     ') 
    print(r'    / /_/ /_  ______/ /________  /       /___  ____/ / /_/ /_  __ ')
    print(r'   / __  / / / / __  / ___/ __ \/ /\,-/ / __ \/ __  / ____/ / / / ')  
    print(r'  / / / / /_/ / /_/ / /  / /_/ / /   / / /_/ / /_/ / /   / /_/ /  ')  
    print(r' /_/ /_/\__, /_____/_/   \____/_/   /_/\____/_____/_/____\__, /   ')  
    print(r'       /____/ Hydrological Modelling in Python /_____________/    ')  
    print(r'                                                                  ')    
    
#%% NOTES
