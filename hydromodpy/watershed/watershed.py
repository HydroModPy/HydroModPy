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
import os
import pickle
from os.path import abspath, dirname


package_root = dirname(dirname(abspath(__file__)))
repo_root = dirname(package_root)

# HydroModPy
from hydromodpy.spatial.geographic.geographic import Geographic
from hydromodpy.core.tools import get_logger
from hydromodpy.core.tools import setup_simulation_log
from hydromodpy.core.tools.display import plot_params, print_hydromodpy
from hydromodpy.core.tools.filesystem import create_folder

fontprop = plot_params(8,15,18,20) # small, medium, interm, large

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
        """Initialize one preserved watershed container.

        Parameters
        ----------
        geographic_object : Geographic
            Geographic context already prepared for the watershed.
        load : bool, optional
            If ``True``, try to reload a previously pickled watershed object
            before rebuilding it from the provided inputs.
        initializing_object : object, optional
            Historical initialization object carrying the workspace-derived output
            paths and catchment name.
        setting_object : object, optional
            Settings payload attached to the watershed.
        hydraulic_object : object, optional
            Hydraulic payload attached to the watershed.
        save_object : bool, optional
            If ``True``, persist the watershed object with ``pickle``
            after initialization.
        transport_object : object, optional
            Transport payload attached to the watershed.
        hydrography_object : object, optional
            Hydrography payload attached to the watershed.
        subbasin_object : object, optional
            Subbasin payload attached to the watershed.
        geology_object : object, optional
            Geology payload attached to the watershed.
        hydrometry_object : object, optional
            Hydrometry payload attached to the watershed.
        intermittency_object : object, optional
            Intermittency payload attached to the watershed.
        climatic_object : object, optional
            Climatic payload attached to the watershed.
        oceanic_object : object, optional
            Oceanic payload attached to the watershed.

        Notes
        -----
        This class is preserved for notebook and regression workflows. New code
        should prefer the modern workspace, domain, and data stack.
        """

        print_hydromodpy()
                
        self.watershed_name = initializing_object.catch_name
        self.out_path = initializing_object.out_dir_path

        self.load = load

        self.bin_path = os.path.join(repo_root, 'bin')

        self.watershed_folder = os.path.join(self.out_path, self.watershed_name)
        create_folder(self.watershed_folder)

        # Setup simulation log in watershed folder
        setup_simulation_log(self.watershed_folder)

        self.add_data_folder = os.path.join(str(initializing_object.project_root), 'add_data')
        create_folder(self.add_data_folder)

        self.figure_folder = str(getattr(initializing_object, 'figure_folder',
                                         os.path.join(str(initializing_object.project_root), 'figures')))
        create_folder(self.figure_folder)

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
        raise NotImplementedError(
            "Watershed visualisation has been removed. Use the figure registry "
            "in :mod:`hydromodpy.display` (e.g. ``get('piezometric_map')``) "
            "operating on a :class:`Simulation`."
        )

    #%% ADDING DATA

    def add_driasclimat(self, driasclimat_path, list_models='all', list_vars='all'):
        """Deprecated. Legacy DRIAS-Climat loader removed with `hydromodpy.data.climatic`."""
        raise NotImplementedError(
            "add_driasclimat() has been removed. Use the custom data scaffold "
            "(drop NetCDFs in ~/hydromodpy/<variable>_custom/) or a dedicated "
            "DataSource registered under hydromodpy.data.sources."
        )

    def add_driaseau(self, driaseau_path, list_models='all', list_vars='all'):
        """Deprecated. Legacy DRIAS-Eau loader removed with `hydromodpy.data.climatic`."""
        raise NotImplementedError(
            "add_driaseau() has been removed. Use the custom data scaffold "
            "(drop NetCDFs in ~/hydromodpy/<variable>_custom/) or a dedicated "
            "DataSource registered under hydromodpy.data.sources."
        )

    def add_piezometry(self):
        """
        Public method to add piezometric data.

        .. deprecated:: Legacy Piezometry class removed.
            Use ``hydromodpy.data.variables.piezometry.manager.PiezometryManager`` instead.
        """
        raise NotImplementedError(
            "Legacy Piezometry class has been removed. "
            "Use PiezometryManager with PiezometryConfig instead."
        )

    def add_safransurfex(self, safransurfex_path):
        """Deprecated. Legacy SAFRAN-SURFEX loader removed with `hydromodpy.data.climatic`."""
        raise NotImplementedError(
            "add_safransurfex() has been removed. Use the SIM2 INRAE client "
            "(hydromodpy.data.common.clients.sim2_inrae) or the custom data "
            "scaffold for SAFRAN-SURFEX NetCDFs."
        )

    #%% EXTRACT NETCDF

    def postprocessing_netcdf(self, *args, **kwargs):
        """Removed: NetCDF export now lives in the simulation pipeline."""
        raise NotImplementedError(
            "postprocessing_netcdf() has been removed. NetCDF/Zarr exports "
            "are produced by the pipeline's extract/derive/export steps."
        )

    #%% PYHELP


    def preprocessing_pyhelp(
            self,
            *,
            grid_csv,   # canonical parameter name
            grid_base,   # historical alias kept for notebook stability
            workdir: str,
            ready_csvs,          # [precip, tair, solrad]
            grid_patch,          # e.g. {"dem": dem_path, "CN": 75}
            compress_level: int = 4,
    ):
        from hydromodpy.process.hydrology.pyhelp import pyhelp_netcdf

        # Keep the former parameter name working in preserved notebooks.
        if grid_csv is None:
            grid_csv = grid_base
        if grid_csv is None:
            raise ValueError("You must provide grid_csv or grid_base.")

        # Unpack the expected meteorological inputs.
        try:
            precip_csv, tair_csv, solrad_csv = ready_csvs
        except ValueError:
            raise ValueError(
                "`ready_csvs` must contain [precip_csv, tair_csv, solrad_csv]"
            )

        # Forward the normalized inputs to the preserved PYHELP pipeline.
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
