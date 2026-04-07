# -*- coding: utf-8 -*-
"""
I/O utilities for HydroModPy examples.

Provides generalized functions for loading and saving data across examples:
- setup_paths(): Configure standardized directory structure
- load_raster(): Load GeoTIFF with optional masking
- load_vector(): Load shapefiles/geojson
- load_csv(): Load CSV with customizable options
- load_simulation_results(): Batch load all simulation outputs
- make_timeseries_data(): Create pandas timeseries
- save_results(): Unified save for multiple formats
- extract_watershed(): Legacy watershed extraction helper
"""

import logging
import os

import numpy as np
import pandas as pd
import rasterio
import geopandas as gpd
import imageio.v2 as imageio

logger = logging.getLogger(__name__)


def setup_paths(root_dir, example_name, results_dir="results", env_var_name=None):
    """
    Setup standardized paths for example data and output.

    Parameters:
    -----------
    root_dir : str
        Root directory of the project
    example_name : str
        Example name (e.g., '00S_short', '01S_short')
    results_dir : str
        Results directory name (default: 'results')
    env_var_name : str or None
        Environment variable name for output path override.
        If None, uses HYDROMODPY_{EXAMPLE_NAME}_OUT_PATH

    Returns:
    --------
    dict : Dictionary with keys:
        - 'regression': example data directory path
        - 'data': data subdirectory path
        - 'output': output/results directory path
        - 'stable': stable results path
        - 'simulations': simulations results path
    """
    regression_path = os.path.join(root_dir, "examples_legacy", example_name)
    data_path = os.path.join(regression_path, "data")

    if env_var_name is None:
        env_var_name = f"HYDROMODPY_{example_name.upper()}_OUT_PATH"

    out_path = os.getenv(env_var_name,
                        os.path.join(root_dir, "examples_legacy", results_dir))

    paths = {
        'regression': regression_path,
        'data': data_path,
        'output': out_path,
        'stable': os.path.join(out_path, example_name, 'results_stable'),
        'simulations': os.path.join(out_path, example_name, 'results_simulations')
    }
    return paths


def load_raster(filepath, band=1, mask_value=None, mask_operator='<='):
    """
    Load raster file with optional masking.

    Parameters:
    -----------
    filepath : str
        Path to raster file (.tif, .tiff, .png, etc.)
    band : int
        Band number for multi-band files (default: 1)
    mask_value : float or None
        Value threshold for masking (e.g., 0 or -9999)
    mask_operator : str
        Masking operator: '<=', '<', '==', '>', '>=' (default: '<=')

    Returns:
    --------
    tuple : (data, rasterio_object) for .tif/.tiff, (data, None) for other formats
        - data: numpy array or masked array
        - rasterio_object: rasterio dataset for coordinate transforms, or None

    Examples:
    ---------
    >>> dem_data, dem_rio = load_raster('dem.tif')
    >>> wtd_data, wtd_rio = load_raster('wtd.tif', mask_value=0, mask_operator='<=')
    """
    if filepath.lower().endswith(('.tif', '.tiff')):
        rio = rasterio.open(filepath)
        data = rio.read(band)

        if mask_value is not None:
            if mask_operator == '<=':
                data = np.ma.masked_where(data <= mask_value, data)
            elif mask_operator == '<':
                data = np.ma.masked_where(data < mask_value, data)
            elif mask_operator == '==':
                data = np.ma.masked_where(data == mask_value, data)
            elif mask_operator == '>':
                data = np.ma.masked_where(data > mask_value, data)
            elif mask_operator == '>=':
                data = np.ma.masked_where(data >= mask_value, data)

        return data, rio
    else:
        # For other formats (png, jpg, etc.)
        data = imageio.imread(filepath)
        return data, None


def load_vector(filepath, file_type='shp'):
    """
    Load vector file (shapefile, geojson, etc.).

    Parameters:
    -----------
    filepath : str
        Path to vector file (.shp, .geojson, etc.)
    file_type : str
        File type hint ('shp', 'geojson', etc.) - detected from filepath

    Returns:
    --------
    GeoDataFrame : GeoPandas GeoDataFrame with geometries and attributes

    Examples:
    ---------
    >>> pathlines_gdf = load_vector('pathlines_weighted.shp')
    >>> contour_gdf = load_vector('watershed_contour.geojson')
    """
    return gpd.read_file(filepath)


def load_csv(filepath, sep=';', index_col=0, parse_dates=False):
    """
    Load CSV file with customizable options.

    Parameters:
    -----------
    filepath : str
        Path to CSV file
    sep : str
        Column separator (default: ';')
    index_col : int or None
        Column index to use as DataFrame index (default: 0)
    parse_dates : bool
        Parse index/columns as dates (default: False)

    Returns:
    --------
    DataFrame : Pandas DataFrame with data

    Examples:
    ---------
    >>> data_df = load_csv('data.csv', sep=',')
    >>> timeseries_df = load_csv('timeseries.csv', parse_dates=True)
    """
    return pd.read_csv(filepath, sep=sep, index_col=index_col, parse_dates=parse_dates)


def load_simulation_results(simulations_folder, model_name, result_types=None):
    """
    Load all simulation results (rasters, vectors, timeseries).

    Automatically loads standard result files from HydroModPy post-processing output.

    Parameters:
    -----------
    simulations_folder : str
        Path to simulations folder (e.g., results/example_00/results_simulations)
    model_name : str
        Name of model/simulation (e.g., 'test_0')
    result_types : list or None
        List of result types to load. If None, loads all available.
        Available types: 'wte' (water table elevation), 'wtd' (water table depth),
                        'seepage', 'pathlines', 'timeseries'

    Returns:
    --------
    dict : Dictionary with loaded results:
        - 'wte_data': water table elevation array
        - 'wte_rio': water table elevation rasterio object
        - 'wtd_data': water table depth masked array
        - 'wtd_rio': water table depth rasterio object
        - 'seep_data': seepage areas masked array
        - 'seep_rio': seepage areas rasterio object
        - 'pathlines': pathlines GeoDataFrame
        - 'timeseries': timeseries DataFrame

    Examples:
    ---------
    >>> results = load_simulation_results(simulations_folder, 'test_0')
    >>> wte_data = results['wte_data']
    >>> results = load_simulation_results(simulations_folder, 'test_0',
    ...                                    result_types=['wte', 'pathlines'])
    """
    if result_types is None:
        result_types = ['wte', 'wtd', 'seepage', 'pathlines', 'timeseries']

    model_path = os.path.join(simulations_folder, model_name)
    results = {}

    try:
        # Load rasters
        if 'wte' in result_types:
            wte_path = os.path.join(model_path, '_postprocess/_rasters/watertable_elevation_t(0).tif')
            results['wte_data'], results['wte_rio'] = load_raster(wte_path)

        if 'wtd' in result_types:
            wtd_path = os.path.join(model_path, '_postprocess/_rasters/watertable_depth_t(0).tif')
            results['wtd_data'], results['wtd_rio'] = load_raster(wtd_path, mask_value=0, mask_operator='<=')

        if 'seepage' in result_types:
            seep_path = os.path.join(model_path, '_postprocess/_rasters/seepage_areas_t(0).tif')
            results['seep_data'], results['seep_rio'] = load_raster(seep_path, mask_value=0, mask_operator='<=')

        # Load vectors
        if 'pathlines' in result_types:
            pathlines_path = os.path.join(model_path, '_postprocess/_particles/pathlines_weighted.shp')
            results['pathlines'] = load_vector(pathlines_path)

        # Load timeseries
        if 'timeseries' in result_types:
            ts_path = os.path.join(model_path, '_postprocess/_timeseries/_simulated_timeseries.csv')
            results['timeseries'] = load_csv(ts_path, parse_dates=True)

        logger.info("Loaded %d result(s) for model '%s'", len(results), model_name)
        return results

    except FileNotFoundError as e:
        logger.warning("Some files not found - %s", e)
        return results


def make_timeseries_data(start_date, end_date, freq, values, name='timeseries'):
    """
    Create pandas timeseries with DatetimeIndex.

    Parameters:
    -----------
    start_date : str
        Start date (e.g., '2017-01-01')
    end_date : str
        End date (e.g., '2017-12-31')
    freq : str
        Frequency ('ME' for month-end, 'D' for daily, etc.)
    values : array-like
        Values for the timeseries
    name : str
        Series name (default: 'timeseries')

    Returns:
    --------
    Series : Pandas Series with DatetimeIndex

    Examples:
    ---------
    >>> recharge = make_timeseries_data('2017-01-01', '2017-12-31', 'ME',
    ...                                  [10, 20, 15, ...], name='recharge')
    """
    time_index = pd.date_range(start=start_date, end=end_date, freq=freq)
    return pd.Series(values, index=time_index, name=name)


def save_results(data, filepath, format='csv'):
    """
    Save results to file in specified format.

    Parameters:
    -----------
    data : DataFrame, Series, GeoDataFrame, or array
        Data to save
    filepath : str
        Output file path
    format : str
        Output format: 'csv', 'geojson', 'netcdf' (default: 'csv')

    Returns:
    --------
    None

    Examples:
    ---------
    >>> save_results(df, 'output.csv', format='csv')
    >>> save_results(geodf, 'polygons.geojson', format='geojson')
    >>> save_results(xr_dataset, 'output.nc', format='netcdf')
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    if format == 'csv':
        if isinstance(data, (pd.DataFrame, pd.Series)):
            data.to_csv(filepath, sep=';')
    elif format == 'geojson':
        if isinstance(data, gpd.GeoDataFrame):
            data.to_file(filepath, driver='GeoJSON')
    elif format == 'netcdf':
        if hasattr(data, 'to_netcdf'):
            data.to_netcdf(filepath)
    logger.info("Saved to %s", filepath)


def extract_watershed(dem_path, out_path, watershed_name, from_xyv=None, from_shp=None,
                      from_dem=None, catch_def="xy", bottom_path=None, load=False, save_object=True):
    """
    Extract watershed with the deprecated legacy watershed runtime.

    This helper is kept only for old notebooks and example scripts.
    New code should build a geographic context from
    ``hydromodpy.spatial.geographic`` and continue through the modern runtime.

    Parameters:
    -----------
    dem_path : str
        Path to regional DEM raster file
    out_path : str
        Output/results directory path
    watershed_name : str
        Name of the watershed (e.g., '00S_short', '01S_short')
    from_xyv : list or None
        Outlet coordinates [x, y, snap_distance, buffer_size, EPSG] for xy-based extraction.
        Example: [150727.164, 6858066.520, 100, 10, 'EPSG:2154']
    from_shp : str or None
        Path to shapefile for shapefile-based extraction
    from_dem : list or None
        [dem_path, cell_size] for DEM-based extraction
    catch_def : str
        Extraction definition mode: 'xy', 'shp', or 'dem' (default: 'xy')
    bottom_path : str or None
        Path to bottom elevation file (default: None = automatic)
    load : bool
        Load existing watershed object (default: False = create new)
    save_object : bool
        Save watershed object to disk (default: True)

    Returns:
    --------
    Watershed : HydroModPy Watershed object with extracted catchment

    Examples:
    ---------
    >>> BV = extract_watershed(dem_path='data/dem.tif',
    ...                         out_path='results',
    ...                         watershed_name='00S_short',
    ...                         from_xyv=[150727.164, 6858066.520, 100, 10, 'EPSG:2154'])

    >>> BV = extract_watershed(dem_path='data/dem.tif',
    ...                         out_path='results',
    ...                         watershed_name='watershed_1',
    ...                         from_shp='data/catchment_boundary.shp')
    """
    from hydromodpy.watershed import Watershed

    BV = Watershed(
        dem_path=dem_path,
        out_path=out_path,
        load=load,
        watershed_name=watershed_name,
        from_dem=from_dem,
        from_shp=from_shp,
        from_xyv=from_xyv,
        catch_def=catch_def,
        bottom_path=bottom_path,
        save_object=save_object
    )
    logger.info("Watershed '%s' extracted successfully", watershed_name)
    return BV



