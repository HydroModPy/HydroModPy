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

# Python
import numpy as np
import os
import pandas as pd
import sys
from os.path import dirname, abspath
import geopandas as gpd

import rasterio as rio
import rasterio.features # necessary to avoid a bug
import xarray as xr
xr.set_options(keep_attrs = True)
# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger

logger = get_logger(__name__)

#%% CLASS

class Netcdf:
    """
    Convert result dicts (.npy) into netCDF spatiotemporal maps.
    """

    def __init__(self,
                 geographic: object,
                 model_modflow: object,
                 datetime_format: bool=True):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        model_modflow : object
            MODFLOW model object.
        datetime_format : bool, optional
            Indicate if the model is referenced with datetime format. The default is True.
        subbasin_results : bool, optional
            Indicated if simulation results need to be created at subassins scale. The default is True.
        """

        logger.info("Exporting MODFLOW results as NetCDF for model %s", model_modflow.model_name)

        self.geographic = geographic

        self.stable_folder = self.geographic.stable_folder
        self.simulations = self.geographic.simulations_folder

        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder

        self.datetime_format = datetime_format

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.tifs_file = os.path.join(self.full_path, '_postprocess', '_rasters')

        # Create folder
        self.save_file = os.path.join(self.full_path, '_postprocess')
        if not os.path.exists(self.save_file):
            toolbox.create_folder(self.save_file)
        self.netcdf_file = os.path.join(self.save_file, '_netcdf')
        if not os.path.exists(self.netcdf_file):
            toolbox.create_folder(self.netcdf_file)

        # Get times
        self.recharge = model_modflow.recharge

        if self.datetime_format==True:
            if isinstance(self.recharge,(int,float)) == True:
                time=[0]
            else:
                time = self.recharge.index
        else:
            if isinstance(self.recharge,(int,float)) == True:
                time=[0]
            else:
                if isinstance(self.recharge,(dict))==False:
                    time = np.array(range(len(self.recharge)))
                else:
                    time = pd.Series(range(len(self.recharge)), index=range(len(self.recharge)))

        # Get npy file names
        npy_list = []
        for f in os.listdir(self.save_file):
             name, ext = os.path.splitext(f)
             if ext == '.npy':
                 npy_list.append(name)

        # Load each npy file and export it to netcdf
        try:
            dict_watertable_elevation = np.load(os.path.join(self.save_file, 'watertable_elevation'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_watertable_elevation,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'watertable_elevation.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_watertable_depth = np.load(os.path.join(self.save_file, 'watertable_depth'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_watertable_depth,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'watertable_depth.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_seepage_areas = np.load(os.path.join(self.save_file, 'seepage_areas'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_seepage_areas,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'seepage_areas.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_outflow_drain = np.load(os.path.join(self.save_file, 'outflow_drain'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_outflow_drain,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'outflow_drain.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_groundwater_flux = np.load(os.path.join(self.save_file, 'groundwater_flux'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_groundwater_flux,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'groundwater_flux.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_saturated_storage = np.load(os.path.join(self.save_file, 'saturated_storage'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_saturated_storage,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'saturated_storage.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_groundwater_storage = np.load(os.path.join(self.save_file, 'groundwater_storage'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_groundwater_storage,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'groundwater_storage.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_accumulation_flux = np.load(os.path.join(self.save_file, 'accumulation_flux'+'.npy'), allow_pickle=True).item()
            self.export_netcdf(dict_accumulation_flux,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'accumulation_flux.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass
        try:
            dict_residence_times = gpd.read_file(os.path.join(self.save_file, '_particules', 'ending'+'.shp'))
            self.export_netcdf(dict_residence_times,
                               base_path = self.geographic.watershed_dem,
                               out_path = os.path.join(self.netcdf_file, 'accumulation_flux.nc'),
                               base_crs = self.geographic.crs_proj,
                               times = time)
        except:
            pass


    #%% EXPORT DATA TO NETCDF FILES

    def export_netcdf(self, data, *, base_path:str, out_path:str, base_crs=None,
                      times=None, y=None, x=None, append:bool=False):
        r"""
        Export raw results from HydroModPy (aggregated results over times stored
        in dict, obtained with the postprocessing_modflow method of the Watershed
        objects) to a netcdf file formated with the same spatial attributes
        (resolution, extent, CRS) as the base file.

        Parameters
        ----------
        data : dict
            Initial data obtained with the postprocessing_modflow method of the
            Watershed objects.
        base_path : str
            Filepath to the file that will be used as the base for the spatial
            attributes. It is advised to use one of the files generated in the
            \results_stable\geographic\ directory.
        out_path : str
            Filepath of the output file.
        base_crs : str or int, optional (the default is none)
            Coordinates reprojection system (both for input and output). The CRS
            from the base file is used first. If there is none, base_crs is used
            instead.
        times : sequence, optional
            A sequence containing the dates for the time coordinate of the netcdf.
            It is advised to use the index from the recharge:
                <Watershed_object>.climatic.recharge.index (DatetimeIndex)
            If 'times' is a pandas.series, the index is extracted and used as
            times.
            The default is None.
        y : array, optional
            Values for the Y-coordinate. If None (default), the values will be
            inferred from the resolution and spatial extent of the domain.
        x : array, optional
            Values for the X-coordinate. If None (default), the values will be
            inferred from the resolution and spatial extent of the domain.
        append : bool
            Option to append values to existing netcdf file (used in sequential
            coupling of modflow simulation).

        Returns
        -------
        Create a *.nc file with the indicated out_path.

        """

        # Metadata
        if isinstance(base_crs, str): base_crs = rio.crs.CRS.from_string(base_crs)
        elif isinstance(base_crs, int): base_crs = rio.crs.CRS.from_epsg(base_crs)
        with rio.open(base_path, 'r') as base:
            base_profile = base.profile
            if base_crs and not base_profile.get('crs'):
                base_profile['crs'] = base_crs
            val_for_mask = base.read(1)
        [reso_x, _, x_min, _, reso_y, y_max, _, _, _] = list(base_profile['transform'])
        if not x:
            x_val = [x for x in np.arange(x_min + reso_x/2, x_min + reso_x*base_profile['width'] + reso_x/2, reso_x)]
        if not y:
            y_val = [y for y in np.arange(y_max + reso_y/2, y_max + reso_y*base_profile['height'] + reso_y/2, reso_y)]
        # If times is a pandas.series, then its index is used as times
        if isinstance(times, pd.core.series.Series):
            times = times.index
        # If times is a number, then it is set to its default value None
        try: len(times)
        except TypeError: times = None

        # Create xarray Dataset
        M = np.array([data[item] for item in data.keys()])
        da = xr.DataArray(M, dims = ('time', 'y', 'x'))
        if times is not None:
            da = da.assign_coords({"time": ("time", times),
                                   "y": ("y", y_val),
                                   "x": ("x", x_val)})
        else:
            da = da.assign_coords({"y": ("y", y_val),
                                   "x": ("x", x_val)})
        da = da.where(val_for_mask != base_profile['nodata'])
        ds = xr.Dataset()
        main_var = os.path.splitext(os.path.split(out_path)[-1])[0]
        ds[main_var] = da

        if append:
            with xr.open_dataset(
                    out_path, decode_coords = 'all', decode_times = True) as ds_prev:
                ds = xr.concat([ds_prev, ds], dim = 'time')

        # Attributes
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
        bound_max = float(ds[main_var].max())
        bound_min = float(ds[main_var].min())
        if bound_min<0: bound_min = bound_min*1.1
        elif bound_min>0: bound_min = bound_min/1.1
        else: bound_min = bound_min - 0.01*bound_max
        scale_factor, add_offset = self.compute_scale_and_offset(bound_min,
                                                                 bound_max,
                                                                 16)
        ds[main_var].encoding['scale_factor'] = scale_factor
        ds[main_var].encoding['add_offset'] = add_offset
        ds[main_var].encoding['dtype'] = 'int16'
        ds[main_var].encoding['_FillValue'] = -32768

        # Export
        ds.to_netcdf(out_path)

    #%% PACKING NETCDF
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

    @staticmethod
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

    @staticmethod
    def pack_value(unpacked_value, scale_factor, add_offset):
        logger.debug(
            "Packing value %.6f with scale %.6f and offset %.6f",
            unpacked_value,
            scale_factor,
            add_offset,
        )
        return (unpacked_value - add_offset) / scale_factor

    @staticmethod
    def unpack_value(packed_value, scale_factor, add_offset):
        return packed_value * scale_factor + add_offset

#%% NOTES
"""
First implemented in May 2024. Alexandre Coche
"""
