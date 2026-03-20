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
import sys
import os
import pickle
import geopandas as gpd
import rasterio

# Root
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from hydromodpy.geographic.geographic import Geographic
import warnings as _warnings
with _warnings.catch_warnings():
    _warnings.filterwarnings("ignore", category=DeprecationWarning,
                             message=".*hydromodpy\\.data_managers\\.climatic.*")
    from hydromodpy.data_managers.climatic.driaseau import Driaseau
    from hydromodpy.data_managers.climatic import driasclimat, safransurfex
from hydromodpy.postprocess import netcdf
from hydromodpy.support.tools import toolbox, get_logger
from hydromodpy.support.tools import setup_simulation_log

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

logger = get_logger(__name__)


#%% CLASS

class Watershed:
    """
    Class Watershed is used to extract watershed and its data from regional DEM.
    Hub to all elements necessary or optional to construct watersheds (meaning catchements) and run modflow simulations.
    """

    def __init__(self,
                 geographic_object: Geographic,
                 load: bool=False,
                 initializing_object: object=None,
                 setting_object: object=None,
                 hydraulic_object: object=None,
                 save_object: bool=True,
                 transport_object: object=None,
                 hydrography_object: object=None,
                 subbasin_object: object=None,
                 geology_object: object=None,
                 hydrometry_object: object=None,
                 intermittency_object: object=None,
                 climatic_object: object=None,
                 oceanic_object: object=None
                 ):
        """
        Parameters
        ----------
        dem_path : str
            Path of the initial Digital Elevation Model (DEM).
        out_path : str
            Path of the HydroModPy outputs to store results.
        load : bool, optional
            Load the existing watershed object. The default is False.
        watershed_name : str, optional
            Name of the watershed (name of folder results). The default is 'Default'.
        from_dem : list, optional
            List with two parameters: [path, cell_size]
            path: Path of the DEM
            cell_size: Resolution of the DEM. To change the initial resolution.
            The default is empty list.
        from_shp : list, optional
            List of tow parameters: [path, buffer_size]
            path: Path of the polygon shapefile.
            buffer_size: Buffer distance (value in percent)
            The default is empty list.
        from_xyv : list, optional
            List of four parameters: [x, y, snap_distance, buffer_size]
            x: X coordinate [m] of the watershed outlet
            y: Y coordinate [m] of the watershed outlet
            snap_dist: Maximum distance where the outlet can be moved.
            buffer_size: Buffer added to the generated watershed polygon (value in percent)
            The default is empty list.
        catch_def : str, optional
            Catchment definition mode.
            Supported modes are:
            - ``"dem"``: model domain defined directly from ``from_dem``.
            - ``"txt"``: model domain built from an XYZ text file
              (``dem_path`` ending with ``.txt``).
            - ``"xy"``: watershed defined from outlet coordinates provided in
              ``from_xyv``.
            - ``"shp"``: watershed defined from a polygon shapefile provided in
              ``from_shp``.
            The default is None.
        reg_fold : str, None
            Path of the folder with regional data/results.
            If informed, the regional results will not be created, just loaded from folder.
            The default is None.
        bottom_path : str, optional
            Path of a raster representing the bottom elevation.
            Need to be the same shape of the model domain area (watershed DEM).
            The default is None.
        save_object : bool, optional
            True : To save the watershed object (using pickle). The default is True.
        """

        toolbox.print_hydromodpy()
                
        self.watershed_name = initializing_object.catch_name
        self.out_path = initializing_object.out_dir_path

        self.load = load

        self.bin_path = os.path.join(os.path.dirname(root_dir), 'bin')

        self.watershed_folder = os.path.join(self.out_path, self.watershed_name)
        toolbox.create_folder(self.watershed_folder)

        # Setup simulation log in watershed folder
        setup_simulation_log(self.watershed_folder)

        self.stable_folder = initializing_object.stable_folder
        self.simulations_folder = initializing_object.simulations_folder
        self.calibration_folder = initializing_object.calibration_folder

        self.add_data_folder = os.path.join(self.stable_folder, 'add_data')
        toolbox.create_folder(self.add_data_folder)

        self.figure_folder = os.path.join(self.stable_folder, '_figures')
        toolbox.create_folder(self.figure_folder)

        self.elt_def = []

        success = False

        if load==True:
            # Load from previously stored (saved) watershed
            success = self.__load_object()
            if success == True:
                logger.info("Python object was successfully loaded as requested; imported from output directory %s", self.watershed_folder)
            if success == False:
                logger.warning("Stored watershed object not available; rebuilding from inputs")
                # Definition of the watershed
                self.__init_object()
                # Creation of the watershed defined at the previous line
                self.geographic = geographic_object
                self.elt_def.append('geographic')
                # Save object
                if save_object == True:
                    self.save_object()
        else:
            logger.info("Initializing watershed object from scratch as requested")
            # Definition of the watershed
            self.__init_object()
            # Creation of the watershed defined at the previous line
            self.geographic = geographic_object
            self.elt_def.append('geographic')
            # Save object
            if save_object == True:
                self.save_object()
                
        self.settings = setting_object
        self.elt_def.append('settings')
        self.hydraulic = hydraulic_object
        self.elt_def.append('hydraulic')
        self.transport = transport_object
        self.elt_def.append('transport')
        self.hydrography = hydrography_object
        self.elt_def.append('hydrography')
        self.subbasin = subbasin_object
        self.elt_def.append('subbasin')
        self.geology = geology_object
        self.elt_def.append('geology')
        self.hydrometry = hydrometry_object
        self.elt_def.append('hydrometry')
        self.intermittency = intermittency_object
        self.elt_def.append('intermittency')
        self.climatic = climatic_object
        self.elt_def.append('climatic')
        self.oceanic = oceanic_object
        self.elt_def.append('oceanic')

    #%% PYTHON OBJECT

    def __load_object(self):
        """
        Private method to load watershed object.

        Returns
        -------
        success : bool
            True if the watershed object is load succesfully.
        """
        if os.path.exists(os.path.join(self.watershed_folder, 'watershed_object')):

            # Load watershed object from pickle file
            with open(os.path.join(self.watershed_folder, 'watershed_object'), 'rb') as config_dictionary_file:
                BV = pickle.load(config_dictionary_file)

            # At least geographic should have been stored
            if ('geographic' in BV.__dir__()) == True:
                self.geographic = BV.geographic
                self.elt_def.append('geographic')
            else:
                logger.warning("geographic doesn't exist in object")
                return False
            if ('subbasin' in BV.__dir__()) == True:   # Generates basin where there are hydrological stations
                self.subbasin = BV.subbasin
                self.elt_def.append('subbasin')
            # Sub-surface
            if ('hydraulic' in BV.__dir__()) == True:
                self.hydraulic = BV.hydraulic
                self.elt_def.append('hydraulic')
            if ('geology' in BV.__dir__()) == True:
                self.geology = BV.geology
                self.elt_def.append('geology')
            if ('geometric' in BV.__dir__()) == True:
                self.geometric = BV.geometric
                self.elt_def.append('geometric')
            if ('piezometry' in BV.__dir__()) == True:
                self.piezometry = BV.piezometry
                self.elt_def.append('piezometry')
            # Surface
            if ('hydrography' in BV.__dir__()) == True:
                self.hydrography = BV.hydrography
                self.elt_def.append('hydrography')
            if ('hydrometry' in BV.__dir__()) == True:
                self.hydrometry = BV.hydrometry
                self.elt_def.append('hydrometry')
            if ('intermittency' in BV.__dir__()) == True:
                self.intermittency = BV.intermittency
                self.elt_def.append('intermittency')
            # Atmospheric
            if ('safransurfex' in BV.__dir__()) == True:
                self.safransurfex = BV.safransurfex
                self.elt_def.append('safransurfex')
            if ('climatic' in BV.__dir__()) == True:
                self.climatic = BV.climatic
                self.elt_def.append('climatic')
            if ('driasclimat' in BV.__dir__()) == True:
                self.driasclimat = BV.driasclimat
                self.elt_def.append('driasclimat')
            if ('driaseau' in BV.__dir__()) == True:
                self.driaseau = BV.driaseau
                self.elt_def.append('driaseau')
            if ('oceanic' in BV.__dir__()) == True:
                self.oceanic = BV.oceanic
                self.elt_def.append('oceanic')
            if ('settings' in BV.__dir__()) == True:
                self.settings = BV.settings
                self.elt_def.append('settings')
            if ('transport' in BV.__dir__()) == True:
                self.transport = BV.transport
                self.elt_def.append('transport')

            return True

        else:
            logger.warning("watershed_object doesn't exist in %s", self.watershed_folder)

            return False

    def __init_object(self):
        """
        Private method initializing condition to generate watershed.

        Returns
        -------
        None.
        """
        # if self.catch_def == "txt":
        #     if self.from_dem is None:
        #         raise ValueError(
        #             "catch_def='txt' requires from_dem=[path_to_txt, cell_size]"
        #         )
        #     self.dem_path = self.from_dem[0]
        #     self.bottom_path = self.bottom_path
        #     self.cell_size = self.from_dem[1]
        #     self.x_outlet = None
        #     self.y_outlet = None
        #     self.snap_dist = None
        #     self.buff_percent = None
        #     self.crs_proj = None

        # if self.catch_def == "dem":
        #     if self.from_dem is None:
        #         raise ValueError("catch_def='dem' requires from_dem to be provided")
        #     with rasterio.open(self.from_dem[0]) as dem_src:
        #         src_crs = dem_src.crs
        #     self.dem_path = self.from_dem[0]
        #     self.bottom_path = self.bottom_path
        #     self.cell_size = self.from_dem[1]
        #     self.x_outlet = None
        #     self.y_outlet = None
        #     self.snap_dist = None
        #     self.buff_percent = None
        #     if src_crs:
        #         epsg_code = src_crs.to_epsg()
        #         self.crs_proj = f"EPSG:{epsg_code}" if epsg_code else src_crs.to_string()
        #     else:
        #         self.crs_proj = None

        # if self.catch_def == "shp":
        #     if self.from_shp is None:
        #         raise ValueError("catch_def='shp' requires from_shp to be provided")
        #     shp_file = gpd.read_file(self.from_shp[0])
        #     self.dem_path = self.dem_path
        #     self.bottom_path = self.bottom_path
        #     self.cell_size = None
        #     self.x_outlet = None
        #     self.y_outlet = None
        #     self.snap_dist = None
        #     self.buff_percent = self.from_shp[1]
        #     # self.crs_proj = shp_file.crs.srs.upper()
        #     self.crs_proj = f"EPSG:{shp_file.crs.to_epsg()}"

        # if self.catch_def == "xy":
        #     if self.from_xyv is None:
        #         raise ValueError("catch_def='xy' requires from_xyv to be provided")
        #     self.dem_path = self.dem_path
        #     self.bottom_path = self.bottom_path
        #     self.cell_size = None
        #     self.x_outlet = self.from_xyv[0]
        #     self.y_outlet = self.from_xyv[1]
        #     self.snap_dist = self.from_xyv[2]
        #     self.buff_percent = self.from_xyv[3]
        #     self.crs_proj = self.from_xyv[4]
        
    def save_object(self):
        """
        Public method to save watershed object.

        Returns
        -------
        None.
        """
        # If folder already exists, removes it
        if os.path.exists(os.path.join(self.watershed_folder,'watershed_object')):
            os.remove(os.path.join(self.watershed_folder,'watershed_object'))
        with open(os.path.join(self.watershed_folder,'watershed_object'), 'xb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()

    def display_object(self, dtype: str = 'watershed_dem'):
        """
        Public method to display watershed.

        Parameters
        ----------
        dtype : str, optional
            Three possibilities:

            - ``'watershed_dem'`` to display the watershed elevation (default).
            - ``'watershed_geology'`` to display the watershed geology.
            - ``'watershed_zones'`` to display the hydraulic zones of the watershed.
        """
        try:
            from hydromodpy.display import visualization_watershed
        except Exception as exc:
            raise ModuleNotFoundError(
                "Display dependencies are not installed. Install the full stack (contextily, matplotlib, vedo)."
            ) from exc
        if dtype == 'watershed_dem':
            visualization_watershed.watershed_dem(self)
        if dtype == 'watershed_geology':
            visualization_watershed.watershed_geology(self)
        if dtype == 'watershed_zones':
            visualization_watershed.watershed_zones(self)

    #%% ADDING DATA

    def add_driasclimat(self, driasclimat_path, list_models='all', list_vars='all'):
        """
        Public method to add drias climat data.
        Link: https://www.drias-climat.fr/

        Returns
        -------
        None.
        """
        self.driasclimat_path = driasclimat_path
        self.driasclimat = driasclimat.Driasclimat(out_path=self.watershed_folder,
                                          driasclimat_path=self.driasclimat_path,
                                          watershed_shp=self.geographic.watershed_shp,
                                          list_models=list_models,
                                          list_vars=list_vars)
        self.elt_def.append('driasclimat')

    def add_driaseau(self, driaseau_path, list_models='all', list_vars='all'):
        """
        Public method to add drias eau data.
        Link: https://www.drias-eau.fr/

        Returns
        -------
        None.
        """
        self.driaseau_path = driaseau_path
        self.driaseau = Driaseau(out_path=self.watershed_folder,
                                          driaseau_path=self.driaseau_path,
                                          watershed_shp=self.geographic.watershed_shp,
                                          list_models=list_models,
                                          list_vars=list_vars)
        self.elt_def.append('driaseau')

    def add_piezometry(self):
        """
        Public method to add piezometric data.

        .. deprecated:: Legacy Piezometry class removed.
            Use ``hydromodpy.data_managers.variables.piezometry.manager.PiezometryManager`` instead.
        """
        raise NotImplementedError(
            "Legacy Piezometry class has been removed. "
            "Use PiezometryManager with PiezometryConfig instead."
        )

    def add_safransurfex(self, safransurfex_path):
        """
        Pulic method to add safran-surfex (historical reanalysis) climate data.

        Returns
        -------
        None.
        """
        self.safransurfex_path = safransurfex_path
        self.safransurfex = safransurfex.SafranSurfex(out_path=self.watershed_folder,
                                                      safransurfex_path=self.safransurfex_path,
                                                      watershed_shp=self.geographic.box_buff)
        safransurfex.Merge(out_path=self.watershed_folder)
        self.elt_def.append('safransurfex')
        self.save_object()

    #%% EXTRACT NETCDF

    def postprocessing_netcdf(self,
                                  model_modflow: object,
                                  datetime_format: bool=True):
        """
        Public method to postprocess the watershed netCDF.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        datetime_format : bool, optional
            True if the index is in datetime format (e.g. 1995-10-17 00:00:00). The default is True.

        Returns
        -------
        netcdf_results :
            Python object with results stored.
        """
        if model_modflow != None:
            netcdf_results = netcdf.Netcdf(self.geographic,
                                           model_modflow=model_modflow,
                                           datetime_format=datetime_format)

            return netcdf_results

    #%% PYHELP


    def preprocessing_pyhelp(
            self,
            *,
            grid_csv,   # nom « officiel »
            grid_base,   # alias rétro-compat
            workdir  : str,
            ready_csvs,          # [precip, tair, solrad]
            grid_patch, # ex. {"dem": dem_path, "CN":75}
            compress_level: int = 4,
    ):
        from hydromodpy.hydrology.pyhelp import pyhelp_netcdf

        # 1) compatibilité ancien nom
        if grid_csv is None:
            grid_csv = grid_base
        if grid_csv is None:
            raise ValueError("Vous devez fournir grid_csv ou grid_base.")

        # 2) dépaqueter la liste météo
        try:
            precip_csv, tair_csv, solrad_csv = ready_csvs
        except ValueError:
            raise ValueError(
                "`ready_csvs` doit contenir [precip_csv, tair_csv, solrad_csv]"
            )

        # 3) appel correctement typé
        return pyhelp_netcdf.preprocessing_pyhelp_netcdf(
            workdir      = workdir,
            grid_csv     = grid_csv,
            precip_csv   = precip_csv,
            tair_csv     = tair_csv,
            solrad_csv   = solrad_csv,
            grid_patch   = grid_patch,
            compress_level = compress_level,
        )



#%% NOTES
