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
import pandas as pd
import geopandas as gpd
import rasterio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
from os.path import dirname, abspath
root_dir = (dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from hydromodpy.watershed import climatic, driasclimat, driaseau, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, settings, safransurfex, subbasin, transport
from hydromodpy.modeling import modflow, modpath, mt3dms, timeseries, netcdf
from hydromodpy.tools import toolbox, get_logger
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

logger = get_logger(__name__)


#%% CLASS

class Watershed:
    """
    Class Watershed is used to extract watershed and its data from regional DEM.
    Hub to all elements necessary or optional to construct watersheds (meaning catchements) and run modflow simulations.
    """

    def __init__(self,
                 dem_path: str,
                 out_path: str,
                 load: bool=False,
                 watershed_name: str='Default',
                 from_lib: str=None, # os.path.join(root_dir,'watershed_library.csv')
                 from_dem: list=None, # [path, cell size]
                 from_shp: list=None, # [path, buffer size]
                 from_xyv: list=None, # [x, y, snap distance, buffer size]
                 reg_fold: str=None,
                 bottom_path: str=None, # path
                 save_object: bool=True):
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
        from_lib : str, optional
            Path of the library (.csv) with list of watershed to generate. The default is None.
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

        self.dem_path = dem_path
        self.out_path = out_path
        self.load = load
        self.watershed_name = watershed_name
        self.from_lib = from_lib
        self.from_dem = from_dem
        self.from_shp = from_shp
        self.from_xyv = from_xyv
        self.reg_fold = reg_fold
        self.bottom_path = bottom_path
        self.bin_path = os.path.join(os.path.dirname(root_dir), 'bin')

        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)

        # Setup simulation log in watershed folder
        from hydromodpy.tools import setup_simulation_log
        setup_simulation_log(self.watershed_folder)

        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)

        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)

        self.calibration_folder = os.path.join(self.watershed_folder, 'results_calibration')
        toolbox.create_folder(self.calibration_folder)

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
                self.__create_object()
                # Save object
                if save_object == True:
                    self.save_object()
        else:
            logger.info("Initializing watershed object from scratch as requested")
            # Definition of the watershed
            self.__init_object()
            # Creation of the watershed defined at the previous line
            self.__create_object()
            # Save object
            if save_object == True:
                self.save_object()

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
        if self.from_lib != None:
            watershed_list = pd.read_csv(self.from_lib, delimiter=';')
            watershed_info = watershed_list.loc[watershed_list['watershed_name'] == self.watershed_name]
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = watershed_info.iloc[0]['x_outlet']
            self.y_outlet = watershed_info.iloc[0]['y_outlet']
            self.snap_dist = watershed_info.iloc[0]['snap_dist']
            self.buff_percent = watershed_info.iloc[0]['buff_percent']
            self.crs_proj = watershed_info.iloc[0]['crs_proj']

        if self.from_dem != None:
            with rasterio.open(self.from_dem[0]) as dem_src:
                src_crs = dem_src.crs
            self.dem_path = self.from_dem[0]
            self.bottom_path = self.bottom_path
            self.cell_size = self.from_dem[1]
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = None
            if src_crs:
                epsg_code = src_crs.to_epsg()
                self.crs_proj = f"EPSG:{epsg_code}" if epsg_code else src_crs.to_string()
            else:
                self.crs_proj = None

        if self.from_shp != None:
            shp_file = gpd.read_file(self.from_shp[0])
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = self.from_shp[1]
            # self.crs_proj = shp_file.crs.srs.upper()
            self.crs_proj = f"EPSG:{shp_file.crs.to_epsg()}"

        if self.from_xyv != None:
            self.dem_path = self.dem_path
            self.bottom_path = self.bottom_path
            self.cell_size = None
            self.x_outlet = self.from_xyv[0]
            self.y_outlet = self.from_xyv[1]
            self.snap_dist = self.from_xyv[2]
            self.buff_percent = self.from_xyv[3]
            self.crs_proj = self.from_xyv[4]

    def __create_object(self):
        """
        Private method to create geographic watershed.

        Returns
        -------
        None.
        """
        # Structure data
        self.geographic = geographic.Geographic(self.dem_path,
                                                self.bottom_path,
                                                self.cell_size,
                                                self.x_outlet,
                                                self.y_outlet,
                                                self.snap_dist,
                                                self.buff_percent,
                                                self.crs_proj,
                                                self.watershed_folder,
                                                self.stable_folder,
                                                self.simulations_folder,
                                                self.calibration_folder,
                                                self.from_lib,
                                                self.from_dem,
                                                self.from_shp,
                                                self.from_xyv,
                                                self.reg_fold)

        self.elt_def.append('geographic')

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

    def add_climatic(self):
        """
        Public method to add climatic data.

        Returns
        -------
        None.
        """
        self.climatic = climatic.Climatic(out_path=self.watershed_folder)
        self.elt_def.append('climatic')
        self.save_object()

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
        self.driaseau = driaseau.Driaseau(out_path=self.watershed_folder,
                                          driaseau_path=self.driaseau_path,
                                          watershed_shp=self.geographic.watershed_shp,
                                          list_models=list_models,
                                          list_vars=list_vars)
        self.elt_def.append('driaseau')

    def add_geology(self,
                    geology_path: str,
                    types_obs: str='GEO1M.shp',
                    fields_obs: str='CODE_LEG'):
        """
        Public method to add geology data.

        Parameters
        ----------
        geology_path : str
            Path where the polygon shapefile is located.
            To date, work for BRGM geological map data: http://infoterre.brgm.fr/page/telechargement-cartes-geologiques
        types_obs : str, optional
            Name of the geology shapefile. The default is 'GEO1M.shp'.
        fields_obs : str, optional
            Field data of the polygons. The default is 'CODE_LEG'.
        """
        self.geology_path = geology_path
        self.geology = geology.Geology(out_path=self.watershed_folder,
                                       geographic=self.geographic,
                                       geo_path = self.geology_path,
                                       landsea=None,
                                       types_obs=types_obs,
                                       fields_obs= fields_obs)
        self.elt_def.append('geology')
        self.save_object()

    def add_hydraulic(self):
        """
        Public method to add hydraulic data.

        Returns
        -------
        None.
        """
        self.hydraulic = hydraulic.Hydraulic(nrow=self.geographic.y_pixel,
                                             ncol=self.geographic.x_pixel,
                                             box_dem=self.geographic.watershed_box_buff_dem)
        self.elt_def.append('hydraulic')
        self.save_object()

    def add_hydrography(self,
                        hydrography_path: str,
                        types_obs: list=['streams'],
                        fields_obs: list=['FID'],
                        streams_file=None):
        """
        Public method to add hydrography data.

        Parameters
        ----------
        hydrography_path : str
            Path where the hydrography shapefiles are located.
        types_obs : list, optional
            List of shapefile names. The default is ['streams'].
        fields_obs : list, optional
            List of field names. The default is ['FID'].
        """
        self.hydrography_path = hydrography_path
        self.types_obs = types_obs
        self.fields_obs = fields_obs
        self.hydrography = hydrography.Hydrography(out_path=self.watershed_folder,
                                                   types_obs=self.types_obs,
                                                   fields_obs=self.fields_obs,
                                                   geographic=self.geographic,
                                                   hydro_path=self.hydrography_path,
                                                   streams_file=streams_file)
        self.elt_def.append('hydrography')
        self.save_object()

    def add_hydrometry(self, hydrometry_path: str, file_name: str):
        """
        Public method to add watershed hydrometry.

        Parameters
        ----------
        hydrometry_path : str
            Path where the hydrometry files are located.
        file_name : str
            Name of the file.
        """
        self.hydrometry_path = hydrometry_path
        self.hydrometry = hydrometry.Hydrometry(out_path=self.watershed_folder,
                                                hydrometry_path=self.hydrometry_path,
                                                file_name=file_name,
                                                geographic=self.geographic)
        self.elt_def.append('hydrometry')
        self.save_object()

    def add_intermittency(self, intermittency_path: str, file_name: str):
        """
        Public method to add hydraulic intermittency.

        Parameters
        ----------
        intermittency_path : str
            Path where the intermittency files are located.
        file_name : str
            Name of the file.
        """
        self.intermittency_path = intermittency_path
        self.intermittency = intermittency.Intermittency(out_path=self.watershed_folder,
                                                         intermittency_path=self.intermittency_path,
                                                         file_name=file_name,
                                                         geographic=self.geographic)
        self.elt_def.append('intermittency')
        self.save_object()

    def add_oceanic(self, oceanic_path: str):
        """
        Public method to add oceanic/sea data.

        Parameters
        ----------
        oceanic_path : str
            Path where the oceanic data are located.
        """
        self.oceanic = oceanic.Oceanic()
        self.oceanic_path = oceanic_path
        self.oceanic.extract_data(out_path=self.watershed_folder,
                                  oceanic_path=self.oceanic_path,
                                  geographic=self.geographic)
        self.elt_def.append('oceanic')
        self.save_object()

    def add_piezometry(self):
        """
        Public method to add piezometric data.

        Returns
        -------
        None.
        """
        self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,
                                                geographic=self.geographic)
        self.elt_def.append('piezometry')
        self.save_object()

    def add_settings(self):
        """
        Pulic method to add specific model settings.

        Returns
        -------
        None.
        """
        self.settings = settings.Settings()
        self.elt_def.append('settings')
        self.save_object()

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

    def add_subbasin(self, add_path: str = None, sub_snap_dist: int = 200):
        """
        Public method to add subbasins.

        Parameters
        ----------
        add_path : str, optional
            Path of the folder where the data are located. Default is None.
        sub_snap_dist : int
            Maximum distance where the subasin outlet can be moved.
        """
        if not hasattr(self, 'hydrometry'):
            self.hydrometry = None

        if not hasattr(self, 'intermittency'):
            self.intermittency = None

        self.subbasin = subbasin.Subbasin(
            geographic=self.geographic,
            hydrometry=self.hydrometry,
            intermittency=self.intermittency,
            add_path=add_path,
            out_path=self.watershed_folder,
            sub_snap_dist=sub_snap_dist
        )

        self.elt_def.append('subbasin')
        self.save_object()


    def add_transport(self):
        """
        Pulic method to add specific model transport parameters.

        Returns
        -------
        None.
        """
        self.transport = transport.Transport()
        self.elt_def.append('transport')
        self.save_object()

    #%% MODFLOW MODEL

    def preprocessing_modflow(self, for_calib: bool=False):
        """
        Public method to build the hydrogeological model.

        Parameters
        ----------
        for_calib : bool, False
            If False, the simulation results are store in folder results_simulations.
            If True, the simulation results are store in folder results_calibration.

        Returns
        -------
        model_modflow : object
            Python object of the created MODFLOW model.
        """
        if for_calib == False:
            model_folder = self.simulations_folder
        else:
            model_folder = self.calibration_folder

        # Type of run: classical simulation or calibration
        model_modflow = modflow.Modflow(self.geographic,
                                        # Workflow settings
                                        model_folder=model_folder,   # self.simulations_folder
                                        model_name=self.settings.model_name,
                                        bin_path=self.bin_path,
                                        # Model settings
                                        box=self.settings.box,
                                        sink_fill=self.settings.sink_fill,
                                        sim_state=self.settings.sim_state,
                                        dis_perlen=self.settings.dis_perlen,
                                        # Well settings
                                        well_coords=self.settings.well_coords,
                                        well_fluxes=self.settings.well_fluxes,
                                        # Output settings
                                        plot_cross=self.settings.plot_cross,
                                        cross_ylim=self.settings.cross_ylim,
                                        check_grid=self.settings.check_grid,
                                        # Boundary settings
                                        sea_level=self.oceanic.MSL,
                                        bc_left=self.settings.bc_left,
                                        bc_right=self.settings.bc_right,
                                        # Climatic settings
                                        recharge=self.climatic.recharge,
                                        runoff=self.climatic.runoff,
                                        first_clim=self.climatic.first_clim,
                                        # Hydraulic settings
                                        bottom=self.hydraulic.bottom,
                                        thick=self.hydraulic.thick,
                                        nlay=self.hydraulic.nlay,
                                        lay_decay=self.hydraulic.lay_decay,
                                        hk_value=self.hydraulic.hk_value,
                                        sy_value=self.hydraulic.sy_value,
                                        ss_value=self.hydraulic.ss_value,
                                        hk_decay=self.hydraulic.hk_decay,
                                        sy_decay=self.hydraulic.sy_decay,
                                        ss_decay=self.hydraulic.ss_decay,
                                        verti_hk=self.hydraulic.verti_hk,
                                        verti_sy=self.hydraulic.verti_sy,
                                        verti_ss=self.hydraulic.verti_ss,
                                        cond_drain=self.hydraulic.cond_drain,
                                        vka=self.hydraulic.vka,
                                        exdp=self.hydraulic.exdp)

        # Preprocessing Modflow
        model_modflow.pre_processing() # verbose

        return model_modflow

    def processing_modflow(self,
                           model_modflow: object,
                           write_model: bool=True,
                           run_model: bool=False,
                           link_mt3dms: bool=False):
        """
        Public method to run the MODFLOW model.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        write_model : bool, True
            If True, write input files before run simulation.
        run_model : bool, False
            Run simulation. The default is False.

        Returns
        -------
        success_model : bool
            Boolean to know if the simulation rans succesfully.
        """
        # Processing Modflow
        success_model = model_modflow.processing(write_model=write_model, run_model=run_model, link_mt3dms=link_mt3dms)

        return success_model

    def postprocessing_modflow(self, model_modflow: object,
                               watertable_elevation: bool=True,
                               watertable_depth: bool=True,
                               seepage_areas: bool=True,
                               outflow_drain: bool=True,
                               groundwater_flux: bool=True,
                               groundwater_storage: bool=True,
                               accumulation_flux: bool=True,
                               persistency_index: bool=False,
                               intermittency_yearly: bool=False,
                               intermittency_monthly: bool=False,
                               intermittency_weekly: bool=False,
                               intermittency_daily: bool=False,
                               export_all_tif: bool=False):
        """
        Public method to post-process the simulation of the model.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        watertable_elevation : bool, optional
            Build watertable elevation outputs. The default is True.
        watertable_depth : bool, optional
            Build watertable_depth outputs. The default is True.
        seepage_areas : bool, optional
            Build seepage area outputs. The default is True.
        outflow_drain : bool, optional
            Build outflow drain outputs. The default is True.
        groundwater_flux : bool, optional
            Build groudwater flux outputs. The default is True.
        groundwater_storage : bool, optional
            Build groundwater storage ouputs. The default is True.
        accumulation_flux : bool, optional
            Build accumulation flux outputs. The default is True.
        persistency_index : bool, optional
            Build persistency index outputs. The default is False.
        intermittency_monthly : bool, optional
            Build intermittency monthly. The default is False.
        intermittency_yearly : bool, optional
            Build intermittency daily. The default is False.
        intermittency_daily : bool, optional
            Build intermittency yearly. The default is False.
        export_all_tif : bool, optional
            Build tif files for all time steps. The default is False.
        """
        # Postprocessing Modflow
        model_modflow.post_processing(model_modflow,
                                      watertable_elevation=watertable_elevation,
                                      watertable_depth=watertable_depth,
                                      seepage_areas=seepage_areas,
                                      outflow_drain=outflow_drain,
                                      groundwater_flux=groundwater_flux,
                                      groundwater_storage=groundwater_storage,
                                      accumulation_flux=accumulation_flux,
                                      persistency_index=persistency_index,
                                      intermittency_yearly=intermittency_yearly,
                                      intermittency_monthly=intermittency_monthly,
                                      intermittency_weekly=intermittency_weekly,
                                      intermittency_daily=intermittency_daily,
                                      export_all_tif=export_all_tif)

    #%% MODPATH MODEL

    def preprocessing_modpath(self, model_modflow: object, for_calib: bool=False):
        """
        Public method to set the partickle tracking method.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        for_calib : bool, False
            If False, the simulation results are store in folder results_simulations.
            If True, the simulation results are store in folder results_calibration.

        Returns
        -------
        model_modpath : object
            Python object of the created MODPATH model.
        """
        if for_calib == False:
            model_folder = self.simulations_folder
        else:
            model_folder = self.calibration_folder

        model_modpath = modpath.Modpath(self.geographic,
                                        model_modflow,
                                        # Frame settings
                                        model_folder = model_folder,
                                        model_name = model_modflow.model_name,
                                        bin_path = self.bin_path,
                                        # Specific settings
                                        zone_partic = self.settings.zone_partic,
                                        cell_div = self.settings.cell_div,
                                        zloc_div = self.settings.zloc_div,
                                        bore_depth = self.settings.bore_depth,
                                        track_dir = self.settings.track_dir,
                                        sel_random = self.settings.sel_random,
                                        sel_slice = self.settings.sel_slice)

        # Preprocessing Modflow
        model_modpath.pre_processing() # verbose

        return model_modpath

    def processing_modpath(self, model_modpath: object, write_model: bool=True, run_model: bool=False):
        """
        Public method to run the partickle tracking.

        Parameters
        ----------
        model_modpath : object
            MODPATH model in a Python object.
        write_model : bool, True
            If True, write input files before run simulation.
        run_model : bool, False
            Run simulation. The default is False.

        Returns
        -------
        success_model : bool
            Boolean to know if the simulation rans succesfully.
        """
        # Processing Modpath
        success_model = model_modpath.processing(write_model=write_model, run_model=run_model)

        return success_model

    def postprocessing_modpath(self,
                               model_modpath: object,
                               ending_point: bool=True,
                               starting_point: bool=True,
                               pathlines_shp: bool=True,
                               particles_shp: bool=True,
                               random_id: int=None,
                               norm_flux: bool=False):
        """
        Public method to post-process the simulation of the particle tracking.

        Parameters
        ----------
        model_modpath : object
            MODPATH model in a Python object.
        ending_point : bool, optional
            Save ending point shapefile of particles. The default is True.
        starting_point : bool, optional
            Save starting point shapefile of particles. The default is True.
        pathlines_shp : bool, optional
            Save pathlines shapefile (one line per particles). The default is True.
        particles_shp : bool, optional
            Save particles shapefile (some lines per particles). The default is True.
        random_id : int, optional
            Number of particles to save randomly. The default is None.
        """
        model_modpath.post_processing(model_modpath,
                                      ending_point=ending_point,
                                      starting_point=starting_point,
                                      pathlines_shp=pathlines_shp,
                                      particles_shp=particles_shp,
                                      random_id=random_id)

    def filtprocessing_modpath(self,
                               model_modpath: object,
                               norm_flux: bool=False,
                               filt_time: bool=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                               filt_seep: bool=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                               filt_inout: bool=True, # delete particles in and out in the same cell (first layer)
                               calc_rtd: bool=True, # compute residence time distribution
                               random_id: int=None # select randomly to keep
                               ):
        """
        Public method to filter output shapefiles of particles.

        Parameters
        ----------
        model_modpath : object
            MODPATH model in a Python object.
        norm_flux : bool, optional
            Noramlization of time by input fluxes (recharge). The default is False.
        filt_time : bool, optional
            Divide the output column "time" by 365 to converte days in years.
            Delete particles with time at 0.
            The default is True.
        filt_seep : bool, optional
            Only if 'track_dir' is 'forward'.
            Keep only particles ending in the first layer.
            The default is True.
        filt_inout : bool, optional
            Delete partciles in and out in the same cell.
            The default is True.
        calc_rtd : bool, optional
            Compute and plot the PDF of residence times.
            The default is True.
        random_id : int, optional
            Select randomly the number of prticles to keep.
            The default is None.
        """

        model_modpath.filt_processing(model_modpath,
                                      norm_flux,
                                      filt_time, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                                      filt_seep, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                                      filt_inout, # delete particles in and out in the same cell (first layer)
                                      calc_rtd, # compute residence time distribution
                                      random_id # select randomly to keep
                                      )

    #%% MT3DMS MODEL

    def preprocessing_mt3dms(self, model_modflow: object, for_calib: bool=False, suffix_name: str='_mt'):
        """
        Public method to set the partickle tracking method.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        for_calib : bool, False
            If False, the simulation results are store in folder results_simulations.
            If True, the simulation results are store in folder results_calibration.

        Returns
        -------
        model_mt3dms : object
            Python object of the created MT3DMS model.
        """
        if for_calib == False:
            model_folder = self.simulations_folder
        else:
            model_folder = self.calibration_folder

        model_mt3dms = mt3dms.Mt3dms(self.geographic,
                                     model_modflow,
                                     # Frame settings
                                     model_folder = model_folder,
                                     model_name = model_modflow.model_name,
                                     suffix_name = suffix_name,
                                     bin_path = self.bin_path,
                                     # Specific settings
                                     spc_name = self.transport.spc_name,
                                     sconc_init = self.transport.sconc_init,
                                     sconc_input = self.transport.sconc_input,
                                     disp_long = self.transport.disp_long,
                                     disp_transh = self.transport.disp_transh,
                                     disp_transv = self.transport.disp_transv,
                                     diffu_coeff = self.transport.diffu_coeff,
                                     react_order = self.transport.react_order,
                                     rate_decay = self.transport.rate_decay,
                                     plot_conc = self.transport.plot_conc,
                                     )

        # Preprocessing Modflow
        model_mt3dms.pre_processing() # verbose

        return model_mt3dms

    def processing_mt3dms(self, model_mt3dms: object, write_model: bool=True, run_model: bool=False, verbose: bool=True):
        """
        Public method to run the partickle tracking.

        Parameters
        ----------
        model_mt3dms : object
            MT3DMS model in a Python object.
        write_model : bool, True
            If True, write input files before run simulation.
        run_model : bool, False
            Run simulation. The default is False.

        Returns
        -------
        success_model : bool
            Boolean to know if the simulation rans succesfully.
        """
        # Processing Modpath
        success_model = model_mt3dms.processing(write_model=write_model, run_model=run_model, verbose=verbose)

        return success_model

    def postprocessing_mt3dms(self,
                              model_mt3dms: object,
                              concentration_seepage:bool=True,
                              mass_seepage:bool=True,
                              mass_accumulated:bool=False,
                              export_all_tif:bool=False):
        """
        Public method to post-process the simulation of the particle tracking.

        Parameters
        ----------
        model_mt3dms : object
            MT3DMS model in a Python object.
        """
        model_mt3dms.post_processing(model_mt3dms,
                                      concentration_seepage=concentration_seepage,
                                      mass_seepage=mass_seepage,
                                      mass_accumulated=mass_accumulated,
                                      export_all_tif=export_all_tif)

        return model_mt3dms

    #%% EXTRACT TIMESERIES

    def postprocessing_timeseries(self,
                                  model_modflow: object,
                                  model_modpath: int=None,
                                  model_mt3dms: int=None,
                                  suffix_name: int=None,
                                  datetime_format: bool=True,
                                  subbasin_results: bool=True,
                                  intermittency_yearly: bool=False,
                                  intermittency_monthly: bool=False,
                                  intermittency_weekly: bool=False,
                                  intermittency_daily: bool=False,
                                  residence_times: bool=False,
                                  concentration_seepage: bool=False,
                                  mass_accumulated: bool=False
                                  ):
        """
        Public method to postprocess the watershed timeseries.

        Parameters
        ----------
        model_modflow : object
            MODFLOW model in a Python object.
        model_modpath : object
            MODPATH model in a Python object. Optional if only flow outputs are
            required.
        model_mt3dms : object, optional
            MT3DMS model used when extracting concentration/mass indicators.
        datetime_format : bool, optional
            True if the index is in datetime format (e.g. 1995-10-17 00:00:00). The default is True.
        subbasin_results : bool, optional
            Extract and clip results for each subbasins previously generated and stored. The default is True.
        intermittency_yearly : bool, optional
            Compute yearly intermittency metrics for the hydrographic network.
        intermittency_monthly : bool
            If True, the intermittent and perennial part of hydrographic network is calculated on a monthly basis.
        intermittency_weekly : bool
            If True, the intermittent and perennial part of hydrographic network is calculated on a weekly basis.
        intermittency_daily : bool
            If True, the intermittent and perennial part of hydrographic network is calculated on a daily basis.
        residence_times : bool, optional
            Export residence-time diagnostics if MODPATH results are available.
        concentration_seepage : bool, optional
            When True the MT3DMS seepage concentrations are summarised.
        mass_accumulated : bool, optional
            Aggregate the accumulated mass time series from MT3DMS outputs.

        Returns
        -------
        timeseries_results : hydromodpy.modeling.timeseries.Timeseries
            Python object with results stored.
            The variable 'mfdata' inside correspond to the .csv file results.
        """
        if model_modflow != None:
            timeseries_results = timeseries.Timeseries(self.geographic,
                                                       model_modflow=model_modflow,
                                                       model_modpath=model_modpath,
                                                       model_mt3dms=model_mt3dms,
                                                       suffix_name=suffix_name,
                                                       datetime_format=datetime_format,
                                                       subbasin_results=subbasin_results,
                                                       intermittency_yearly=intermittency_yearly,
                                                       intermittency_monthly=intermittency_monthly,
                                                       intermittency_weekly=intermittency_weekly,
                                                       intermittency_daily=intermittency_daily,
                                                       residence_times=residence_times,
                                                       concentration_seepage=concentration_seepage,
                                                       mass_accumulated=mass_accumulated
                                                       )
            return timeseries_results

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
        from hydromodpy.pyhelp import pyhelp_netcdf

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
