# -*- coding: utf-8 -*-
"""
Created on Thu 16 Dec 2021

@author: Alexandre Kenshilik Coche
@contact: alexandre.co@hotmail.fr

This module is a collection of tools for manipulating hydrological space-time
data, especially netcdf data. It has been originally developped to provide
preprocessing tools for CWatM (https://cwatm.iiasa.ac.at/) and HydroModPy
(https://gitlab.com/Alex-Gauvain/HydroModPy), but most functions have been
designed to be of general use.

"""

#%% Imports:
import xarray as xr
xr.set_options(keep_attrs = True)
import rioxarray as rio #Not necessary, the rio module from xarray is enough
import pandas as pd
import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
from affine import Affine
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry import mapping
import os
import re
import sys
import gc # garbage collector
import pathlib
from osgeo import gdal
from osgeo import osr
from osgeo import ogr
from osgeo import gdalconst
import matplotlib.pyplot as plt
import fiona
import datetime
import math

import matplotlib.pyplot as plt
from pysheds.grid import Grid  # to compute river network

# import whitebox
# wbt = whitebox.WhiteboxTools()
# wbt.verbose = False

#%% LEGENDE: 
# ---- ° = à garder mais mettre à jour
# ---- * = à inclure dans une autre fonction ou supprimer


#%% LOADING & INITIALIZING DATASETS
###############################################################################
def rename_time(data_ds):
    """
    Standardize the name of the temporal coordinate.

    Parameters
    ----------
    data_ds : xarray.dataset
        Dataset whose temporal coordinate should be renamed.

    Returns
    -------
    data_ds : xarray.dataset
        Dataset with the modified name for the temporal coordinate.

    """
    if ('valid_time' in data_ds.coords) | ('valid_time' in data_ds.data_vars):
        data_ds = data_ds.rename({'valid_time': 'time'})
        
    return data_ds


###############################################################################
def load_any(data, name=None, infer_time=False, **xr_kwargs):
             # decode_times=True, decode_cf=True, decode_coords='all'):
    r"""
    This function loads any common spatio-temporal file or variable, without
    the need to think about the file or variable type.
    
    import geoconvert as gc
    data_ds = gc.load_any(r'D:\data.nc', decode_times = True, decode_coords = 'all')

    Parameters
    ----------
    data : TYPE
        DESCRIPTION.
    name : TYPE, optional
        DESCRIPTION. The default is None.
    **xr_kwargs: keyword args
        Argument passed to the xarray.open_dataset function call.
        May contain: 
            . decode_coords
            . decode_times
            . decode_cf
            > help(xr.open_dataset

    Returns
    -------
    data_ds : TYPE
        DESCRIPTION.

    """
    
    # data is a variable
    if isinstance(data, xr.Dataset):
        data_ds = data.copy()
        # Rename time coord
        data_ds = rename_time(data_ds)
    
    elif isinstance(data, xr.DataArray):
        if name is None:
            name = input('Name of main variable: ')
        data_ds = data.to_dataset(name = name, promote_attrs = True)
        # Rename time coord
        data_ds = rename_time(data_ds)
    
    elif isinstance(data, gpd.GeoDataFrame):
        data_ds = data.copy()
    
    # data is a string/path
    elif isinstance(data, (str, pathlib.Path)):
        print("\nLoading data...")
        if not os.path.isfile(data):
            print("   Err: the path provided is not a file")
            return
        
        if os.path.splitext(data)[-1] == '.shp':
            data_ds = gpd.read_file(data)
        
        elif os.path.splitext(data)[-1] == '.nc':
            try:
                with xr.open_dataset(data, **xr_kwargs) as data_ds:
                    data_ds.load() # to unlock the resource
                    # Rename time coord
                    data_ds = rename_time(data_ds)
            except:
                xr_kwargs['decode_times'] = False
                if not infer_time:
                    print("   _ decode_times = False")
                try:
                    with xr.open_dataset(data, **xr_kwargs) as data_ds:
                        data_ds.load() # to unlock the resource
                
                except:
                    xr_kwargs['decode_coords'] = False
                    print("   _ decode_coords = False")
                    with xr.open_dataset(data, **xr_kwargs) as data_ds:
                        data_ds.load() # to unlock the resource
                
                # Rename time coord
                data_ds = rename_time(data_ds)        
                
                if infer_time:
                    print("   _ inferring time axis...")
                    units, reference_date = data_ds.time.attrs['units'].split('since')
                    if units.replace(' ', '').casefold() in ['month', 'months', 'M']: 
                        freq = 'M'
                    elif units.replace(' ', '').casefold() in ['day', 'days', 'D']:
                        freq = 'D'
                    start_date = pd.date_range(start = reference_date, 
                                               periods = int(data_ds.time[0].values)+1, 
                                               freq = freq) 
                    try:
                        data_ds['time'] = pd.date_range(start = start_date[-1], 
                                                        periods = data_ds.sizes['time'], 
                                                        freq = freq)
                    except: # SPECIAL CASE to handle truncated output files from failed CWatM simulations
                        data_ds = data_ds.where(data_ds['time']<1e5, drop = True)
                        data_ds['time'] = pd.date_range(start = start_date[-1], 
                                                        periods = data_ds.sizes['time'], 
                                                        freq = freq)
                        
                    print(f"     . initial time = {data_ds.time[0].values.strftime('%Y-%m-%d')} | final time = {data_ds.time[-1].values.strftime('%Y-%m-%d')} | units = {units}")
                    

        elif os.path.splitext(data)[-1] in ['.tif', '.asc']:
            xr_kwargs['decode_coords'] = None
            with xr.open_dataset(data, **xr_kwargs) as data_ds:
                data_ds.load() # to unlock the resource   
            
            # Rename time coord
            data_ds = rename_time(data_ds)
            
            if name is None:
                name = input('Name of main variable: ')
            data_ds = data_ds.squeeze('band')
            data_ds = data_ds.drop('band')
            data_ds = data_ds.rename(band_data = name)
    
    # Return
    return data_ds


###############################################################################
def main_var(data_ds):
    var = list(set(list(data_ds.data_vars)) - set(['x', 'y', 'X','Y', 'i', 'j',
                                                   'lat', 'lon', 
                                                   'spatial_ref', 
                                                   'LambertParisII',
                                                   'bnds', 'time_bnds',
                                                   'valid_time']))
    if len(var) == 1:
        var = var[0]
    
    return var


###############################################################################
def get_filelist(data, filetype = '.nc'):
    """
    This function converts a folder (or a file) in a list of relevant files.

    Parameters
    ----------
    data: str or iterable
        Folder, filepath or iterable of filepaths
    filetype: str
        Extension.

    Returns
    -------
    data_folder : str
        Root of the files.
    filelist : list of str
        List of files.

    """
    
    # ---- Data is a single element
    
    # if data is a single string/path
    if isinstance(data,  (str, pathlib.Path)): 
        # if this string points to a folder
        if os.path.isdir(data): 
            data_folder = data    
            filelist = [f for f in os.listdir(data_folder)
                             if (os.path.isfile(os.path.join(data_folder, f)) \
                                 & (os.path.splitext(os.path.join(data_folder, f))[-1] == filetype))]
            
        # if this string points to a file
        else: 
            data_folder = os.path.split(data)[0]    # root of the file 
            filelist = [data]
    
    # ---- Data is an iterable
    elif isinstance(data, (list, tuple)):
        # [Safeguard] It is assumed that data contains an iterable of files
        if not os.path.isfile(data[0]):
            print("Err: Argument should be a folder, a filepath or a list of filepath")
            return
        
        data_folder = os.path.split(data[0])[0] # root of the first element of the list
        filelist = list(data)
        
        
    return data_folder, filelist 


###############################################################################
#%%% ° pick_dates_fields
def pick_dates_fields(*, input_file, output_format = 'NetCDF', **kwargs):
    """
    % DESCRIPTION:
    This function extracts the specified dates or fields from NetCDF files that
    contain multiple dates or fields, and exports it as a single file.
    
    
    % EXAMPLE:
    import geoconvert as gc
    gc.pick_dates_fields(input_file = r"D:/path/test.nc", 
                  dates = ['2020-10-15', '2021-10-15'])

    % OPTIONAL ARGUMENTS:
    > output_format = 'NetCDF' (default) | 'GeoTIFF'
    > kwargs:
        > dates = ['2021-10-15', '2021-10-19']
        > fields = ['T2M', 'PRECIP', ...]
    """    
    
    with xr.open_dataset(input_file) as _dataset:
        _dataset.load() # to unlock the resource
    
    #% Get arguments (and build output_name):
    # ---------------------------------------
    _basename = os.path.splitext(input_file)[0]
    
    # Get fields:
    if 'fields' in kwargs:
        fields = kwargs['fields']
        if isinstance(fields, str): fields = [fields]
        else: fields = list(fields) # in case fields are string or tuple
    else:
        fields = list(_dataset.data_vars) # if not input_arg, fields = all
    
    # Get dates:
    if 'dates' in kwargs:
        dates = kwargs['dates']
        if isinstance(dates, str): 
            output_file = '_'.join([_basename, dates, '_'.join(fields)])
            dates = [dates]
        else: 
            dates = list(dates) # in case dates are tuple
            output_file = '_'.join([_basename, dates[0], 'to', 
                                    dates[-1], '_'.join(fields)])

    else:
        dates = ['alldates'] # if not input_arg, dates = all  
        output_file = '_'.join([_basename, '_'.join(fields)])
        
    
    #% Standardize terms:
    # -------------------
    if 't' in list(_dataset.dims):
        print('Renaming time coordinate')
        _dataset = _dataset.rename(t = 'time')    

    if 'lon' in list(_dataset.dims) or 'lat' in list(_dataset.dims):
        print('Renaming lat/lon coordinates')
        _dataset = _dataset.rename(lat = 'latitude', lon = 'longitude')
        # Change the order of coordinates to match QGIS standards:
        _dataset = _dataset.transpose('time', 'latitude', 'longitude')
        # Insert georeferencing metadata to match QGIS standards:
        _dataset.rio.write_crs("epsg:4326", inplace = True)
        # Insert metadata to match Panoply standards: 
        _dataset.longitude.attrs = {'units': 'degrees_east',
                                    'long_name': 'longitude'}
        _dataset.latitude.attrs = {'units': 'degrees_north',
                                    'long_name': 'latitude'}
    
    if 'X' in list(_dataset.dims) or 'Y' in list(_dataset.dims):
        print('Renaming X/Y coordinates')
        _dataset = _dataset.rename(X = 'x', Y = 'y')
        # Change the order of coordinates to match QGIS standards:
        _dataset = _dataset.transpose('time', 'y', 'x')
        # Insert metadata to match Panoply standards: 
        _dataset.x.attrs = {'standard_name': 'projection_x_coordinate',
                            'long_name': 'x coordinate of projection',
                            'units': 'Meter'}
        _dataset.y.attrs = {'standard_name': 'projection_y_coordinate',
                            'long_name': 'y coordinate of projection',
                            'units': 'Meter'}

        
# =============================================================================
#     # Rename coordinates (ancienne version):
#     try:
#         _dataset.longitude
#     except AttributeError:
#         _dataset = _dataset.rename({'lon':'longitude'})
#     try:
#         _dataset.latitude
#     except AttributeError:
#         _dataset = _dataset.rename({'lat':'latitude'})    
#     try:
#         _dataset.time
#     except AttributeError:
#         _dataset = _dataset.rename({'t':'time'}) 
# =============================================================================
    
    #% Extraction and export:
    # -----------------------
    # Extraction of fields:
    _datasubset = _dataset[fields]
    # Extraction of dates:
    if dates != 'alldates':
        _datasubset = _datasubset.sel(time = dates)

    if output_format == 'NetCDF':
        _datasubset.attrs = {'Conventions': 'CF-1.6'} # I am not sure...
        
        # Export:
        _datasubset.to_netcdf(output_file + '.nc')
    
    elif output_format == 'GeoTIFF':
        _datasubset.rio.to_raster(output_file + '.tiff')
        
        
#%% GEOREFERENCING
###############################################################################
# Georef (ex-decorate_NetCDF_for_QGIS)
def georef(*, data, data_type = 'other', include_crs = True, export_opt = False, crs = None):   
    r"""
    Description
    -----------
    Il est fréquent que les données de source externe présentent des défauts
    de formattage (SCR non inclus, coordonnées non standard, incompatibilité
    avec QGIS...).
    Cette fonction permet de générer un raster ou shapefile standardisé, 
    en particulier du point de vue de ses métadonnées, facilitant ainsi les
    opérations de géotraitement mais aussi la visualisation sous QGIS.
    
    Exemple
    -------
    import geoconvert as gc
    gc.georef(data = r"D:\CWatM\raw_results\test1\modflow_watertable_monthavg.nc", 
              data_type = 'CWatM')
    
    Parametres
    ----------
    data : str or xr.Dataset (or xr.DataArray)
        Chemin d'accès au fichier à modifier
        (le fichier original ne sera pas altéré, un nouveau fichier '(...)_QGIS.nc'
         sera créé.)
    data_type : str
        Type de données :
            'modflow' | 'DRIAS-Climat 2020' | 'DRIAS-Eau 2021' \ 'SIM 2021' |
            'DRIAS-Climat 2022' \ 'Climat 2022' | 'DRIAS-Eau 2024' \ 'SIM 2024' |
            'CWatM' | 'autre' \ 'other'
            (case insensitive)
    include_crs : bool, optional
        DESCRIPTION. The default is True.
    export_opt : bool, optional
        DESCRIPTION. The default is True.
        Le NetCDF crée est directement enregistré dans le même dossier que 
        le fichier d'origine, en rajoutant 'georef' à son nom.
    crs : int, optional
        Destination CRS, only necessary when data_type == 'other' The default is None.

    Returns
    -------
    xarray.Dataset or geopandas.GeoDataFrame. 
    
    """
    
    # ---- NetCDF de ModFlow
    # --------------------
    if data_type.casefold() == 'modflow': 
        # Load
        data_ds = load_any(data, decode_coords = 'all', decode_times = False)
        
        print("\nFormatting data...")
        # Add standard attributes for coordinates (mandatory for QGIS to correctly read data)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                            'long_name': 'x coordinate of projection',
                            'units': 'Meter'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                            'long_name': 'y coordinate of projection',
                            'units': 'Meter'}
        print("   _ Standard attributes added for coordinates x and y")
        
        # Add CRS
        data_epsg = 2154 # Lambert 93
        crs_suffix = ''
        if include_crs:
            data_ds.rio.write_crs(data_epsg, inplace = True)
            print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included.')
        else:
            print(f'   _ Coordinates Reference System not included. {data_epsg} has to be manually specified in QGIS')
            crs_suffix = 'nocrs'
        
    # ========== USELESS ==========================================================
    #     data_ds = data_ds.transpose('time', 'y', 'x')
    # =============================================================================


    # ---- NetCDF de CWatM
    # Inclusion du SCR
    # ------------------
    elif data_type.casefold() == 'cwatm'.casefold():
        # Load
        data_ds = load_any(data, decode_coords = 'all', decode_times = False)
        
        print("\nFormatting data...")
        # Add CRS
        data_epsg = 2154 # Lambert 93
        crs_suffix = ''
        if include_crs:
            data_ds.rio.write_crs(data_epsg, inplace = True)
            print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included.')
        else:
            print(f'   _ Coordinates Reference System not included. {data_epsg} has to be manually specified in QGIS')
            crs_suffix = 'nocrs'
    
    
    # ---- NetCDF de la DRIAS-Climat 2020 et de la DRIAS-Eau 2021
    # Données SAFRAN (tas, prtot, rayonnement, vent... ) "DRIAS-2020"
    # ainsi que : 
    # Données SURFEX (evapc, drainc, runoffc, swe, swi...) "EXPLORE2-SIM2 2021"
    # ------------------------------------------------------------
    if data_type.replace(" ", "").casefold() in ['drias2020', 'drias-climat2020',
                                'sim2021', 'drias-eau2021']:         
        # Load
        data_ds = load_any(decode_coords = 'all')
        
        print("\nFormating data...")
        # Create X and Y coordinates if necessary, from i and j
        list_var_lowcase = [v.casefold() for v in list(data_ds.coords) + list(data_ds.data_vars)]
        if 'x' not in list_var_lowcase:
            data_ds = data_ds.assign_coords(
                X = ('i', 52000 + data_ds.i.values*8000))
            print("   _ X values created from i")
        if 'y' not in list_var_lowcase:
            data_ds = data_ds.assign_coords(
                Y = ('j', 1609000 + data_ds.j.values*8000))
            print("   _ Y values created from j")
        # Replace X and Y as coordinates, and rename them
        data_ds = data_ds.swap_dims(i = 'X', j = 'Y')
        print("   _ Coordinates i and j replaced with X and Y")
        data_ds = data_ds.rename(X = 'x', Y = 'y')
        print("   _ Coordinates renamed as lowcase x and y [optional]")
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        # Ensure that lat, lon, i and j will be further loaded by xarray as coords
        data_ds[var].attrs['coordinates'] = 'x y i j lat lon'
        print("   _ x, y, i, j, lat, lon ensured to be read as coordinates")

# ============== USELESS ======================================================
#         # Reorder data, to ensure QGIS Mesh detects the correct data set   
#         data_ds = data_ds[[var, 'x', 'y', 'time']]
#         print("   _ Data reordered [safety]")
# =============================================================================
# ============== USELESS ======================================================
#         # To avoid conflicts with missing values
#         data_ds[var].encoding.pop('missing_value')
#         data_ds['lat'].encoding.pop('missing_value')
#         # data_ds['lat'].encoding['_FillValue'] = np.nan
#         data_ds['lon'].encoding.pop('missing_value')
#         # data_ds['lon'].encoding['_FillValue'] = np.nan
# =============================================================================
        
        # Add standard attributes for coordinates (mandatory for QGIS to correctly read data)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                            'long_name': 'x coordinate of projection',
                            'units': 'Meter'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                            'long_name': 'y coordinate of projection',
                            'units': 'Meter'}
        print("   _ Standard attributes added for coordinates x and y")
        
        # Add CRS
        data_epsg = 27572 # Lambert zone II
        crs_suffix = ''
        if include_crs:
            data_ds.rio.write_crs(data_epsg, inplace = True)
            print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included. (NB: This might alter Panoply georeferenced vizualisation)')
        else:
            print(f'   _ Coordinates Reference System not included. {data_epsg} has to be manually specified in QGIS')
            crs_suffix = 'nocrs'
         # Incompatibilité QGIS - Panoply :
         # Pour une raison inconnue, l'inclusion du CRS 27572 ("Lambert 
         # Zone II" / "NTF (Paris)" pose problème pour le géo-référencement
         # dans Panoply (c'est comme si Panoply prenait {lat = 0 ; lon = 0} 
         # comme origine de la projection). Sans 'spatial_ref' incluse dans le
         # netCDF, Panoply géo-référence correctement les données, probablement
         # en utilisant directement les variables 'lat' et 'lon'.
      
        
    # ---- NetCDF de la DRIAS-Climat 2022 
    # Données SAFRAN (tas, prtot, rayonnement, vent... ) "EXPLORE2-Climat 2022" 
    # -------------------------------------------------------------------------
    elif data_type.replace(" ", "").casefold() in ['drias2022', 'climat2022', 'drias-climat2022']:
        # Load
        data_ds = load_any(data, decode_cf = False)

        print("\nFormating data...")
        # Correcting the spatial_ref
# =============================================================================
#         data_ds['LambertParisII'] = xr.DataArray(
#             data = np.array(-2147220352.0),
#             coords = {'LambertParisII': -2147220352.0},
#             attrs = {'grid_mapping_name': 'lambert_conformal_conic_1SP',
#                      'latitude_of_origin': 52.0,
#                      'central_meridian': 0.0,
#                      'false_easting': 600000.0,
#                      'false_northing': 2200000.0,
#                      'epsg': 27572,
#                      'references': 'http://www.umr-cnrm.fr/spip.php?article125&lang=en'}) 
#         crs_suffix = 'georef'
# =============================================================================
        data_epsg = 27572 # Lambert zone II
        if include_crs:
            # data_ds = data_ds.drop('LambertParisII')
            # data_ds.rio.write_crs(f'epsg:{data_epsg}', inplace = True)
            data_ds = standard_grid_mapping(data_ds, data_epsg)
            print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included. (NB: This might alter Panoply georeferenced vizualisation)')
            crs_suffix = ''
        else:
            print(f'   _ Coordinates Reference System not included. {data_epsg} has to be manually specified in QGIS')
            crs_suffix = 'nocrs'
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        # Ensure that lat, and lon will be further loaded by xarray as coords
        data_ds[var].encoding['coordinates'] = 'x y lat lon'
        if 'coordinates' in data_ds[var].attrs:
            data_ds[var].attrs.pop('coordinates')
        data_ds.lat.encoding['grid_mapping'] = data_ds[var].encoding['grid_mapping']
        data_ds.lon.encoding['grid_mapping'] = data_ds[var].encoding['grid_mapping']
        print("   _ x, y, lat, lon ensured to be read as coordinates [safety]")
        # Remove grid_mapping in attributes (it is already in encoding)
        if 'grid_mapping' in data_ds[var].attrs:
            data_ds[var].attrs.pop('grid_mapping')
    
    
    # ---- NetCDF de la DRIAS-Eau 2024 
    # Données SURFEX (evapc, drainc, runoffc, swe, swi...) "EXPLORE2-SIM2 2024" 
    # -------------------------------------------------------------------------
    elif data_type.replace(" ", "").replace("-", "").casefold() in [
            'sim2024', 'driaseau2024']: 
        # Load
        data_ds = load_any(data, decode_cf = False)

        print("\nFormating data...")
        # Correcting the spatial_ref
# =============================================================================
#         data_ds['LambertParisII'] = xr.DataArray(
#             data = np.array(-2147220352.0),
#             coords = {'LambertParisII': -2147220352.0},
#             attrs = {'grid_mapping_name': 'lambert_conformal_conic_1SP',
#                      'latitude_of_origin': 52.0,
#                      'central_meridian': 0.0,
#                      'false_easting': 600000.0,
#                      'false_northing': 2200000.0,
#                      'epsg': 27572,
#                      'references': 'http://www.umr-cnrm.fr/spip.php?article125&lang=en'}) 
#         crs_suffix = ''
# =============================================================================
        data_epsg = 27572 # Lambert zone II
        if include_crs:
            # if ('LambertParisII' in data_ds.coords) | ('LambertParisII' in data_ds.data_vars):
            #     data_ds = data_ds.drop('LambertParisII')
            # data_ds.rio.write_crs(data_epsg, inplace = True)
            data_ds = standard_grid_mapping(data_ds, data_epsg)
            print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included. (NB: This might alter Panoply georeferenced vizualisation)')
            crs_suffix = ''
        else:
            print(f'   _ Coordinates Reference System not included. {data_epsg} has to be manually specified in QGIS')
            crs_suffix = 'nocrs'
        
        # Create X and Y coordinates if necessary, from i and j
        list_var_lowcase = [v.casefold() for v in list(data_ds.coords) + list(data_ds.data_vars)]
        data_ds = data_ds.assign_coords(
            X = ('x', 52000 + data_ds.x.values*8000))
        print("   _ X values corrected from erroneous x")
        data_ds = data_ds.assign_coords(
            Y = ('y', 1609000 + data_ds.y.values*8000))
        print("   _ Y values corrected from erroneous y")
        # Replace X and Y as coordinates, and rename them
        data_ds = data_ds.swap_dims(x = 'X', y = 'Y')
        print("   _ Coordinates x and y replaced with X and Y")
        data_ds = data_ds.drop(['x', 'y'])
        print("   _ Previous coordinates x and y removed")
        data_ds = data_ds.rename(X = 'x', Y = 'y')
        print("   _ Coordinates renamed as lowcase x and y [optional]")
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        
        # Ensure that lat, and lon will be further loaded by xarray as coords
        data_ds[var].encoding['coordinates'] = 'x y lat lon'
        if 'coordinates' in data_ds[var].attrs:
            data_ds[var].attrs.pop('coordinates')
        # Reporting grid_mapping to coords/vars that should not be displayed in QGIS:
        for c in ['lat', 'lon']: 
            if (c in data_ds.coords) | (c in data_ds.data_vars):
                data_ds[c].encoding['grid_mapping'] = data_ds[var].encoding['grid_mapping']
        print("   _ x, y, lat, lon ensured to be read as coordinates [safety]")
       # ======== USELESS ============================================================
       #         for c in ['lat', 'lon', 'time_bnds']:
       #             if c in data_ds.data_vars:
       #                 data_ds = data_ds.set_coords([c])
       # =============================================================================
        
       # Remove grid_mapping in attributes (it is already in encoding)
        if 'grid_mapping' in data_ds[var].attrs:
            data_ds[var].attrs.pop('grid_mapping')
        
# ============== USELESS ======================================================
#         # Reorder data, to ensure QGIS Mesh detects the correct data set   
#         data_ds = data_ds[[var, 'x', 'y', 'time']]
#         print("   _ Data reordered [safety]")
# =============================================================================
# ============== USELESS ======================================================
#         # To avoid conflicts with missing values
#         data_ds[var].encoding.pop('missing_value')
#         data_ds['lat'].encoding.pop('missing_value')
#         # data_ds['lat'].encoding['_FillValue'] = np.nan
#         data_ds['lon'].encoding.pop('missing_value')
#         # data_ds['lon'].encoding['_FillValue'] = np.nan
# =============================================================================
        
        # Add standard attributes for coordinates (mandatory for QGIS to correctly read data)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                            'long_name': 'x coordinate of projection',
                            'units': 'metre'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                            'long_name': 'y coordinate of projection',
                            'units': 'metre'}
        print("   _ Standard attributes added for coordintes x and y")


    # ---- Autres fichiers ou variables
    # Inclusion du SCR
    # ------------------
# =============================================================================
#     elif data_type.casefold() in ['autre', 'other']:
# =============================================================================
    else:
        # Load
        data_ds = load_any(data, decode_times = True, decode_coords = 'all')
        
        # Standardize spatial coords
        if 'X' in data_ds.coords:
            data_ds = data_ds.rename({'X': 'x'})
        if 'Y' in data_ds.coords:
            data_ds = data_ds.rename({'Y': 'y'})
        if 'latitude' in data_ds.coords:
            data_ds = data_ds.rename({'latitude': 'lat'})
        if 'longitude' in data_ds.coords:
            data_ds = data_ds.rename({'longitude': 'lon'})
        
        if isinstance(data_ds, gpd.GeoDataFrame):
            print("\nFormatting data...")
            # Add CRS
            crs_suffix = ''
            if include_crs:
                if crs is not None:
                    data_epsg = crs
                else:
                    print("   _ Err: it is required to pass the crs argument")
                    return
                # data_ds.set_crs(epsg = data_epsg, 
                #                  inplace = True, 
                #                  allow_override = True)
                data_ds = standard_grid_mapping(data_ds, data_epsg)
                print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included.')
            else:
                print('   _ Coordinates Reference System not included.')
                crs_suffix = 'nocrs'
        
        elif isinstance(data_ds, xr.Dataset):        
            print("\nFormatting data...")
            # Add CRS
            crs_suffix = ''
            if include_crs:
                if crs is not None:
                    data_epsg = crs
                else:
                    print("   _ Err: it is required to pass the crs argument")
                    return
                data_ds.rio.write_crs(data_epsg, inplace = True)
                print(f'   _ Coordinates Reference System (epsg:{data_epsg}) included.')
            else:
                print('   _ Coordinates Reference System not included.')
                crs_suffix = 'nocrs'
            
            # Add standard attributes for coordinates (mandatory for QGIS to correctly read data)
            if ('x' in list(data_ds.coords)) & ('y' in list(data_ds.coords)):
                data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                                    'long_name': 'x coordinate of projection',
                                    'units': 'metre'}
                data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                                    'long_name': 'y coordinate of projection',
                                    'units': 'metre'}
                print("   _ Standard attributes added for coordinates x and y")
            elif ('lon' in list(data_ds.coords)) & ('lat' in list(data_ds.coords)):
                data_ds.lon.attrs = {'standard_name': 'longitude',
                                     'long_name': 'longitude',
                                     'units': 'degrees_east'}
                data_ds.lat.attrs = {'standard_name': 'latitude',
                                     'long_name': 'latitude',
                                     'units': 'degrees_north'}
                print("   _ Standard attributes added for coordinates lat and lon")


    # ---- Export
    # ---------
    if export_opt == True:
        print('\nExporting...')
        # Output filepath
        if isinstance(data, (str, pathlib.Path)):
            (folder_name, _basename) = os.path.split(data)
            (file_name, file_extension) = os.path.splitext(_basename)
            output_file = os.path.join(folder_name, f"{'_'.join([file_name, 'georef', crs_suffix])}{file_extension}")
        else:
            print("   _ As data input is not a file, the result is exported to a standard directory")
            output_file = os.path.join(os.getcwd(), f"{'_'.join(['data', 'georef', crs_suffix])}.nc")
        
        # Export
        export(data_ds, output_file)
        
        
    # ---- Return variable
    return data_ds


    # =========================================================================
    #%    Mémos / Corrections bugs
    # =========================================================================
    # Si jamais il y a un problème de variable qui se retrouve en 'data_var'
    # au lieu d'etre en 'coords' : 
    #     data_ds = data_ds.set_coords('i')
    
    # S'il y a un problème d'incompatibilité 'missing_value' / '_FillValue' :
    #     data_ds['lon'] = data_ds.lon.fillna(np.nan)
    #     data_ds['lat'] = data_ds.lat.fillna(np.nan)
    
    # Si jamais une variable non essentielle pose problème à l'export : 
    #     data_ds = data_ds.drop('lon')
    #     data_ds = data_ds.drop('lat')
    
    # Pour trouver les positions des valeurs nan :
    #     np.argwhere(np.isnan(data_ds.lon.values))
    
    # Pour reconvertir la date
    #     units, reference_date = ds.time.attrs['units'].split('since')
    #     ds['time'] = pd.date_range(start = reference_date, 
    #                                periods = ds.sizes['time'], freq = 'MS')
    # =========================================================================


    # Créer les coordonnées 'x' et 'y'...
# =============================================================================
#         # ... à partir des lon.lat :
#         # LAISSÉ TOMBÉ, PARCE QUE LEURS VALEURS DE LATITUDE SONT FAUSSES [!]
#         coords_xy = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(4326), 
#                                             rasterio.crs.CRS.from_epsg(27572), 
#                                             np.array(data_ds.lon).reshape((data_ds.lon.size), order = 'C'),
#                                             np.array(data_ds.lat).reshape((data_ds.lat.size), order = 'C'))
#         
#         # data_ds['x'] = np.round(coords_xy[0][0:data_ds.lon.shape[1]], -1) 
#         
#         # Arrondi à la dizaine à cause de l'approx. initiale sur les lat/lon :                                               
#         x = np.round(coords_xy[0], -1).reshape(data_ds.lon.shape[0], 
#                                                data_ds.lon.shape[1], 
#                                                order = 'C')
#         # donne un motif qui se répète autant de fois qu'il y a de latitudes
#         y = np.round(coords_xy[1], -1).reshape(data_ds.lon.shape[1], 
#                                                data_ds.lon.shape[0], 
#                                                order = 'F')
#         # donne un motif qui se répète autant de fois qu'il y a de longitudes
#         
#         # data_ds['x'] = x[0,:] 
#         # data_ds['y'] = y[0,:]
#         data_ds = data_ds.assign_coords(x = ('i', x[0,:]))
#         data_ds = data_ds.assign_coords(y = ('j', y[0,:]))
# =============================================================================


###############################################################################
def standard_grid_mapping(data, epsg = None):
    """
    QGIS needs a standard structure for grid_mapping information:
       - grid_mapping info should be in encodings and not in attrs
       - grid_mapping info should be stored in a coordinate names 'spatial_ref'
       - ...
    In MeteoFrance data, these QGIS standards are not met.
    This function standardizes grid_mapping handling, so that it is 
    compatible with QGIS.

    Parameters
    ----------
    data : TYPE
        DESCRIPTION.
    epsg : TYPE
        DESCRIPTION.

    Returns
    -------
    data_ds : TYPE
        DESCRIPTION.

    """
    # ---- Load
    data_ds = load_any(data)
    # Get main variable
    var = main_var(data_ds)
    
    # ---- Get the potential names of grid_mapping variable and clean all 
    # grid_mapping information
    
    # Remove all the metadata about grid_mapping, and save grid_mapping names
    names = set()
    if 'grid_mapping' in data_ds.attrs:
        names.add(data_ds.attrs['grid_mapping'])
        data_ds.attrs.pop('grid_mapping')
    if "grid_mapping" in data_ds.encoding:
        names.add(data_ds.encoding['grid_mapping'])
        data_ds.encoding.pop('grid_mapping')
    if 'grid_mapping' in data_ds[var].attrs:
        names.add(data_ds[var].attrs['grid_mapping'])
        data_ds[var].attrs.pop('grid_mapping')
    if "grid_mapping" in data_ds[var].encoding:
        names.add(data_ds[var].encoding['grid_mapping'])
        data_ds[var].encoding.pop('grid_mapping')

    # Drop all variable or coord corresponding to the previously founded 
    # grid_mapping names
    for n in list(names):
        if n in data_ds.data_vars:
            temp = data_ds[n]
            data_ds = data_ds.drop(n)
        if n in data_ds.coords:
            temp = data_ds[n]
            data_ds = data_ds.reset_coords(n, drop = True)
        
    if epsg is None:
        # Use the last grid_mapping value as the standard spatial_ref
        dummy_epsg = 2154
        data_ds.rio.write_crs(dummy_epsg, inplace = True) # creates the spatial_ref structure and mapping
        data_ds['spatial_ref'] = temp
    else:
        data_ds.rio.write_crs(epsg, inplace = True)

    
    return data_ds


###############################################################################
def standard_fill_value(*, data_ds, attrs, encod):
    
    var = main_var(data_ds)
    
    # Clean all fill_value info
    if '_FillValue' in data_ds[var].attrs:
        data_ds[var].attrs.pop('_FillValue')
    if 'missing_value' in data_ds[var].attrs:
        data_ds[var].attrs.pop('missing_value')
    if 'missing_value' in data_ds[var].attrs:
        data_ds[var].attrs.pop('missing_value')
        
    # Set the fill_value, according to a hierarchical rule
    if '_FillValue' in encod:
        data_ds[var].encoding['_FillValue'] = encod['_FillValue']
    elif '_FillValue' in attrs:
        data_ds[var].encoding['_FillValue'] = attrs['_FillValue']
    elif 'missing_value' in encod:
        data_ds[var].encoding['_FillValue'] = encod['missing_value']
    elif 'missing_value' in attrs:
        data_ds[var].encoding['_FillValue'] = attrs['missing_value']
    else:
        data_ds[var].encoding['_FillValue'] = np.nan
        
    return data_ds


#%% FILE MANAGEMENT
###############################################################################
# Shorten names
def shortname(data, data_type, ext = 'nc'):
    """
    ext : str
        
    """
    
    if ext is not None:
        ext = ext.replace('.', '')
    
    if os.path.isfile(data):
        root_folder = os.path.split(data)[0]
    else:
        root_folder = data
        
    if os.path.isdir(data):
        content_list = [os.path.join(data, f)
                     for f in os.listdir(data)]
    else:
        content_list = [data]
    
    # ---- DRIAS-Eau 2024 Indicateurs (netcdf)
    # Indicateurs SAFRAN (SWIAV, SSWI-3...) "EXPLORE2-SIM2 2024" 
    if data_type.casefold().replace(' ', '').replace('-', '') in [
            'indicateursim2024', 'indicateurssim2024','indicateurdriaseau2024',
            'indicateursdriaseau2024']:
        
        folder_pattern = re.compile('Indicateurs_(.*Annuel|.*Saisonnier)_(.*)_MF_ADAMONT_(.*)_SIM2')
        
        for elem in content_list:
            # Raccourcir le nom
            if os.path.isdir(elem):
                res = folder_pattern.findall(elem)
                if len(res) > 0:
                    outpath = '_'.join(res[0])
                    os.rename(elem, os.path.join(root_folder, outpath))
                    
    # ---- Remove custom added date-time
    elif data_type.casefold().replace(' ', '').replace('-', '') in [
            'removedate']:
        # This option enables to remove the '2024-11-06_12h53'-like suffixes
        # that I have added to file names (in order to trace the date of creation,
        # but it is unnecessary and causes file names to be too long for Windows).
        
        datetime_pattern = re.compile('(.*)_\d{4,4}-\d{2,2}-\d{2,2}_\d{2,2}h\d{2,2}.'+f'{ext}')
        
        for elem in content_list:
            if len(datetime_pattern.findall(elem)) > 0:
                os.rename(os.path.join(root_folder, elem), 
                          os.path.join(root_folder, datetime_pattern.findall(elem)[0] + f'.{ext}'))
            elif os.path.isdir(os.path.join(root_folder, elem)):
                shortname(os.path.join(root_folder, elem), data_type = data_type, ext = ext)
        

###############################################################################
def remove_double(data_folder, data_type):
    """
    The data downloaded from DRIAS website contains *some* data sets 
    available for different periods (it is the same data, but one version
    goes from 1950 to 2005, and another from 1970 to 2005). For some models,
    there are no duplicate of that sort.
    These duplicates are unnecessary. This script moves these duplicates to a
    subfolder named "doublons".
    
    Example
    -------
    folder_list = [r"Eau-SWIAV_Saisonnier_EXPLORE2-2024_historical", 
                   r"Eau-SWIAV_Saisonnier_EXPLORE2-2024_rcp45", 
                   r"Eau-SWIAV_Saisonnier_EXPLORE2-2024_rcp85"]
    root_folder = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\DRIAS\DRIAS-Eau\EXPLORE2-SIM2 2024\Pays Basque\Indicateurs"
    
    for folder in folder_list:
        base_folder = os.path.join(root_folder, folder)
        subfolder_list = [os.path.join(base_folder, f)
                     for f in os.listdir(base_folder) 
                     if os.path.isdir(os.path.join(base_folder, f))]
        for subfolder in subfolder_list:
            gc.remove_double(subfolder, data_type = "indicateurs drias eau 2024")
    """
    
    # ---- DRIAS-Eau 2024 Indicateurs (netcdf)
    # Indicateurs SAFRAN (SWIAV, SSWI-3...) "EXPLORE2-SIM2 2024" 
    if data_type.casefold().replace(' ', '').replace('-', '') in [
            'indicateursim2024', 'indicateurssim2024','indicateurdriaseau2024',
            'indicateursdriaseau2024']:
                
        content_list = [os.path.join(data_folder, f)
                     for f in os.listdir(data_folder) 
                     if (os.path.isfile(os.path.join(data_folder, f)) \
                         & (os.path.splitext(os.path.join(data_folder, f))[-1] == '.nc'))]
        
        model_pattern = re.compile("(.*)_(\d{4,4})-(\d{4,4})_(historical|rcp45|rcp85)_(.*)_(SIM2.*)")
        model_dict = {}
        
        # List all models
        for elem in content_list:
            filename = os.path.split(elem)[-1]
            var, date, datef, scenario, model, creation_date = model_pattern.findall(filename)[0]
            date = int(date)
            if model in model_dict:
                model_dict[model].append(date)
            else:
                model_dict[model] = [date]
        
        # Move duplicates
        if not os.path.exists(os.path.join(data_folder, "doublons")):
            os.makedirs(os.path.join(data_folder, "doublons"))
        
        for model in model_dict:
            if len(model_dict[model]) > 1:
                filename = '_'.join([var, f"{max(model_dict[model])}-{datef}", scenario, model, creation_date])
                os.rename(
                    os.path.join(data_folder, filename),
                    os.path.join(data_folder, 'doublons', filename)
                    )


###############################################################################
def name_xml_attributes(*, output_file, fields):  
    band_str_open = '\t<PAMRasterBand band="{}">\t\t<Description>{}'
    band_str_close = '</Description>\t</PAMRasterBand>\n</PAMDataset>'
    base_str = ''.join(['<PAMDataset>\n',
                       '\t<Metadata>\n',
                       '\t\t<MDI key="CRS">epsg:27572</MDI>\n',
                       '\t</Metadata>\n',
                       len(fields) * (band_str_open + band_str_close)])
    
    band_ids = [str(item) for item in list(range(1, len(fields)+1))]
    # Create a string list of indices: '1', '2', '3' ...
    addstr = [item for pair in zip(band_ids, fields) for item in pair]
    # Create a list alternating indices and names: '1', 'CLDC', '2', 'T2M' ...
    
    file_object = open(output_file + '.aux.xml', 'w')
    file_object.write(base_str.format(*addstr))
    file_object.close()


#%% REPROJECTION
###############################################################################
def reproject(data, *, src_crs=None, base_template=None, bounds=None,  
              x0=None, y0=None, mask=None, **rio_kwargs):
    r"""
    Reproject space-time data, using rioxarray.reproject().

    Parameters
    ----------
    data : str, pathlib.Path, xarray.Dataset or xarra.Dataarray
        Data to reproject. Supported file formats are .tif and .nc.
    src_crs : int or str or rasterio.crs.CRS, optional, default None
        Source coordinate reference system.    
        For *integers*, src_crs refers to the EPSG code. 
        For *strings*, src_crs can be OGC WKT string or Proj.4 string.
    base_template : str, pathlib.Path, xarra.Dataarray or geopandas.GeoDataFrame, optional, default None
        Filepath, used as a template for spatial profile. Supported file formats
        are .tif, .nc and .shp.
    bounds : tuple (float, float, float, float), optional, default None
        Boundaries of the target domain: (x_min, y_min, x_max, y_max)
    x0: number, optional, default None
        Origin of the X-axis, used to align the reprojection grid. 
    y0: number, optional, default None
        Origin of the Y-axis, used to align the reprojection grid. 
    mask : str or pathlib.Path, optional, default None
        Filepath of geopandas.dataframe of mask.    
    
    **rio_kwargs : keyword args, optional, defaults are None
        Argument passed to the ``xarray.Dataset.rio.reproject()`` function call.
        
        **Note**: These arguments are prioritary over ``base_template`` attributes.
        
        May contain: 
            - dst_crs : str
            - resolution : float or tuple
            - shape : tuple (int, int)
            - transform : Affine
            - resampling
            - nodata : float or None
            - see ``help(xarray.Dataset.rio.reproject)``

    Returns
    -------
    Reprojected xarray.Dataset.

    """
    
    #%%%% Load data, base and mask
    # ===========================
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    base_ds = None
    if base_template is not None:
        base_ds = load_any(base_template, decode_times = True, decode_coords = 'all')
    if mask is not None:
        mask_ds = load_any(mask, decode_times = True, decode_coords = 'all')
    
    if src_crs is not None:
        data_ds.rio.write_crs(src_crs, inplace = True)
    
    # Identify spatial coord names
    for yname in ['latitude', 'lat', 'y', 'Y']:
        if yname in data_ds.coords:
            yvar = yname
    for xname in ['longitude', 'lon', 'x', 'X']:
        if xname in data_ds.coords:
            xvar = xname
    
    # Initialize x0 and y0 if None
    x_res, y_res = data_ds.rio.resolution()
    if x0 is None:
        x0 = data[xvar][0].item() + x_res/2
    if y0 is None:
        y0 = data[yvar][0].item() + y_res/2
    
    #%%%% Compute parameters
    # =====================
    print("\nComputing parameters...")
    
    # ---- Safeguards against redundant arguments
    # -------------------------------------------
    if ('transform' in rio_kwargs) & ('shape' in rio_kwargs) & (bounds is not None):
        print("   _ Err: bounds cannot be passed alongside with both transform and shape")
        return
    
    if 'resolution' in rio_kwargs:
        if ('shape' in rio_kwargs) | ('transform' in rio_kwargs):
        # safeguard to avoid RioXarrayError
            print("   _ Err: resolution cannot be used with shape or transform.")
            return
        
    if (bounds is not None) & (mask is not None):
        print("   _ Err: bounds and mask cannot be passed together")
        return
    
    
    # ---- Backup of rio_kwargs
    # -------------------------
    rio_kwargs0 = rio_kwargs.copy()
    
    # Info message
    if ('transform' in rio_kwargs) & (bounds is not None):
        if (bounds[0] != rio_kwargs['transform'][2]) | (bounds[3] != rio_kwargs['transform'][5]):
            print("   _ ...")
    
    
    # ---- No base_template
    # ---------------------
    if base_ds is None:
        ### Retrieve <dst_crs> (required parameter)
        if 'dst_crs' not in rio_kwargs:
            rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            
    # ---- Base_template
    # ------------------
    # if there is a base, it will be used after being updated with passed parameters
    else:
        base_kwargs = {}
        
        ### 1. Retrieve all the available info from base:
        if isinstance(base_ds, xr.Dataset):
            # A- Retrieve <dst_crs> (required parameter)
            if 'dst_crs' not in rio_kwargs:
                try:
                    rio_kwargs['dst_crs'] = base_ds.rio.crs.to_string()
                except:
                    rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            # B- Retrieve <shape> and <transform>
            base_kwargs['shape'] = base_ds.rio.shape
            base_kwargs['transform'] = base_ds.rio.transform()
            # Note that <resolution> is ignored from base_ds
                
        elif isinstance(base_ds, gpd.GeoDataFrame):
            # A- Retrieve <dst_crs> (required parameter)
            if 'dst_crs' not in rio_kwargs:
                try:
                    rio_kwargs['dst_crs'] = base_ds.crs.to_string()
                except:
                    rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            # B- Retrieve <shape> and <transform>
            if 'resolution' in rio_kwargs:
                # The bounds of gpd base are used with the user-defined resolution
                # in order to compute 'transform' and 'shape' parameters:
                x_res, y_res = format_xy_resolution(
                    resolution = rio_kwargs['resolution'])
                shape, x_min, y_max = get_shape(
                    x_res, y_res, base_ds.total_bounds, x0, y0)
                base_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                                  0.0, y_res, y_max)
                base_kwargs['shape'] = shape
            else:
                print("   _ Err: resolution needs to be passed when using a vector base")
                return
            
        ### 2. Update <base_kwargs> with <rio_kwargs>
        for k in rio_kwargs:
            base_kwargs[k] = rio_kwargs[k]
        # Replace rio_kwargs with the updated base_kwargs
        rio_kwargs = base_kwargs
    
    
    # ---- Mask
    # ---------
    # <mask> has priority over bounds or rio_kwargs
    if mask is not None:
        # Reproject the mask
        if isinstance(mask_ds, gpd.GeoDataFrame):
            mask_ds.to_crs(crs = rio_kwargs['dst_crs'], inplace = True)
            bounds_mask = mask_ds.total_bounds
        elif isinstance(mask_ds, xr.Dataset):
            mask_ds = mask_ds.rio.reproject(dst_crs = rio_kwargs['dst_crs'])
            bounds_mask = (mask_ds.rio.bounds()[0], mask_ds.rio.bounds()[3],
                           mask_ds.rio.bounds()[2], mask_ds.rio.bounds()[1])
    else:
        bounds_mask = None
    
    
    # ---- Bounds
    # -----------
    # <bounds> has priority over rio_kwargs
    if (bounds is not None) | (bounds_mask is not None):
        if bounds is not None:
            print("   _ Note that bounds should be in the format (x_min, y_min, x_max, y_max)")
        elif bounds_mask is not None:
            bounds = bounds_mask
            
        ### Apply <bounds> values to rio arguments
        if ('shape' in rio_kwargs0):
            # resolution will be defined from shape and bounds
            x_res, y_res = format_xy_resolution(bounds = bounds, 
                                                shape = rio_kwargs['shape'])
            rio_kwargs['transform'] = Affine(x_res, 0.0, bounds[0],
                                              0.0, y_res, bounds[3])
            
        elif ('resolution' in rio_kwargs0):
            # shape will be defined from resolution and bounds
            x_res, y_res = format_xy_resolution(
                resolution = rio_kwargs['resolution'])
            shape, x_min, y_max = get_shape(
                x_res, y_res, bounds, x0, y0)
            rio_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                              0.0, y_res, y_max)
            rio_kwargs['shape'] = shape
            
        # elif ('transform' in rio_kwargs0):
        else:
            # shape will be defined from transform and bounds
            if not 'transform' in rio_kwargs:
                rio_kwargs['transform'] = data_ds.rio.transform()
            x_res, y_res = format_xy_resolution(
                resolution = (rio_kwargs['transform'][0],
                              rio_kwargs['transform'][4]))
            shape, x_min, y_max = get_shape(
                x_res, y_res, bounds, x0, y0)
            rio_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                              0.0, y_res, y_max)
            rio_kwargs['shape'] = shape
        
    
    # ---- Resolution
    # ---------------
    if ('resolution' in rio_kwargs) and ('transform' in rio_kwargs):
        x_res, y_res = format_xy_resolution(
            resolution = rio_kwargs['resolution'])
        transform = list(rio_kwargs['transform'])
        transform[0] = x_res
        transform[4] = y_res
        rio_kwargs['transform'] = Affine(*transform[0:6])
        rio_kwargs.pop('resolution')   
        
    
    # ---- Resampling
    # ---------------
    if 'resampling' not in rio_kwargs:
        # by default, resampling is 5 (average) instead of 0 (nearest)
        rio_kwargs['resampling'] = rasterio.enums.Resampling(5)


    #%%%% Reproject
    # ===========
    print("\nReprojecting...")
    
    var = main_var(data_ds)
    # Backup of attributes and encodings
    attrs = data_ds[var].attrs.copy()
    encod = data_ds[var].encoding.copy()
    
    # Handle timedelta, as they are not currently supported (https://github.com/corteva/rioxarray/discussions/459)
    NaT = False
    if isinstance(data_ds[var].values[0, 0, 0], (pd.Timedelta, np.timedelta64)):
        NaT = True
        
        data_ds[var] = data_ds[var].dt.days
        data_ds[var].encoding = encod
        
    if ('x' in list(data_ds.coords)) & ('y' in list(data_ds.coords)) & \
        (('lat' in list(data_ds.coords)) | ('lon' in list(data_ds.coords))):
        # if lat and lon are among coordinates, they should be temporarily moved
        # to variables to be reprojected
        data_ds = data_ds.reset_coords(['lat', 'lon'])
        data_reprj = data_ds.rio.reproject(**rio_kwargs)
        data_reprj = data_reprj.set_coords(['lat', 'lon'])

    else:
        data_reprj = data_ds.rio.reproject(**rio_kwargs)
    
# ======= NOT FINISHED ========================================================
#     # Handle timedelta
#     if NaT:
#         val = pd.to_timedelta(data_reprj[var].values.flatten(), unit='D').copy()
#         data_reprj[var] = val.to_numpy().reshape(data_reprj[var].shape)
#         # It is still required to precise the dimensions...
# =============================================================================
    
    # Correct _FillValues    
    data_reprj = standard_fill_value(
        data_ds = data_reprj, encod = encod, attrs = attrs)

    return data_reprj  

    
###############################################################################
#%% modification - odela
def _reproject(data, *, src_crs=None, base_template=None, bounds=None,  
              x0=None, y0=None, mask=None, **rio_kwargs):
    r"""
    Reproject space-time data, using rioxarray.reproject().

    Parameters
    ----------
    data : str, pathlib.Path, xarray.Dataset or xarra.Dataarray
        Data to reproject. Supported file formats are .tif and .nc.
    src_crs : int or str or rasterio.crs.CRS, optional, default None
        Source coordinate reference system.    
        For *integers*, src_crs refers to the EPSG code. 
        For *strings*, src_crs can be OGC WKT string or Proj.4 string.
    base_template : str, pathlib.Path, xarra.Dataarray or geopandas.GeoDataFrame, optional, default None
        Filepath, used as a template for spatial profile. Supported file formats
        are .tif, .nc and .shp.
    bounds : tuple (float, float, float, float), optional, default None
        Boundaries of the target domain: (x_min, y_min, x_max, y_max)
    x0: number, optional, default None
        Origin of the X-axis, used to align the reprojection grid. 
    y0: number, optional, default None
        Origin of the Y-axis, used to align the reprojection grid. 
    mask : str or pathlib.Path, optional, default None
        Filepath of geopandas.dataframe of mask.    
    
    **rio_kwargs : keyword args, optional, defaults are None
        Argument passed to the ``xarray.Dataset.rio.reproject()`` function call.
        
        **Note**: These arguments are prioritary over ``base_template`` attributes.
        
        May contain: 
            - dst_crs : str
            - resolution : float or tuple
            - shape : tuple (int, int)
            - transform : Affine
            - resampling
            - nodata : float or None
            - see ``help(xarray.Dataset.rio.reproject)``

    Returns
    -------
    Reprojected xarray.Dataset.

    """
    
    #%%%% Load data, base and mask
    # ===========================
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    base_ds = None
    if base_template is not None:
        base_ds = load_any(base_template, decode_times = True, decode_coords = 'all')
    if mask is not None:
        mask_ds = load_any(mask, decode_times = True, decode_coords = 'all')
    
    if src_crs is not None:
        data_ds.rio.write_crs(src_crs, inplace = True)
    
    # Identify spatial coord names
    for yname in ['latitude', 'lat', 'y', 'Y']:
        if yname in data_ds.coords:
            yvar = yname
    for xname in ['longitude', 'lon', 'x', 'X']:
        if xname in data_ds.coords:
            xvar = xname
    
    # Initialize x0 and y0 if None
    x_res, y_res = data_ds.rio.resolution()
    if x0 is None:
        x0 = data[xvar][0].item() + x_res/2
    if y0 is None:
        y0 = data[yvar][0].item() + y_res/2
    
    #%%%% Compute parameters
    # =====================
    print("\nComputing parameters...")
    
    # ---- Safeguards against redundant arguments
    # -------------------------------------------
    if ('transform' in rio_kwargs) & ('shape' in rio_kwargs) & (bounds is not None):
        print("   _ Err: bounds cannot be passed alongside with both transform and shape")
        return
    
    if 'resolution' in rio_kwargs:
        if ('shape' in rio_kwargs) | ('transform' in rio_kwargs):
        # safeguard to avoid RioXarrayError
            print("   _ Err: resolution cannot be used with shape or transform.")
            return
        
    if (bounds is not None) & (mask is not None):
        print("   _ Err: bounds and mask cannot be passed together")
        return
    
    
    # ---- Backup of rio_kwargs
    # -------------------------
    rio_kwargs0 = rio_kwargs.copy()
    
    # Info message
    if ('transform' in rio_kwargs) & (bounds is not None):
        if (bounds[0] != rio_kwargs['transform'][2]) | (bounds[3] != rio_kwargs['transform'][5]):
            print("   _ ...")
    
    
    # ---- No base_template
    # ---------------------
    if base_ds is None:
        ### Retrieve <dst_crs> (required parameter)
        if 'dst_crs' not in rio_kwargs:
            rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            
    # ---- Base_template
    # ------------------
    # if there is a base, it will be used after being updated with passed parameters
    else:
        base_kwargs = {}
        
        ### 1. Retrieve all the available info from base:
        if isinstance(base_ds, xr.Dataset):
            # A- Retrieve <dst_crs> (required parameter)
            if 'dst_crs' not in rio_kwargs:
                try:
                    rio_kwargs['dst_crs'] = base_ds.rio.crs.to_string()
                except:
                    rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            # B- Retrieve <shape> and <transform>
            base_kwargs['shape'] = base_ds.rio.shape
            base_kwargs['transform'] = base_ds.rio.transform()
            # Note that <resolution> is ignored from base_ds
                
        elif isinstance(base_ds, gpd.GeoDataFrame):
            # A- Retrieve <dst_crs> (required parameter)
            if 'dst_crs' not in rio_kwargs:
                try:
                    rio_kwargs['dst_crs'] = base_ds.crs.to_string()
                except:
                    rio_kwargs['dst_crs'] = data_ds.rio.crs.to_string()
            
            # B- Retrieve <shape> and <transform>
            if 'resolution' in rio_kwargs:
                # The bounds of gpd base are used with the user-defined resolution
                # in order to compute 'transform' and 'shape' parameters:
                x_res, y_res = format_xy_resolution(
                    resolution = rio_kwargs['resolution'])
                shape, x_min, y_max = get_shape(
                    x_res, y_res, base_ds.total_bounds, x0, y0)
                base_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                                  0.0, y_res, y_max)
                base_kwargs['shape'] = shape
            else:
                print("   _ Err: resolution needs to be passed when using a vector base")
                return
            
        ### 2. Update <base_kwargs> with <rio_kwargs>
        for k in rio_kwargs:
            base_kwargs[k] = rio_kwargs[k]
        # Replace rio_kwargs with the updated base_kwargs
        rio_kwargs = base_kwargs
    
    
    # ---- Mask
    # ---------
    # <mask> has priority over bounds or rio_kwargs
    if mask is not None:
        # Reproject the mask
        if isinstance(mask_ds, gpd.GeoDataFrame):
            mask_ds.to_crs(crs = rio_kwargs['dst_crs'], inplace = True)
            bounds_mask = mask_ds.total_bounds
        elif isinstance(mask_ds, xr.Dataset):
            mask_ds = mask_ds.rio.reproject(dst_crs = rio_kwargs['dst_crs'])
            bounds_mask = (mask_ds.rio.bounds()[0], mask_ds.rio.bounds()[3],
                           mask_ds.rio.bounds()[2], mask_ds.rio.bounds()[1])
    else:
        bounds_mask = None
    
    
    # ---- Bounds
    # -----------
    # <bounds> has priority over rio_kwargs
    if (bounds is not None) | (bounds_mask is not None):
        if bounds is not None:
            print("   _ Note that bounds should be in the format (x_min, y_min, x_max, y_max)")
        elif bounds_mask is not None:
            bounds = bounds_mask
            
        ### Apply <bounds> values to rio arguments
        if ('shape' in rio_kwargs0):
            # resolution will be defined from shape and bounds
            x_res, y_res = format_xy_resolution(bounds = bounds, 
                                                shape = rio_kwargs['shape'])
            rio_kwargs['transform'] = Affine(x_res, 0.0, bounds[0],
                                              0.0, y_res, bounds[3])
            
        elif ('resolution' in rio_kwargs0):
            # shape will be defined from resolution and bounds
            x_res, y_res = format_xy_resolution(
                resolution = rio_kwargs['resolution'])
            shape, x_min, y_max = get_shape(
                x_res, y_res, bounds, x0, y0)
            rio_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                              0.0, y_res, y_max)
            rio_kwargs['shape'] = shape
            
        # elif ('transform' in rio_kwargs0):
        else:
            # shape will be defined from transform and bounds
            if not 'transform' in rio_kwargs:
                rio_kwargs['transform'] = data_ds.rio.transform()
            x_res, y_res = format_xy_resolution(
                resolution = (rio_kwargs['transform'][0],
                              rio_kwargs['transform'][4]))
            shape, x_min, y_max = get_shape(
                x_res, y_res, bounds, x0, y0)
            rio_kwargs['transform'] = Affine(x_res, 0.0, x_min,
                                              0.0, y_res, y_max)
            rio_kwargs['shape'] = shape
        
    
    # ---- Resolution
    # ---------------
    if ('resolution' in rio_kwargs) and ('transform' in rio_kwargs):
        x_res, y_res = format_xy_resolution(
            resolution = rio_kwargs['resolution'])
        transform = list(rio_kwargs['transform'])
        transform[0] = x_res
        transform[4] = y_res
        rio_kwargs['transform'] = Affine(*transform[0:6])
        rio_kwargs.pop('resolution')   
        
    
    # ---- Resampling
    # ---------------
    if 'resampling' not in rio_kwargs:
        # by default, resampling is 5 (average) instead of 0 (nearest)
        rio_kwargs['resampling'] = rasterio.enums.Resampling(5)


    #%%%% Reproject
    # ===========
    print("\nReprojecting...")
    
    var = main_var(data_ds)
    # Backup of attributes and encodings
    attrs = data_ds[var].attrs.copy()
    encod = data_ds[var].encoding.copy()
    
    # Handle timedelta, as they are not currently supported (https://github.com/corteva/rioxarray/discussions/459)
    NaT = False
    if isinstance(data_ds[var].values[0, 0, 0], (pd.Timedelta, np.timedelta64)):
        NaT = True
        
        data_ds[var] = data_ds[var].dt.days
        data_ds[var].encoding = encod
        
    if ('x' in list(data_ds.coords)) & ('y' in list(data_ds.coords)) & \
        (('lat' in list(data_ds.coords)) | ('lon' in list(data_ds.coords))):
        # if lat and lon are among coordinates, they should be temporarily moved
        # to variables to be reprojected
        data_ds = data_ds.reset_coords(['lat', 'lon'])
        data_reprj = data_ds.rio.reproject(**rio_kwargs)
        data_reprj = data_reprj.set_coords(['lat', 'lon'])

    else:
        data_reprj = data_ds.rio.reproject(**rio_kwargs)
    
# ======= NOT FINISHED ========================================================
#     # Handle timedelta
#     if NaT:
#         val = pd.to_timedelta(data_reprj[var].values.flatten(), unit='D').copy()
#         data_reprj[var] = val.to_numpy().reshape(data_reprj[var].shape)
#         # It is still required to precise the dimensions...
# =============================================================================
    
    # Correct _FillValues    
    data_reprj = standard_fill_value(
        data_ds = data_reprj, encod = encod, attrs = attrs)

    return data_reprj  

    
###############################################################################




#%%% * Clip
# =============================================================================
# def clip(data, mask, src_crs=None, dst_crs=None):
#     """
#     The difference between clipping with clip() and with reproject() is that
#     clip() keeps the same grid as input, whereas reproject() aligns on the 
#     passed x0 and y0 values (by default x0=0 and y0=0).
# 
#     Parameters
#     ----------
#     data : TYPE
#         DESCRIPTION.
#     mask : TYPE
#         DESCRIPTION.
#     src_crs : TYPE, optional
#         DESCRIPTION. The default is None.
#     dst_crs : TYPE, optional
#         DESCRIPTION. The default is None.
# 
#     Returns
#     -------
#     TYPE
#         DESCRIPTION.
# 
#     """
#     kwargs = {}
#     if dst_crs is not None:
#         kwargs['dst_crs'] = dst_crs
#     
#     x_res, y_res = data.rio.resolution()
#     x0 = data.x[0].item() + x_res/2
#     y0 = data.y[0].item() + y_res/2
#     
#     return reproject(data, src_crs = src_crs, mask = mask, 
#                      x0 = x0, y0 = y0, **kwargs)
# =============================================================================

###############################################################################
#%%% Align on the closest value
def nearest(x = None, y = None, x0 = 700012.5, y0 = 6600037.5, res = 75): 
    """
    
    
    Exemple
    -------
    import geoconvert as gc
    gc.nearest(x = 210054)
    gc.nearest(y = 6761020)
    
    Parameters
    ----------
    x : float, optional
        Valeur de la coordonnée x (ou longitude). The default is None.
    y : float, optional
        Valeur de la coordonnée y (ou latitude). The default is None.

    Returns
    -------
    Par défault, cette fonction retourne la plus proche valeur (de x ou de y) 
    alignée sur la grille des cartes topo IGN de la BD ALTI.
    Il est possible de changer les valeurs de x0, y0 et res pour aligner sur
    d'autres grilles.
    """
    
    # ---- Paramètres d'alignement : 
    # ---------------------------
# =============================================================================
#     # Documentation Lambert-93
#     print('\n--- Alignement d'après doc Lambert-93 ---\n')
#     x0 = 700000 # origine X
#     y0 = 6600000 # origine Y
#     res = 75 # résolution
# =============================================================================
    
    # Coordonnées des cartes IGN BD ALTI v2
    if (x0 == 700012.5 or y0 == 6600037.5) and res == 75:
        print('\n--- Alignement sur grille IGN BD ALTI v2 (defaut) ---')   
    
    closest = []

    if x is not None and y is None:
        # print('x le plus proche = ')
        if (x0-x)%res <= res/2:
            closest = x0 - (x0-x)//res*res
        elif (x0-x)%res > res/2:
            closest = x0 - ((x0-x)//res + 1)*res
    
    elif y is not None and x is None:
        # print('y le plus proche = ')
        if (y0-y)%res <= res/2:
            closest = y0 - (y0-y)//res*res
        elif (y0-y)%res > res/2:
            closest = y0 - ((y0-y)//res + 1)*res
    
    else:
        print('Err: only one of x or y parameter should be passed')
        return
        
    return closest


###############################################################################
#%%% Format x_res and y_res
def format_xy_resolution(*, resolution=None, bounds=None, shape=None):
    """
    Format x_res and y_res from a resolution value/tuple/list, or from 
    bounds and shape.

    Parameters
    ----------
    resolution : number | iterable, optional
       xy_res or (x_res, y_res). The default is None.
    bounds : iterable, optional
        (x_min, y_min, x_max, y_max). The default is None.
    shape : iterable, optional
        (height, width). The default is None.

    Returns
    -------
    x_res and y_res

    """
    if (resolution is not None) & ((bounds is not None) | (shape is not None)):
        print("Err: resolution cannot be specified alongside with bounds or shape")
        return
    
    if resolution is not None:
        if isinstance(resolution, (tuple, list)):
            x_res = abs(resolution[0])
            y_res = -abs(resolution[1])
        else:
            x_res = abs(resolution)
            y_res = -abs(resolution)
            
    if ((bounds is not None) & (shape is None)) | ((bounds is None) & (shape is not None)):
        print("Err: both bounds and shape need to be specified")
    
    if (bounds is not None) & (shape is not None):
        (height, width) = shape
        (x_min, y_min, x_max, y_max) = bounds
        x_res = (x_max - x_min) / width
        y_res = -(y_max - y_min) / height
        
    return x_res, y_res


###############################################################################
#%%% Get shape
def get_shape(x_res, y_res, bounds, x0=0, y0=0):
    # bounds should be xmin, ymin, xmax, ymax
    # aligne sur le 0, arrondit, et tutti quanti
    (x_min, y_min, x_max, y_max) = bounds
    
    x_min2 = nearest(x = x_min, res = x_res, x0 = x0)
    if x_min2 > x_min:
        x_min2 = x_min2 - x_res
        
    y_min2 = nearest(y = y_min, res = y_res, y0 = y0)
    if y_min2 > y_min:
        y_min2 = y_min2 - abs(y_res)
        
    x_max2 = nearest(x = x_max, res = x_res, x0 = x0)
    if x_max2 < x_max:
        x_max2 = x_max2 + x_res
        
    y_max2 = nearest(y = y_max, res = y_res, y0 = y0)
    if y_max2 < y_max:
        y_max2 = y_max2 + abs(y_res)
    
    
    width = (x_max2 - x_min2)/x_res
    height = -(y_max2 - y_min2)/y_res
    if (int(width) == width) & (int(height) == height):
        shape = (int(height), int(width))
    else:
        print("Err: shape values are not integers")
    
    return shape, x_min2, y_max2

           
#%% COMPRESS & UNCOMPRESS
###############################################################################
def unzip(data):
    """
    In some cases, especially for loading in QGIS, it is much quicker to load
    uncompressed netcdf than compressed netcdf.
    This function only applies to non-destructive compression.

    Parameters
    ----------
    data : TYPE
        DESCRIPTION.

    Returns
    -------
    None.

    """
    # Load
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    # Get main variable
    var = main_var(data_ds)
    # Deactivate zlib
    data_ds[var].encoding['zlib'] = False
    # Return
    return data_ds
    # Export
# =============================================================================
#     outpath = '_'.join([
#         os.path.splitext(data)[0], 
#         'unzip.nc',
#         ])
#     export(data_ds, outpath)
# =============================================================================
    

###############################################################################
def gzip(data, complevel = 3, shuffle = False):
    """
    Quick tool to apply lossless compression on a NetCDF file using gzip.
    
    examples
    --------
    gc.gzip(filepath_comp99.8, complevel = 4, shuffle = True)
    gc.gzip(filepath_drias2022like, complevel = 5)

    Parameters
    ----------
    data : TYPE
        DESCRIPTION.

    Returns
    -------
    None.

    """
    # Load
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    # Get main variable
    var = main_var(data_ds)
    # Activate zlib
    data_ds[var].encoding['zlib'] = True
    data_ds[var].encoding['complevel'] = complevel
    data_ds[var].encoding['shuffle'] = shuffle
    data_ds[var].encoding['contiguous'] = False
    # Return
    return data_ds
    # Export
# =============================================================================
#     outpath = '_'.join([
#         os.path.splitext(data)[0], 
#         'gzip.nc',
#         ])
#     export(data_ds, outpath)
# =============================================================================
    
    
###############################################################################
def pack(data, nbits = 16):
    """

    
    examples
    --------

    Parameters
    ----------
    data : TYPE
        DESCRIPTION.

    Returns
    -------
    None.

    """
    if (nbits != 16) & (nbits != 8):
        print("Err: nbits should be 8 or 16")
        return
    
    nval = {8: 256,
            16: 65536}

    # Load
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    # Get main variable
    var = main_var(data_ds)
    # Determine if there are negative and positive values or not
    if ((data_ds[var]>0).sum().item() > 0) & ((data_ds[var]<0).sum().item() > 0):
        rel_val = True
    else:
        rel_val = False
    # Compress
    bound_min = data_ds[var].min().item()
    bound_max = data_ds[var].max().item()
    # Add an increased max bound, that will be used for _FillValue
    bound_max = bound_max + (bound_max - bound_min + 1)/nval[nbits]
    scale_factor, add_offset = compute_scale_and_offset(
        bound_min, bound_max, nbits)
    data_ds[var].encoding['scale_factor'] = scale_factor
    if rel_val:
        data_ds[var].encoding['dtype'] = f'int{nbits}'
        data_ds[var].encoding['_FillValue'] = nval[nbits]//2-1
        data_ds[var].encoding['add_offset'] = add_offset
    else:
        data_ds[var].encoding['dtype'] = f'uint{nbits}'
        data_ds[var].encoding['_FillValue'] = nval[nbits]-1
        data_ds[var].encoding['add_offset'] = 0
    print("   Compression (lossy)")
    # Prevent _FillValue issues
    if ('missing_value' in data_ds[var].encoding) & ('_FillValue' in data_ds[var].encoding):
        data_ds[var].encoding.pop('missing_value')
    # Return
    return data_ds
    # Export
# =============================================================================
#     outpath = '_'.join([
#         os.path.splitext(data)[0], 
#         'pack' + os.path.splitext(data)[-1],
#         ])
#     export(data_ds, outpath)
# =============================================================================


#%%% Packing netcdf (previously packnetcdf.py)
"""
Created on Wed Aug 24 16:48:29 2022

@author: script based on James Hiebert's work (2015):
    http://james.hiebert.name/blog/work/2015/04/18/NetCDF-Scale-Factors.html

RAPPEL des dtypes :
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

###############################################################################
def compute_scale_and_offset(min, max, n):
    """
    Computes scale and offset necessary to pack a float32 (or float64?) set 
    of values into a int16 or int8 set of values.
    
    Parameters
    ----------
    min : float
        Minimum value from the data
    max : float
        Maximum value from the data
    n : int
        Number of bits into which you wish to pack (8 or 16)

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


###############################################################################
def pack_value(unpacked_value, scale_factor, add_offset):
    """
    Compute the packed value from the original value, a scale factor and an 
    offset.

    Parameters
    ----------
    unpacked_value : numeric
        Original value.
    scale_factor : numeric
        Scale factor, multiplied to the original value.
    add_offset : numeric
        Offset added to the original value.

    Returns
    -------
    numeric
        Packed value.

    """
    
    print(f'math.floor: {math.floor((unpacked_value - add_offset) / scale_factor)}')
    return (unpacked_value - add_offset) / scale_factor


###############################################################################
def unpack_value(packed_value, scale_factor, add_offset):
    """
    Retrieve the original value from a packed value, a scale factor and an
    offset.

    Parameters
    ----------
    packed_value : numeric
        Value to unpack.
    scale_factor : numeric
        Scale factor that was multiplied to the original value to retrieve.
    add_offset : numeric
        Offset that was added to the original value to retrieve.

    Returns
    -------
    numeric
        Original unpacked value.

    """
    return packed_value * scale_factor + add_offset


#%% EXPORT
###############################################################################
def export(data, output_filepath):
    extension_dst = os.path.splitext(output_filepath)[-1]
    
    data_ds = load_any(data, decode_times = True, decode_coords = 'all')
    
    if isinstance(data_ds, gpd.GeoDataFrame):
        if extension_dst == '.shp':
            print("\nExporting...")
            data_ds.to_file(output_filepath)
            print(f"   _ Success: The data has been exported to the file '{output_filepath}'")

        elif extension_dst in ['.nc', '.tif']:
            print("Err: To convert vector to raster, use geoconvert.reproject() instead")
            return
    
    if isinstance(data_ds, xr.Dataset):
        print("\nExporting...")
        if extension_dst == '.nc':
            data_ds.to_netcdf(output_filepath)
        
        elif extension_dst in ['.tif', '.asc']:
            data_ds.rio.to_raster(output_filepath)
        
        print(f"   _ Success: The data has been exported to the file '{output_filepath}'")
   

#%% CONVERSIONS
###############################################################################
def hourly_to_daily(data, mode = 'sum'):
   
    # ---- Process data
    #% Load data:
    data_ds = load_any(data, decode_coords = 'all', decode_times = True)
    
    var = main_var(data_ds)
    
    #% Resample:
    print("   _ Resampling time...")
    if mode == 'mean':
        datarsmpl = data_ds.resample(time = '1D').mean(dim = 'time',
                                                            keep_attrs = True)
    elif mode == 'max':
        datarsmpl = data_ds.resample(time = '1D').max(dim = 'time',
                                                           keep_attrs = True)
    elif mode == 'min':
        datarsmpl = data_ds.resample(time = '1D').min(dim = 'time',
                                                           keep_attrs = True)
    elif mode == 'sum':
        datarsmpl = data_ds.resample(time = '1D').sum(dim = 'time',
                                                           skipna = False,
                                                           keep_attrs = True)
    
    # ---- Preparing export   
    # Transfer encodings
    for c in list(datarsmpl.coords):
        datarsmpl[c].encoding = data_ds[c].encoding
        datarsmpl[c].attrs = data_ds[c].attrs
    datarsmpl['time'].encoding['units'] = datarsmpl['time'].encoding['units'].replace('hours', 'days')
    
    datarsmpl[var].encoding = data_ds[var].encoding
        
    # Case of packing
    if ('scale_factor' in datarsmpl[var].encoding) | ('add_offset' in datarsmpl[var].encoding):
        # Packing (lossy compression) induces a loss of precision of 
        # apprx. 1/1000 of unit, for a quantity with an interval of 150 
        # units. The packing is initially used in some original ERA5-Land data.
        if mode == 'sum':
            print("   Correcting packing encodings...")
            datarsmpl[var].encoding['scale_factor'] = datarsmpl[var].encoding['scale_factor']*24
            datarsmpl[var].encoding['add_offset'] = datarsmpl[var].encoding['add_offset']*24
        
    return datarsmpl


###############################################################################
def merge_folder(data):
    """
    This function merge all NetCDF inside a folder.

    Parameters
    ----------
    data: str or iterable
        Folder, filepath or iterable of filepaths.

    Returns
    -------
    Merged xarray.Dataset.
    """
    
    # ---- Load file list
    data_folder, filelist = get_filelist(data, filetype = '.nc')

    c = 0
    ds_list = []
    if len(filelist) > 1:
        print("Merging files...")
        
        # ---- Append all xr.Datasets in a list
        for f in filelist:
            ds_list.append(load_any(os.path.join(data_folder, f), 
                                    decode_coords = 'all', 
                                    decode_times = True))
            print(f"      . {f}  ({c}/{len(filelist)})")
            c += 1
            
        # ---- Backup of attributes and encodings
        var = main_var(ds_list[0])
# ========== useless ==========================================================
#         attrs = ds_list[0][var].attrs.copy()
# =============================================================================
        encod = ds_list[0][var].encoding.copy()
    
        # ---- Merge
        merged_ds = xr.merge(ds_list) # Note: works only when doublons are identical
# ========== wrong ============================================================
#         merged_ds = xr.concat(ds_list, dim = 'time')
# =============================================================================
# ========== useless ==========================================================
#         merged_ds = merged_ds.sortby('time') # In case the files are not loaded in time order   
# =============================================================================
        
        # ---- Transferring encodings (_FillValue, compression...)
        merged_ds[var].encoding = encod
        return merged_ds
    
    else:
        print("Err: Only one NetCDF file was found.")
        return

###############################################################################
# Convert to CWatM (ex Prepare CWatM inputs)
def convert_to_cwatm(data, data_type, reso_m = None, EPSG_out=None, 
                        EPSG_in = None, coords_extent = 'Bretagne'):
# =============================================================================
#     previously prepare_CWatM_input(*, data, data_type, reso_m = None, 
#                                    EPSG_out, EPSG_in = None, 
#                                    coords_extent = 'Bretagne'):
# =============================================================================
    """
    Example
    -------
    # Standard:
    ds = gc.prepare_CWatM_input(data = r"",
                                data_type = 'DRIAS',
                                reso_m = 8000,
                                EPSG_out = 3035)
    
    # Crop coefficients:
    gc.prepare_CWatM_input(data = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\data\input_1km_LeMeu\landcover\grassland\cropCoefficientGrassland_10days_refined.nc", 
                           data_type = "crop coeff", 
                           reso_m = 1000, 
                           EPSG_out = 3035, 
                           EPSG_in = 4326)

    Parameters
    ----------
    data : str
        Fichier à convertir.
    data_type : str
        Type de données : 'ERA5' | 'mask' | 'soil depth' | 'DRIAS'
    reso_m : float
        Résolution de sortie [m] : 75 | 1000 | 5000 | 8000
    EPSG_out : int
        Système de coordonnées de référence de sortie : 2154 | 3035 | 4326...
    EPSG_in : int
        Système de coordonnées de référence d'entrée
    coords_extent : list, or str
        Emprise spatiale : [x_min, x_max, y_min, y_max] 
        (for Elias: [3202405.9658273868262768,
                     4314478.7219533622264862,
                     2668023.2067883270792663,
                     2972043.0969522628001869]) -> shape = (35, 22)
        or keywords: "Bretagne", "from_input"

    Returns
    -------
    None.

    """
    
# ====== Ancienne version du script ===========================================
#     (input_folder, _file_name) = os.path.split(data)
#     (file_name, file_extension) = os.path.splitext(_file_name)
# =============================================================================

    #%%% ERA5
    if data_type.casefold().replace('-', '') in ["era5", "era5land", "era"]:
        # ---- Merge files
        # Usually ERA5-Land files are too big to be downloaded for the full period.
        # Here the first step is to merge the available ERA5.nc files.
        merged_ds = merge_folder(data)
        
        var = main_var(data)
        
        # ---- Convert hourly to daily
        print("   _ Converting hourly to daily...")
        modelist = { # to differentiate extensive from intensive quantities
            'ro': 'sum',
            'sro': 'sum',
            'ssro': 'sum',
            'evavt': 'sum',
            'evatc': 'sum',
            'pev': 'sum',
            'tp': 'sum',
            'fal': 'mean',
            'rh': 'mean',
            'ssrd': 'mean',
            'strd': 'mean',
            'sp': 'mean',
            't2m': 'mean',
            'd2m': 'mean',
            'u10': 'mean',
            'v10': 'mean',
            'wind_speed': 'mean'}
        daily_ds = hourly_to_daily(merged_ds, mode = modelist[var])
        
        # ---- Convert units when needed
        if var in ['ssrd', 'strd']:
            print("   _ Converting radiation units from J/m²/h to W/m²")
            daily_ds = convert_downwards_radiation(daily_ds)
        
        elif var == 'pev':
            print("   _ Converting negative potential evapotranspiration to positive")
            # Backup of attributes and encodings
            attrs = daily_ds[var].attrs.copy()
            encod = daily_ds[var].encoding.copy()
            
            daily_ds[var] = daily_ds[var]*-1
            
            # Transferring attributes and encodings
            daily_ds[var].encoding = encod
            daily_ds[var].attrs = attrs
            
            # Case of packing
            if ('scale_factor' in daily_ds[var].encoding) | ('add_offset' in daily_ds[var].encoding):
                # Packing (lossy compression) induces a loss of precision of 
                # apprx. 1/1000 of unit, for a quantity with an interval of 150 
                # units. The packing is initially used in some original ERA5-Land data.
                print("      . Correcting packing encodings...")
                daily_ds[var].encoding['add_offset'] = daily_ds[var].encoding['add_offset']*-1
        
        return daily_ds
        

    
    #%%% IGN BD ALTI 25m (DEM)
    elif data_type.casefold().replace(' ', '') in ["alti", "bdalti", "ignalti"]:
        data_folder, filelist = get_filelist(data, filetype = '.asc')
        
        c = 0
        ds_list = []
        for f in filelist:
            ds_list.append(load_any(os.path.join(data_folder, f), name = 'elev'))
            print(c)
            c += 1
            if c == 10:
                ds_list = [xr.merge(ds_list)]
                c = 0
        merged_ds = xr.merge(ds_list)
        
        # Replace 0 with NaN
        merged_ds['elev'] = merged_ds['elev'].where(merged_ds['elev'] != 0)
        
        # Encodings (_FillValue, compression...)
        temp = load_any(filelist[0], name = 'elev')
        merged_ds['elev'].encoding = temp['elev'].encoding

        
        return merged_ds
        
        # export(merged_ds, os.path.join(data_folder, 'MNT_fusion.asc'))
        
        
    #%%% ° Maskmap
    elif data_type.casefold() in ["mask", "areamaps"]:
        print("\nNB : Conversion à titre illustratif. Pour convertir proprement le masque, il convient d'utiliser le LDD\n")
        with xr.open_dataset(data) as mask_ds:
            mask_ds.load() # to unlock the resource
        
        mask_ds = mask_ds.squeeze().drop("band")
        
        if 'spatial_ref' in mask_ds.coords or 'spatial_ref' in mask_ds.data_vars:
            # _motif = re.compile('"EPSG","\d+"')
            # _substr = _motif.findall(mask_ds.spatial_ref.crs_wkt)[-1]
            # _epsg_motif = re.compile('\d+')
            # _mask_epsg = int(_epsg_motif.search(_substr).group())
            _mask_epsg = int(mask_ds.rio.crs.to_epsg())
        
        else:
            print('\nFor transforming, mask needs to have a CRS associated.')
            return
        
        #% Reprojection of the mask in the CRS and the resolution of the data:
        print('\nReprojecting...')
        print('   from epsg:{} to epsg:{}'.format(str(_mask_epsg), str(EPSG_out)))
        if reso_m//1000 == 0:
            print('   resolution: {} m'.format(reso_m))
        else:
            print('   resolution: {} km'.format(reso_m/1000))

        mask_coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(_mask_epsg), 
                                                   rasterio.crs.CRS.from_epsg(EPSG_out), 
                                                   [mask_ds.x.values.min()], [mask_ds.y.values.max()])
        
        reso_input = abs(mask_ds.x.values[1] - mask_ds.x.values[0])
        print('   resolution input: {} m'.format(reso_input))
        
        if reso_m == 75:
            x_min = nearest(x = mask_coords_conv[0][0] - reso_input)
            y_max = nearest(x = mask_coords_conv[1][0] + reso_input)
        else:
            x_min = (mask_coords_conv[0][0] - reso_input) // reso_m * reso_m - reso_m/2
            y_max = (mask_coords_conv[1][0] + reso_input) // reso_m * reso_m + reso_m/2
        
        # mask_coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(_mask_epsg), 
        #                                            rasterio.crs.CRS.from_epsg(EPSG_out), 
        #                                            [mask_ds.x.values.min()], [mask_ds.y.values.min()])
        
        # y_min = mask_coords_conv[1][0]//reso_m*reso_m - reso_m/2
        
        transform_ = Affine(reso_m, 0.0, x_min,  
                            0.0, -reso_m, y_max)
        
        width_ = int(mask_ds.x.shape[0] * reso_input / reso_m //1 +1)
        height_ = int(mask_ds.y.shape[0] * reso_input / reso_m //1 +1)
        
        mask_reprj = mask_ds.rio.reproject(dst_crs = 'epsg:'+str(EPSG_out),
                                          transform = transform_,
                                          resampling = rasterio.enums.Resampling(5),
                                          shape = (height_, width_),
                                          )
        
        # mask_reprj.rio.write_crs("epsg:"+str(EPSG_out), inplace = True)
        
        #% Export :
        print('\nCompressing and saving...')
        print('   output file type: *{}'.format(file_extension))
        
        output_file = os.path.join(input_folder, 
                                   ' '.join([file_name, 
                                             'res='+str(reso_m)+'m', 
                                             'CRS='+str(EPSG_out),
                                             ]) + file_extension)
        
        if file_extension == '.nc':
            var = main_var(mask_reprj)
            # mask_reprj[var].encoding['_FillValue'] = None # ou np.nan ?
            # ERREUR : mask_reprj.to_netcdf(output_file, encoding = {var: {'zlib': True, 'dtype': 'float32', 'scale_factor': 0.00000001, '_FillValue': np.nan}})
            mask_reprj.to_netcdf(output_file)
        
        elif file_extension == '.tif':
            ### Version courte ###
            mask_reprj.rio.to_raster(output_file)
            
            ### Version longue ###
# =============================================================================
#             # Ouvrir le fichier : 
#             _data_tmp = rasterio.open(data, 'r')
#             # Récupérer le profil :
#             profile_ = _data_tmp.profile
#             # Mettre à jour le profil
#             profile_.update(transform = transform_,
#                             dtype = str(mask_reprj.band_data.dtype),
#                             crs = 'epsg:'+str(EPSG_out), 
#                             width = width_, 
#                             height = height_,
#                             )
#             _data_tmp.close()
# 
#             with rasterio.open(output_file, 'w', **profile_) as out_f:
#                 out_f.write_band(1, mask_reprj.band_data)
# =============================================================================
        
        return mask_reprj
    
    #%%% ° Soil depth
    elif data_type.casefold() in ["soil depth", "soildepth", "ucs_pp_bzh"]:
        data_df = gpd.read_file(data) # data_df = soil depth
        data_epsg = data_df.crs.to_epsg()
        
        #% Calcul des profondeurs locales moyennes pondérées
        print('\nComputing local weighted depth averages...')
        soil_depth_limit = 140 # valeur semi-arbitraire
        class_depth_convert = {'0':0,
                               '1':soil_depth_limit - (soil_depth_limit-100)/2,
                               '2':90,
                               '3':70,
                               '4':50,
                               '5':30,
                               '6':10,
                               }
        data_df['EPAIS_1_NUM'] = [class_depth_convert[val] for val in data_df['EPAIS_DOM'].values] 
        data_df['EPAIS_2_NUM'] = [class_depth_convert[val] for val in data_df['EPAIS_2'].values] 
        data_df['EPAIS_1_2'] = (data_df['EPAIS_1_NUM'] * data_df['P_EPAISDOM'] + data_df['EPAIS_2_NUM'] * data_df['P_EPAIS2']) / (data_df['P_EPAISDOM'] + data_df['P_EPAIS2'])
        data_df['EPAIS_1_2'] = data_df['EPAIS_1_2']/100 # Convertir cm vers m
        
        #% Reprojection dans le CRS voulu
        print('\nReprojecting...')
        print('   from epsg:{} to epsg:{}'.format(str(data_epsg), str(EPSG_out)))
        data_df.to_crs('epsg:'+str(EPSG_out), inplace = True)
        
        #% Rasterisation
        print('\nRasterizing...')
        x_min = 74000
        y_max = 6901000
        bounds_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(2154), 
                                              rasterio.crs.CRS.from_epsg(EPSG_out), 
                                              [74000], [6901000]) # Limites (larges) de la Bretagne en L93
        x_min = bounds_conv[0][0] // reso_m * reso_m
        y_max = bounds_conv[1][0] // reso_m * reso_m
        
        # Décalage d'un demi pixel
        if reso_m == 75:
            x_min = nearest(x = x_min) - 75/2
            y_max = nearest(x = y_max) + 75/2
        else:
            x_min = x_min - reso_m/2
            y_max = y_max + reso_m/2
        
        transform_ = Affine(reso_m, 0.0, x_min,  
                            0.0, -reso_m, y_max)
        
# =============================================================================
#         transform_ = Affine(reso_m, 0.0, x_min,  
#                             0.0, reso_m, 670500)
# =============================================================================
        
        width_ = 377000 // reso_m + 1
        height_ = 227000 // reso_m + 1
        
        raster_data = rasterio.features.rasterize(
            [(val['geometry'], val['EPAIS_1_2']) for i, val in data_df.iterrows()],
            out_shape = (height_, width_),
            transform = transform_,
            fill = np.NaN,
            all_touched = True)
        
        #% Convertir en DataSet
        print('\nConverting into xarray.Dataset...')
        # Converting to xarray dataarray:
        dataarray_ = xr.DataArray(raster_data, 
                                  coords = [np.arange(y_max,
                                                      y_max - reso_m * height_,
                                                      -reso_m).astype(np.float32),
                                            np.arange(x_min, 
                                                      x_min + reso_m * width_, 
                                                      reso_m).astype(np.float32)], 
                                  dims = ['y', 'x'])
        # NB : La fonction 'range()' est évitée car elle renvoie des entiers
        # QGIS n'arrive pas à détecter le CRS lorsque les axes sont des entiers
        
# =============================================================================
#         dataarray_ = xr.DataArray(raster_data.transpose(), 
#                                   coords = [range(x_min, 
#                                                   x_min + reso_m * width_, 
#                                                   reso_m),
#                                             range(y_max,
#                                                   y_max - reso_m * height_,
#                                                   -reso_m)], 
#                                   dims = ['x', 'y'])
# =============================================================================
        
        # Converting to xarray dataset:
        dataset_ = dataarray_.to_dataset(name = 'soildepth')
        
        # Adding attributes:
        dataset_.rio.write_crs("epsg:"+str(EPSG_out), inplace = True)
        dataset_.x.attrs = {'standard_name': 'projection_x_coordinate',
                                    'long_name': 'x coordinate of projection',
                                    'units': 'Meter'}
        dataset_.y.attrs = {'standard_name': 'projection_y_coordinate',
                                    'long_name': 'y coordinate of projection',
                                    'units': 'Meter'}
        dataset_.soildepth.attrs = {'grid_mapping': "spatial_ref"} # A supprimer ???
        # dataset_.assign_coords(spatial_ref = dataset_.spatial_ref)
        # dataset_.rio.write_crs("epsg:"+str(EPSG_out), inplace = True)
        

        #% Export :
        print('\nCompressing and saving...')
        
        full_file_name = ' '.join([file_name, 
                                     'res='+str(reso_m)+'m', 
                                     'CRS='+str(EPSG_out),
                                     'lim='+str(soil_depth_limit),
                                     ])
        output_file = os.path.join(input_folder, 
                                   full_file_name + '.nc')
        print('   --> result exported to:\n   --> ' + output_file)
        
        var = main_var(dataset_)
        # dataset_[var].encoding['_FillValue'] = None # ou np.nan ?
        # ERREUR : dataset_.to_netcdf(output_file, encoding = {var: {'zlib': True, 'dtype': 'float32', 'scale_factor': 0.00000001, '_FillValue': np.nan},})
        dataset_.to_netcdf(output_file)
        
        #% Fichiers pour CWatM
        topsoil_ds = dataset_.where(dataset_['soildepth']<0.30, 0.30)
        topsoil_ds = topsoil_ds.where(~np.isnan(dataset_), np.nan)
        # topsoil_ds = topsoil_ds.where(~np.isnan(dataset_), 0)
        subsoil_ds = dataset_ - topsoil_ds
        output_top = os.path.join(input_folder, 
                                  'soildepth1_' + full_file_name + '.nc')
        output_sub = os.path.join(input_folder, 
                                  'soildepth2_' + full_file_name + '.nc')
        
        # topsoil_ds.to_netcdf(output_top, encoding = {var: {'zlib': True, 'dtype': 'float32', 'scale_factor': 0.00000001, '_FillValue': np.nan},})
        topsoil_ds.to_netcdf(output_top)
        # subsoil_ds.to_netcdf(output_sub, encoding = {var: {'zlib': True, 'dtype': 'float32', 'scale_factor': 0.00000001, '_FillValue': np.nan},})
        subsoil_ds.to_netcdf(output_sub)
        """
        La compression (27x plus petit) fait planter CWatM lorsqu'il utilise
        l'option use_soildepth_as_GWtop
        """

        
        return dataset_
        
    #%%% DRIAS-Climat 2022 (netcdf)
    # Données SAFRAN (tas, prtot, rayonnement, vent... ) "EXPLORE2-Climat 2022" 
    # -------------------------------------------------------------------------
    elif data_type.replace(" ", "").casefold() in ['drias2022', 'climat2022', 'drias-climat2022']:
        
        # Load
        data_ds = load_any(data)
        
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        # Backup of attributes and encodings
        attrs = data_ds[var].attrs.copy()
        encod = data_ds[var].encoding.copy()
        
        # If it contains time_bnds (periods time)
        if ('time_bnds' in data_ds.coords) | ('time_bnds' in data_ds.data_vars):
            # The closing bounds is used for time coordinates
            attributes = data_ds['time'].attrs.copy()
            data_ds['time'] = data_ds.time_bnds.loc[{'bnds': 1}]
            data_ds['time'].attrs = attributes
            # time_bnds and bnds are removed
            data_ds = data_ds.drop_dims('bnds')
            print("   _ 'time_bnds' and 'bnds' removed")
        
        # Convert units
        if var in ['evspsblpotAdjust', 'prsnAdjust', 'prtotAdjust']:
            data_ds[var] = data_ds[var]/1000*(60*60*24) # conversion from mm.s-1 to m.d-1
            data_ds[var].attrs = attrs
            data_ds[var].attrs['units'] = 'm.d-1'
            data_ds[var].encoding = encod
            print('   _ Units converted from mm/s to m/d')
        
# =============================================================================
#         # Remove compression (too long to load in QGIS otherwise)
#         data_ds[var].encoding['zlib'] = False
# =============================================================================
        
        return data_ds
        
    #%%% DRIAS-Eau 2024 (netcdf)
    # Données SURFEX (evapc, drainc, runoffc, swe, swi...) "EXPLORE2-SIM2 2024" 
    # -------------------------------------------------------------------------
    elif data_type.replace(" ", "").casefold() in ['sim2024', 'drias-eau2024',
                                                   'driaseau2024']:
        
        # Load
        xr_kwargs = {}
# =============================================================================
#         # Particular case for SSWI (grid_mapping is bugged)
#         sswi_pattern = re.compile('.*(SSWI).*')
#         if len(sswi_pattern.findall(data)) > 0:
#             xr_kwargs['drop_variables'] = 'LambertParisII'
# =============================================================================
        xr_kwargs['drop_variables'] = 'LambertParisII'
        
        data_ds = load_any(data, **xr_kwargs)
        
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        # Backup of attributes and encodings
        attrs = data_ds[var].attrs.copy()
        encod = data_ds[var].encoding.copy()
        
        # If it contains time_bnds (periods time)
        if ('time_bnds' in data_ds.coords) | ('time_bnds' in data_ds.data_vars):
            # The closing bounds is used for time coordinates
            attributes = data_ds['time'].attrs.copy()
            data_ds['time'] = data_ds.time_bnds.loc[{'bnds': 1}]
            data_ds['time'].attrs = attributes
            # time_bnds and bnds are removed
            data_ds = data_ds.drop_dims('bnds')
            print("   _ 'time_bnds' and 'bnds' removed")
        
        # Convert units
        if var in ['DRAINC', 'EVAPC', 'RUNOFFC']:
            data_ds[var] = data_ds[var]/1000 # conversion from mm.d-1 to m.d-1
            data_ds[var].attrs = attrs
            data_ds[var].attrs['units'] = 'm.d-1'
            data_ds[var].encoding = encod
            print('   _ Units converted from mm/d to m/d')
        
# =============================================================================
#         # Particular case for SSWI (_FillValue is wrong)
#         if ('missing_values' in data_ds[var].encoding) \
#             & ('_FillValue' in data_ds[var].encoding):
#             print(data_ds[var].encoding['missing_value'])
#             print(data_ds[var].encoding['_FillValue'])
# =============================================================================
# =============================================================================
#             data_ds[var].encoding['_FillValue'] = 999999
#             data_ds[var].encoding.pop('missing_value')
# =============================================================================
# ======= NOT ACCURATE ENOUGH =================================================
#         # Also, if SSWI and seasonal, dates should be shifted 45 days back
#         sswi_season_pattern = re.compile('.*(SSWI_seas).*')
#         if len(sswi_season_pattern.findall(data)) > 0:
#             encodings = data_ds['time'].encoding.copy()
#             data_ds['time'] = data_ds['time'] - pd.Timedelta(days = 45)
#             data_ds['time'].encoding = encodings
# =============================================================================
        
# =============================================================================
#         # Remove compression (too long to load in QGIS otherwise)
#         data_ds[var].encoding['zlib'] = False
# =============================================================================
        
        return data_ds
    
    #%%% C3S seasonal forecast
    # https://cds.climate.copernicus.eu/datasets/seasonal-original-single-levels?tab=overview
    elif data_type.casefold() in ["c3s"]:
        data_ds = load_any(data, 
                           # decode_times = True, 
                           # decode_coords = 'all'
                           )

        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variables are: {', '.join(var)}")
        # Backup of attributes and encodings
        attrs = dict()
        encod = dict()
        for v in var:
            attrs[v] = data_ds[v].attrs.copy()
            encod[v] = data_ds[v].encoding.copy()
        
        # Format time coordinate
        data_ds = data_ds.squeeze('forecast_reference_time').drop('forecast_reference_time')
        data_ds = data_ds.swap_dims({'forecast_period': 'time'}).drop('forecast_period')
# =========== implemented in load_any =========================================
#         data_ds = data_ds.rename({'valid_time': 'time'})
# =============================================================================
        
        return data_ds
        
    
    #%%% * DRIAS
    elif data_type.casefold() in ["drias"]:
        print(f'\nProcessed file = {data}')
        
        with xr.open_dataset(data, decode_coords = 'all') as data_ds:
            data_ds.load() # to unlock the resource
        
        #% Formating
        # -----------
        print('\nPre-formating...')
        # Drop useless variables
        data_ds = data_ds.drop(['i', 'j', 'lat', 'lon'])
        print('   _ Additional coords (i, j, lat, lon) dropped')
        # Add CRS
        if not EPSG_in: # EPSG = None, by default
            if 'spatial_ref' not in list(data_ds.coords) + list(data_ds.data_vars):
                EPSG_in = 27572
                data_ds.rio.write_crs(f"epsg:{EPSG_in}", inplace = True)
                print(f"   _ The Coordinates Reference System is not indicated in the original file. By default, epsg:{EPSG_in} is used")
            else:
                EPSG_in = data_ds.rio.crs.to_epsg()
        
# =============================================================================
#         data_ds = data_ds.rename(prtotAdjust = 'pr')
#         print(f"   _ Precipitation variable name modified: prtotAdjust -> pr")
# =============================================================================
        # Get main variable
        var = main_var(data_ds)
        print(f"   _ Main variable is: {var}")
        
        data_ds[var] = data_ds[var]/1000*(60*60*24) # conversion from from mm.s-1 to m.d-1
        data_ds[var].attrs['units'] = 'm.d-1'
        print('   _ Units converted from mm/s to m/d')
        
        #% Reproject in defined CRS
        # -------------------------
        print('\nReprojecting...')
        print('   _ From epsg:{} to epsg:{}'.format(str(EPSG_in), str(EPSG_out)))
        
        # Resolution
        coord1 = list(data_ds.coords)[1]
        coord2 = list(data_ds.coords)[2]
        if reso_m is None:
            print('   _ Input resolution is taken as output resolution based on {}'.format(coord1))
            reso = float(data_ds[coord1][1] - data_ds[coord1][0])
            if data_ds[coord1].units[0:6].casefold() == 'degree':
                reso_m = round(reso*111200)
            elif data_ds[coord1].units[0:1].casefold() == 'm':
                reso_m = reso
        print('   _ Resolution: {} km'.format(reso_m/1000))
        
# =============================================================================
#         data_coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(EPSG_in), 
#                                                    rasterio.crs.CRS.from_epsg(EPSG_out), 
#                                                    [data_ds.x.values.min()], [data_ds.y.values.max()])
#         if reso_m == 75:
#             x_min = ac.nearest(x = data_coords_conv[0][0] - reso_input)
#             y_max = ac.nearest(x = data_coords_conv[1][0] + reso_input)
#         else:
#             x_min = (data_coords_conv[0][0] - reso_input) // reso_m * reso_m - reso_m/2
#             y_max = (data_coords_conv[1][0] + reso_input) // reso_m * reso_m + reso_m/2    
# =============================================================================
        
        
        if coords_extent == 'from_input':
            reprj_ds = data_ds.rio.reproject(
                dst_crs = 'epsg:'+str(EPSG_out), 
                resampling = rasterio.enums.Resampling(5),
                )
            print('   _ Data reprojected based on the extent and resolution of input data')
            print('     (user-defined resolution is not taken into account)')
        
        else: # In all other cases, x_min, x_max, y_max and y_min will be determined before .rio.reproject()
            if type(coords_extent) == str & coords_extent.casefold() in ["bretagne", "brittany"]:
                # Emprise sur la Bretagne
                if EPSG_out == 3035:   #LAEA
                    x_min = 3164000
                    x_max = 3572000
                    y_max = 2980000
                    y_min = 2720000
                elif EPSG_out == 2154: #Lambert-93
                    x_min = 70000
                    x_max = 460000
                    y_max = 6909000
                    y_min = 6651000
                elif EPSG_out == 4326: #WGS84
                    x_min = -5.625
                    x_max = -0.150
                    y_max = 49.240
                    y_min = 46.660
                print('   _ Extent based on Brittany')
            
            elif type(coords_extent) == list:
                [x_min, x_max, y_min, y_max] = coords_extent
                print('   _ User-defined extent')
            
            # Alignement des coordonnées selon la résolution (valeurs rondes)
            x_min = nearest(x = x_min, res = reso_m, x0 = 0)
            x_max = nearest(x = x_max, res = reso_m, x0 = 0)
            y_max = nearest(y = y_max, res = reso_m, y0 = 0)
            y_min = nearest(y = y_min, res = reso_m, y0 = 0)
            print("   _ Bounds:")
            print("               {}".format(y_max))
            print("      {}           {}".format(x_min, x_max))
            print("               {}".format(y_min))
            
            transform_ = Affine(reso_m, 0.0, x_min,  
                                0.0, -reso_m, y_max)
            
# =============================================================================
#         width_ = int(data_ds.x.shape[0] * reso_input / reso_m //1 +1)
#         height_ = int(data_ds.y.shape[0] * reso_input / reso_m //1 +1)
# =============================================================================
            
            dst_height = (y_max - y_min)//reso_m
            dst_width = (x_max - x_min)//reso_m
            
            reprj_ds = data_ds.rio.reproject(
                dst_crs = 'epsg:'+str(EPSG_out), 
                shape = (dst_height, dst_width),
                transform = transform_, 
                resampling = rasterio.enums.Resampling(5),
                # nodata = np.nan,
                )


# =============================================================================
#         # Adding attributes:
#         ds_reprj.rio.write_crs("epsg:"+str(EPSG_out), inplace = True)
#         ds_reprj.x.attrs = {'standard_name': 'projection_x_coordinate',
#                                     'long_name': 'x coordinate of projection',
#                                     'units': 'Meter'}
#         ds_reprj.y.attrs = {'standard_name': 'projection_y_coordinate',
#                                     'long_name': 'y coordinate of projection',
#                                     'units': 'Meter'}
#         ds_reprj.soildepth.attrs = {'grid_mapping': "spatial_ref"}
# =============================================================================
        
# =============================================================================
#         #% Convert values units :
#         # from [kg m-2s-1] to [mm d-1] 
#         ds_reprj[var] = ds_reprj[var] *60*60*24
#         ds_reprj.pr.attrs['units'] = 'mm.d-1'
#         # -> plutôt appliquer un facteur de conversion dans les settings de CWatM
# =============================================================================

        #% Export :
        print("\nPreparing export, formating encodings and attributes...")
        print('   _ Output file type: {}'.format(file_extension))
        
        reprj_ds[coord1].encoding = data_ds[coord1].encoding
        reprj_ds[coord2].encoding = data_ds[coord2].encoding
        print("   _ Coords attributes transferred")
        
        if 'original_shape' in reprj_ds[var].encoding.keys():
            reprj_ds[var].encoding.pop('original_shape')
            reprj_ds[coord1].encoding.pop('original_shape')
            reprj_ds[coord2].encoding.pop('original_shape')
            print("   _ 'original_shape' has been removed")
        
        
        # If it is the PrecipitationMaps, it is necessary to erase the x and y
        # '_FillValue' encoding, because precipitation inputs are taken as 
        # format model by CWatM
        if var == 'tp': 
            reprj_ds.x.encoding['_FillValue'] = None
            reprj_ds.y.encoding['_FillValue'] = None
            print("   _ Fill Value removed from x and y")
        
        # reprj_ds.x.encoding['_FillValue'] = None
        # reprj_ds.y.encoding['_FillValue'] = None
        # reprj_ds[var].encoding['_FillValue'] = np.nan
        
        # Compression (not lossy)
        reprj_ds[var].encoding['zlib'] = True
        reprj_ds[var].encoding['complevel'] = 4
        reprj_ds[var].encoding['contiguous'] = False
        reprj_ds[var].encoding['shuffle'] = True
        print('   _ Compression x4 without loss (zlib)')
        
        output_file = os.path.join(input_folder,
                                   ' '.join([file_name, 
                                             'res='+str(reso_m)+'m', 
                                             'CRS='+str(EPSG_out),
                                             ]) + file_extension)
        
        reprj_ds.to_netcdf(output_file)      
        """
        La compression (2x plus petit) fait planter QGIS lorsqu'il essaye
        de lire le fichier comme un maillage.
        Il est nécessaire d'effacer la _FillValue des coordonnées x et y.
        """
        
        print('\n -> Successfully exported to:\n' + output_file)
        
        return reprj_ds


    #%%% ° CORINE Land Cover
    elif data_type.casefold() in ["corine", "cld", "corine land cover"]:
        
        (folder_name, file_name) = os.path.split(data)
        (file_name, extension) = os.path.splitext(file_name)
        
        data_years = [1990, 2000, 2006, 2012, 2018]
        y = data_years[4]
        
        land_convert = [
            [23, 24, 25, 26, 27, 28, 29], # 1. forests
            [12, 15, 16, 17, 18, 19, 20, 21, 22], # 2. grasslands and non-irrigated crops
            [14], # 3. rice fields
            [13, ], # 4. irrigated crops
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], # 5. sealed lands
            [40, 41, 42, 43], # 6. water surfaces
            # [7, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39], # x. sol nu
            ]
        
# =============================================================================
#         with xr.open_dataset(data) as data_ds:
#             data_ds.load() # to unlock the resource
# =============================================================================
        
        #%%%% Découpe du fichier (mondial) sur la Bretagne 
        # -----------------------------------------------
        with rasterio.open(data, 'r') as data:
            # data_profile = data.profile
            # data_crs = data.crs # epsg:3035
            # data_val = data.read()[0] # np.ndarray
            #     # 46000 lignes
            #     # 65000 colonnes
            # data_dtype = data.dtypes[0] # int8
            
            # Définition du périmètre de découpe
# =============================================================================
#             shapes = Polygon([
#                 (3188000, 2960000),
#                 (3188000 + 364000, 2960000),
#                 (3188000 + 364000, 2960000 - 231000),
#                 (3188000, 2960000 - 231000),
#                 (3188000, 2960000)])
# =============================================================================
# =============================================================================
#             shapes = rasterio.warp.transform_geom(
#                 {'init': 'epsg:3035'},
#                 data.crs,
#                 {'type': 'Polygon',
#                  'coordinates': [[
#                      (3188000, 2960000),
#                      (3188000 + 364000, 2960000),
#                      (3188000 + 364000, 2960000 - 231000),
#                      (3188000, 2960000 - 231000),
#                      (3188000, 2960000)]]}
#                 )
# =============================================================================
            with fiona.open(r"D:\2- Postdoc\2- Travaux\2- Suivi\2- CWatM\2022-01-12) Synthèse inputs\Mask_Bretagne_3035_1km.shp", "r") as shapefile:
                shapes = [feature["geometry"] for feature in shapefile]
            
            # Découpe
            out_raster, out_transform = rasterio.mask.mask(data, 
                                                          shapes, 
                                                          crop = True)
            
            crp_data = out_raster[0]
            
            # Mise à jour des attributs
            # data_profile = data.meta
            data_profile = data.profile
            data_profile.update({
                # "driver": "Gtiff",
            	"height": crp_data.shape[0],
            	"width": crp_data.shape[1],
            	# "nodata": -128,
            	"transform": out_transform})
            
            # Export (fichier facultatif)
            output_file = os.path.join(folder_name, file_name + '_Brittany.tif')
            with rasterio.open(output_file, 'w', **data_profile) as output_f:
                output_f.write_band(1, crp_data)
            print('\nCropped file has been successfully exported')
            
        
        #%%%% Extraction des types d'occupation du sol
        # -------------------------------------------
        data_profile['dtype'] = 'float32' # pour limiter la taille sur disque
        
        for i in range(0,6):
            # Création d'une carte de mêmes dimensions, avec la valeur 1 sur
            # les pixels correspondant au landcover voulu, et 0 sur les autres
            print('\nClass ' + str(i+1) + ":")
            count = np.zeros(crp_data.shape, dtype = data_profile['dtype'])
            count = count.astype('float32') # pour limiter la taille sur disque
            
            for code in land_convert[i]:
                # count[crp_data == code] += 1 # Normalement ça ne dépasse jamais 1
                count[crp_data == code] = 1
            
            # Export en résolution initiale (fichiers facultatifs)
            output_file = os.path.join(folder_name, file_name + '_class' + str(i+1) + '.tif')
            with rasterio.open(output_file, 'w', **data_profile) as output_f:
                output_f.write_band(1, count)
            print('   - Successfully exported into initial-resolution *.tif')

          

            # Reprojection and conversion of counts into percentages
            # dst_trsfm = Affine(1000, 0, 900000,
            #                    0, -1000, 5500000)
            # dst_trsfm = Affine(1000, 0, 3188000,
            #                    0, -1000, 2960000)
            dst_trsfm = Affine(1000, 0, 3165000,
                               0, -1000, 2954000)
            
            # data_reprj = np.zeros((4600, 6500), dtype = np.float32)
            # data_reprj = np.zeros((231, 364), dtype = np.float32)
            data_reprj = np.zeros((258, 407), dtype = np.float32)
            
            dst_data_profile = data_profile.copy()
            dst_data_profile.update({
            	"height": data_reprj.shape[0],
            	"width": data_reprj.shape[1],
            	"transform": dst_trsfm,
                "nodata": np.nan})
            
            rasterio.warp.reproject(count, 
                                    destination = data_reprj, 
                                    src_transform = data_profile['transform'],
                                    src_crs = data_profile['crs'],
                                    src_nodata = data_profile['nodata'],
                                    dst_transform = dst_data_profile['transform'],
                                    dst_crs = dst_data_profile['crs'],
                                    dst_nodata = dst_data_profile['nodata'],
                                    resampling = rasterio.enums.Resampling(5),
                                    )
            
            # Export en résolution finale (fichiers intermédiaires nécessaires)
            output_file = os.path.join(folder_name, 
                                       '_'.join([file_name, '_class' + str(i+1), '1000m.tif'])
                                       )
            with rasterio.open(output_file, 'w', **dst_data_profile) as output_f:
                output_f.write_band(1, data_reprj)
            print('   - Successfully exported into coarse-resolution *.tif')
            
            
        #%%%% Conversion des derniers fichiers créés (*.tif) en *.nc
        # ---------------------------------------------------------
        var_names = [
            'fracforest',
            'fracgrassland',
            'fracirrNonPaddy',
            'fracirrPaddy',
            'fracsealed',
            'fracwater',
            ]
        
        # Initialization:
        i = 0
        with xr.open_dataset(os.path.join(folder_name, '_'.join([file_name, '_class' + str(i+1), '1000m.tif']))) as data_ds:
            data_ds.load()
        # data_ds = data_ds.squeeze('band').drop('band')
        data_ds = data_ds.rename(band = 'time')
        # data_ds = data_ds.reindex(time = [datetime.datetime(2018, 1, 31)])
        data_ds = data_ds.assign_coords({'time': ('time', [datetime.datetime(y, 1, 31)])})
        data_ds = data_ds.rename(band_data = var_names[i])
 
        for i in range(1,6):
            with xr.open_dataset(os.path.join(folder_name, '_'.join([file_name, '_class' + str(i+1), '1000m.tif']))) as data_tmp:
                data_tmp.load()
            # data_tmp = data_tmp.squeeze('band').drop('band')
            data_tmp = data_tmp.rename(band = 'time')
            # data_tmp = data_tmp.reindex(time = [datetime.datetime(2018, 1, 31)])
            data_tmp = data_tmp.assign_coords({'time': ('time', [datetime.datetime(y, 1, 31)])})
            data_tmp = data_tmp.rename(band_data = var_names[i])
            data_ds[var_names[i]] = data_tmp[var_names[i]]
        
        # Rectification de la normalisation des pourcentages
# =============================================================================
#         # data_ds.fillna(0)
#         sum_norm = data_ds[var_names[0]]+data_ds[var_names[1]]+data_ds[var_names[2]]+data_ds[var_names[3]]+data_ds[var_names[4]]+data_ds[var_names[5]]
#         for i in range(0,6):
#             data_ds[var_names[i]] = data_ds[var_names[i]]/sum_norm
# =============================================================================
        
        data_ds.rio.write_crs('epsg:3035', inplace = True)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                            'long_name': 'x coordinate of projection',
                            'units': 'Meter'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                            'long_name': 'y coordinate of projection',
                            'units': 'Meter'}
        output_file = os.path.join(folder_name, 'fractionLandcover_Bretagne_CORINE_{}.nc'.format(str(y)))
        
        # NB : Il est nécessaire de faire disparaître les valeurs nan
# =============================================================================
#         data_ds['fracforest'].encoding['_FillValue'] = 0 # ou None ??
#         data_ds['fracgrassland'].encoding['_FillValue'] = 0 # ou None ??
#         data_ds['fracirrNonPaddy'].encoding['_FillValue'] = 0 # ou None ??
#         data_ds['fracirrPaddy'].encoding['_FillValue'] = 0 # ou None ??
#         data_ds['fracsealed'].encoding['_FillValue'] = 0 # ou None ??
#         data_ds['fracwater'].encoding['_FillValue'] = 0 # ou None ??
# =============================================================================
        
        data_ds.to_netcdf(output_file)

            
    #%%% ° Observatoire botanique de Brest (2018-2019)
    elif data_type.casefold() in ["observatoire", "obb"]:
        land_convert = [
            [0, 0, 0], # 1. forests
            [0, 0, 0], # 2. grasslands and non-irrigated crops
            [0, 0, 0], # 3. rice fields
            [0, 0, 0], # 4. irrigated crops
            [0, 0, 0], # 5. sealed lands
            [0, 0, 0], # 6. water surfaces
            # [7, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39], # x. sol nu
            ]
        return 'Pas encore implémenté'
    
    #%%% ° CES OSO
    elif data_type.casefold() in ['ces oso', 'oso', 'ces']:
        return 'Pas encore implémenté'
    
    
    #%%% ° Crop coefficients, version "better"
    elif data_type.casefold() in ['crop', 'crop coeff', 'crop coefficient']:
        #%%%% Initialization:
        landcover_motif = re.compile('cropCoefficient[a-zA-Z]*')
        pos = landcover_motif.search(file_name).span()
        landcover = file_name[15:pos[1]]
        name = os.path.splitext(file_name)[0][0:pos[1]]
        print(f'\nProcessed landcover = {landcover}')
        print("___________________")
        
        
        with xr.open_dataset(
                data,
                decode_coords = 'all',
                ) as data:
            data.load()
        
        #%%%% Reprojection:
        print('\nReprojecting...')
        
        if not EPSG_in: # EPSG = None, by default
            if 'spatial_ref' not in list(data.coords) + list(data.data_vars):
                print("   Le SCR n'est pas renseigné dans les données initiales. Par défaut, le WGS84 est utilisé")
                EPSG_in = 4326
            else:
                EPSG_in = data.rio.crs.to_epsg()
        print("   From epsg:{} to espg:{}".format(EPSG_in, EPSG_out))
        data.rio.write_crs("epsg:{}".format(EPSG_in), inplace = True)
        
        # Emprise sur la Bretagne
        if EPSG_out == 3035:   #LAEA
            x_min = 3164000
            x_max = 3572000
            y_max = 2980000
            y_min = 2720000
        elif EPSG_out == 2154: #Lambert-93
            x_min = 70000
            x_max = 460000
            y_max = 6909000
            y_min = 6651000
# =============================================================================
#         # To properly implement management of lat/lon, reso_m should be upgraded
#         # with a system including reso_deg (future developments)
#         elif EPSG_out == 4326: #WGS84 (in this case, reso_m should be in ° instead of m)
#             x_min = -5.625
#             x_max = -0.150
#             y_max = 49.240
#             y_min = 46.660
# =============================================================================

        # Alignement des coordonnées selon la résolution (valeurs rondes)
        x_min = nearest(x = x_min, res = reso_m, x0 = 0)
        x_max = nearest(x = x_max, res = reso_m, x0 = 0)
        y_max = nearest(y = y_max, res = reso_m, y0 = 0)
        y_min = nearest(y = y_min, res = reso_m, y0 = 0)
        print("   Final bounds:")
        print("               {}".format(y_max))
        print("      {}           {}".format(x_min, x_max))
        print("               {}".format(y_min))

        # Reproject
        if reso_m is None:
            coord1 = list(data.coords)[1]
            print('NB : La resolution est déterminée à partir des {}\n'.format(coord1))
            reso = float(data[coord1][1] - data[coord1][0])
            if data[coord1].units[0:6].casefold() == 'degree':
                reso_m = round(reso*111200)
            elif data[coord1].units[0:1].casefold() == 'm':
                reso_m = reso
        print('   Resolution: {} km'.format(str(reso_m/1000)))
        
        dst_height = (y_max - y_min)//reso_m
        dst_width = (x_max - x_min)//reso_m
        
        data_reprj = data.rio.reproject(
            dst_crs = 'epsg:'+str(EPSG_out), 
            # resolution = (1000, 1000),
            shape = (dst_height, dst_width),
            transform = Affine(reso_m, 0.0, x_min,
                               0.0, -reso_m, y_max), 
            resampling = rasterio.enums.Resampling(5),
            nodata = np.nan)
        
        
        #%%%% Preparing export:
        print("\nPreparing export...")
# =============================================================================
#         # Change the order of coordinates to match QGIS standards:
#             # Normally, not necessary
#         data_reprj = data_reprj.transpose('time', 'y', 'x')
#         print("      order of coordinates = 'time', 'y', 'x'")
# =============================================================================
        # Formatting to match standards (encodings and attributes)
        print("   Formating encodings and attributes")
# =============================================================================
#         for c in ['time', 'latitude', 'longitude']:
#             data_reprj[c].attrs = data[c].attrs
#             data_reprj[c].encoding = data[c].encoding
#         for f in _fields_intersect:
#             data_reprj[f].attrs = data[f].attrs
#             data_reprj[f].encoding = data[f].encoding
# =============================================================================
        # Insert georeferencing metadata to match QGIS standards:
        # data_reprj.rio.write_crs("epsg:4326", inplace = True)
        # print("      CRS set to epsg:4326")
                
        data_reprj.x.encoding = data.lon.encoding
        data_reprj.y.encoding = data.lat.encoding
        data_reprj.x.encoding.pop('original_shape')
        data_reprj.y.encoding.pop('original_shape')
        
        var = main_var(data)
        
        # If it is the PrecipitationMaps, it is necessary to erase the x and y
        # '_FillValue' encoding, because precipitation inputs are taken as 
        # format model by CWatM
        if var == 'tp': 
        # if name == 'Total precipitation daily_mean':
            data_reprj.x.encoding['_FillValue'] = None
            data_reprj.y.encoding['_FillValue'] = None
        
        # Compression (not lossy)
        data_reprj[var].encoding = data[var].encoding
        data_reprj[var].encoding.pop('chunksizes')
        data_reprj[var].encoding.pop('original_shape')
# =============================================================================
#         data_reprj[var].encoding['zlib'] = True
#         data_reprj[var].encoding['complevel'] = 4
#         data_reprj[var].encoding['contiguous'] = False
#         data_reprj[var].encoding['shuffle'] = True
# =============================================================================
        # NB: The packing induces a loss of precision of apprx. 1/1000 of unit,
        # for a quantity with an interval of 150 units. The packing is
        # initially used in the original ERA5-Land data.    
        
        print("   All attributes and encodings transfered")
        

        #%%%% Export :
        print('\nSaving...')          
        output_file = os.path.join(input_folder,
                                   '_'.join([file_name, 
                                            'res='+str(reso_m)+'m', 
                                            'epsg'+str(EPSG_out),
                                             ]) + '.nc')        

        data_reprj.to_netcdf(output_file)
        print("\nLe resultat a bien été exporté dans le fichier : {}".format(output_file))
        
        return data_reprj


###############################################################################
#%%% * Formate les données RHT
def process_rht(shp_file, attrs_file, fields = 'all'):
    """
    Pour rajouter les attributs dans le shapefile, de anière à pouvoir 
    l'afficher facilement dans QGIS.

    Parameters
    ----------
    shp_file : str
        Chemin vers le fichier shapefile
    attrs_file : str
        Chemin vers la table externe d'attributs
    fields : list
        Liste des noms de colonnes que l'on veut insérer dans le shapefile

    Returns
    -------
    Create a new file.
    """
    
    # Inputs
    # ------
    gdf_in = gpd.read_file(shp_file)
    
    df_attrs = pd.read_csv(attrs_file, sep = r";", header = 0, skiprows = 0)
    
    if fields == 'all': fields = list(df_attrs.columns)
    if not isinstance(fields, list): fields = [fields]
    if 'id_drain' not in fields: fields.append('id_drain')
    print('Fields :\n{}'.format(fields))

    # Fusion
    # ------
    gdf_out = gdf_in.merge(df_attrs[fields], left_on = "ID_DRAIN", right_on = "id_drain")
    
    # Export
    # ------
    out_name = os.path.splitext(shp_file)[0] + '_merged.shp'
    gdf_out.to_file(out_name)
    
    return gdf_out    


###############################################################################
#%%% * convert_from_h5_newsurfex (with recessions)
def convert_from_h5_newsurfex(*, input_file, mesh_file, scenario = 'historic', 
                    output_format = 'NetCDF', **kwargs):
    r"""
    % DESCRIPTION:
    This function converts Ronan *.h5 files from SURFEX into NetCDF files, or
    GeoTIFF images, in order to make output files readable by QGIS.
    
    % EXAMPLE:
    >> import geoconvert as gc
    >> gc.convert_from_h5_newsurfex(input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\BZH\REA.h5",
                          mesh_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\BZH\shapefile\maille_meteo_fr_pr93.shp",
                          output_format = "NetCDF",
                          fields = ["REC", "TAS"])
    
    % ARGUMENTS:
    >    
    
    % OPTIONAL ARGUMENTS:
    > output_format = 'NetCDF' (défault) | 'GeoTIFF'
    > scenario = 'historic' | 'RCP2.6' | 'RCP4.5' | 'RCP8.5'
    > kwargs:
        > fields = variable(s) to conserve (among all attributes in input file)
                 = ['ETP', 'PPT', 'REC', 'RUN', 'TAS']
        (One file per variable will be created.)
        
        > dates = for instance : ['2019-01-01', '2019-01-02', ...]
        (If no date is specified, all dates from input file are considered)
    """
    
    #% Get fields argument:
    # ---------------------
    if 'fields' in kwargs:
        fields = kwargs['fields']
        if isinstance(fields, str): fields = [fields]
        else: fields = list(fields) # in case fields are string or tuple
    else:
        print('\n/!\ Fields need to be specified\n')
        
    
    
    for _field in fields:
        print('Processing ' + _field + '...')
        print('   Loading data...')
        #% Load data sets:
        # ----------------
        # _data contains the values, loaded as a pandas dataframe
        _data = pd.read_hdf(input_file, _field + '/' + scenario)
        _data.index.freq = 'D' # Correct the frequency of timestamp, because it
                               # is altered during importation
        _data = _data.iloc[:, 0:-1] # Get rid of the last 'MEAN' column
        _data = _data.transpose()
        
        # _dataset contains the spatial metadata, and will be used as the
        # final output structure
        _dataset = gpd.read_file(mesh_file)
        _dataset.num_id = _dataset.num_id.astype(int) # Convert 'num_id' (str) 
                                                      # into integer
        
        # Only cells present in _data are considered:
        _datasubset = _dataset[_dataset.num_id.isin(_data.index)]
        _datasubset = _datasubset.merge(_data, left_on = "num_id", 
                                        right_index = True)
        _datasubset.index = _datasubset.num_id # replace indexes by id_values
        
        #% Get dates argument: (and build output_name)
        # --------------------
        _basename = os.path.splitext(input_file)[0]
        
        if 'dates' in kwargs:
            dates = kwargs['dates']
            if isinstance(dates, str): 
                output_file = '_'.join([_basename, dates, _field])
                dates = [dates]
            else: 
                dates = list(dates) # in case dates are tuple
                output_file = '_'.join([_basename, dates[0], 'to', dates[-1], _field])
        else:
            dates = _data.columns # if not input_arg, dates = all
            output_file = '_'.join([_basename, scenario, _field])
        
        #% Exports:
        # ---------       
        profile_base = {'driver': 'NetCDF',
                        'dtype': 'float32',
                        'nodata': None,
                        'width': 37,
                        'height': 23,
                        'count': 1,
                        # 'count': len(dates),
                        'crs': rio.crs.CRS.from_epsg(27572),
                        'transform': Affine(8000, 0.0, 56000, 0.0, 8000, 2261000),
                        # values deducted from Xlamb and Ylamb
                        # can also be found from QGIS: "X (ou Y) du sommet le plus proche"
                        'tiled': False,
                        'interleave': 'band'}
        
    # =============================================================================
    #     # Getting bounds from polygons is less precise:
    #     _datasubset.geometry.total_bounds[0:1]
    #     # >> [ 107438.43514434074, 6697835.528522245 ] in epsg:2154
    #     Affine(8000, 0.0, 56092.06862427108, 0.0, 8000, 2260917.5598924947)
    #     # more precise values: 57092.06862427143, 2259917.559892499
    #     #   --> does not improve much...
    # =============================================================================
    
    # =============================================================================
    #     # Using polygon limits instead of polygon centers is less precise:
    #     rasterized_data = rasterio.features.rasterize(
    #         [(_dataval.loc['geometry'], _dataval.loc[pd.to_datetime(_date)]) for i, _dataval in _datasubset.to_crs(27572).iterrows()],
    #         out_shape = (profile_base['height'], profile_base['width']),
    #         transform = profile_base['transform'],
    #         fill = 0,
    #         all_touched = True)
    #         # dtype = rasterio.uint8
    # =============================================================================
        
        #% Add coordinates of the center of each polygon, as a POINT object:
        # ------------------------------------------------------------------
        _datasubset['centers'] = [Point(x_y) 
                                  for x_y in zip(_datasubset.loc[:, 'Xlamb'], 
                                                 _datasubset.loc[:, 'Ylamb'])]
        # NB: Coordinates are here in Lambert Zone II (epsg:27572)    
        
# =============================================================================
#    #{a}     # Previous version, creating a raster per date (very slow):
#             rasterized_data = rasterio.features.rasterize(
#             [(_dataval.loc['centers'], _dataval.loc[pd.to_datetime(_date)]) 
#               for i, _dataval in _datasubset.iterrows()],
#             out_shape = (profile_base['height'], profile_base['width']),
#             transform = profile_base['transform'],
#             fill = np.NaN,
#             all_touched = True)
#             # dtype = rasterio.uint8
# =============================================================================
        
        #% Create a raster mask:
        # ---------------------
        rasterized_mask = rasterio.features.rasterize(
            [(_dataval.loc['centers'], _dataval.loc['num_id']) 
             for i, _dataval in _datasubset.iterrows()],
            out_shape = (profile_base['height'], profile_base['width']),
            transform = profile_base['transform'],
            fill = np.NaN,
            all_touched = True)
            # dtype = rasterio.uint16
        
# =============================================================================
#         #% Apercu visuel rapide :
#         plt.imshow(rasterized_mask, origin = 'lower')
# =============================================================================
        
        #% Build a xarray based on the previous mask:
        # -------------------------------------------
        print('   Building an xarray...')
        # Initialization:
        array3D = np.full((len(dates), 
                           profile_base['height'], 
                           profile_base['width']), np.nan)
        
        # Filling:
        for (_y, _x), _id_val in np.ndenumerate(rasterized_mask):
            if not np.isnan(_id_val):
                array3D[:, _y, _x] = _datasubset.loc[_id_val].iloc[10:-1]
        
        # Converting to xarray dataarray:
        dataarray = xr.DataArray(array3D, 
                                  coords = [dates, 
                                            np.arange(2265000,
                                                      2265000 + 8000*profile_base['height'],
                                                      8000).astype(np.float32),
                                            np.arange(60000, 
                                                      60000 + 8000*profile_base['width'], 
                                                      8000).astype(np.float32)],
        # NB : La fonction 'range()' est évitée car elle renvoie des entiers
        # QGIS n'arrive pas à détecter le CRS lorsque les axes sont des entiers
                                  dims = ['time', 'y', 'x'])
        
        # Converting to xarray dataset:
        dataset = dataarray.to_dataset(name = _field)
        
        # Adding attributes:
        dataset.rio.write_crs("epsg:27572", inplace = True)
        dataset.x.attrs = {'standard_name': 'projection_x_coordinate',
                                    'long_name': 'x coordinate of projection',
                                    'units': 'Meter'}
        dataset.y.attrs = {'standard_name': 'projection_y_coordinate',
                                    'long_name': 'y coordinate of projection',
                                    'units': 'Meter'}
        
        # Export:
        # -------
        if output_format.casefold() in ['nc', 'netcdf']:
            dataset.to_netcdf(output_file + '.nc')
            (folder_name, file_name) = os.path.split(output_file + '.nc')
            print("   The dataset has been successfully exported to the file '{}' in the folder '{}'\n".format(file_name, folder_name))
            
        elif output_format.casefold() in ['tif', 'tiff', 'geotiff']:
            with rasterio.open(output_file + '.tiff', 'w', **profile_base) as out_f:
                for i, d in enumerate(dates):
                    out_f.write_band(i, dataset.sel(time = d))
            (folder_name, file_name) = os.path.split(output_file + '.nc')
            print("   The dataset has been successfully exported to the file '{}' in the folder '{}'\n".format(file_name, folder_name))

        
    return fields
    
    
# =============================================================================
#     #- - - - - - SANDBOX - - - - - 
#     #% Single day:
#     # date = _data.loc[:,_data.columns == '2019-10-15'].columns.values
#     date = _data.loc[:,_data.columns == _date].columns[0]
#     _datasingleday = _datasubset.loc[:, date]
#     
#     #% Matplot:
#     _datasubset.plot(column = date, cmap = 'RdYlBu_r', vmin = 10.5, vmax = 15)
# =============================================================================


#%%% * convert_from_h5_oldsurfex (data from Quentin)
###############################################################################
def convert_from_h5_oldsurfex(*, output_format = 'csv', **kwargs):
    r"""
    % DESCRIPTION :
    Cette fonction formate les fichiers Surfex de Quentin en fichiers *.csv
    organisés par dates (lignes) et identifiants de mailles (colonnes).
    
    % EXEMPLES :
    >> import surfexconvert as sc  #(NB : il faut au préalable que le dossier soit ajouté dans le PYTHONPATH))
    >> sc.convert_from_h5_oldsurfex(output_format = "csv", 
                                 start_years = list(range(2005, 2011, 1)),
                                 variables = ['DRAIN', 'ETR'])
            
    >> sc.convert_from_oldsurfex(output_format = "nc", 
                                 mesh_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\BZH\shapefile\maille_meteo_fr_pr93.shp")

    % ARGUMENTS (OPTIONNELS) :
    > output_format = 'csv' (défault) | 'NetCDF' | 'GeoTIFF'
    > kwargs:
        > input_folder = dossier contenant les fichiers à traiter.
            Si rien n'est spécifié, le dossier du script est pris en compte
        > variables = variable(s) à traiter (parmi DRAIN, ETR, PRCP et RUNOFF)
            Si ce n'est pas spécifié, toutes les variables sont considérées
        > start_years = années à traiter
            (par ex : 2012 correspond au fichier blabla_2012_2013)
            Si rien n'est spécifié, toutes les années sont considérées
        > mesh_file = chemin d'accès au fichier de correspondances entre les
        id des tuiles et leurs coordonnées
            (nécessaire uniquement pour NetCDF et GeoTIFF)
    """   
    
    # ---- RECUPERATION DES INPUTS
    #--------------------------
    if 'input_folder' in kwargs:
        input_folder = kwargs['input_folder']
    else:
        input_folder = os.path.dirname(os.path.realpath(__file__))
    
     # Si 'variables' est renseigné, il est converti en liste de strings.
     # Sinon, toutes les variables sont prises en compte (DRAIN, ETR, PRCP...).
    if 'variables' in kwargs:
        variables = kwargs['variables']
        if isinstance(variables, str): variables = [variables]
        else: variables = list(variables)
    else:
        variables = ['DRAIN', 'ETR', 'PRCP', 'RUNOFF']
    print('> variables = ' + ', '.join(variables))
    
     # Si 'start_years' est renseigné, il est converti en liste de strings.
     # Sinon, toutes les années sont considérées (1970-1971 -> 2011-2012).
    if 'start_years' in kwargs:
        start_years = kwargs['start_years']
        if isinstance(start_years, str): start_years = [start_years]
        else: 
            start_years = list(start_years)
            start_years = [str(y) for y in start_years]
    else:
        start_years = [str(y) for y in range(1970, 2012, 1)]
    print("> années de départ = " + ', '.join(start_years))
    
    if 'mesh_file' in kwargs:
        mesh_file = kwargs['mesh_file']
    
    
    #% Localisation des dossiers et fichiers de base : 
    #-------------------------------------------------
    idlist_file = os.path.join(input_folder, 
                               r"numero_mailles_bretagne_etendue.txt")
    # (= fichier des identifiants des mailles) 
    mesh_indexes = np.loadtxt(idlist_file, dtype = int)
    
    
    # ---- TRAITEMENT DES DONNEES
    for _variable in variables:
        print("Traitement de " + _variable + "...")
        dataset_allyears = pd.DataFrame(columns = mesh_indexes) #(initialisation)
        
        for _year in start_years:
            print(_year)
            input_file = os.path.join(input_folder, 
                                      "_".join([_variable, _year, 
                                                str(int(_year)+1)])) 
            # (= fichier de données)

            #% Importation :
            #---------------
            raw_data = pd.read_table(input_file, delimiter = "   ", 
                                     engine = 'python', header = None)
            
            # Redimensionnement :
            #--------------------
            if pd.to_datetime(str(int(_year) + 1)).is_leap_year: n_days = 366
            else: n_days = 365
            reshp_array = np.array(raw_data).reshape((n_days, 610), 
                                                     order = 'C')
            reshp_array = reshp_array[:, 0:-6] # Array de 365 lignes et 604 col
            
            # Ajout des étiquettes :
            #-----------------------
            _start_date = _year + '-07-31'
            date_indexes = pd.date_range(start = _start_date, 
                                         periods = n_days, freq = '1D')
            dataframe_1y = pd.DataFrame(data = reshp_array, 
                                        index = date_indexes, 
                                        columns = mesh_indexes, copy = True)
            
            dataset_allyears = dataset_allyears.append(dataframe_1y)
            
            # =================================================================
            #     #% Rajouter des moyennes ou sommes annuelles comme sur les 
            #        précédentes données Surfex :
            #     T['mean'] = T.mean(axis = 1)
            #     T['sum'] = T.sum(axis = 1)
            # =================================================================
          
            
        # ---- EXPORTATION
        output_file = os.path.join(input_folder, 
                                   "_".join([_variable, start_years[0],
                                            str(int(start_years[-1])+1)]
                                            )
                                   )
        
        #% Export en CSV :
        #-----------------
        if output_format in ['csv', 'CSV']:
            dataset_allyears.to_csv(output_file + ".csv", sep = '\t', 
                                    header = True) 
            (folder_name, file_name) = os.path.split(output_file + ".csv")
            print("> Le fichier \'{}\' a été créé dans le dossier \'{}\'.".format(
                file_name, folder_name))
            
        
        #% Export en NetCDF ou TIFF :
        #----------------------------
        elif output_format in ['NetCDF', 'nc', 'TIFF', 'tiff', 'tif', 'GeoTIFF']:            
            #% Géoréférencement des données / formatage
            print("Formatage...")
            # (NB : dataset_allyears sera écrasé plus tard)
            all_date_indexes = dataset_allyears.index
            n_dates = len(all_date_indexes)
            _data = dataset_allyears.transpose(copy = True)
            _geodataset = gpd.read_file(mesh_file)
            _geodataset.num_id = _geodataset.num_id.astype(int)
            
            _geodataset = _geodataset[_geodataset.num_id.isin(_data.index)]
            _geodataset = _geodataset.merge(_data, left_on = "num_id", 
                                            right_index = True)
            
            res_x = 8000 # résolution Surfex [m]
            res_y = 8000
            n_x = len(pd.unique(_geodataset.loc[:, 'Xlamb']))
            n_y = len(pd.unique(_geodataset.loc[:, 'Ylamb']))
            x_min = min(_geodataset.loc[:, 'Xlamb']) - res_x/2 #NB : not 56000
            y_min = min(_geodataset.loc[:, 'Ylamb']) - res_y/2
            profile_base = {'driver': 'NetCDF',
                            'dtype': 'float64',
                            'nodata': None,
                            # 'time': n_dates,
                            'height': n_y, #23
                            'width': n_x, #37
                            'count': n_dates,
                            'crs': rio.crs.CRS.from_epsg(27572),
                            'transform': Affine(res_x, 0.0, x_min,  
                                                0.0, res_y, y_min),
                            # values deducted from Xlamb and Ylamb and QGIS
                            'tiled': False,
                            'interleave': 'band'}
            
            _geodataset['centers'] = [Point(x_y) for x_y in 
                                        zip(_geodataset.loc[:, 'Xlamb'], 
                                            _geodataset.loc[:, 'Ylamb'])]
            # NB: Coordinates are here in Lambert Zone II (epsg:27572)    
            
            raster_data_allyears = np.empty(shape = (n_dates,
                                                     profile_base['height'], 
                                                     profile_base['width']))
            
            print("  Rasterisation... ({} éléments. Peut prendre plusieurs minutes)".format(len(all_date_indexes)))
            for d, _date in enumerate(all_date_indexes):
                _raster_data = rasterio.features.rasterize(
                    [(_dataval.loc['centers'], _dataval.loc[pd.to_datetime(_date)]) 
                      for i, _dataval in _geodataset.iterrows()],
                    out_shape = (profile_base['height'], profile_base['width']),
                    transform = profile_base['transform'],
                    fill = np.NaN,
                    all_touched = True)
                
                raster_data_allyears[d, :, :] = _raster_data
                #*** Est-ce que cette étape peut être faite telle quelle avec 
                # des données incluant tous les temps ?***
                
            print("  xarray...")
            dataarray_allyears = xr.DataArray(
                raster_data_allyears, 
                #raster_data_allyears.astype('float32'), 
                coords = [all_date_indexes, 
                          np.sort(pd.unique(_geodataset.loc[:, 'Ylamb'])), 
                          np.sort(pd.unique(_geodataset.loc[:, 'Xlamb']))],
                # <!> NB <!> Il est extrêmement important de trier les
                # indices dans l'ordre croissant !!! (ils sont désordonnés dans 
                # _geodataset). Sinon QGIS n'arrive pas à lire les fichiers !
                dims = ['time', 'y', 'x']) 
# =============================================================================
#                 # [AVANT : dims = ['time', 'latitude', 'longitude'])]
# =============================================================================
                # L'ordre conseillé des dimensions est t, lat, lon, mais ça n'a
                # pas d'incidence.
            
            # Conversion en Dataset :
            dataset_allyears = dataarray_allyears.to_dataset(name = _variable)
            
            print("Exportation...")
            if output_format in ['NetCDF', 'nc']:
                #% Pour NetCDF :
                # - - - - - - - -        
                # Formatage des attributs selon les conventions QGIS :
                # Insert georeferencing metadata :
                dataset_allyears.rio.write_crs("epsg:27572", inplace = True)
                dataset_allyears.x.attrs = {'standard_name': 'projection_x_coordinate',
                                            'long_name': 'x coordinate of projection',
                                            'units': 'Meter'}
                dataset_allyears.y.attrs = {'standard_name': 'projection_y_coordinate',
                                            'long_name': 'y coordinate of projection',
                                            'units': 'Meter'}
# =============================================================================
#                 # AVANT :
#                 dataset_allyears.longitude.attrs = {'units': 'degrees_east',
#                                            'long_name': 'longitude'}
#                 dataset_allyears.latitude.attrs = {'units': 'degrees_north',
#                                            'long_name': 'latitude'}
# =============================================================================
                # dataset_allyears.time.attrs = {'units': 'days since 1970-01-01',
                #                       'calendar': 'gregorian',
                #                       'long_name': 'time'}
                dataset_allyears.attrs = {'Conventions': 'CF-1.6'}
                
                dataset_allyears.to_netcdf(output_file + ".nc")
                (folder_name, file_name) = os.path.split(output_file + ".nc")
                print("> Le fichier \'{}\' a été créé dans le dossier \'{}\'.".format(
                    file_name, folder_name))
            
            else:
                #% Pour TIFF :
                # - - - - - - -
                dataset_allyears[_variable].rio.to_raster(output_file + '.tiff')
    # =============================================================================
    #             # Méthode sans rioxarray :
    #             # (Problème : les valeurs des coordonnées semblent désordonnées)
    #             with rasterio.open(output_file + ".tiff", 'w', 
    #                                **profile_base) as out_f:
    #                 for d, _date in enumerate(all_date_indexes):
    #                     # out_f.write_band(d + 1, raster_data_allyears[d, :, :])
    #                     out_f.write_band(d + 1, 
    #                                      dataset_allyears[_variable].sel(time = _date))      
    # =============================================================================
                (folder_name, file_name) = os.path.split(output_file + ".tiff")
                print("> Le fichier \'{}\' a été créé dans le dossier \'{}\'.".format(
                    file_name, folder_name))
                    
    return dataset_allyears


###############################################################################
#%%% correct biaises: Corrige les précipitations, rayonnements, ETP... de ERA5-Land
def correct_bias(input_file, correct_factor = 1, to_dailysum = True,
                 progressive = False):
    """
    Fonction plutôt à utiliser sur les données finales formatées
    correct_factor:
        - for precipitations (hourly) : 1.8
        - for precipitations (daily sum): 0.087 
        - for radiations (daily sum): 0.0715 (and progressive = True)
        - for potential evapotranspiration pos (daily sum): 0.04
    """
    
    print("\nLoading...")
    with xr.open_dataset(input_file, decode_coords = 'all') as ds:
        ds.load() # to unlock the resource
        
    ds2 = ds.copy(deep = True)
    
    print("\nCorrecting values: multiply by {}...".format(correct_factor))
    
    if not progressive: # constant correction for any day
        var = main_var(ds)
        suffix = f"{correct_factor}"
        ds2[var] = ds2[var]*correct_factor
        correct_factor_max = correct_factor
    
    elif progressive: # varying correction along the year (stronger in summer, weaker in winter)
        var = main_var(ds)
        suffix = f"{correct_factor}P1"
        monthly_correction = np.array([0.74130111, 0.6586179, 1.04861236, 
                                       0.98615636, 0.96493336, 1.15048825, 
                                       1.06386533, 1.16570181, 1.001253, 
                                       0.81417812, 0.71620761, 0.76901861]) * correct_factor
        # Redefinition of correct_factor as a monthly correction:
        # correct_factor = ds2.mean(dim = ['latitude', 'longitude']).groupby("time.month").mean()
        # correct_factor[var] = monthly_correction
        correct_factor_monthly = xr.DataArray(monthly_correction, dims = 'month', coords = {'month': list(range(1,13))})
        ds2[var] = ds2[var].groupby('time.month', squeeze = False)*correct_factor_monthly
        ds2 = ds2.drop("month")
        correct_factor_max = float(correct_factor_monthly.max())
        
# =============================================================================
#         # Pipeline pour calculer les coefficients
#         month_length = ds.time.dt.days_in_month
#         weights = (
#             month_length.groupby("time.month") / month_length.groupby("time.month").sum())
#         # Pour vérifier que la somme des pondérations fait bien 1 pour chaque mois
#         np.testing.assert_allclose(weights.groupby("time.month").sum().values, np.ones(12))
#         ds_weighted = (ds * weights).groupby("time.month").sum(dim="time")
#         ds_weighted.mean(dim = ['longitude', 'latitude'])
#         # Référence (visuelle, d'après https://loa.univ-lille.fr/documents/LOA/formation/stages/B_Anh.pdf)
#         [20, 30, 90, 125, 145, 170, 165, 155, 100, 50, 25, 20] # kWh/m²/month
#         [2322581, 3857143, 10451613, 15000000, 16838710, 20400000,
#          19161290, 18000000, 12000000, 5806452, 3000000, 2322581] # J/m²/d
# =============================================================================
        
    
    unit_factor = 1
    if to_dailysum: # Si les données d'entrée sont des moyennes en m/h :
        print("\nCorrecting units:")
        print("   input values are in .../h")
        print("   multiply by 24 --> .../d")
        ds2[var] = ds2[var]*24
        unit_factor = 24
        
    
    print("\nCorrecting encodings...")
    ds2[var].encoding = ds[var].encoding
    ds2[var].encoding['scale_factor'] = ds[var].encoding['scale_factor']*correct_factor_max*unit_factor
    ds2[var].encoding['add_offset'] = ds[var].encoding['add_offset']*correct_factor_max*unit_factor

    ds2.x.encoding['_FillValue'] = None
    ds2.y.encoding['_FillValue'] = None
    
    print("\nExporting...")
    output_file = os.path.splitext(input_file)[0] + f" x{suffix}.nc"
    ds2.to_netcdf(output_file)
    

###############################################################################
#%%% * hourly_to_daily (OLD)
def hourly_to_daily_old(*, data, mode = 'mean', **kwargs):
    # Cette version précédente (mise à jour) gère des dossiers
    
    """
    Example
    -------
    import geoconvert as gc
    # full example:
    gc.hourly_to_daily(input_file = r"D:/2011-2021_hourly Temperature.nc",
                       mode = 'max',
                       output_path = r"D:/2011-2021_daily Temperature Max.nc",
                       fields = ['t2m', 'tp'])
    
    # input_file can also be a folder:
    gc.hourly_to_daily(input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\ERA5\Brittany\test", 
                       mode = 'mean')
    
    Parameters
    ----------
    input_file : str, or list of str
        Can be a path to a file (or a list of paths), or a path to a folder, 
        in which cas all the files in this folder will be processed.
    mode : str, or list of str, optional
        = 'mean' (default) | 'max' | 'min' | 'sum'
    **kwargs 
    --------
    fields : str or list of str, optional
        e.g: ['t2m', 'tp', 'u10', 'v10', ...]
        (if not specified, all fields are considered)
    output_path : str, optional
        e.g: [r"D:/2011-2021_daily Temperature Max.nc"]
        (if not specified, output_name is made up according to arguments)
        
    Returns
    -------
    None. Processed files are created in the output destination folder.

    """

    # ---- Get input file path(s)
    data_folder, filelist = get_filelist(data, filetype = '.nc')
        
    #% Safeguard for output_names:
    if len(filelist) > 1 and 'output_path' in kwargs:
        print('Warning: Due to multiple output, names of the output files are imposed.') 
    
    
    # ---- Format modes
    if isinstance(mode, str): mode = [mode]
    else: mode = list(mode)
    
    if len(mode) != len(filelist):
        if (len(mode) == 1) & (len(filelist)>1):
            mode = mode*len(filelist)
        else:
            print("Error: lengths of input file and mode lists do not match")
            return
            
        
    # ---- Process data
    for i, f in enumerate(filelist):  
        print(f"\n\nProcessing file {i+1}/{len(filelist)}: {f}...")
        print("-------------------")
        #% Load data:
        data_ds = load_any(os.path.join(data_folder, f), 
                           decode_coords = 'all', decode_times = True)

        #% Get fields:
        if 'fields' in kwargs:
            fields = kwargs['fields']
            if isinstance(fields, str): fields = [fields]
            else: fields = list(fields) # in case fields are string or tuple
        else:
            fields = list(data_ds.data_vars) # if not input_arg, fields = all
        
        #% Extract subset according to fields
        fields_intersect = list(set(fields) & set(data_ds.data_vars))
        data_subset = data_ds[fields_intersect]
        print("   _ Extracted fields are {}".format(fields_intersect))
        if fields_intersect != fields:
            print('Warning: ' + ', '.join(set(fields) ^ set(fields_intersect)) 
                  + ' absent from ' + data)
        
        #% Resample:
        print("   _ Resampling time...")
        if mode[i] == 'mean':
            datarsmpl = data_subset.resample(time = '1D').mean(dim = 'time',
                                                                keep_attrs = True)
        elif mode[i] == 'max':
            datarsmpl = data_subset.resample(time = '1D').max(dim = 'time',
                                                               keep_attrs = True)
        elif mode[i] == 'min':
            datarsmpl = data_subset.resample(time = '1D').min(dim = 'time',
                                                               keep_attrs = True)
        elif mode[i] == 'sum':
            datarsmpl = data_subset.resample(time = '1D').sum(dim = 'time',
                                                               skipna = False,
                                                               keep_attrs = True)
        
        #% Build output name(s):
        if len(filelist) > 1 or not 'output_path' in kwargs:         
            basename = os.path.splitext(f)[0]
            output_name = os.path.join(
                data_folder, 'daily',
                basename + ' daily_' + mode[i] + '.nc')
            ## Regex solution, instead of splitext:
            # _motif = re.compile('.+[^\w]')
            # _basename = _motif.search(data).group()[0:-1]
            
            if not os.path.isdir(os.path.join(data_folder, 'daily')):
                os.mkdir(os.path.join(data_folder, 'daily'))
            
        else:
            output_name = kwargs['output_path']
        
        
        # ---- Preparing export   
        # Transfer encodings
        for c in list(datarsmpl.coords):
            datarsmpl[c].encoding = data_ds[c].encoding
        
        for f in fields_intersect:
            datarsmpl[f].encoding = data_ds[f].encoding
            
            # Case of packing
            if ('scale_factor' in datarsmpl[f].encoding) | ('add_offset' in datarsmpl[f].encoding):
                # Packing (lossy compression) induces a loss of precision of 
                # apprx. 1/1000 of unit, for a quantity with an interval of 150 
                # units. The packing is initially used in some original ERA5-Land data.
                if mode[i] == 'sum':
                    print("   Correcting packing encodings...")
                    datarsmpl[f].encoding['scale_factor'] = datarsmpl[f].encoding['scale_factor']*24
                    datarsmpl[f].encoding['add_offset'] = datarsmpl[f].encoding['add_offset']*24
            
        #% Export
        export(datarsmpl, output_name)


#%% EXTRACTIONS
###############################################################################
#%%% ° times_series
def time_series(*, input_file, epsg_coords = None, epsg_data = None, 
                coords = None, mode = 'mean', dates = None, 
                fields = None, cumul = False):
    """
    % DESCRIPTION:
    This function extracts the temporal data in one location given by 
    coordinate.
    
    % EXAMPLE:
    import geoconvert as gc
    era5 = gc.time_series(input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\ERA5\Brittany\daily/2011-2021_Temperature_daily_mean.nc", 
                          coords = (-2.199337, 48.17824), epsg = 4326, 
                          fields = 't2m')
    cwatm_ds = gc.time_series(input_file = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\results\raw_results\005_calib_groundwater\01_base_Ronan\sum_gwRecharge_daily.nc", 
                          coords = (3417964, 2858067), epsg = 3035)

    % OPTIONAL ARGUMENTS:
        > coords = coordinates of one point
            /!\ Coordinates should be indicated in (X,Y) or (lon,lat) order 
            (and not (lat,lon) !!!)
        > coords can also indicate a mask: 
            coords = 'all' | filepath to a mask.tiff | filepath to a mask.shp
        > epsg_coords = 4326 | 3035 | 2154 | 27572 | etc.
            EPSG of the coords ! Useless if coords is a mask that includes a CRS 
        > epsg_data = same principle, for data without any included information about CRS
        > mode = 'mean' (standard) | 'sum' | 'max' | 'min'
    > dates = ['2021-09', '2021-12-01' ...]
    > fields = ['T2M', 'PRECIP', ...]
    """  
    _dataset = load_any(input_file, decode_times = True, decode_coords = 'all')
    
    #% Get and process arguments:
    # ---------------------------
    if epsg_coords is not None:
        if isinstance(epsg_coords, str):
            if epsg_coords.casefold()[0:5] == 'epsg:':
                epsg_coords = int(epsg_coords[5:])
                
    if fields is not None:
        if isinstance(fields, str): fields = [fields]
        else: fields = list(fields) # in case fields are string or tuple
    else:
        fields = list(_dataset.data_vars) # if not input_arg, fields = all
    
    if dates is not None:
        if not isinstance(dates, tuple): fields = tuple(fields)
        # in case dates are a list instead of a tuple
        
    if not isinstance(coords, str): 
    # if coords is not None:
        if not isinstance(coords, tuple): coords = tuple(coords)
        # in case coords are a list instead of a tuple
    
    
    #% Standardize terms:
    # -------------------
# =============================================================================
#     if 'lon' in list(_dataset.dims) or 'lat' in list(_dataset.dims):
#         print('Renaming lat/lon coordinates')
#         _dataset = _dataset.rename(lat = 'latitude', lon = 'longitude')
# =============================================================================
    if 'lon' in list(_dataset.dims) or 'lat' in list(_dataset.dims):
        print('Renaming lat/lon coordinates')
        _dataset = _dataset.rename(lat = 'y', lon = 'x')
    if 'longitude' in list(_dataset.dims) or 'latitude' in list(_dataset.dims):
        print('Renaming lat/lon coordinates')
        _dataset = _dataset.rename(latitude = 'y', longitude = 'x')
    if 'X' in list(_dataset.dims) or 'Y' in list(_dataset.dims):
        print('Renaming X/Y coordinates')
        _dataset = _dataset.rename(X = 'x', Y = 'y')
        
    _dataset.x.attrs = {'standard_name': 'projection_x_coordinate',
                                'long_name': 'x coordinate of projection',
                                'units': 'Meter'}
    _dataset.y.attrs = {'standard_name': 'projection_y_coordinate',
                                'long_name': 'y coordinate of projection',
                                'units': 'Meter'}
        
# =============================================================================
#     #% Convert temperature:
#     for _field in fields:
#         if 'units' in _dataset[_field].attrs:
#             if _dataset[_field].units == 'K':
#                 _dataset[_field] = _dataset[_field]-273.15
#                 # _datasubset[_field].units = '°C'
# =============================================================================
    
    print('Fields = {}'.format(str(fields)))
        
    
    if not isinstance(coords, str):
        if epsg_coords is not None:
            0
            # print('Coordinates = {} in epsg:{}'.format(str(coords), str(epsg_coords)))
        else:
            print('For numerical coords, it is necessary to indicate their CRS, by using the *epsg_coords* argument.')
            return
            
        #% Convert into appropriate CRS = CRS from the data:
        if epsg_data is not None:
            # 1re méthode de conversion : (x,y) ou (lon,lat) :
            coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(epsg_coords), 
                                                  rasterio.crs.CRS.from_epsg(epsg_data), 
                                                  [coords[0]], [coords[1]])
            coords_conv = (coords_conv[0][0], coords_conv[1][0])
            # (pour convertir une tuple de arrays en tuple)
            
# =============================================================================
#             # 2e méthode de conversion : (x,y) ou (lat,lon) :
#             coords_conv = convert_coord(coords[0], coords[1], 
#                                         inputEPSG = epsg_coords, 
#                                         outputEPSG = epsg_data)
# =============================================================================
            print('Coordinates = {} in epsg:{}'.format(str(coords_conv), 
                                                       str(epsg_data)))
            
        elif 'spatial_ref' in _dataset.coords or 'spatial_ref' in _dataset.data_vars:
            # _motif = re.compile('"EPSG","\d+"')
            # _substr = _motif.findall(_dataset.spatial_ref.crs_wkt)[-1]
            # _epsg_motif = re.compile('\d+')
            # epsg_data = int(_epsg_motif.search(_substr).group())
            epsg_data = int(_dataset.rio.crs.to_epsg())
            
            coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(epsg_coords), 
                                                  rasterio.crs.CRS.from_epsg(epsg_data), 
                                                  [coords[0]], [coords[1]])
            coords_conv = (coords_conv[0][0], coords_conv[1][0])

            print('Coordinates = {} in epsg:{}'.format(str(coords_conv), 
                                                       str(epsg_data)))
            
        else:
            print("'spatial_ref' is not indicated in the data file, and the argument *epsg_data* is not used. Be sure to use the same CRS as in the data.")
            coords_conv = coords
        
        #% Extract data:
        _dataset = _dataset[fields]
        if dates is not None:
            _dataset = _dataset.sel(time = slice(dates[0], dates[1]))
            
        if 'longitude' in list(_dataset.dims) or 'latitude' in list(_dataset.dims):
            results = _dataset.sel(longitude = coords_conv[0], 
                                   latitude = coords_conv[1],
                                   method = 'nearest')
        elif 'x' in list(_dataset.dims) or 'y' in list(_dataset.dims):
            results = _dataset.sel(x = coords_conv[0], 
                                   y = coords_conv[1],
                                   method = 'nearest')
        
        del _dataset # memory cleaning

                 
    else: # elif isinstance(coords, str): 
    # Dans ce cas, 'coords' indique un masque
        if coords.casefold() == 'all':
            print('All cells are considered')
                 
        else: # coords is a file_path
            #% Get CRS from the data:
            if 'spatial_ref' in _dataset.coords or 'spatial_ref' in _dataset.data_vars:
                # _motif = re.compile('"EPSG","\d+"')
                # _substr = _motif.findall(_dataset.spatial_ref.crs_wkt)[-1]
                # _epsg_motif = re.compile('\d+')
                # epsg_data = int(_epsg_motif.search(_substr).group())
                epsg_data = int(_dataset.rio.crs.to_epsg())
            elif epsg_data is None:
                print('Data file has no associated CRS.')
                return
            
            _mask_extension = os.path.splitext(coords)[-1]
            
            if _mask_extension in ['.tif', '.tiff', '.nc']: # If the mask is a geotiff or a netcdf
                if _mask_extension in ['.tif', '.tiff']:
                    with xr.open_dataset(coords) as mask_ds:
                        mask_ds.load()
                        mask_ds = mask_ds.squeeze('band').drop('band')
                        # NB: mask_ds.y.values are decreasing
                elif  _mask_extension in ['.nc']:
                    with xr.open_dataset(coords, decode_coords = 'all') as mask_ds:
                        mask_ds.load()
                        mask_ds = mask_ds.rename({list(mask_ds.data_vars)[0]: 'band_data'})

                if 'spatial_ref' in mask_ds.coords or 'spatial_ref' in mask_ds.data_vars:
                    # _motif = re.compile('"EPSG","\d+"')
                    # _substr = _motif.findall(mask_ds.spatial_ref.crs_wkt)[-1]
                    # _epsg_motif = re.compile('\d+')
                    # epsg_coords = int(_epsg_motif.search(_substr).group())
                    epsg_coords = int(mask_ds.rio.crs.to_epsg())
                else:
                    if epsg_coords is not None:
                        mask_ds.rio.write_crs('epsg:' + str(epsg_coords), inplace = True)
                        print('For clipping/masking, epsg:' + str(epsg_coords) + ' will be used.')
                    else:
                        print('For clipping/masking, mask needs to have a CRS associated.')
                        return
                    
                
                # Reprojection of the mask in the CRS of the data:
                res_x = float(_dataset.x[1] - _dataset.x[0])
                res_y = float(_dataset.y[1] - _dataset.y[0])
                
                # mask_ds['x'] = np.sort(mask_ds.x)
                # mask_ds['y'] = np.sort(mask_ds.y)
                
                mask_coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(epsg_coords), 
                                                      rasterio.crs.CRS.from_epsg(epsg_data), 
                                                      [mask_ds.x.values.min()], [mask_ds.y.values.max()])
                
                idx_x = (np.abs(_dataset.x.values - mask_coords_conv[0][0])).argmin()
                # if idx_x > 0: idx_x = idx_x - 1
                x_min = float(_dataset.x[idx_x]) - res_x/2
                
                idx_y = (np.abs(_dataset.y.values - mask_coords_conv[1][0])).argmin()
                # if idx_y > 0: idx_y = idx_y - 1
                y_max = float(_dataset.y[idx_y]) + res_y/2
                
                mask_proj = mask_ds.rio.reproject('epsg:' + str(epsg_data),
                                                  transform = Affine(res_x, 0.0, x_min,  
                                                                      0.0, -res_y, y_max),
                                                  resampling = rasterio.enums.Resampling(5))
                
                _dataset = _dataset.where(mask_proj.band_data == 1, drop = True)
                _dataset.rio.write_crs("epsg:"+str(epsg_data), inplace = True)
                
            elif _mask_extension in ['.shp']: # If the mask is a shapefile
                mask_df = gpd.read_file(coords)
                
                if epsg_coords is not None:
                    mask_df.set_crs('epsg:' + str(epsg_coords))
                else:
                    try: 
                        epsg_coords = mask_df.crs.to_epsg()
                    except AttributeError:
                        print('For clipping/masking, mask needs to have a CRS associated.')
                        return
                
                print('For clipping/masking, epsg:' + str(epsg_coords) + ' will be used.')
            
                _dataset = _dataset.rio.clip(mask_df.geometry.apply(mapping),
                                             mask_df.crs,
                                             all_touched = True)
        
            print('Data CRS is {}. Mask CRS is {}.'.format(epsg_data, epsg_coords))
        
        #% Extract data:
        if mode == 'mean':
            # results = _dataset.mean(dim = list(_dataset.dims)[-2:], 
            #                         skipna = True, keep_attrs = True)
            results = _dataset.mean(dim = ['x', 'y'], 
                                    skipna = True, keep_attrs = True)
        elif mode == 'sum':
            results = _dataset.sum(dim = ['x', 'y'], 
                                   skipna = True, keep_attrs = True)
        elif mode == 'max':
            results = _dataset.max(dim = ['x', 'y'], 
                                   skipna = True, keep_attrs = True)
        elif mode == 'min':
            results = _dataset.min(dim = ['x', 'y'], 
                                   skipna = True, keep_attrs = True)
            
        # memory cleaning
        del _dataset 
        gc.collect()
        
        
    if cumul:
        print('\ncumul == True')
        timespan = results['time'
            ].diff(
                dim = 'time', label = 'lower')/np.timedelta64(1, 'D')
        
        _var = main_var(results)
        results[_var][dict(time = slice(0, timespan.size))
                       ] = (results[_var][dict(time = slice(0, timespan.size))
                                           ] * timespan.values).cumsum(axis = 0)

        # Last value:
        results[_var][-1] = np.nan
                
    # Convert to pandas.dataframe
    results = results.drop('spatial_ref').to_dataframe()
    
    return results


###############################################################################
#%%% * xr.DataSet to DataFrame
def xr_to_pd(xr_data):
    """
    Format xr objects (such as those from gc.time_series) into pandas.DataFrames
    formatted as in gc.tss_to_dataframe.

    Parameters
    ----------
    xr_data : xarray.DataSet or xarray.DataArary
        Initial data to convert into pandas.DataFrame
        NB: xr_data needs to have only one dimension.

    Returns
    -------
    Pandas.DataFrame

    """
    print("\n_Infos...")
    
    if type(xr_data) == xr.core.dataset.Dataset:
        main_var = main_var(xr_data)
        print(f"    Data is a xr.Dataset, with '{main_var}' as the main variable")
        xr_data = xr_data[main_var]
    elif type(xr_data) == xr.core.dataarray.DataArray:
        print("    Data is a xr.Dataarray")
    
    res = xr_data.to_dataframe(name = 'val')
    res = res[['val']]
    res['time'] = pd.to_datetime(res.index)
    if not res.time.dt.tz:
        print("    The timezone is not defined")
        # res['time'] = res.time.dt.tz_localize('UTC')
    res.index = range(0, res.shape[0])
# =============================================================================
#     res['id'] = res.index
# =============================================================================
    
    print('') # newline
    return res
    

###############################################################################
#%%% ° tss_to_dataframe
def tss_to_dataframe(*, input_file, skip_rows, start_date, cumul = False):
    """
    Example
    -------
    base = gc.tss_to_dataframe(input_file = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\results\raw_results\001_prelim_cotech\2022-03-19_base\discharge_daily.tss",
                         skip_rows = 4,
                         start_date = '1991-08-01')
    
    precip = gc.tss_to_dataframe(input_file = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\results\raw_results\003_artif\2022-03-25_base\Precipitation_daily.tss",
                         skip_rows = 4,
                         start_date = '2000-01-01')
    precip.val = precip.val*534000000/86400
    # (le BV topographique du Meu fait 471 851 238 m2)
    precip['rolling_mean'] = precip['val'].rolling(10).mean()
    
    Parameters
    ----------
    input_file : str
        Chemin d'accès au fichier d'entrée
    skip_rows : int
        Nombre de lignes à enlever en tête de fichier. /!\ ce nombre n'est '
    start_date : str ou datetime
        Date de la 1re valeur du fichier
        /!\ Si str, il faut qu'elle soit au format "%Y-%m-%d"

    Returns
    -------
    df : pandas.DataFrame

    
    Implémentations futures
    -----------------------
    Récupérer la start_date à partir du fichier de settings indiqué au début
    du fichier *.tss., et regarder ensuite le SpinUp
    """
    
    #%% Récupération des inputs :
    # ---------------------------
    if start_date == 'std':
        print('> Pas encore implémenté...')
        # récupérer la start_date du fichier de settings
    else:
        start_date = pd.to_datetime(start_date)
    # print('> start_date = ' + str(start_date))
    
    
    #%% Création des dataframes :
    # ---------------------------
    # df = pd.read_csv(input_file, sep = r"\s+", header = 0, names = ['id', 'val'], skiprows = skip_rows)
    if skip_rows == 0: # Cas des fichiers de débits *.css, sans lignes d'info,
                       # avec seulement un header
        _fields = ['']
        n_col = 1
        
    else: # Cas des outputs *.tss avec plusieurs lignes d'info, la 2e ligne 
          # indiquant le nombre de colonnes. Dans ce cas, skip_rows doit être
          # égal à 2.
        with open(input_file) as temp_file:
            # temp_file.readline()
            # n_col = int(temp_file.readline()[0])
            content = temp_file.readlines()
            n_col = int(content[skip_rows-1][0])
        _fields = [str(n) for n in range(1, n_col)]
        _fields[0] = ''
        
    df = pd.read_csv(input_file, 
                     sep = r"\s+", 
                     header = 0, 
                     skiprows = skip_rows -1 + n_col, 
                     names = ['id'] +  ['val' + ending for ending in _fields],
                     )
    
    # Si la colonne id contient déjà des dates (au format texte ou datetime) :
    if type(df.id[0]) in [str, 
                          pd.core.indexes.datetimes.DatetimeIndex,
                          pd._libs.tslibs.timestamps.Timestamp]:
        df['time'] = pd.to_datetime(df.id)
    # Sinon (= si la colonne id contient des indices), il faut reconstruire les dates :
    else:
        date_indexes = pd.date_range(start = start_date, 
                                     periods = df.shape[0], freq = '1D')
        df['time'] = date_indexes
    
    if cumul:
        print('\ncumul == True')
        # Values are expected to be expressed in [.../d]
        # Cumsum is applied on all columns with values ('val', 'val2', 'val3', ...)
        
        timespan = df.loc[
            :, df.columns == 'time'
            ].diff().shift(-1, fill_value = 0)/np.timedelta64(1, 'D')
        
        # timespan = df.loc[
        #     :, df.columns == 'time'
        #     ].diff()/np.timedelta64(1, 'D')
        
        df.iloc[
            :].loc[:, (df.columns != 'id') * (df.columns != 'time')
            ] = (df.iloc[
                :].loc[:, (df.columns != 'id') * (df.columns != 'time')
                ] * timespan.values).cumsum(axis = 0)
        
        # Last value
        # df.iloc[-1].loc[:, (df.columns != 'id') * (df.columns != 'time')] = np.nan
        
                # np.diff(df.time)/np.timedelta64(1, 'D')
    return df


#%% WATERSHED OPERATIONS
###############################################################################
#%%% ° Extract watershed
def extract_watershed(d8_path, outlets_file, method):
    #%%% Vérification de la compatibilité des CRS
    with rasterio.open(d8_path) as d8:
        crs_d8 = d8.read_crs()
        print()
        gdf = gpd.read_file(outlets_file)
        crs_outlets = gdf.crs
        
        if crs_d8 == crs_outlets:
            print('Le SCR du d8 et des exutoires est EPSG:{}'.format(crs_d8.to_epsg()))
        else:
            print('ATTENTION : Le SCR détecté du d8 est EPSG:{} tandis que le SCR détecté des exutoires est EPSG:{}'.format(crs_d8.to_epsg(), crs_outlets.to_epsg()))
            print('Si les SCR sont différents, le résultat sera faux.')
    
    #%%% Avec pysheds
    if method.casefold() in ["pyshed", "pysheds"]:
        print('\nMéthode choisie : pysheds')
        
    #%%% Avec WhiteToolBox
    elif method.casefold() in ["wtb", "whitetoolbox"]:
        print('\nMéthode choisie : WhiteToolBox')
    
    wbt.watershed(
        d8_path,
        outlets_file,
        os.path.join(os.path.split(d8_path)[0], "mask_bassin_xxx_wbt.tif"),
        esri_pntr = True,
        )
    print('    Masque créé')
    
    
###############################################################################
#%%% ° Compute LDD
def compute_ldd(dem_path, method):
    """
    dem_path = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\0- MNT\IGN\MNT_fusion\RGEALTI_FXX_1m_0318_6774_0340_6781_MNT_LAMB93_IGN69.tif"
    """
    
    
    #%%% Avec pysheds
    if method.casefold() in ["pyshed", "pysheds"]:
        print('Méthode choisie : pysheds')
        
        # Compute the river network
        grid = Grid.from_raster(dem_path, data_name = 'dem')
        dem = grid.read_raster(dem_path)
        # Fill depressions in DEM
        print('dem no data is ', grid.nodata)
        flooded_dem = grid.fill_depressions(dem)
        # Resolve flats in DEM
        inflated_dem = grid.resolve_flats(flooded_dem)
        # Specify directional mapping
        dirmap = (64, 128, 1, 2, 4, 8, 16, 32)  #D8 system
        # dirmap = (8, 9, 6, 3, 2, 1, 4, 7)       #LDD system
        # Compute flow directions
        direc = grid.flowdir(inflated_dem, dirmap=dirmap)
        dem = read(dem_file)
        dem_corrected = wbt.BreachDepressionsLeastCost(dem)
        # dem_corrected = wbt.FillDepressions(dem)
        

    
    #%%% Avec WhiteToolBox
    elif method.casefold() in ["wtb", "whitetoolbox"]:
        print('Méthode choisie : WhiteToolBox')
        dist_ = 10
        
        # Breach depressions
        wbt.breach_depressions_least_cost(
            dem_path,
            os.path.splitext(dem_path)[0] + "_breached{}[wtb].tif".format(dist_),
            dist_)
        print('    Fichier intermédiaire créé')
        
# =============================================================================
#         # Fill depression (alternative)
#         wbt.fill_depressions(
#             dem_path,
#             os.path.splitext(dem_path)[0] + "_filled[wtb].tif",
#             10)
# =============================================================================
        
        # Creation du D8
        suffix = "breached{}[wtb]".format(dist_)
        wbt.d8_pointer(
            os.path.splitext(dem_path)[0] + "_" + suffix + ".tif",
            os.path.join(os.path.split(dem_path)[0], "D8_xxx_" + suffix + "_wtb.tif"), 
            esri_pntr = True)
        print('    LDD "D8 ESRI" créé')
    

###############################################################################
#%%% ° Convert LDD code
"""
To switch between different direction mappings
"""
def switch_direction_map(input_file, input_mapping, output_mapping):
    
    #%%% Inputs
    mapping = [input_mapping, output_mapping]
    position = ['entrée', 'sortie']
    print("")
    
    for i in [0, 1]:
        if mapping[i].casefold().replace("_", "").replace(" ", "") in ["ldd","localdraindirections"]:
            mapping[i] = "LDD"
        elif mapping[i].casefold().replace("_", "").replace(" ", "") in ["d8", "esri", "d8esri", "esrid8", "d8standard", "standardd8"]:
            mapping[i] = "D8 ESRI"
        elif mapping[i].casefold().replace("_", "").replace(" ", "") in ["wtb", "whitetoolbox", "d8whitetoolbox", "d8wtb", "wtbd8"]:
            mapping[i] = "WTB"
        else:
            mapping[i] = "/!\ non reconnu /!\ "
        print("Direction mapping en {} : {}".format(position[i], mapping[i]))

    if "/!\ non reconnu /!\ " in mapping:
        return "error"
    

    #%%% Conversion    
    # Chargement des données
    data_in = rasterio.open(input_file, 'r')
    data_profile = data_in.profile
    val = data_in.read()
    data_in.close()
    
    # Conversion
    
    # rows: 0:'LDD', 1:'D8', 2:'WTB'
    col = ['LDD', 'D8 ESRI', 'WTB']
    keys_ = np.array(
        [[8, 64,  128,],#N
         [9, 128, 1,],  #NE
         [6, 1,   2,],  #E
         [3, 2,   4,],  #SE
         [2, 4,   8,],  #S
         [1, 8,   16,], #SO
         [4, 16,  32,], #O
         [7, 32,  64,], #NO
         [5, 0,   0,]]) #-
    
    for d in range(0, 9):
        val[val == keys_[d, 
                         col.index(mapping[0])
                         ]
            ] = -keys_[d, 
                      col.index(mapping[1])]
        
    val = -val # On passe par une valeur négative pour éviter les redondances
    # du type : 3 --> 2, 2 --> 4
    
    #%%% Export
    output_file = os.path.splitext(input_file)[0] + "_{}.tif".format(mapping[1])
    
    with rasterio.open(output_file, 'w', **data_profile) as output_f:
        output_f.write(val)
        print("\nFichier créé.")
        

###############################################################################
#%%% ° Alter modflow_river_percentage
def river_pct(input_file, value):
    """
    Creates artificial modflow_river_percentage inputs (in *.nc) to use for
    drainage.

    Parameters
    ----------
    input_file : str
        Original modflow_river_percentage.tif file to duplicate/modify
    value : float
        Value to impose on cells (from [0 to 1], not in percentage!)
        This value is added to original values as a fraction of the remaining
        "non-river" fraction:
            For example, value = 0.3 (30%):
                - cells with 0 are filled with 0.3
                - cells with 1 remain the same
                - cells with 0.8 take the value 0.86, because 30% of what should
                have been capillary rise become baseflow (0.8 + 0.3*(1-0.8))
                - cells with 0.5 take the value 0.65 (0.5 + 0.3*(1-0.5))

    Returns
    -------
    None.

    """
    #%% Loading
    # ---------
    if os.path.splitext(input_file)[-1] == '.tif':
        with xr.open_dataset(input_file, # .tif 
                             decode_times = True, 
                             ) as ds:
            ds.load()
    elif os.path.splitext(input_file)[-1] == '.nc':
        with xr.open_dataset(input_file, 
                             decode_times = True, 
                             decode_coords = 'all',
                             ) as ds:
            ds.load()   
    
    #%% Computing
    # -----------
    # ds['band_data'] = ds['band_data']*0 + value
    ds_ones = ds.copy(deep = True)
    ds_ones['band_data'] = ds_ones['band_data']*0 + 1
    
    #% modflow_river_percentage_{value}.nc:
    ds1 = ds.copy(deep = True)
    ds1['band_data'] = ds1['band_data'] + (ds_ones['band_data'] - ds1['band_data'])*value
    
    #% drainage_river_percentage_{value}.nc :
    ds2 = ds1 - ds
    
    #%% Formatting
    # ------------
    ds1.rio.write_crs(2154, inplace = True)
    ds1.x.attrs = {'standard_name': 'projection_x_coordinate',
                                'long_name': 'x coordinate of projection',
                                'units': 'Meter'}
    ds1.y.attrs = {'standard_name': 'projection_y_coordinate',
                                'long_name': 'y coordinate of projection',
                                'units': 'Meter'}
    # To avoid conflict when exporting to netcdf:
    ds1.x.encoding['_FillValue'] = None
    ds1.y.encoding['_FillValue'] = None
    
    ds2.rio.write_crs(2154, inplace = True)
    ds2.x.attrs = {'standard_name': 'projection_x_coordinate',
                                'long_name': 'x coordinate of projection',
                                'units': 'Meter'}
    ds2.y.attrs = {'standard_name': 'projection_y_coordinate',
                                'long_name': 'y coordinate of projection',
                                'units': 'Meter'}
    # To avoid conflict when exporting to netcdf:
    ds2.x.encoding['_FillValue'] = None
    ds2.y.encoding['_FillValue'] = None
    
    #%% Exporting
    # -----------
    (folder, file) = os.path.split(input_file)
    (file, extension) = os.path.splitext(file)
    
    output_file1 = os.path.join(folder, "_".join([file, str(value)]) + '.nc')
    ds1.to_netcdf(output_file1)
    
    output_file2 = os.path.join(folder, "_".join(['drainage_river_percentage', str(value)]) + '.nc')
    ds2.to_netcdf(output_file2)


#%% QUANTITIES OPERATIONS
###############################################################################
# Calcule ETref et EWref à partir de la "pan evaporation" de ERA5-Land
def compute_Erefs_from_Epan(input_file):
    print("\nDeriving standard grass evapotranspiration and standard water evapotranspiration from pan evaporation...")
    Epan = load_any(input_file, decode_coords = 'all', decode_times = True)
    
    var = main_var(Epan)
    
    print("   _ Computing ETref (ET0) from Epan...")
    ETref = Epan.copy()
    ETref[var] = ETref[var]*0.675
    
    print("   _ Computing EWref from Epan...")
    EWref = Epan.copy()
    EWref[var] = EWref[var]*0.75
    
    print("   _ Transferring encodings...")
    ETref[var].encoding = Epan[var].encoding
    EWref[var].encoding = Epan[var].encoding
    # Case of packing
    if ('scale_factor' in Epan[var].encoding) | ('add_offset' in Epan[var].encoding):
        # Packing (lossy compression) induces a loss of precision of 
        # apprx. 1/1000 of unit, for a quantity with an interval of 150 
        # units. The packing is initially used in some original ERA5-Land data
        ETref[var].encoding['scale_factor'] = ETref[var].encoding['scale_factor']*0.675
        ETref[var].encoding['add_offset'] = ETref[var].encoding['add_offset']*0.675
        EWref[var].encoding['scale_factor'] = EWref[var].encoding['scale_factor']*0.75
        EWref[var].encoding['add_offset'] = EWref[var].encoding['add_offset']*0.75
    
    return ETref, EWref


###############################################################################
def compute_wind_speed(u_wind_data, v_wind_data):
    """
    U-component of wind is parallel to the x-axis
    V-component of wind is parallel to the y-axis
    """
    
# =============================================================================
#     print("\nIdentifying files...")
#     U_motif = re.compile('U-component')
#     U_match = U_motif.findall(input_file)
#     V_motif = re.compile('V-component')
#     V_match = V_motif.findall(input_file)
#     
#     if len(U_match) > 0:
#         U_input_file = '%s' % input_file # to copy the string
#         V_input_file = '%s' % input_file
#         V_input_file = V_input_file[:U_motif.search(input_file).span()[0]] + 'V' + V_input_file[U_motif.search(input_file).span()[0]+1:]
#     elif len(V_match) > 0:
#         V_input_file = '%s' % input_file # to copy the string
#         U_input_file = '%s' % input_file
#         U_input_file = U_input_file[:V_motif.search(input_file).span()[0]] + 'U' + U_input_file[V_motif.search(input_file).span()[0]+1:]
# =============================================================================
    
    print("\nComputing wind speed from U- and V-components...")

    U_ds = load_any(u_wind_data, decode_coords = 'all', decode_times = True)
    V_ds = load_any(v_wind_data, decode_coords = 'all', decode_times = True)
    
    wind_speed_ds = U_ds.copy()
    wind_speed_ds = wind_speed_ds.rename(u10 = 'wind_speed')
    wind_speed_ds['wind_speed'] = np.sqrt(U_ds.u10*U_ds.u10 + V_ds.v10*V_ds.v10)
        # nan remain nan
    
    print("   _ Transferring encodings...")
    wind_speed_ds['wind_speed'].encoding = V_ds.v10.encoding
    wind_speed_ds['wind_speed'].attrs['long_name'] = '10 metre wind speed'
    # Case of packing
    if ('scale_factor' in V_ds.v10.encoding) | ('add_offset' in V_ds.v10.encoding):
        # Packing (lossy compression) induces a loss of precision of 
        # apprx. 1/1000 of unit, for a quantity with an interval of 150 
        # units. The packing is initially used in some original ERA5-Land data
    
        # Theoretical max wind speed: 
        max_speed = 56 # m/s = 201.6 km/h
        (scale_factor, add_offset) = compute_scale_and_offset(-max_speed, max_speed, 16)
            # Out: (0.0017090104524299992, 0.0008545052262149966)
        wind_speed_ds['wind_speed'].encoding['scale_factor'] = scale_factor
        wind_speed_ds['wind_speed'].encoding['add_offset'] = add_offset
        # wind_speed_ds['wind_speed'].encoding['FillValue_'] = -32767
            # To remain the same as originally
            # Corresponds to -55.99829098954757 m/s
    
    return wind_speed_ds
    

###############################################################################
def compute_relative_humidity(*, dewpoint_input_file, 
                              temperature_input_file,
                              pressure_input_file,
                              method = "Penman-Monteith"):
    
    """
    cf formula on https://en.wikipedia.org/wiki/Dew_point
    
    gc.compute_relative_humidity(
        dewpoint_input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\ERA5\Brittany\2011-2021 Dewpoint temperature.nc", 
        temperature_input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\ERA5\Brittany\2011-2021 Temperature.nc",
        pressure_input_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\ERA5\Brittany\2011-2021 Surface pressure.nc",
        method = "Sonntag")
    
    """
    
    
    # ---- Loading data
    # --------------
    print("\nLoading data...")
    # Checking that the time period matches:
    years_motif = re.compile('\d{4,4}-\d{4,4}')
    years_dewpoint = years_motif.search(dewpoint_input_file).group()
    years_pressure = years_motif.search(pressure_input_file).group()
    years_temperature = years_motif.search(temperature_input_file).group()
    if (years_dewpoint == years_pressure) and (years_dewpoint == years_temperature):
        print("   Years are matching: {}".format(years_dewpoint))
    else:
        print("   /!\ Years are not matching: {}\n{}\n{}".format(years_dewpoint, years_pressure, years_temperature))
        # return 0
    
    with xr.open_dataset(dewpoint_input_file, decode_coords = 'all') as Dp:
        Dp.load() # to unlock the resource
    with xr.open_dataset(temperature_input_file, decode_coords = 'all') as T:
        T.load() # to unlock the resource
    with xr.open_dataset(pressure_input_file, decode_coords = 'all') as Pa:
        Pa.load() # to unlock the resource
    
    # ---- Sonntag formula
    # -----------------
    if method.casefold() in ['sonntag', 'sonntag1990']:
        print("\nComputing the relative humidity, using the Sonntag 1990 formula...")
        # NB : air pressure Pa is not used in this formula
        
        # Constants:
        alpha_ = 6.112 # [hPa]
        beta_ = 17.62 # [-]
        lambda_ = 243.12 # [°C]
        
        # Temperature in degrees Celsius:
        Tc = T.copy()
        Tc['t2m'] = T['t2m'] - 273.15
        Dpc = Dp.copy()
        Dpc['d2m'] = Dp['d2m'] - 273.15
        
        # Saturation vapour pressure [hPa]:
        Esat = Tc.copy()
        Esat = Esat.rename(t2m = 'vpsat')
        Esat['vpsat'] = alpha_ * np.exp((beta_ * Tc['t2m']) / (lambda_ + Tc['t2m']))
        
        # Vapour pressure [hPa]:
        E = Dp.copy()
        E = E.rename(d2m = 'vp')
        E['vp'] = alpha_ * np.exp((Dpc['d2m'] * beta_) / (lambda_ + Dpc['d2m']))
        
        # Relative humidity [%]:
        RHS = Dp.copy()
        RHS = RHS.rename(d2m = 'rh')
        RHS['rh'] = E['vp']/Esat['vpsat']*100
    
    elif method.casefold() in ['penman', 'monteith', 'penman-monteith']:
        print("\nComputing the relative humidity, using the Penman Monteith formula...")
        # NB : air pressure Pa is not used in this formula
        # Used in evaporationPot.py
        # http://www.fao.org/docrep/X0490E/x0490e07.htm   equation 11/12
        
        # Constants:
        alpha_ = 0.6108 # [kPa]
        beta_ = 17.27 # [-]
        lambda_ = 237.3 # [°C]
        
        # Temperature in degrees Celsius:
        Tc = T.copy()
        Tc['t2m'] = T['t2m'] - 273.15
        Dpc = Dp.copy()
        Dpc['d2m'] = Dp['d2m'] - 273.15
        
        # Saturation vapour pressure [kPa]:
        Esat = Tc.copy()
        Esat = Esat.rename(t2m = 'vpsat')
        Esat['vpsat'] = alpha_ * np.exp((beta_ * Tc['t2m']) / (lambda_ + Tc['t2m']))
        
        # Vapour pressure [kPa]:
        E = Dp.copy()
        E = E.rename(d2m = 'vp')
        E['vp'] = alpha_ * np.exp((beta_ * Dpc['d2m']) / (lambda_ + Dpc['d2m']))
        
        # Relative humidity [%]:
        # https://www.fao.org/3/X0490E/x0490e07.htm Eq. (10)
        RHS = Dp.copy()
        RHS = RHS.rename(d2m = 'rh')
        RHS['rh'] = E['vp']/Esat['vpsat']*100
        
    #% Attributes
    print("\nTransferring encodings...")
    RHS['rh'].attrs['units'] = '%'
    RHS['rh'].attrs['long_name'] = 'Relative humidity (from 2m dewpoint temperature)'
    RHS['rh'].encoding = Dp['d2m'].encoding
    # Case of packing
    if ('scale_factor' in Dp['d2m'].encoding) | ('add_offset' in Dp['d2m'].encoding):
        # Packing (lossy compression) induces a loss of precision of 
        # apprx. 1/1000 of unit, for a quantity with an interval of 150 
        # units. The packing is initially used in some original ERA5-Land data.
        
        # RHS['rh'].encoding['scale_factor'] = 0.0016784924086366065
        # RHS['rh'].encoding['add_offset'] = 55.00083924620432
        # RHS['rh'].encoding['_FillValue'] = 32767
        # RHS['rh'].encoding['missing_value'] = 32767
        (scale_factor, add_offset) = compute_scale_and_offset(-1, 100, 16)
            # Out: (0.0015411612115663385, 49.50077058060578)
        RHS['rh'].encoding['scale_factor'] = scale_factor
        RHS['rh'].encoding['add_offset'] = add_offset
        # RHS['rh'].encoding['_FillValue'] = -32767 
            # To match with original value
            # Corresponds to -0.9984588387884301 %
    
    
    return RHS


###############################################################################
# Convertit les données de radiation (J/m2/h) en W/m2
def convert_downwards_radiation(input_file, is_dailysum = False):   
    print("\nConverting radiation units...")
    rad = load_any(input_file, decode_coords = 'all', decode_times = True)
    
    var = main_var(rad)
    print("   _ Field is: {}".format(var))
    
    print("   _ Computing...")
    rad_W = rad.copy()
    if not is_dailysum:
        conv_factor = 3600 # because 3600s in 1h
    else:
        conv_factor = 86400 # because 86400s in 1d
    rad_W[var] = rad_W[var]/conv_factor 
    
    print("   _ Transferring encodings...")
    rad_W[var].attrs['units'] = 'W m**-2'
    rad_W[var].encoding = rad[var].encoding
    
    # Case of packing
    if ('scale_factor' in rad_W[var].encoding) | ('add_offset' in rad_W[var].encoding):
        # Packing (lossy compression) induces a loss of precision of 
        # apprx. 1/1000 of unit, for a quantity with an interval of 150 
        # units. The packing is initially used in some original ERA5-Land data.
        rad_W[var].encoding['scale_factor'] = rad_W[var].encoding['scale_factor']/conv_factor
        rad_W[var].encoding['add_offset'] = rad_W[var].encoding['add_offset']/conv_factor
        # NB: 
        # rad_W[var].encoding['FillValue_'] = -32767
            # To remain the same as originally
            # Corresponds to -472.11... m/s
            # NB: For few specific times, data are unavailable. Such data are coded 
            # with the value -1, packed into -32766
    
    return rad_W
    

###############################################################################
# Complete CWatM climatic variables
def secondary_era5_climvar(data):
    """
    This function computes the secondary data from ERA5-Land data, such as:
        - crop and water standard ETP from pan evaporation
        - wind speed from U- and V-components
        - relative humidity from T°, P and dewpoint

    Parameters
    ----------
    data : filepath or xarray.dataset (or xarray.dataarray)
        Main dataset used to generate secondary quantities.

    Returns
    -------
    None. Generates intended files.

    """
    
    # ---- Load main dataset
    data_ds = load_any(data, decode_coords = 'all', decode_times = True)
    var = main_var(data_ds)
    
    # ---- Corrections
    if var == 'pev': 
        ETref, EWref = compute_Erefs_from_Epan(data_ds)
        export(ETref, ' ET0crop'.join(os.path.splitext(data_ds)))
        export(EWref, ' EW0'.join(os.path.splitext(data_ds)))
    
    elif var in ['u10', 'v10']:
        if var == 'u10': 
            v10 = input("Filepath to V-component of wind")
            u10 = data_ds
            
        elif var == 'v10':
            u10 = input("Filepath to U-component of wind")
            v10 = data_ds
        
        wind_speed_ds = compute_wind_speed(u10, v10)
        export(wind_speed_ds, ' wind_speed'.join(os.path.splitext(data_ds)))
    
    elif var == 'rh':
        dewpoint_file = input("Filepath to dewpoint data: ")
        temperature_file = input("Filepath to 2m mean temperature data: ")
        pressure_file = input("Filepath to surface pressurce data: ")
        rhs_ds = compute_relative_humidity(
            dewpoint_input_file = dewpoint_file, 
            temperature_input_file = temperature_file,
            pressure_input_file = pressure_file,
            method = "Sonntag"
            )
        export(rhs_ds, ' Relative humidity'.join(os.path.splitext(data_ds)))

#%% * OBSOLETE ? Shift rasters (GeoTIFF or NetCDF)
###############################################################################
# Pas totalement fini. Code issu de 'datatransform.py'
def transform_tif(*, input_file, x_shift = 0, y_shift = 0, x_size = 1, y_size = 1):
    """
    EXAMPLE:
        import datatransform as dt
        dt.transform_tif(input_file = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\data\input_1km_LeMeu\areamaps\mask_cwatm_LeMeu_1km.tif",
                     x_shift = 200,
                     y_shift = 300)
    """
    
    # Ouvrir le fichier : 
    data = rasterio.open(input_file, 'r')
    # Récupérer le profil :
    _prof_base = data.profile
    trans_base = _prof_base['transform']
    # Juste pour visualiser :
    print('\nLe profil affine initial est :')
    print(trans_base)
    # Modifier le profile :  
    trans_modf = Affine(trans_base[0]*x_size, trans_base[1], trans_base[2] + x_shift,
                        trans_base[3], trans_base[4]*y_size, trans_base[5] + y_shift)
    print('\nLe profil modifié est :')
    print(trans_modf)
    _prof_modf = _prof_base
    _prof_modf.update(transform = trans_modf)
    
    # Exporter :
    _basename = os.path.splitext(input_file)[0]
    
    add_name = ''
    if x_shift != 0 or y_shift !=0:
        add_name = '_'.join([add_name, 'shift'])
        if x_shift != 0:
            add_name = '_'.join([add_name, 'x' + str(x_shift)])
        if y_shift != 0:
            add_name = '_'.join([add_name, 'y' + str(y_shift)])
    if x_size != 1 or y_size !=1:
        add_name = '_'.join([add_name, 'size'])
        if x_size != 1:
            add_name = '_'.join([add_name, 'x' + str(x_size)])
        if y_size != 1:
            add_name = '_'.join([add_name, 'y' + str(y_size)])
    output_file = '_'.join([_basename, add_name]) + '.tif'
    with rasterio.open(output_file, 'w', **_prof_modf) as out_f:
        out_f.write_band(1, data.read()[0])
    
    data.close()
    
def transform_nc(*, input_file, x_shift = 0, y_shift = 0, x_size = 1, y_size = 1):
    """
    EXAMPLE:
        import datatransform as dt
        dt.transform_nc(input_file = r"D:\2- Postdoc\2- Travaux\3_CWatM_EBR\data\input_1km_LeMeu\landsurface\topo\demmin.nc",
                     x_shift = 200,
                     y_shift = 400)       
    """
    
    with xr.open_dataset(input_file) as data:
        data.load() # to unlock the resource
        
    # Modifier :
    data['x'] = data.x + x_shift
    data['y'] = data.y + y_shift
    
    # Exporter :
    _basename = os.path.splitext(input_file)[0]
    
    add_name = ''
    if x_shift != 0 or y_shift !=0:
        add_name = '_'.join([add_name, 'shift'])
        if x_shift != 0:
            add_name = '_'.join([add_name, 'x' + str(x_shift)])
        if y_shift != 0:
            add_name = '_'.join([add_name, 'y' + str(y_shift)])
    if x_size != 1 or y_size !=1:
        add_name = '_'.join([add_name, 'size'])
        if x_size != 1:
            add_name = '_'.join([add_name, 'x' + str(x_size)])
        if y_size != 1:
            add_name = '_'.join([add_name, 'y' + str(y_size)])
    output_file = '_'.join([_basename, add_name]) + '.nc'
    
    data.to_netcdf(output_file)
    

#%% * tools for computing coordinates
###############################################################################
def convert_coord(pointXin, pointYin, inputEPSG = 2154, outputEPSG = 4326):	
    """
    Il y a un soucis dans cette fonction. X et Y se retrouvent inversées.
    Il vaut mieux passer par les fonctions rasterio (voir plus haut) :
        
    coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(inputEPSG), 
                                          rasterio.crs.CRS.from_epsg(outputEPSG), 
                                          [pointXin], [pointYin])
    pointXout = coords_conv[0][0]
    pointYout = coords_conv[1][0]
    """
    #% Inputs (standards)
    # =============================================================================
    # # Projected coordinates in Lambert-93 
    # pointXin = 350556.92318   #Easthing
    # pointYin = 6791719.72296  #Northing
    # (Rennes coordinates)
    # =============================================================================
    
    # =============================================================================
    # # Geographical coordinates in WGS84 (2D) 
    # pointXin = 48.13222  #Latitude (Northing)
    # pointYin = -1.7      #Longitude (Easting)
    # (Rennes coordinates)
    # =============================================================================
    
    # =============================================================================
    # # Spatial Reference Systems
    # inputEPSG = 2154   #Lambert-93
    # outputEPSG = 4326  #WGS84 (2D)
    # =============================================================================
    
    # # Conversion into EPSG system
    # For easy use, inputEPSG and outputEPSG can be defined with identifiers strings
    switchEPSG = {
        'L93': 2154,   #Lambert-93
        'L-93': 2154,  #Lambert-93
        'WGS84': 4326, #WGS84 (2D)
        'GPS': 4326,   #WGS84 (2D)
        'LAEA': 3035,  #LAEA Europe 
        }
    
    if isinstance(inputEPSG, str):
        inputEPSG = switchEPSG.get(inputEPSG, False)
        # If the string is not a valid identifier:
        if not inputEPSG:
            print('Unknown input coordinates system')
            return
            
    if isinstance(outputEPSG, str):
        outputEPSG = switchEPSG.get(outputEPSG, False)
        # If the string is not a valid identifier:
        if not outputEPSG:
            print('Unknown output coordinates system')
            return

    
    #% Outputs
# =============================================================================
#     # Méthode osr
#     # create a geometry from coordinates
#     point = ogr.Geometry(ogr.wkbPoint)
#     point.AddPoint(pointXin, pointYin)
#     
#     # create coordinate transformation
#     inSpatialRef = osr.SpatialReference()
#     inSpatialRef.ImportFromEPSG(inputEPSG)
#     
#     outSpatialRef = osr.SpatialReference()
#     outSpatialRef.ImportFromEPSG(outputEPSG)
#     
#     coordTransform = osr.CoordinateTransformation(inSpatialRef, outSpatialRef)
#     
#     # transform point
#     point.Transform(coordTransform)
#     pointXout = point.GetX()
#     pointYout = point.GetY()
# =============================================================================
    
    # Méthode rasterio      
    coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(inputEPSG), 
                                          rasterio.crs.CRS.from_epsg(outputEPSG), 
                                          [pointXin], [pointYin])
    pointXout = coords_conv[0][0]
    pointYout = coords_conv[1][0]
    
    # Return point coordinates in output format
    return(pointXout, pointYout)


#%% date tools for QGIS
"""
Pour faire facilement la conversion "numéro de bande - date" dans QGIS lorsqu'on
ouvre les fichers NetCDF comme rasters.

/!\ Dans QGIS, le numéro de 'band' est différent du 'time'
(parfois 'band' = 'time' + 1, parfois il y a une grande différence)
C'est le 'time' qui compte.
"""
###############################################################################
def date_to_index(_start_date, _date, _freq):
    time_index = len(pd.date_range(start = _start_date, end = _date, freq = _freq))-1
    print('La date {} correspond au temps {}'.format(_date, str(time_index)))
    return time_index


###############################################################################
def index_to_date(_start_date, _time_index, _freq):
    date_index = pd.date_range(start = _start_date, periods = _time_index+1, freq = _freq)[-1]
    print('Le temps {} correspond à la date {}'.format(_time_index, str(date_index)))
    return date_index


#%% main
if __name__ == "__main__":
    # Format the inputs (assumed to be strings) into floats
    sys.argv[1] = float(sys.argv[1])
    sys.argv[2] = float(sys.argv[2])
    # Print some remarks
    print('Arguments:')
    print(sys.argv[1:])
    # Execute the ConvertCoord function
    (a,b) = convert_coord(*sys.argv[1:])
    print(a,b)