# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import numbers
import datetime
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
import rasterio as rio
import rasterio.features # necessary to avoid a bug
from rasterio.warp import calculate_default_transform, reproject
import geopandas as gpd
from shapely.geometry import Point
import xarray as xr
xr.set_options(keep_attrs = True)
# import rioxarray as rio #Not necessary, the rio module from xarray is enough
from pyproj import CRS
from pyproj import Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
import pandas as pd
import numpy as np
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from .log_manager import get_logger

logger = get_logger(__name__)

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
        except Exception as exc:
            logger.error(
                "Failed to read coordinate CSV %s; expected columns 'id;x;y'",
                file,
            )
            logger.debug("Coordinate CSV parsing error: %s", exc)

    if file_vect is not None: # shapefile
        if base_profile:
            # CRS initialization
            if not file_vect.crs: # if not file_vect.crs.is_geographic nor file_vect.crs.is_projected:
                if src_crs:
                    file_vect.set_crs(crs = src_crs, inplace = True, allow_override = True)
                else:
                    logger.error("Source CRS (src_crs) required to rasterize vector dataset")
                    return

            if not base_profile['crs'].is_valid:
                if dst_crs: base_profile['crs'] = dst_crs
                else:
                    logger.error("Destination CRS (dst_crs) required to rasterize vector dataset")
                    return

            # The vector needs to be in the same CRS as the base raster:
            logger.info(f"Before rasterization, the vector will be converted from 'EPSG:{file_vect.crs.to_epsg()}' into 'EPSG:{base_profile['crs'].to_epsg()}'.")
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
            logger.error("Raster profile required to rasterize vector dataset; provide base raster or profile")
            return

    else: # input file is a raster
        with rio.open(file, 'r') as data:
            data_profile = data.profile
            if src_crs and not data_profile['crs'].is_valid:
                data_profile['crs'] = src_crs
                # print(f"The CRS of input data has been set to 'EPSG:{data_profile['crs'].to_epsg()}'.\n")
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
                logger.error("Source CRS (src_crs) required to reproject raster dataset")
                return
            if not base_profile['crs'].is_valid:
                logger.error("Destination CRS (dst_crs) required to reproject raster dataset")
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
            ds = ds.drop_vars('band')
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
                logger.warning("Unable to decode NetCDF time units; falling back to manual parsing")
                with xr.open_dataset(file, decode_coords = 'all',
                                     decode_times = False) as ds:
                    ds.load()

                try: ds.time.attrs['units']
                except:
                    logger.error("No time unit metadata found in NetCDF dataset")
                    return
                # Build back time scale:
                # print(f"Time axis will be inferred from 'time' attributes: \"{ds.time.attrs['units']}\"...")
                timeunit = ds.time.attrs['units'].split()[0].casefold()
                if timeunit in ['month', 'months', 'mois']:
                    freq = 'MS'
                    freq_info = 'monthly'
                elif timeunit in ['day', 'days', 'jour', 'jours']:
                    freq = '1D'
                    freq_info = 'daily'

                logger.info(
                    "Expecting origin date formatted as YYYY MM DD or DD MM YYYY when rebuilding time axis"
                )
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
                # print(f"Time axis from {date_index[0]} to {date_index[-1]} ({freq_info}).\n")
                ds['time'] = date_index

        else:
            logger.error("File extension %s not supported for xarray loading", os.path.splitext(file)[-1])
            return

    elif isinstance(file, xr.core.dataset.Dataset):
        ds = file


    # ---- Reprojection
    # Helper function to check if a CRS is invalid
    def _is_crs_invalid(crs):
        if crs is None:
            return True
        crs_str = str(crs)
        invalid_patterns = ['EngineeringCRS', 'Unknown engineering datum',
                          'LOCAL_CS', 'UNIT["unknown"', 'unnamed']
        if any(p in crs_str for p in invalid_patterns):
            return True
        try:
            return crs.to_dict().get('type') == 'EngineeringCRS'
        except:
            return False

    # Apply source CRS if provided and needed
    if src_crs:
        current_crs = ds.rio.crs
        if _is_crs_invalid(current_crs) or 'spatial_ref' not in ds.coords:
            if 'spatial_ref' in ds.coords:
                ds = ds.drop_vars('spatial_ref')
            ds.rio.write_crs(src_crs, inplace = True)

    data_transform = ds.rio.transform()

    # Reproject to match base profile if provided
    if base_profile:
        # Fix base CRS if invalid
        if dst_crs and _is_crs_invalid(base_profile['crs']):
            base_profile['crs'] = dst_crs

        # Reproject if geometry or CRS differ
        if (data_transform != base_profile['transform']) | (ds.rio.crs != base_profile['crs']):
            if _is_crs_invalid(ds.rio.crs):
                logger.error("Source CRS (src_crs) required to reproject xarray dataset")
                return
            if _is_crs_invalid(base_profile['crs']):
                logger.error("Destination CRS (dst_crs) required to reproject xarray dataset")
                return
            ds = ds.rio.reproject(dst_crs = base_profile['crs'],
                                 transform = base_profile['transform'],
                                 shape = (base_profile['height'], base_profile['width']),
                                 nodata = np.nan,
                                 resampling = rasterio.enums.Resampling(1))

    # Or reproject to dst_crs if specified without base
    elif dst_crs is not None:
        if _is_crs_invalid(ds.rio.crs):
            logger.error("Source CRS (src_crs) required to reproject - current CRS is invalid: %s", ds.rio.crs)
            return
        ds = ds.rio.reproject(dst_crs = dst_crs)

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

def rmse_manual(sim, obs):
    """Root Mean Square Error (RMSE)."""
    return np.sqrt(np.mean((sim - obs) ** 2))

def nse_manual(sim, obs, transform=None):
    """Nash–Sutcliffe Efficiency (optionally on log‑transformed Q)."""
    if transform == 'log':
        eps = 1e-6
        sim, obs = np.log(sim + eps), np.log(obs + eps)
    num = np.sum((obs - sim) ** 2)
    den = np.sum((obs - np.mean(obs)) ** 2)
    return 1 - num/den

def mare_manual(sim, obs):
    """Mean Absolute Relative Error (MARE)."""
    return np.mean(np.abs(sim - obs) / obs)

def kge_manual(sim, obs):
    """Kling–Gupta Efficiency and its three components (r, α, β)."""
    # Pearson r
    r = np.corrcoef(sim, obs)[0,1]
    # spread ratio α
    alpha = np.std(sim) / np.std(obs)
    # bias ratio β (sum‑based, same as mean‑based)
    beta = np.sum(sim) / np.sum(obs)
    kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
    return kge, r, alpha, beta

def efficiency_criteria(sim, obs):
    """
    Compute [RMSE, nRMSE, NSE, NSElog, BAL, MARE, KGE] on two 1D arrays,
    doing pair‑wise deletion of NaNs in obs.
    """
    # flatten and mask out any NaN in obs
    sim = np.asarray(sim).ravel()
    obs = np.asarray(obs).ravel()
    mask = ~np.isnan(obs)
    sim, obs = sim[mask], obs[mask]

    # now all metrics on equal‑length vectors
    rmse = rmse_manual(sim, obs)
    nrmse = rmse / np.mean(obs)
    nse   = nse_manual(sim, obs)
    nselog= nse_manual(sim, obs, transform='log')
    bal   = np.sum(sim) / np.sum(obs)
    mare  = mare_manual(sim, obs)
    kge   = kge_manual(sim, obs)[0]

    return rmse, nrmse, nse, nselog, bal, mare, kge

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
        logger.error("No recognized datetime index in input series for hydrological_mean")
        return

    #% Get the most recent date that falls within the accuracy range
    idx = data[data.index.month == data.index[0].month][
            abs(data[data.index.month == data.index[0].month].index.day - \
                data.index[0].day)-3 <= 0].index[-1]

    # n_years = np.mean((data.index[-1]-data.index[0])/365.2425)

    if (idx - data.index[0]).days < 350:
        logger.warning("Time range shorter than one year; using simple mean instead of hydrological mean")

    # print(f"Average values are computed from {data.index[0].strftime('%Y-%m-%d')} to {idx.strftime('%Y-%m-%d')}")

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
    with rio.open(raw_dem_path) as src:
        dst_crs = rio.crs.CRS.from_epsg(4326)
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({
            'crs': dst_crs,
            'transform': transform,
            'width': width,
            'height': height
        })
        with rio.open(wgs_dem_path, 'w', **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rio.band(src, band),
                    destination=rio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=rio.enums.Resampling.bilinear
                )

    with rio.open(wgs_dem_path) as wgs_dem:
        wgs_dem_data = wgs_dem.read(1)
        geodata = wgs_dem.transform.to_gdal()
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
        utm_crs_list = query_utm_crs_info(
            datum_name="WGS 84",
            area_of_interest=AreaOfInterest(
                west_lon_degree=lon,
                south_lat_degree=lat,
                east_lon_degree=lon,
                north_lat_degree=lat,
            ),
        )
        utm_crs = CRS.from_epsg(utm_crs_list[0].code).srs

        dst_crs = rio.crs.CRS.from_string(utm_crs)
        transform, width, height = calculate_default_transform(
            wgs_dem.crs, dst_crs, wgs_dem.width, wgs_dem.height, *wgs_dem.bounds
        )
        kwargs = wgs_dem.meta.copy()
        kwargs.update({
            'crs': dst_crs,
            'transform': transform,
            'width': width,
            'height': height
        })
        with rio.open(utm_dem_path, 'w', **kwargs) as dst:
            for band in range(1, wgs_dem.count + 1):
                reproject(
                    source=rio.band(wgs_dem, band),
                    destination=rio.band(dst, band),
                    src_transform=wgs_dem.transform,
                    src_crs=wgs_dem.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=rio.enums.Resampling.bilinear
                )
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

#%% PYHELP HELPER FUNCTIONS (migrated from pyhelp/helper.py)

def load_csv(file_path: str) -> pd.DataFrame:
    """
    Load a CSV file into a dataframe.
    """
    try:
        return pd.read_csv(file_path)
    except Exception as e:
        logger.exception("Failed to load CSV file %s", file_path)
        return pd.DataFrame()

def load_shapefile(shapefile_path: str) -> gpd.GeoDataFrame:
    """
    Load a shapefile into a GeoDataFrame.

    Return a geodataframe containing the shapefile geometry
    """
    try:
        return gpd.read_file(shapefile_path)
    except Exception as e:
        logger.exception("Failed to load shapefile %s", shapefile_path)
        return None

def get_centroid_coordinates(gdf: gpd.GeoDataFrame) -> tuple:
    """
    Calculate the centroid of the geometry contained in the given geodataframe file.

    Return --> (float, float)
    tuple (longitude, latitude) of the centroid
    """
    if gdf is None:
        logger.error("GeoDataFrame input is None")
        return None, None

    if gdf.empty:
        logger.error("GeoDataFrame contains no features")
        return None, None

    if gdf.crs is None:
        logger.error("GeoDataFrame has no CRS defined")
        return None, None

    try:
        gdf = gdf.to_crs("EPSG:2056")
        gdf["geometry"] = gdf.geometry.centroid
        gdf = gdf.to_crs("EPSG:4326")
        point = gdf.geometry.iloc[0]
        return point.x, point.y
    except Exception as e:
        logger.exception("Failed computing centroid coordinates")
        return None, None

def transform_coordinates(dem_file_path: str, from_crs: str, to_crs: str) -> list:
    """
    Read a DEM file, iterate through its pixels and
    convert the coordinates from  a crs to another

    return --> list of (float, float)
    list of tuples (longitude, latitude)
    """
    try:
        dem_dataset = rio.open(dem_file_path)
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
        logger.exception("Failed processing DEM raster %s", dem_file_path)
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
        logger.exception("Failed filtering coordinates with shapefile %s", shapefile_path)
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
        logger.exception("Failed selecting dataset points within polygon")
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

#%% DISPLAY

_banner_printed = False


def print_hydromodpy():
    global _banner_printed
    if _banner_printed:
        return
    banner_lines = [
        r'      __  __          __           __  ____          ________     ',
        r'     / / / /         / /          /  \/   /         / / __  /     ',
        r'    / /_/ /_  ______/ /________  /       /___  ____/ / /_/ /_  __ ',
        r'   / __  / / / / __  / ___/ __ \/ /\,-/ / __ \/ __  / ____/ / / / ',
        r'  / / / / /_/ / /_/ / /  / /_/ / /   / / /_/ / /_/ / /   / /_/ /  ',
        r' /_/ /_/\__, /_____/_/   \____/_/   /_/\____/_____/_/____\__, /   ',
        r'       /____/ Hydrological Modelling in Python /_____________/    ',
        r'                                                                  ',
    ]
    for line in banner_lines:
        logger.info(line)
    _banner_printed = True

#%% NOTES
