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

# Python
import sys
import os
import pickle
import pandas as pd
import geopandas as gpd
from osgeo import gdal, osr # or import gdal
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
from os.path import dirname, abspath
root_dir = (dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from watershed import climatic, driasclimat, driaseau, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, lakeres, settings, safransurfex, subbasin
from modeling import modflow, modpath, timeseries
from display import visualization_watershed
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

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
                 bottom_path: str=None, # path
                 save_object: bool=True):
        """        
        Parameters
        ----------
        dem_path : str
            Path of the initial Digital Elevation Model.
        out_path : str
            Path of the HydroModPy outputs.
        load : bool, optional
            To load the watershed object. The file Must be already created. The default is False.
        watershed_name : str, optional
            Name of the watershed. The default is 'Default'.
        from_lib : str, optional
            Path of the watershed librairies. If None : method not used. The default is None.
        from_dem : list, optional
            List with two parameters: [path, cell_size]
            path: Path of the DEM
            cell_size: Resolution of the DEM. To change the initial resolution
            The default is empty list.
        from_shp : list, optional
            List of tow parameters: [path, buffer_size] 
            path: Path of the polygon shapefile. 
            buffer_size: Buffer distance (value in percent)
            The default is empty list.
        from_xyv : list, optional
            List of four parameters: [x, y, snap_distance, buffer_size]
            x: x coordinate of the watershed outlet
            y: y coordinate of the watershed outlet
            snap_dist: Maximum distance where the outlet can be moove
            buffer_size: Buffer distance (value in percent)
            The default is empty list.
        bottom_path : str, optional
            Path of a raster representing the bottom elevation. The default is None.
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
        self.bottom_path = bottom_path
        self.bin_path = os.path.join(os.path.dirname(root_dir), 'bin/')
        
        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)
        
        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)
        
        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)
        
        # self.add_data_folder = os.path.join(self.stable_folder, 'add_data/')
        # toolbox.create_folder(self.add_data_folder)
        
        self.figure_folder = os.path.join(self.stable_folder, '_figures/')
        toolbox.create_folder(self.figure_folder)
        
        self.elt_def = []
        
        success = False
        if load==True:
             # Load from previously stored (saved) watershed
             success = self.__load_object()
             print("Object was loaded successfully")
        else: 
             print("Object was not loaded as demanded, but created from scratch")
             
        if load==False or success==False: 
            print("Create new object, will removed previousy stored object")
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
            
            # Test the existence of the stored watershed within the default path name "watershed_object"
            with open(os.path.join(self.watershed_folder, 'watershed_object'), 'rb') as config_dictionary_file:
                BV = pickle.load(config_dictionary_file)
                
            # At least geographic should have been stored
            if ('geographic' in BV.__dir__()) == True:
                self.geographic = BV.geographic
                self.elt_def.append('geographic')
            else:
                print("Warning : geographic doesn't exist in object")
                return False
            if ('subbasin' in BV.__dir__()) == True:   # Generates basin where there are hydrological stations
                self.subbasin = BV.subbasin
                self.elt_def.append('subbasin')
            # Sub-surface (compulsory: hydrodynamic)
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
            if ('lakeres' in BV.__dir__()) == True:
                self.lakeres = BV.lakeres
                self.elt_def.append('lakeres')
            # Atmospheric (compulsory: hydrodynamic)
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
                
            return True 
        
        else:
            print("Warning : file doesn't exist, watershed_object", self.watershed_folder)
            
            return False

    def __init_object(self):
        """
        Private method to initialize condition to generate watershed.

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
            dem = gdal.Open(self.from_dem[0])
            proj = osr.SpatialReference(wkt=dem.GetProjection())
            self.dem_path = self.from_dem[0]
            self.bottom_path = self.bottom_path
            self.cell_size = self.from_dem[1]
            self.x_outlet = None
            self.y_outlet = None
            self.snap_dist = None
            self.buff_percent = None
            self.crs_proj = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
                        
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
                                                self.from_lib,
                                                self.from_dem,
                                                self.from_shp,
                                                self.from_xyv)
        
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

    def display_object(self,dtype: str = 'watershed_dem'):
        """
        Public method to display watershed.

        Parameters
        ----------
        dtype : str, optional
            Three posibilities:
                'watershed_dem' to display the watershed elevation
                'watershed_geology' to display the watershed geology
                'watershed_zones' to display hydraulic zones of the watershed
            The default is 'watershed_dem'
        """
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
        # drias.Merge(out_path=self.watershed_folder)
        self.elt_def.append('driasclimat')
        # self.save_object()
    
    def add_driaseau(self, driaseau_path, list_models='all', list_vars='all'):
        """
        Public method to add drias eau data.

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
        # drias.Merge(out_path=self.watershed_folder)
        self.elt_def.append('driaseau')
        # self.save_object()
        
    def add_geology(self, 
                    geology_path: str,
                    types_obs: str='GEO1M.shp',
                    fields_obs: str='CODE_LEG'):
        """
        Public method to add geologic data.

        Parameters
        ----------
        geology_path : str
            Path where the polygon shapefile is located.
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
        
    def add_geometric(self):
        """
        Public method to add geometric data.

        Returns
        -------
        None.
        """
        self.geometric = None
        self.elt_def.append('geometric')
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
                        fields_obs: list=['FID']):
        """
        Public method to add watershed hydrography.

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
                                                   hydro_path=self.hydrography_path)
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
            DName of the file.
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
            Path where the hydraulic intermittency files are located.
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
        Pulic method to add settings model.

        Returns
        -------
        None.
        """
        self.settings = settings.Settings()
        self.elt_def.append('settings')
        self.save_object()
    
    def add_safransurfex(self, safransurfex_path):
        self.safransurfex_path = safransurfex_path
        self.safransurfex = safransurfex.SafranSurfex(out_path=self.watershed_folder,
                                                      safransurfex_path=self.safransurfex_path,
                                                      watershed_shp=self.geographic.box_buff)
        safransurfex.Merge(out_path=self.watershed_folder)
        self.elt_def.append('safransurfex')
        # self.save_object()
        
    def add_lakeres(self, stable_folder):
        self.lakeres = lakeres.Lakeres(stable_folder)
        self.elt_def.append('lakeres')
        self.save_object()
            
    def add_subbasin(self, add_path:str, sub_snap_dist: int):
        """
        Public method to add subbasins.

        Parameters
        ----------
        add_path : str
            Path of the folder where the data are located.
        """
        if hasattr(self, 'hydrometry') == False:
            self.hydrometry=None
        self.subbasin = subbasin.Subbasin(geographic=self.geographic, hydrometry=self.hydrometry, 
                                          intermittency=self.intermittency, 
                                          add_path=add_path,
                                          out_path=self.watershed_folder,
                                          sub_snap_dist=self.geographic.snap_dist/2)
        self.elt_def.append('subbasin')
        self.save_object()
    
    #%% MODFLOW MODEL
    
    def preprocessing_modflow(self, for_calib: bool=False):
        """
        Public method to build the hydrologic model.

        Returns
        -------
        model_modflow : object
            Python object of the hydraulic model    
        """        
        if for_calib == False:
            model_folder = self.simulations_folder
        else:
            self.calibration_folder = os.path.join(self.watershed_folder, 'results_calibration')
            toolbox.create_folder(self.calibration_folder)
            model_folder = self.calibration_folder
        
        # Type of run: classical simulation or calibration
        model_modflow = modflow.Modflow(self.geographic,
                                        # Frame settings
                                        model_folder=model_folder,   # self.simulations_folder
                                        model_name=self.settings.model_name,
                                        bin_path=self.bin_path,
                                        box=self.settings.box,
                                        sink_fill=self.settings.sink_fill,
                                        sim_state=self.settings.sim_state,
                                        plot_cross=self.settings.plot_cross,
                                        # Climatic settings
                                        climatic=self.climatic.recharge,
                                        runoff=self.climatic.runoff,
                                        first_clim=self.climatic.first_clim,
                                        # Hydraulic settings
                                        nlay=self.hydraulic.nlay,
                                        lay_decay=self.hydraulic.lay_decay,
                                        bottom=self.hydraulic.bottom,
                                        thick=self.hydraulic.thick,
                                        hyd_cond=self.hydraulic.hyd_cond,
                                        cond_decay=self.hydraulic.cond_decay,
                                        verti_cond=self.hydraulic.verti_cond,
                                        verti_poro=self.hydraulic.verti_poro,
                                        cond_drain=self.hydraulic.cond_drain,
                                        porosity=self.hydraulic.porosity,
                                        ss=self.hydraulic.ss,
                                        poro_decay=self.hydraulic.poro_decay,
                                        ss_decay=self.hydraulic.ss_decay,
                                        # Boundary settings
                                        sea_level=self.oceanic.MSL,
                                        bc_left=self.settings.bc_left, 
                                        bc_right=self.settings.bc_right,
                                        # Lakes/reservoirs
                                        lakeres=self.lakeres)
        
        # Preprocessing Modflow
        model_modflow.pre_processing() # verbose
                
        return model_modflow
         
    def processing_modflow(self, 
                           model_modflow: object, 
                           write_model: bool=True,
                           run_model: bool=False):
        """
        Public method to run the simulation of the model.

        Parameters
        ----------
        model_modflow : object
            Modflow model
        write_model : bool, optional
            write input files before run simulation. The default is True.
        run_model : bool, optional
            Run simulation. The default is False.

        Returns
        -------
        success_model : bool
            Boolean to know if the simulation rans succesfully.
        """
        # Processing Modflow
        success_model = model_modflow.processing(write_model=write_model, run_model=run_model)
        
        return success_model
        
    def postprocessing_modflow(self, model_modflow: object,
                               watertable_elevation: bool=True,
                               watertable_depth: bool=True, 
                               seepage_areas: bool=True,
                               outflow_drain: bool=True,
                               groundwater_flux: bool=True,
                               groundwater_storage: bool=True,
                               accumulation_flux: bool=True,
                               lake_seepage: bool=True,
                               persistency_index: bool=False,
                               intermittency_monthly: bool=False,
                               intermittency_weekly: bool=False,
                               intermittency_daily: bool=False,
                               export_all_tif: bool=False,
                               export_netcdf: bool=False):
        """
        Public method to post-process the simulation of the model.

        Parameters
        ----------
        model_modflow : object
            Modflow object.
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
        intermittency_yearly : bool, optional
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
                                      intermittency_monthly=intermittency_monthly,
                                      intermittency_weekly=intermittency_weekly,
                                      intermittency_daily=intermittency_daily,
                                      export_all_tif=export_all_tif,
                                      export_netcdf=export_netcdf)

    #%% MODPATH MODEL        
    
    def preprocessing_modpath(self, model_modflow: object, for_calib: bool=False):
        """
        Public method to set the partickle tracking.

        Parameters
        ----------
        model_modflow : object
            Modflow object.

        Returns
        -------
        model_modpath : object
            Modpath object.
        """
        if for_calib == False:
            model_folder = self.simulations_folder
        else:
            self.calibration_folder = os.path.join(self.watershed_folder, 'results_calibration')
            toolbox.create_folder(self.calibration_folder)
            model_folder = self.calibration_folder
        
        model_modpath = modpath.Modpath(self.geographic,
                                        model_modflow,
                                        # Frame settings
                                        model_folder=model_folder,
                                        model_name=self.settings.model_name,
                                        bin_path = self.bin_path,
                                        # Specific settings  
                                        zone_partic=self.settings.zone_partic)
        
        # Preprocessing Modflow
        model_modpath.pre_processing() # verbose
                
        return model_modpath
                            
    def processing_modpath(self, model_modpath: object, write_model: bool=True, run_model: bool=False):
        """
        Public method to run the partickle tracking.

        Parameters
        ----------
        model_modpath : object
            Modpath object.
        write_model : bool, optional
            Write input files before run simulation. The default is True.
        run_model : bool, optional
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
                               particules_shp: bool=True,
                               random_id: int=None):
        """
        Public method to post-process the simulation of the particle tracking.

        Parameters
        ----------
        model_modpath : object
            Modpath object.
        ending_point : bool, optional
            Save ending point. The default is True.
        starting_point : bool, optional
            Save starting point. The default is True.
        pathlines_shp : bool, optional
            Save pathlines as lines shapefile. The default is True.
        particules_shp : bool, optional
            Save particule as points shapefile. The default is True.
        random_id : int, optional
            Number of particules which are saved. The default is None.
        """
        model_modpath.post_processing(model_modpath,
                                      ending_point=ending_point,
                                      starting_point=starting_point,
                                      pathlines_shp=pathlines_shp,
                                      particules_shp=particules_shp,
                                      random_id=random_id)

    #%% EXTRACT TIMESERIES
    
    def postprocessing_timeseries(self,
                                  model_modflow: object,
                                  model_modpath: object,
                                  actual_date: bool=True,
                                  subbasin_results: bool=True,
                                  freq_time: str='D'):
        """
        Public method to postprocess the watershed timeseries.

        Parameters
        ----------
        model_modflow : object
            Modflow object.
        model_modpath : object
            Modpath object.
        actual_date : bool, optional
            True if data are referenced temporally. The default is True.
        subbasin_results : bool, optional
            Generate all results for each subbassin. The default is True.

        Returns
        -------
        timeseries_results : pandas.dataframe
            Table with all results.
        """
        if model_modflow != None:
            timeseries_results = timeseries.Timeseries(self.geographic,
                                                        model_modflow=model_modflow,
                                                        model_modpath=model_modpath,
                                                        actual_date=actual_date,
                                                        subbasin_results=subbasin_results,
                                                        freq_time=freq_time)
            
            return timeseries_results

#%% NOTES
