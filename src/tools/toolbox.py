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
import numbers
import logging
import datetime
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
import rasterio as rio
import rasterio.features # necessary to avoid a bug
import geopandas as gpd
from shapely.geometry import Point
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

def load_to_numpy(file, src_crs=None,
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
    file : str or geopandas.GeoDataFrame
        Path to the input file to process, or geopandas GoDataFrame.
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
        with rio.open(base_path, 'r') as base: 
            base_profile = base.profile
            base_val = base.read(1) # base.read()[0]
    else:
        base_profile = None
    if isinstance(src_crs, str): src_crs = rio.crs.CRS.from_string(src_crs)
    elif isinstance(src_crs, int): src_crs = rio.crs.CRS.from_epsg(src_crs)
    if isinstance(dst_crs, str): dst_crs = rio.crs.CRS.from_string(dst_crs)
    elif isinstance(dst_crs, int): dst_crs = rio.crs.CRS.from_epsg(dst_crs)

    file_vect = None
    if isinstance(file, gpd.geodataframe.GeoDataFrame):
        file_vect = file
    elif os.path.splitext(file)[-1] in ['.shp', '.dbf', '.shx']: # shapefile
        file_vect = gpd.read_file(file)
    elif os.path.splitext(file)[-1] in ['.txt', '.csv']: # coordinates array
        """
        The input file should be formated as:
            id;x;y
            0;34500;7456125  
            1;35675;7991500
            ...
        """
        try:
            df = pd.read_csv(file, sep = ";")
            geometry = [Point(xy) for xy in zip(df.x, df.y)]
            df = df.drop(columns = ['x', 'y'])
            file_vect = gpd.GeoDataFrame(df, geometry = geometry)
        except:
            logging.error("The input file should be formated as:")
            logging.error("    id;x;y\n    0;34500;7456125\n    1;35675;7991500\n    ...")
    
    if file_vect is not None: # shapefile
        if base_profile:
            # CRS initialization
            if not file_vect.crs: # if not file_vect.crs.is_geographic nor file_vect.crs.is_projected:
                if src_crs: 
                    file_vect.set_crs(crs = src_crs, inplace = True, allow_override = True)
                else: 
                    logging.error("Source CRS (src_crs) is required to rasterize.")
                    return
                    
            if not base_profile['crs'].is_valid:
                if dst_crs: base_profile['crs'] = dst_crs
                else: 
                    logging.error("Destination CRS (dst_crs) is required to rasterize.")
                    return
                    
            # The vector needs to be in the same CRS as the base raster:
            logging.debug(f"Before rasterization, the vector will be converted from 'EPSG:{file_vect.crs.to_epsg()}' into 'EPSG:{base_profile['crs'].to_epsg()}'.")            
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
            logging.error('RasterizeError: A rasterio profile is required to convert vectoriel data into raster.')
            return
    
    else: # input file is a raster
        with rio.open(file, 'r') as data:
            data_profile = data.profile
            if src_crs and not data_profile['crs'].is_valid:
                data_profile['crs'] = src_crs
                logging.debug(f"The CRS of input data has been set to 'EPSG:{data_profile['crs'].to_epsg()}'.")
            # data_crs = data.crs
            val = data.read(1) # data.read()[0] # extract the first layer
    
    # Reprojection:
    # if (crs_proj and (str(data_crs) != crs_proj)) or (base_profile and (data_profile != base_profile)):    
    if base_profile:
        # CRS initialization
        if dst_crs and not base_profile['crs'].is_valid:
            base_profile['crs'] = dst_crs
                
        if data_profile != base_profile:
            if not data_profile['crs'].is_valid:
                logging.error('Source CRS (src_crs) is required to reproject.')
                return
            if not base_profile['crs'].is_valid:
                logging.error('Destination CRS (dst_crs) is required to reproject.')
                return
            rio.warp.reproject(source = val, 
                               destination = base_val, 
                               src_transform = data_profile['transform'],
                               src_crs = data_profile['crs'],
                               src_nodata = data_profile['nodata'],
                               dst_transform = base_profile['transform'],
                               dst_crs = base_profile['crs'],
                               dst_nodata = base_profile['nodata'],
                               # resampling = rio.enums.Resampling(0),
                                resampling = rasterio.enums.Resampling(1), # (0), (5)
                               )
            # update_profile
            data_profile = base_profile
            # update values array
            val = base_val
        
    
    
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
        dst_crs = base_profile['crs']
        nodata = base_profile['nodata']
    else:
        nodata = None
    
    if file_vect is not None:
        src_crs = file_vect.crs
    else:
        src_crs = data_profile['crs']
    
    return val, src_crs, dst_crs, nodata


def load_to_xarray(file, src_crs=None, main_var=None, 
                   base_path:str=None, dst_crs=None):
    """
    

    Parameters
    ----------
    file : str (path) or xarray.Dataset
        DESCRIPTION.
    src_crs : TYPE, optional
        DESCRIPTION. The default is None.
    main_var : TYPE, optional
        DESCRIPTION. The default is None.
    base_path : str, optional
        DESCRIPTION. The default is None.
    dst_crs : TYPE, optional
        DESCRIPTION. The default is None.

    Returns
    -------
    TYPE
        DESCRIPTION.
    src_crs : TYPE
        DESCRIPTION.
    dst_crs : TYPE
        DESCRIPTION.
    nodata : TYPE
        DESCRIPTION.

    """
    
    # ---- Initialization
    if base_path:
        with rio.open(base_path, 'r') as base: 
            base_profile = base.profile
            base_val = base.read(1) # base.read()[0]
    else:
        base_profile = None
    if isinstance(src_crs, str): src_crs = rio.crs.CRS.from_string(src_crs)
    elif isinstance(src_crs, int): src_crs = rio.crs.CRS.from_epsg(src_crs)
    if isinstance(dst_crs, str): dst_crs = rio.crs.CRS.from_string(dst_crs)
    elif isinstance(dst_crs, int): dst_crs = rio.crs.CRS.from_epsg(dst_crs)
    
    # ---- Loading netcdf
    if isinstance(file, str):
        if os.path.splitext(file)[-1].casefold() in ['.tif', '.tiff']:
            with xr.open_dataset(file) as ds:
                ds.load() # to unlock the resource
            ds = ds.squeeze('band')
            ds = ds.drop('band')
            if main_var:
                ds = ds.rename(dict(band_data = main_var))
            
        elif os.path.splitext(file)[-1].casefold() == '.nc':
            try:
                with xr.open_dataset(file, decode_coords = 'all') as ds:
                    ds.load() # to unlock the resource
                    
            except ValueError: 
                # Usually this error appears when unable to decode 
                # time units 'Months since 1901-01-01' with 
                # "calendar 'proleptic_gregorian'"
                logging.warning("Unable to decode time units.")
                with xr.open_dataset(file, decode_coords = 'all', 
                                     decode_times = False) as ds:
                    ds.load()
                    
                try: ds.time.attrs['units']
                except: 
                    logging.error("No information on time units in attributes.")
                    return
                # Build back time scale:
                logging.debug(f"Time axis will be inferred from 'time' attributes: \"{ds.time.attrs['units']}\"...")
                timeunit = ds.time.attrs['units'].split()[0].casefold()
                if timeunit in ['month', 'months', 'mois']:
                    freq = 'MS'
                    freq_info = 'monthly'
                elif timeunit in ['day', 'days', 'jour', 'jours']:
                    freq = '1D'
                    freq_info = 'daily'
                
                logging.info("   | Note that The format of the origin date is expected to be either")
                logging.info("   | YYYY MM DD or DD MM YYYY (with any separator). The american format")
                logging.info("   | MM DD YYYY will not be considered.")
                # The format of the origin date is expected to be either 
                # YYYY MM DD or DD MM YYYY (with any separator)
                # The american format MM DD YYYY is not considered
                initdate_pattern = re.compile(r"\d{2,4}.*\d{2,4}")
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
                logging.debug(f"Time axis from {date_index[0]} to {date_index[-1]} ({freq_info}).")
                ds['time'] = date_index  
        
        else:
            logging.error(f"Extension {os.path.splitext(file)[-1]} is not recognized by xarray.")
            return
    
    elif isinstance(file, xr.core.dataset.Dataset):
        ds = file
    
    
    # ---- Reprojection
    # Add Coordinate Reference System if needed
    if not src_crs:
        if 'spatial_ref' not in list(ds.coords):
            ds.rio.write_crs(src_crs, inplace = True)
            logging.debug(f"The CRS of input data has been set to '{ds.rio.crs.to_string()}'.")
    else:
        if not ds.rio.crs.is_valid:
            ds.rio.write_crs(src_crs, inplace = True)
        logging.debug(f"The CRS of input data has been set to '{ds.rio.crs.to_string()}'.")
    
    data_transform = ds.rio.transform()
    
    # if (crs_proj and (str(data_crs) != crs_proj)) or (base_profile and (data_profile != base_profile)):    
    if base_profile:
        # CRS initialization
        if dst_crs and not base_profile['crs'].is_valid:
            base_profile['crs'] = dst_crs
                
        if (data_transform != base_profile['transform']) | (ds.rio.crs != base_profile['crs']):
            if not ds.rio.crs.is_valid:
                logging.error('Source CRS (src_crs) is required to reproject.')
                return
            if not base_profile['crs'].is_valid:
                logging.error('Destination CRS (dst_crs) is required to reproject.')
                return
            ds_reprj = ds.rio.reproject(dst_crs = base_profile['crs'],
                                             # resolution = (1000, 1000),
                                             transform = base_profile['transform'],
                                             shape = (base_profile['height'], base_profile['width']),
                                             nodata = np.nan,
                                             resampling = rasterio.enums.Resampling(1), # (0), (5)
                                             )
            ds = ds_reprj
            
    # ---- Format spatial attributes for compatibility with QGIS
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
    
    return ds #, src_crs, dst_crs, nodata

        
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

def hydrological_mean(data, accuracy=15):
    """
    Compute the mean value on the longest period that meets the following
    conditions:
        - period should be made of full years (period is a year-multiple)
        - period should be larger than one year
        - end date of the period should be same day and month as the first date
        of the period, more or less the accuracy

    Parameters
    ----------
    data : pandas.core.series.Series or pandas.core.frame.DataFrame
        DESCRIPTION.
    accuracy : number, optional
        DESCRIPTION. The default is 15.

    Returns
    -------
    avg : float or pandas.core.series.Series
        The average value.

    """
    
    #% Get rid of the first and last value (there are great chances that
    # they are irrelevant, especially in resampled data sets)
    data = data[1:-1]
    
    #% Format the index to Timestamp, if needed
    if isinstance(data.index[0], numbers.Number):
        data.index = data['time']
    if isinstance(data.index[0], str):
        data.index = pd.to_datetime(data.index)
    # Safeguard
    if not isinstance(data.index[0], datetime.datetime):
        logging.error("Error: No recognized time index in data")
        return
    
    #% Get the most recent date that falls within the accuracy range
    idx = data[data.index.month == data.index[0].month][
            abs(data[data.index.month == data.index[0].month].index.day - \
                data.index[0].day)-3 <= 0].index[-1]

    # n_years = np.mean((data.index[-1]-data.index[0])/365.2425)
    
    if (idx - data.index[0]).days < 350:
        logging.warning("HydrologicalMean Warning: Total time range is too short (less than 1 year)")
        logging.warning("    Simple mean is used instead")
    
    logging.debug(f"Average values are computed from {data.index[0].strftime('%Y-%m-%d')} to {idx.strftime('%Y-%m-%d')}")

    avg = data[data.index[0]:idx].mean(numeric_only = False)

    return avg


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

def export_tif(base_dem_path, data_to_tif, data_tif_path, 
               data_nodata_val=None, data_crs=None):
    """
    Export tif from 2D matrix data following raster reference.

    Parameters
    ----------
    base_dem_path : str
        Path of raster reference.
    data_to_tif : 2D matrix
        Data to export in raster..
    data_tif_path : TYPE
        Output path of the exported raster.
    data_nodata_val : float, optional
        To replace base nodata value.
    data_crs : str or int or CRS, optional
        To replace base Coordinates Reference System
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
    if data_nodata_val is not None:
        ras_meta['nodata'] = data_nodata_val
    if data_crs is not None:
        if isinstance(data_crs, str): 
            ras_meta['crs'] = rio.crs.CRS.from_string(data_crs)
        elif isinstance(data_crs, int): 
            ras_meta['crs'] = rio.crs.CRS.from_epsg(data_crs)
        else:
            ras_meta['crs'] = data_crs
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

class LogManager:
    """
    A class to configure and manage logging for the application.
    """

    def __init__(self, mode="verbose", log_dir="logs", overwrite=True, verbose_libraries=False):
        """
        Initialize the LogManager.

        Parameters
        ----------
        mode : str, optional
            Logging mode, "dev" or "user". Default is "user".
            - "dev": Logs all messages (DEBUG and above) to both console and file.
            - "verbose": Logs INFO and above messages to both console and file.
            - "quiet": Logs WARNING and above messages to both console and file.
        log_dir : str, optional
            Directory where log files will be saved. Default is "logs".
        overwrite : bool, optional
            Whether to overwrite existing log files. Default is True.
        verbose_libraries : bool, optional
            If True, library logs are set to WARNING; otherwise, they are set to CRITICAL.
        """
        
        self.mode = mode
        self.log_dir = log_dir
        self.overwrite = overwrite
        self.verbose_libraries = verbose_libraries
        self.logger = logging.getLogger()

        # Validate mode
        if self.mode not in ["dev", "verbose", "quiet"]:
            raise ValueError("Invalid mode. Use 'dev', 'verbose' or 'quiet'.")

        self._setup_logging()
        self._suppress_library_logs()

    def _setup_logging(self):
        """
        Configure the logging settings based on the mode.
        """
        # Ensure the log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

        # Remove existing handlers to prevent duplicates
        # This is necessary when the LogManager is re-initialized (e.g., in a Jupyter notebook or Spyder)
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # Define log file paths
        log_file = os.path.join(self.log_dir, "dev.log")

        # Set the base logger level
        self.logger.setLevel(logging.DEBUG)

        # Create formatters
        detailed_formatter_file = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s")
        detailed_formatter_console = logging.Formatter("[%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s")
        simple_formatter_console = logging.Formatter("[%(levelname)s] %(message)s")

        # Determine file mode based on overwrite parameter
        file_mode = 'w' if self.overwrite else 'a'

        if self.mode == "dev":
            # Console handler for dev mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(detailed_formatter_console)
            self.logger.addHandler(console_handler)
            
        elif self.mode == "verbose":
            # Console handler for verbose mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(simple_formatter_console)
            self.logger.addHandler(console_handler)
            
        elif self.mode == "quiet":
            # Console handler for quiet mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(simple_formatter_console)
            self.logger.addHandler(console_handler)

        # File handler for logs (DEBUG and above)
        # This handler is used in all modes (allows verbose and quiet mode to easily share debug logs)
        dev_file_handler = logging.FileHandler(log_file, mode=file_mode, encoding='utf-8')
        dev_file_handler.setLevel(logging.DEBUG)
        dev_file_handler.setFormatter(detailed_formatter_file)
        self.logger.addHandler(dev_file_handler)

    def _suppress_library_logs(self):
        """
        Suppress logs from third-party libraries while keeping custom logs visible.
        """
        libraries_to_silence = [
            "fiona",
            "rasterio",
            "urllib3",
            "geopy",
            "matplotlib",
            "PIL",
        ]

        level = logging.WARNING if self.verbose_libraries else logging.CRITICAL

        for library in libraries_to_silence:
            logging.getLogger(library).setLevel(level)

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
