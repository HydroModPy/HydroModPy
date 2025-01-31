# -*- coding: utf-8 -*-
"""
Created on Fri Jan 31 2025

@author: Alexandre Coche
"""

#%% Imports
import os
import geohydroconvert as ghc


#%% Pipeline
def pipeline(data, *, 
             mask=None, bounds=None, 
             resolution=None, x0=None, y0=None,
             base_template=None, **rio_kwargs,
             ):
    """
    Pipeline to execute all the necessary steps to format ERA5-Land original
    datasets to CWatM.

    Parameters
    ----------
    data : str, list of str
        Folder, filepath or list of filepaths
    mask : optional
        Filepath of geopandas.dataframe of mask.
        The default is None.
    bounds : TYPE, optional
        DESCRIPTION. The default is None.
    resolution : TYPE, optional
        DESCRIPTION. The default is None.
    x0: number, optional
        Origin of the X-axis, used to align the reprojection grid. 
        The default is None
    y0: number, optional
        Origin of the Y-axis, used to align the reprojection grid. 
        The default is None
    base_template : str, optional
        Filepath, used as a template for spatial profile. The default is None.
    
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
    None. Generates the formated files.

    """
    #### Initialisation
    # -+-+-+-+-+-+-+-+-   
    if isinstance(resolution, int) or resolution is None:
        resolution = [resolution]
        
    if not isinstance(mask, list):
        mask = [mask]
    
    ### Pipeline
    # -+-+-+-+-+-
    # ---- Convertit l'argument 'data' en liste de fichiers
    data_folder, filelist = ghc.get_filelist(data, filetype = '.nc')

    outpath = os.path.splitext(filelist[0])[0]
    outpath = os.path.join(data_folder, outpath)
    
    
    # ---- Corrige les données
    #   - fusionne les fichiers
    #   - convertit valeurs horaires en journalières
    #   - corrige les unités si besoin
    ds = ghc.convert_to_cwatm([os.path.join(data_folder, f) for f in filelist])
    
    
    # ---- Géoréférence les données
    #   - embed the coordinate reference system coord
    #   - standardize coords, to be recognized by QGIS
    ds = ghc.georef(data = ds, dst_crs = 4326)
    
    
    # ---- Reprojections et exports
    for res in resolution:
        if res is None:
            res_suffix = ''
            if 'resolution' in rio_kwargs:
                rio_kwargs.pop('resolution')
        else:
            res_suffix = f'_{res}m'
            rio_kwargs['resolution'] = res
        n_mask = 0
        for m in mask:
            n_mask += 1
            ds_rprj = ghc.reproject(data = ds, mask = m, bounds = bounds,
                                 x0 = x0, y0 = y0, base_template = base_template,
                                 **rio_kwargs)
            ghc.export(ds_rprj, outpath + res_suffix + f'_mask{n_mask}' + '.nc')
            

#%% Correct biaises
def correct_biais(data, correct_factor, to_dailysum, progressive):
    """
    Correction très simpliste des valeurs ERA5-Land en appliquant un facteur 
    de correction.
    
    Fonction plutôt à utiliser sur les données finales formatées
    correct_factor:
        - for precipitations (hourly) : 1.8
        - for precipitations (daily sum): 0.087 
        - for radiations (daily sum): 0.0715 (and progressive = True)
        - for potential evapotranspiration pos (daily sum): 0.04
    """
    
    ghc.correct_era5_bias(data, correct_factor, to_dailysum, progressive)


#%% Additional variables
def derived_var(data):
    """
    To generate the secondary data from ERA5-Land data, such as:
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
    
    ghc.secondary_climvar(data)
