# -*- coding: utf-8 -*-
"""
Created on Thu 16 Dec 2021

@author: Alexandre Coche Kenshilikov
@contact: alexandre.co@hotmail.fr
@version: 1.9.0
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
import os
import re
import sys
import pathlib
import math


#%% Rename time coord
def rename_time(data_ds):
    if ('valid_time' in data_ds.coords) | ('valid_time' in data_ds.data_vars):
        data_ds = data_ds.rename({'valid_time': 'time'})
        
    return data_ds

#%% Load
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
            

#%% Georef (ex-decorate_NetCDF_for_QGIS)
def georef(*, data, include_crs = True, export_opt = False, dst_crs = None):   
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
    dst_crs : int, optional
        Destination CRS, only necessary when data_type == 'other' The default is None.

    Returns
    -------
    xarray.Dataset or geopandas.GeoDataFrame. 
    
    """
    
    
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
            if dst_crs is not None:
                data_epsg = dst_crs
            else:
                print("   _ Err: it is required to pass the dst_crs argument")
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
            if dst_crs is not None:
                data_epsg = dst_crs
            else:
                print("   _ Err: it is required to pass the dst_crs argument")
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


    #%%% Export
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
        
        
    #%% Return variable
    return data_ds



#%% Standard grid_mapping
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


#%% Standard _FillValue
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


#%% Align on the closest value
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
    
    #%% Paramètres d'alignement : 
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


#%% Format x_res and y_res
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


#%% Get shape
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

#%% Reproject
def reproject(data, *, src_crs=None, base_template=None, bounds=None,  
              x0=None, y0=None, mask=None, **rio_kwargs):
    r"""
    

    Parameters
    ----------
    data : 
        Data to reproject. Filepath, xarray.dataset or dataarray.
    src_crs : int (epsg) or CRS, optional
        Source coordinate reference system. The default is None.
    base_template : str, optional
        Filepath, used as a template for spatial profile. The default is None.
    x0: number, optional
        Origin of the X-axis, used to align the reprojection grid. 
        The default is None
    y0: number, optional
        Origin of the Y-axis, used to align the reprojection grid. 
        The default is None
    mask : optional
        Filepath of geopandas.dataframe of mask.
        The default is None.
    
    **rio_kwargs : keyword args
        Argument passed to the xarray.Dataset.rio.reproject() function call.
        These arguments are prioritary over base_template attributes.
        May contain: 
            . dst_crs
            . resolution
            . shape
            . transform
            . resampling
            . nodata
            > help(xr.Dataset.rio.reproject)

    Returns
    -------
    None.

    """
    
    #%%% Load data, base and mask
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
    
    #%%% Compute parameters
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


    #%% Reproject
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
  
            
#%% Compress or decompress
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


#%% Export
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


#%% Get filelist
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
    
   
#%% Calcule ETref et EWref à partir de la "pan evaporation" de ERA5-Land
def compute_Erefs_from_ERA5L(input_file):
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


#%% Calcule la vitesse du vent
def compute_wind_speed(u_wind_data, v_wind_data):
    """
    U-component of wind is parallel to the x-axis
    V-component of wind is parallel to the y-axis
    """
    
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
    

#%% Calcule l'humidité relative (RHS)
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
    
    
    #%% Loading data
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
    
    #%% Sonntag formula
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


#%% Convertit les données de radiation (J/m2/h) en W/m2
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
    

#%% hourly_to_daily
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


#%% correct_era5: Corrige les précipitations, rayonnements, ETP... de ERA5-Land
def correct_era5_bias(input_file, correct_factor = 1, to_dailysum = True,
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


#%% Convert to CWatM (ex Prepare CWatM inputs)
def convert_to_cwatm(data, reso_m = None, EPSG_out=None, 
                        EPSG_in = None, coords_extent = 'Bretagne'):
    """
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
        or keywords: "Bretagne", "from_input"

    Returns
    -------
    None.

    """
    

    # ---- Merge files
    # Usually ERA5-Land files are too big to be downloaded for the full period.
    # Here the first step is to merge the available ERA5.nc files.
    
    data_folder, filelist = get_filelist(data, filetype = '.nc')

    ds_list = []
    if len(filelist) > 1:
        print("Merging files...")
        
    for f in filelist:
        ds_list.append(load_any(os.path.join(data_folder, f), 
                                decode_coords = 'all', 
                                decode_times = True))
        print(f"      . {f}")
    var = main_var(ds_list[0])
    # Backup of attributes and encodings
# ========== useless ==========================================================
#         attrs = ds_list[0][var].attrs.copy()
# =============================================================================
    encod = ds_list[0][var].encoding.copy()

    merged_ds = xr.merge(ds_list)
# ========== wrong ============================================================
#         merged_ds = xr.concat(ds_list, dim = 'time')
# =============================================================================
# ========== useless ==========================================================
#         merged_ds = merged_ds.sortby('time') # In case the files are not loaded in time order   
# =============================================================================
    
    # Encodings (_FillValue, compression...)
    merged_ds[var].encoding = encod
    
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
        
    
#%% Complete CWatM climatic variables
def secondary_climvar(data):
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
        ETref, EWref = compute_Erefs_from_ERA5L(data_ds)
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
    

#%% tools for computing coordinates
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

def date_to_index(_start_date, _date, _freq):
    time_index = len(pd.date_range(start = _start_date, end = _date, freq = _freq))-1
    print('La date {} correspond au temps {}'.format(_date, str(time_index)))
    return time_index

def index_to_date(_start_date, _time_index, _freq):
    date_index = pd.date_range(start = _start_date, periods = _time_index+1, freq = _freq)[-1]
    print('Le temps {} correspond à la date {}'.format(_time_index, str(date_index)))
    return date_index


#%% Packing netcdf (previously packnetcdf.py)
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


def pack_value(unpacked_value, scale_factor, add_offset):
    print(f'math.floor: {math.floor((unpacked_value - add_offset) / scale_factor)}')
    return (unpacked_value - add_offset) / scale_factor


def unpack_value(packed_value, scale_factor, add_offset):
    return packed_value * scale_factor + add_offset

#%% Find main data variable
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