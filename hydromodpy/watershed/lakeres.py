# -*- coding: utf-8 -*-
"""
 * Functionnality developped by Alexandre Coche (2024)
 * 
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy,
 * Alexandre Coche
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
import datetime
import logging
import shutil
import numbers
import pandas as pd
import numpy as np
import rasterio
import rasterio as rio
import xarray as xr
xr.set_options(keep_attrs = True)
from pysheds.grid import Grid
from pysheds.view import Raster
from affine import Affine

# HydroModPy
from hydromodpy.tools import toolbox

#%% CLASS

class Lakeres:

    
    #%% INIT

    def __init__(self, stable_folder):
        """
        Class to initialize the lake/reservoir option.
        At this point, no lake/reservoir is defined. The process of defining
        a lake/reservoir is done during at a later stage using new_lakeres.
        Note that if the class lakeres is activated, but no lake/reservoir has
        been defined when running the modflow model, then the option
        lake/reservoir will be automatically deactivated.

        Parameters
        ----------
        stable_folder : str
            Path where to store stable results for the current simulation

        """

        self.data_folder = os.path.join(stable_folder, 'lakeres')
        if not os.path.exists(self.data_folder):
                os.makedirs(self.data_folder)

        self.n_lakeres:int = 0 # number of lakes/reservoirs
        self.indexes:list = [] # identifiers of lakes/reservoirs
        self.maskmx_by_lake:dict = {} # dict of lakes/reservoirs masks paths,
                                   # keyed by lake_id
                                   # masks correspond to te maximal extent of
                                   # the lake, or larger (see computation of
                                   # bathymetry)
        self.mask_crs_by_lake:dict = {} # user has the possibility to define the source
                                         # CRS of the mask file (if not embeded in the file)
        self.bathymetry_by_lake:dict = {} # bathymetry raster paths,
                                           # or computation option such as 'cuboid'
                                           # or nothing (topography will be used as bathymetry)
        self.bathy_crs_by_lake:dict = {}
        self.ref_table_by_lake:dict = {} # reference table for bathymetry fitting
        self.optimize_bathy_by_lake:dict = {} # flag to enable bathymetry optimization
        self.bathy_fit_params_by_lake:dict = {} # parameters for bathymetry fitting
        self.ssmx_by_lake:dict = {} # dict of maximum stages keyed by lake_id
        self.volmx_by_lake:dict = {}
        self.bdlknc_by_lake:dict = {} # dict of lakebed leakance
        # dict of lakes/reservoirs flux data dataframes, keyed by lake_id:
        self.prcplk_by_lake:dict = {}
        self.evaplk_by_lake:dict = {}
        self.rnf_by_lake:dict = {}
        self.rnf_acc_by_lake:dict = {}
        self.wthdrw_by_lake:dict = {}
        self.rtrn_by_lake:dict = {} # To connect return flow to SFR
        self.stageinit_by_lake:dict = {} # initial stage
        self.lake_by_num_id:dict = {} # Dict betwen num_id and lake_id
                                      # Defined in self.format_to_modflow()
        self.outlet_by_lake:dict = {}
        self.ij_outlet_by_lake:dict = {}
        

    #%% ADD A NEW LAKE/RESERVOIR
    def new_lakeres(self, maskmx:str, lake_id:int=None, mask_crs=None,
                    bathymetry_raster:str=None, bathy_crs=None,
                    ref_table:str=None, optimize_bathymetry:bool=False,
                    bathy_fit_params:dict=None,
                    ssmx:float=None, volmx:float=None, bdlknc:float=86400, # default = 1 m/s
                    prcplk=0, evaplk=0, rnf=0, rnf_acc=False, wthdrw=0, rtrn=None,
                    stageinit=None, outlet=None,
                    ):
        """
        Note that lakeres can be a lake or a reservoir.
        
        Parameters
        ----------
        All values should be expressed in the spatial and temporal units of the
        model.
        
        maskmx : str
            Path to the mask file (shapefile or raster).
            Works with NetCDF files?
        lake_id : optional
            DESCRIPTION. The default is None.
        mask_crs : TYPE, optional
            DESCRIPTION. The default is None.
        bathymetry_raster : str, optional
            Path to bathymetry raster file (.tif or .nc). The default is None.
        bathy_crs : TYPE, optional
            CRS of the bathymetry raster. The default is None.
        ref_table : str, optional
            Path to reference table (CSV) for bathymetry optimization.
            Must contain columns: elevation, volume, and optionally surface.
            The default is None.
        optimize_bathymetry : bool, optional
            Enable bathymetry optimization to match reference table.
            The default is False.
        bathy_fit_params : dict, optional
            Parameters for bathymetry fitting algorithm. Keys:
            - max_iter: maximum iterations (default 80)
            - step_init: initial step size (default 0.3)
            - max_step: maximum adjustment per iteration (default 1.2)
            - backtrack: backtracking steps (default 6)
            - retries: retry attempts (default 3)
            - rmse_stop: convergence threshold (default 0.0)
            - volume_weight: weight for volume error (default 0.5)
            - surface_weight: weight for surface error (default 0.5)
            - mask_buffer: buffer around mask in meters (default 0.0)
            - coverage_threshold: minimum cell coverage (default 0.0)
            - supersample: supersampling factor (default 8)
            The default is None (uses default values).
        ssmx : float, optional
            Maximal stage (level) of the lake/reservoir
            The default is None.
        volmx : float, optional
            Maxaimal volume of the lake. 
            The default is None.
        bdlknc : float, optional
            DESCRIPTION. The default is 86400 m/d (= 1 m/s)
        prcplk : float|array|file_path(str), optional
            Input for precipitations on the lake/reservoir. The default is 0 m/d 
            As for the next 3 parameters, prcplk can be defined by a
                - float: same value for all periods
                - pd.DataFrame: with times as index. Choosen times should also
                be present in watershed.climatic
                - file path: a .csv array or a .tif map or a .nc space-time array
        evaplk : float|array|file_path(str)|mode(str), optional
            Input for evaporation from the lake/reservoir. The default is 0 m/d
            As for the next parameter, evaplk can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic < 0.
        rnf : float|array|file_path(str)|mode(str), optional
            Input for runoff to the lake/reservoir. The default is 0 m/d
            As for the previous parameter, rnf can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic.runoff.
        rnf_acc : bool (optional)
            A flag to indicate whether the <rnf> value will be:
                . [False] used by Modflow as it is (positive value = volumetric 
                  rate, negative value = dimensionless multiplier)
                . [True] interpreted as a rate per unit area that will be 
                  accumulated to raise a volumetric rate added to the lake.
            The default value is False.
        wthdrw : float|array|file_path(str), optional
            Input for anthropic fluxes on the lake (withdrawal and filling). 
            The default is 0 m/d
            wthdrw integrates the sum of water removal (positive values) and
            water addition (negative values).
        rtrn : timesries, optional
            Return flow at the outlet(s) of each lake. This value is injected
            into the StreamFLow Routing network. It is not withdrawn from the
            lake/reservoir (for that, the return flow should be specified as
            well in wthdrw).
        outlet : str (optional)
            Filepaths to outlet file (shapfile, txt with coordinates)
        

        Returns
        -------
        None.

        """
        
        # Store/infer lake_id
        if lake_id in self.indexes:
            logging.error(f"Lake/reservoir with id {lake_id} already exists.")
            return
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id:int = 0 # initialization
            else:
                lake_id:int = np.max(self.indexes) + 1
        logging.info(f"Adding lake '{lake_id}'")
        
        # Lake/reservoir geometry
        self.maskmx_by_lake[lake_id] = maskmx
        self.mask_crs_by_lake[lake_id] = mask_crs
        self.bathymetry_by_lake[lake_id] = bathymetry_raster
        self.bathy_crs_by_lake[lake_id] = bathy_crs
        self.ref_table_by_lake[lake_id] = ref_table
        self.optimize_bathy_by_lake[lake_id] = optimize_bathymetry
        self.bathy_fit_params_by_lake[lake_id] = bathy_fit_params or {}
        self.ssmx_by_lake[lake_id] = ssmx
        self.volmx_by_lake[lake_id] = volmx

        # Lake/reservoir parameters
        self.bdlknc_by_lake[lake_id] = bdlknc # default = 1 m/s
        self.stageinit_by_lake[lake_id] = stageinit
        self.outlet_by_lake[lake_id] = outlet
        
        # Lake/reservoir inflows and outflows
        self.prcplk_by_lake[lake_id] = prcplk
        self.evaplk_by_lake[lake_id] = evaplk
        self.rnf_by_lake[lake_id] = rnf
        self.rnf_acc_by_lake[lake_id] = rnf_acc
        self.wthdrw_by_lake[lake_id] = wthdrw
        self.rtrn_by_lake[lake_id] = rtrn

        # Update Lakeres attributes:
        # self.idlist = self.idlist.append(lake_id)
        self.indexes = list(self.maskmx_by_lake.keys())
        self.n_lakeres = len(self.indexes)
        
        # List of attributes
        self.attr_list = [self.maskmx_by_lake, self.mask_crs_by_lake,
                          self.bathymetry_by_lake, self.bathy_crs_by_lake,
                          self.ref_table_by_lake, self.optimize_bathy_by_lake,
                          self.bathy_fit_params_by_lake,
                          self.ssmx_by_lake, self.volmx_by_lake,
                          self.bdlknc_by_lake, self.stageinit_by_lake,
                          self.outlet_by_lake, self.prcplk_by_lake,
                          self.evaplk_by_lake, self.rnf_by_lake,
                          self.rnf_acc_by_lake, self.wthdrw_by_lake,
                          self.rtrn_by_lake]
        
        
    #%% UPDATE A PREVIOUS LAKE/RESERVOIR
    def update_definition(self, lake_id, new_lake_id:int=None, new_maskmx_path:str=None):
        if new_lake_id and not new_maskmx_path: # just replace the key
            for d in self.attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.indexes = list(self.maskmx_by_lake.keys())
            
        elif new_maskmx_path and not new_lake_id: # just replace the mask
            self.maskmx_by_lake[lake_id] = new_maskmx_path
            
        elif new_lake_id and new_maskmx_path: # replace both the mask and the key
            for d in self.attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.maskmx_by_lake[new_lake_id] = new_maskmx_path
            self.indexes = list(self.maskmx_by_lake.keys())


    #%% REMOVE A LAKE/RESERVOIR
    def remove(self, lake_id):
        for d in self.attr_list:
            d.pop(lake_id)
        
        # Update Lakeres attributes:
        self.indexes = list(self.maskmx_by_lake.keys())
        self.n_lakeres = len(self.indexes)
        
        
    #%% UPDATE GEOMETRY and PHYSICAL PROPERTIES OF THE LAKE/RESERVOIR
    def update_stagemax(self, lake_id, ssmx):
        self.ssmx_by_lake[lake_id] = ssmx
        
    def update_volumemax(self, lake_id, volmx):
        self.volmx_by_lake[lake_id] = volmx
        
    def update_stageinit(self, lake_id, stageinit):
        self.stageinit_by_lake[lake_id] = stageinit
        
    def update_lakebed_leakance(self, lake_id, bdlknc):
        self.bdlknc_by_lake[lake_id] = bdlknc
        
    def update_bathymetry(self, lake_id, bathymetry_raster):
        self.bathymetry_by_lake[lake_id] = bathymetry_raster
        
    def update_outlet(self, lake_id, outlet_file):
        self.outlet_by_lake[lake_id] = outlet_file
        
    #%% UPDATE FLOWS IN AND OUT OF THE LAKE/RESERVOIR    
    def update_precip(self, lake_id, src):
        self.prcplk_by_lake[lake_id] = src
        
    def update_evap(self, lake_id, src):
        self.evaplk_by_lake[lake_id] = src
        
    def update_runoff(self, lake_id, src, runoff_accumulation=False):
        self.rnf_by_lake[lake_id] = src
        self.rnf_acc_by_lake[lake_id] = runoff_accumulation
        
    def update_withdraw_fill(self, lake_id, src):
        self.wthdrw_by_lake[lake_id] = src
    
    def connect_returnflow(self, lake_id, timeseries):
        self.rtrn_by_lake[lake_id] = timeseries
    
   #%% FORMAT ALL ATTRIBUTES INTO INPUTS FOR MODFLOW
    def format_to_modflow(self, geographic, climatic, nper, thickfact, dem, dem_watershed_path):
        logging.info("Lakes/Reservoirs: formating all attributes...")
        
        #%%% Standardize lake identifiers
        # -------------------------------
        # lake_id can be anything, defined by the user: 1, 10, 'lake 155', 'Cheze', ...
        # num_id are: 1, 2, 3...
        self.lake_by_num_id = {idx+1: self.indexes[idx] for idx in range(0, self.n_lakeres)}
        # self.lake_by_num_id = {idx+1: sorted(self.indexes)[idx] for idx in range(0, self.n_lakeres)}
        
        
        #%%% Format lakarr
        # ----------------
        # Load masked np.array of watershed and initialize lakarr
        with rio.open(geographic.watershed_dem, 'r') as base:
            nodata = base.profile['nodata'] # value corresponding to the no data property         
            transform = base.profile['transform']
        watershed_mask, _, _, _ = toolbox.load_to_numpy(geographic.watershed_dem,
                                                        dst_crs = geographic.crs_proj) 
        lakarr = np.ma.array(watershed_mask, 
                            mask = watershed_mask==nodata,
                            fill_value = nodata,
                            ) * 0 # masked np.ndarray with null values
        
# =============================================================================
#         # Load topography
#         dem, _, _, _ = toolbox.load_to_numpy(geographic.watershed_box_buff_dem,
#                                                 dst_crs = geographic.crs_proj) 
# =============================================================================
        
        # Cell area
# =============================================================================
#         cell_area = (dem[0,1] - dem[0,0])*(dem[1,0] - dem[0,0])   
#         cell_area = abs(transform[0]) * abs(transform[4])
# =============================================================================
        cell_area = geographic.cell_size
        
        # Format lakes maskmx (maximal extents)
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            
            maskmx, src_crs, _, _ = toolbox.load_to_numpy(
                self.maskmx_by_lake[lake_id], 
                src_crs = self.mask_crs_by_lake[lake_id],
                base_path = geographic.watershed_dem, 
                dst_crs = geographic.crs_proj)
            
            if self.mask_crs_by_lake[lake_id] is None:
                self.mask_crs_by_lake[lake_id] = src_crs
            
            maskmx[maskmx == nodata] = 0
            maskmx = maskmx.astype(bool)
            
            if not self.bathymetry_by_lake[lake_id]: # None
            # In this case, topography is used for bathymetry, using the same
            # computation as in the next case
                self.bathymetry_by_lake[lake_id] = geographic.watershed_dem
                self.bathy_crs_by_lake[lake_id] = geographic.crs_proj
            
            if os.path.isfile(self.bathymetry_by_lake[lake_id]):
                bathymetry, _, _, _ = toolbox.load_to_numpy(
                    self.bathymetry_by_lake[lake_id],
                    src_crs = self.bathy_crs_by_lake[lake_id],
                    base_path = geographic.watershed_dem,
                    dst_crs = geographic.crs_proj)

                # Export resampled bathymetry before optimization
                bathy_resampled_path = os.path.join(self.data_folder, f'bathymetry_resampled_lake_{lake_id}.tif')
                toolbox.export_tif(
                    geographic.watershed_dem,
                    bathymetry,
                    bathy_resampled_path,
                    geographic.nodata,
                    geographic.crs_proj
                )
                logging.info(f"Exported resampled bathymetry (before optimization): {bathy_resampled_path}")

                # Bathymetry optimization if requested
                if self.optimize_bathy_by_lake[lake_id] and self.ref_table_by_lake[lake_id]:
                    logging.info(f"Starting bathymetry optimization for lake '{lake_id}'")

                    # Load reference table
                    ref_df, has_surface = self._load_reference_table(self.ref_table_by_lake[lake_id])

                    # Filter reference table to max elevation
                    if self.ssmx_by_lake[lake_id]:
                        ref_df = ref_df[ref_df['elevation'] <= self.ssmx_by_lake[lake_id] + 1e-6].reset_index(drop=True)

                    # Prepare mask with fractional coverage (supersampling)
                    fit_params = self.bathy_fit_params_by_lake[lake_id].copy()
                    supersample = fit_params.get('supersample', 8)
                    mask_buffer = fit_params.get('mask_buffer', 0.0)
                    coverage_threshold = fit_params.get('coverage_threshold', 0.0)

                    # Load mask with supersampling for fractional coverage
                    from rasterio.features import rasterize as rio_rasterize
                    if self.maskmx_by_lake[lake_id].endswith('.shp'):
                        import geopandas as gpd
                        from rasterio.transform import from_origin
                        gdf = gpd.read_file(self.maskmx_by_lake[lake_id])
                        if geographic.crs_proj:
                            gdf = gdf.to_crs(geographic.crs_proj)
                        if mask_buffer != 0.0:
                            gdf = gdf.set_geometry(gdf.buffer(mask_buffer))
                            gdf = gdf[~gdf.geometry.is_empty]

                        shape = bathymetry.shape
                        if supersample > 1:
                            # Supersample for fractional coverage
                            fine_shape = (shape[0] * supersample, shape[1] * supersample)
                            fine_transform = rasterio.Affine(
                                transform.a / supersample, 0, transform.c,
                                0, transform.e / supersample, transform.f
                            )
                            fine_mask = rio_rasterize(
                                (geom for geom in gdf.geometry),
                                out_shape=fine_shape,
                                transform=fine_transform,
                                fill=0,
                                default_value=1,
                                dtype='uint8',
                                all_touched=True
                            ).astype(np.float32)
                            fine_mask = fine_mask.reshape(shape[0], supersample, shape[1], supersample)
                            fraction = fine_mask.mean(axis=(1, 3))
                        else:
                            fraction = rio_rasterize(
                                (geom for geom in gdf.geometry),
                                out_shape=shape,
                                transform=transform,
                                fill=0,
                                default_value=1,
                                dtype='float32',
                                all_touched=True
                            )

                        weights = np.where(fraction >= coverage_threshold, fraction, 0.0).astype(np.float32)
                        opt_mask = weights > 0
                    else:
                        # Raster mask - no supersampling
                        opt_mask = maskmx.copy()
                        weights = opt_mask.astype(np.float32)

                    # Set max_elev parameter
                    if self.ssmx_by_lake[lake_id]:
                        fit_params['max_elev'] = self.ssmx_by_lake[lake_id]
                    fit_params['nodata'] = nodata

                    # Store initial volumes/surfaces for comparison
                    vol_init = self._compute_volume_curve(
                        bathymetry,
                        opt_mask & np.isfinite(bathymetry) & (bathymetry != nodata),
                        cell_area,
                        ref_df["elevation"].to_numpy(np.float32),
                        weights
                    )
                    if has_surface:
                        surf_init = self._compute_surface_curve(
                            bathymetry,
                            opt_mask & np.isfinite(bathymetry) & (bathymetry != nodata),
                            cell_area,
                            ref_df["elevation"].to_numpy(np.float32),
                            weights
                        )

                    # Run optimization
                    fitted_bathy, levels, vol_fit, vol_ref, surf_fit, surf_ref = self._fit_bathymetry(
                        bathymetry,
                        opt_mask,
                        cell_area,
                        ref_df,
                        weights,
                        has_surface,
                        fit_params
                    )

                    # Export fitted bathymetry
                    bathy_fitted_path = os.path.join(self.data_folder, f'bathymetry_fitted_lake_{lake_id}.tif')
                    toolbox.export_tif(
                        geographic.watershed_dem,
                        fitted_bathy,
                        bathy_fitted_path,
                        geographic.nodata,
                        geographic.crs_proj
                    )
                    logging.info(f"Exported fitted bathymetry: {bathy_fitted_path}")

                    # Compute and export statistics
                    vol_metrics = self._compute_metrics(vol_fit, vol_ref)
                    stats = {
                        'lake_id': lake_id,
                        'volume_rmse_m3': vol_metrics['rmse'],
                        'volume_mae_m3': vol_metrics['mae'],
                        'volume_rel_error_%': vol_metrics['rel'],
                        'volume_r2': vol_metrics['r2']
                    }

                    if has_surface:
                        surf_metrics = self._compute_metrics(surf_fit, surf_ref)
                        stats.update({
                            'surface_rmse_m2': surf_metrics['rmse'],
                            'surface_mae_m2': surf_metrics['mae'],
                            'surface_rel_error_%': surf_metrics['rel'],
                            'surface_r2': surf_metrics['r2']
                        })

                    stats_df = pd.DataFrame([stats])
                    stats_path = os.path.join(self.data_folder, f'bathymetry_fit_stats_lake_{lake_id}.csv')
                    stats_df.to_csv(stats_path, sep=';', index=False)
                    logging.info(f"Exported fitting statistics: {stats_path}")

                    # Display statistics
                    if has_surface:
                        logging.info(f"Volume metrics -> RMSE: {vol_metrics['rmse']:,.0f} m³, MAE: {vol_metrics['mae']:,.0f} m³, Rel: {vol_metrics['rel']:.2f} %, R²: {vol_metrics['r2']:.4f}")
                        logging.info(f"Surface metrics -> RMSE: {surf_metrics['rmse']:,.0f} m², MAE: {surf_metrics['mae']:,.0f} m², Rel: {surf_metrics['rel']:.2f} %, R²: {surf_metrics['r2']:.4f}")
                    else:
                        logging.info(f"Volume metrics -> RMSE: {vol_metrics['rmse']:,.0f} m³, MAE: {vol_metrics['mae']:,.0f} m³, Rel: {vol_metrics['rel']:.2f} %, R²: {vol_metrics['r2']:.4f}")

                    # Generate diagnostic plot (will be implemented in display module)
                    try:
                        from display import visualization_results
                        plot_path = os.path.join(self.data_folder, f'bathymetry_fit_diagnostics_lake_{lake_id}.png')
                        visualization_results.plot_bathymetry_fit(
                            levels, vol_init, vol_fit, vol_ref,
                            surf_init if has_surface else None,
                            surf_fit if has_surface else None,
                            surf_ref if has_surface else None,
                            has_surface,
                            plot_path
                        )
                        logging.info(f"Exported diagnostic plot: {plot_path}")
                    except Exception as e:
                        logging.warning(f"Could not generate diagnostic plot: {e}")

                    # Use fitted bathymetry
                    bathymetry = fitted_bathy
                else:
                    logging.info(f"Bathymetry optimization disabled for lake '{lake_id}'")

                # Replace topo by bathy, on the area where bathy exists:
                dem = np.where(bathymetry == nodata, dem, bathymetry)

                # Update dem files:
                self.update_dem(geographic, dem)
                
                # Mask dem with maskmx:
                masked_dem = np.ma.array(dem, 
                                         mask = ~maskmx,
                                         fill_value = nodata,
                                         )
                
                if self.ssmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # ssmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    maskmx = np.ma.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
                    maskmx = maskmx.astype(bool)
                    if maskmx.sum() == np.ma.count(masked_dem):
                        logging.warning(f"The lake maximal level (ssmx) is likely to be too small. It can not naturally exceed {masked_dem.max()} m. To match the required ssmx of {self.ssmx_by_lake[lake_id]} m, the lake surface was considered not continuous with the surrounding topography.")
                    
                    if self.volmx_by_lake[lake_id]:
                        masked_dem = np.ma.array(dem, 
                                                 mask = ~maskmx,
                                                 fill_value = nodata,
                                                 )
                        equiv_vol = float((self.ssmx_by_lake[lake_id] - masked_dem).sum()*cell_area)
                        logging.warning(f" The specified maximal volume ({self.volmx_by_lake[lake_id]} m3) is discarded because redundant with the specified maximal level (equiv. to {equiv_vol} m3)")
                        self.volmx_by_lake[lake_id] = equiv_vol
                        
                
                elif self.volmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # volmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    logging.info(f" Computing the maximum lake/reservoir level to match with a volume of {self.volmx_by_lake[lake_id]} m3")
                    # elev = np.arange(masked_dem.min(), masked_dem.max(), 0.1)
                    i = 0
                    vol = 0
                    elev = masked_dem.min()
                    while vol < self.volmx_by_lake[lake_id]:
                        vol = (elev - np.ma.where(masked_dem <= elev,
                                                      masked_dem, elev)).sum()*cell_area
                        elev+=0.1
                        i+=1
                    if elev > masked_dem.max():
                        nat_vol = (masked_dem.max() - np.ma.where(masked_dem <= masked_dem.max(),
                                                      masked_dem, masked_dem.max())).sum()*cell_area
                        logging.warning(f"The lake maximal extent (maskmx) is likely to be too small. It can only naturally contain a volume of {nat_vol} m3. To match the required volmx of {self.volmx_by_lake[lake_id]} m3, the lake surface was considered not continuous with the surrounding topography.")
                    
                    maskmx = np.ma.where(masked_dem <= elev-0.1, 1, 0)
                    maskmx = maskmx.astype(bool)
                    # Update ssmx (might be used in other functions)
                    self.ssmx_by_lake[lake_id] = elev-0.1

                    
                # If no volmx nor ssmx is defined:
                else:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at its maximum extent.
                    logging.warning(f"The '{lake_id}' lake/reservoir mask will be used as a strict mask of the lake at its maximum extent.")
                    self.ssmx_by_lake[lake_id] = masked_dem.max() # Update ssmx (might be used in other functions)
                    
                    
            elif self.bathymetry_by_lake[lake_id] == 'cuboid':
            # In this case, bathymetry will be computed, based on volmx (required)
            # and ssmx (optional)
                if self.volmx_by_lake[lake_id]:
                    if self.ssmx_by_lake[lake_id]:
# =============================================================================
#                     # In this case, maskmx will be adjusted to match the desired
#                     # volmx and ssmx.
#                     # In this situation, maskmx is to be considered as an enlarged
#                     # maximal potential extent of the lake, similar to the mask
#                     # of the valley around the lake.
# =============================================================================
                    # In this case, maskmx will be used as a strick mask of the
                    # lake/reservoir, at its maximal extent.
                        logging.info(f" Computing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum level of {self.ssmx_by_lake[lake_id]} m")
                        # The commented following part is about adjusting the lake extent, using ssmx
# =============================================================================
#                         maskmx = np.ma.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
#                         maskmx = maskmx.astype(bool)
# =============================================================================
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem = np.where(maskmx, self.ssmx_by_lake[lake_id] - depth, dem)
                        
                    else:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at its maximum extent.
                        logging.info(f" Computing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum extent")
                        self.ssmx_by_lake[lake_id] = masked_dem.max() # Update ssmx (might be used in other functions)
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem = np.where(maskmx, self.ssmx_by_lake[lake_id] - depth, dem)
                        
                else:
                    logging.error("Maximum lake/reservoir volume (volmx) is required to compute bathymetry (cuboid mode)")
            
                self.update_dem(geographic, dem)
        
# =============================================================================
#             lakarr = lakarr + np.ma.array(maskmx,
#                                           fill_value = nodata
#                                           ) * lake_id
# =============================================================================
            maskmx = np.ma.array(maskmx,
                                 mask = watershed_mask==nodata,
                                 fill_value = nodata
                                 )
    
            # Check overlapping between lakes
            for num_id2 in self.lake_by_num_id.keys():
                lake_id2 = self.lake_by_num_id[num_id2]
                temp_lakarr = lakarr.copy()*0
                temp_lakarr[lakarr==num_id2] = 1
                intersect = (maskmx*temp_lakarr).sum()
                if intersect > 0:
                    logging.warning(f"Lake '{lake_id}' will overwrite lake '{lake_id2}' on {int(intersect)} cells.")
        
            lakarr[maskmx==1] = num_id
            
        # Convert the masked array into an array
        lakarr = lakarr.filled(0)
        
# =============================================================================
#             lakarr = np.where(maskmx==1, lake_id, lakarr)
# =============================================================================
    
# A SUPPRIMER BIENTOT !    
# =============================================================================
#         # Check overlapping between lakes   
#         if geographic:     
#             with rio.open(geographic.watershed_dem, 'r') as base:
#                 nodata = base.profile['nodata'] # value corresponding to the no data property 
# 
#             maskmx = toolbox.load_to_numpy(maskmx_path, 
#                                          src_crs = src_crs,
#                                          base_path = geographic.watershed_dem, 
#                                          dst_crs = geographic.crs_proj)
#             
#             maskmx[maskmx == nodata] = 0
#             
#             for idx in self.indexes:
#                 prev_maskmx = toolbox.load_to_numpy(maskmx_path, 
#                                                     src_crs = src_crs,
#                                                     base_path = geographic.watershed_dem, 
#                                                     dst_crs = geographic.crs_proj)
#                 
#                 intersect = (maskmx*prev_maskmx).sum()
#                 if intersect > 0:
#                     logging.info(f"NB: Lake n°{lake_id} may overwrite lake n°{idx} on {int(intersect)} cells.")
#         
# =============================================================================

        # Export
# =============== OLD SCHOOL VERSION ==========================================
#         with rio.open(geographic.watershed_dem, 'r') as base:
#             base_profile = base.profile
#             base_profile['crs'] = geographic.crs_proj
#             # base_profile['nodata'] = 0
#             # base_profile['dtype'] = int
#         with rio.open(os.path.join(self.data_folder, 'lakarr.tif'),
#                       'w', **base_profile) as dst: 
#             dst.write_band(1, lakarr.astype(int))
# =============================================================================
        toolbox.export_tif(
            geographic.watershed_dem,
            lakarr, #lakarr.astype(int): computation time appears to be a bit shorter when using float...
            os.path.join(self.data_folder, "lakarr.tif"),
            geographic.nodata,
            geographic.crs_proj
            )
            
        #%%% Format the top of the lake/reservoir layer
        # ---------------------------------------------
        laklay_top = dem.copy()+1
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            laklay_top[lakarr == num_id] = self.ssmx_by_lake[lake_id]
            # laklay_top[(lakarr == num_id) & (laklay_top < thickfact*100)] = thickfact*100
            # laklay_top[(laklay_top - dem) < thickfact*100] = laklay_top + thickfact*100
            laklay_top = np.where(laklay_top < dem + thickfact*100, dem + thickfact*110, laklay_top)
            
        # Exports
        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'laklay_top.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, laklay_top)

        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'laklay_thick.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, laklay_top - dem)
        
            
        #%%% Format initial stage
        # -----------------------
        stages = []
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            if isinstance(self.stageinit_by_lake[lake_id], (int, float)):
                stages.append(self.stageinit_by_lake[lake_id])
            else:
                logging.warning(f"The lake/reservoir '{lake_id}' will be initially considered dry.")
                stages.append(float(dem[maskmx==1].min()))
                
        #%%% Format bedlake leakance
        # --------------------------
        # bdlknc = {}
        # for kper in range(0, nper):
        #     bdlknc_val = []
        #     for num_id in self.lake_by_num_id.keys():
        #         lake_id = self.lake_by_num_id[num_id]
        #         bdlknc_val.append(self.bdlknc_by_lake[lake_id])
        #     bdlknc[kper] = bdlknc_val
        bdlknc = lakarr.copy()*0 + self.bdlknc_by_lake[lake_id]
        
        #%%% Format outlets
        self.format_outlets(lakarr, geographic, dem_watershed_path)
        
        #%%% Format fluxes data
        # ---------------------
        flux_data = {kper:[] for kper in range(0, nper)}
        settings_by_flux = {'PRCPLK': self.prcplk_by_lake, 
                            'EVAPLK': self.evaplk_by_lake, 
                            'RNF': self.rnf_by_lake, 
                            'WTHDRW': self.wthdrw_by_lake}
        # Final format:
        # {0:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  1:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  2:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  ...}
            
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            lake_frame = pd.DataFrame(
                columns = list(settings_by_flux.keys()), 
                index = climatic.index)
        
            for flux in settings_by_flux.keys():
                settings = settings_by_flux[flux][lake_id]
            
                # Constant value: same for all periods
                if isinstance(settings, numbers.Number):
                    if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                        pd_data = self.accumulate_runoff(settings, lake_id, geographic)
                        lake_frame.loc[pd_data.index, flux] = pd_data
                    else:
                        lake_frame[flux] = settings
                
                else:
                    if isinstance(settings, str):
                        # If flux is defined by 'from_climatic' option
                        if settings == 'from_climatic':
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                try: 
                                    pd_data = self.accumulate_runoff(climatic.runoff, 
                                                                     lake_id, 
                                                                     lakarr,
                                                                     geographic)
                                    # flux_frame.loc[climatic.runoff.index, num_id] = climatic.runoff
                                except: 
                                    logging.error(f"{flux} over lake '{lake_id}' cannot be defined from climatic: watershed.climatic.runoff does not exist")
                                    return
                            elif flux == 'EVAPLK':
                                pd_data = -climatic.where(climatic<0, 0)
                                # flux_frame.loc[:, num_id] = -climatic.where(
                                #     climatic<0, 0)
                            else:
                                logging.error(f"{flux} over lake '{lake_id}' cannot be defined from climatic")
                                return
                        
                        # Array file (.csv or .txt): will be read with pandas
                        elif os.path.isfile(settings) & os.path.splitext(settings)[-1].casefold() in ['.csv', '.txt']:
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                pd_data = self.accumulate_runoff(
                                    pd.read_csv(settings, sep=';', index_col=0, parse_dates=True),
                                    lake_id, lakarr, geographic)
                            else:
                                pd_data = pd.read_csv(settings, sep=';', index_col=0, parse_dates=True)
                            
                        # NetCDF file: will be read with xarray
                        elif os.path.isfile(settings) & os.path.splitext(settings)[-1].casefold() == '.nc':
                            ds = toolbox.read_with_xarray(settings)
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                pd_data = self.accumulate_runoff(ds, lake_id, lakarr, geographic)
                            else:
                                # xarray.DataSet: spatial mean over the lake area is extracted to a pandas.DataFrame
                                logging.warning("xr.DataSet needs to be converted into pd.DataFrame (not implemented yet)")
                            
                    # Format df to flux_frame
                    if isinstance(settings, pd.DataFrame):
                    # Convert pandas.DataFrame to pandas.Series
                        if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                            pd_data = self.accumulate_runoff(settings, lake_id, lakarr, geographic)
                        else:
                            pd_data = settings[settings.columns[0]]
                    elif isinstance(settings, pd.Series):
                        if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                            pd_data = self.accumulate_runoff(settings, lake_id, lakarr, geographic)
                        else:
                            pd_data = settings
                    
                    # pd_data.set_index(pd_data.index.normalize()) 
                    pd_data.index = pd_data.index.normalize() # To convert dates-time to midnight.
                    pd_data = pd_data[(pd_data.index >= climatic.index[0]) & (pd_data.index <= climatic.index[-1])]
                    lake_frame.loc[pd_data.index, flux] = pd_data
                    lake_frame[flux].fillna(method = 'ffill', inplace = True) # forward fill
                    lake_frame[flux].fillna(0, inplace = True) # replace remaining NaN with 0
            
            for kper in range(0, nper):
                flux_data[kper].append(lake_frame.iloc[kper].to_list())
            
            # export
            lake_frame.to_csv(os.path.join(self.data_folder,
                                           f"flux_data_lake_{lake_id}.csv"), 
                              sep = ';', 
                              header = True) 
                
        print('\n')
        return stages, lakarr, laklay_top, bdlknc, flux_data, dem
       
   
    #%% UPDATE DEM FILES        
    def update_dem(self, geographic, dem):
        # dem has been modified, and its modifications should also be applied
        # on all dem files.
        logging.info("Updating DEM files...")
        # Update DEM initial file
        # bathy_dem = os.path.join(geographic.reg_path, 'temp_DEM_with_bathymetry.tif')
        
        # Make a backup of the initial DEM input:
        filepath, ext = os.path.splitext(geographic.dem_path)
        backup_path = filepath + '_backup' + ext
        shutil.copy2(geographic.dem_path, backup_path)
        
        # Modify the original DEM input with the dem data (= original dem corrected with bathymetry)
        with rio.open(geographic.dem_path, 'r+') as bathy_dem:
            with rio.open(geographic.watershed_box_buff_dem, 'r') as box:
                window = rio.windows.from_bounds(*box.bounds, transform=bathy_dem.transform)
                # Temp correction            
                dem = np.where(dem == -9999, geographic.nodata, dem)
                # Update original DEM data
                val = bathy_dem.read(1, window=window)
                val = np.where(dem != geographic.nodata, dem, val) 
                bathy_dem.write_band(1, val, window=window)
        
        # Repeat the generation of geographic maps
        geographic.processing()
        
        # Remove the corrected original DEM and replace it with the previous backup
        os.remove(geographic.dem_path)
        os.rename(backup_path, geographic.dem_path)
        

    #%% FORMAT OUTLETS
    def format_outlets(self, lakarr, geographic, dem_watershed_path):
        self.ij_outlet_by_lake = {}
        outlet_map = np.full(lakarr.shape, geographic.nodata, dtype=float)
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            file = self.outlet_by_lake[lake_id]
            if file is None:
                # Automatic detection of the outlet (cell with the highest accumulation flow)
                acc_map, _, _, nodata = toolbox.load_to_numpy(
                    os.path.join(geographic.reg_path, 'region_acc.tif'), 
                    src_crs = geographic.crs_proj, 
                    base_path = dem_watershed_path, 
                    dst_crs = geographic.crs_proj)
# =============================================================================
#                 watershed_mask, _, _, nodata = toolbox.load_to_numpy(
#                     dem_watershed_path,
#                     src_crs = self.geographic.crs_proj, 
#                     base_path = dem_watershed_path,
#                     dst_crs = self.geographic.crs_proj)
# =============================================================================
                acc_map = np.ma.array(
                    acc_map, 
                    mask = lakarr!=num_id, 
                    fill_value = nodata) # masked np.ndarray
                
                i, j = np.unravel_index(np.argmax(acc_map), acc_map.shape)
 
            else:
                arr, _, _, _ = toolbox.load_to_numpy(
                    file,
                    src_crs = self.mask_crs_by_lake[lake_id],
                    base_path = geographic.watershed_dem,
                    dst_crs = geographic.crs_proj)

                i = np.argwhere(arr==num_id)[0,0]
                j = np.argwhere(arr==num_id)[0,1]

            self.ij_outlet_by_lake[lake_id] = (i, j)

        # Export lake outlet
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            outlet_map[self.ij_outlet_by_lake[lake_id][0],
                       self.ij_outlet_by_lake[lake_id][1]
                       ] = num_id
        toolbox.export_tif(
            geographic.watershed_dem,
            outlet_map,
            os.path.join(self.data_folder, "lak_outlets.tif"),
            geographic.nodata,
            geographic.crs_proj
            )
        
# =============================================================================
#         return self.ij_outlet_by_lake
# =============================================================================
                
    #%% ACCUMULATE RUNOFF
    def accumulate_runoff(self, data, lake_id, lakarr, geographic):
        """
        Compute accumulated runoff entering a lake/reservoir using pysheds D8 flow routing.

        This function processes runoff data (constant, timeseries, or spatially distributed)
        and calculates water accumulation at the lake outlet. Performance is optimized by
        detecting spatially uniform runoff and computing a reusable unit accumulation pattern.

        Note: runoff input must be volumetric rate [L³/T]

        Parameters
        ----------
        data : Number, pd.Series, pd.DataFrame, xr.DataArray, xr.Dataset
            Runoff input as volumetric rate [L³/T]. Can be:
            - Single number: constant runoff for all timesteps
            - pd.Series/DataFrame: temporal variation, spatially uniform
            - xr.DataArray/Dataset: spatio-temporal variation
        lake_id : str or int
            Lake identifier defined by user
        lakarr : np.ndarray
            Lake identifier array (0 = land, num_id = lake cells)
        geographic : object
            Watershed object with DEM, flow directions, and coordinate system

        Returns
        -------
        pd.Series
            Timeseries of accumulated runoff at lake outlet [L³/T]

        Notes
        -----
        - Runoff over lake surfaces is automatically set to 0
        - Flow is blocked at lake outlets to capture all incoming runoff
        - Spatial uniformity detection samples 5% of timesteps for efficiency
        - Uses pysheds for fast in-memory flow accumulation (D8 routing)
        - Normalized weights ensure numerical stability

        Dependencies
        ------------
        pysheds, rasterio, numpy, pandas, xarray, affine
        """
        
        # ---- Initialize
        logging.info(f"Initializing runoff accumulation for lake {lake_id}")

        # Create mask of watershed: =0 on lakes/reservoirs, =1 everywhere else
        mask = np.where(lakarr > 0, 0, 1)

        # Get time coordinate
        if isinstance(data, (pd.DataFrame, pd.Series)):
            # if data.index are dates...
            if isinstance(data.index[0], (datetime.datetime,
                                        pd.Timestamp,
                                        np.datetime64,
                                        str)):
                # ...then the index is used as the time coordinate
                time = data.index
        # If data has no index, or no date index...
        else:
            # ...then the time coordinate is built as a 0, 1, 2, 3... array
            time = np.array(range(len(data)))
            # In that case, data is formatted to a pd.dataframe
            data = pd.DataFrame(data=data, index=time, columns=['runoff'])

        # Build space coordinates based on lakarr dimensions (not mask)
        # This ensures consistency throughout the function
        actual_shape = lakarr.shape  # Use lakarr as reference
        x = [x for x in np.arange(
            geographic.xmin + geographic.resolution_x/2,
            geographic.xmin + geographic.resolution_x*actual_shape[1] + geographic.resolution_x/2,
            geographic.resolution_x)]
        y = [y for y in np.arange(
            geographic.ymax + geographic.resolution_y/2,
            geographic.ymax + geographic.resolution_y*actual_shape[0] + geographic.resolution_y/2,
            geographic.resolution_y)]
        
        # Generate a xarray.DataArray of runoff: data_4D
        units = ''
        # If data is already a xr.dataarray, no operation is needed
        if isinstance(data, xr.DataArray):
            data_4D = data
            units = data.attrs['units'].copy() if 'units' in data.attrs else ''
        
        # if data is a xr.dataset, the corresponding xr.dataarray is extracted
        elif isinstance(data, xr.Dataset):
            main_var = list(data.data_vars)[0]
            data_4D = data[main_var]
            units = data[main_var].attrs['units'].copy() if 'units' in data[main_var].attrs else ''
        
        # if data is something else, a xr.dataarray will be built from scratch
        else:
            # Create an empty dataarray
            data_4D = xr.DataArray(
                data=np.zeros((len(time), len(y), len(x))),
                coords=[time, y, x],
                dims=["time", "y", "x"]
            )
            # if data is a single number, it is used to fill the xr.dataarray
            if isinstance(data, numbers.Number):
                data_4D[:] = data
            # if data is a pd.dataframe, it is used to fill the xr.dataarray for each time
            elif isinstance(data, pd.DataFrame):
                for t_idx, t in enumerate(time):
                    data_4D[t_idx, :, :] = data.loc[t].iloc[0] # value of the column 0 at the time t
            elif isinstance(data, pd.Series):
                for t_idx, t in enumerate(time):
                    data_4D[t_idx, :, :] = data.loc[t] # value at the time t
        
        # Set runoff values over the extent of all lake/reservoirs to 0
        # (no runoff over water surfaces)
        # Note that, in the place of runoff, the precipitations falling directly on
        # lakes/reservoirs are expected to be user-defined as the 'PRCPLK' flux (self.prcplk_by_lake)
        data_4D = data_4D.where(np.tile(mask, (len(time), 1, 1)) == 1, 0)
        
        # ---- Determine if runoff is spatially uniform across all time steps
        is_spatially_uniform = True
        
        # Check first time step for uniformity
        sample_timestep = data_4D.isel(time=0).values
        sample_masked = sample_timestep * mask  # Apply mask to only consider land cells
        unique_values = np.unique(sample_masked[sample_masked > 0])
        
        # If more than one non-zero value, or no values at all, it's not uniform
        if len(unique_values) != 1:
            is_spatially_uniform = False
        
        # If first timestep is uniform, check if all other timesteps maintain the same pattern
        if is_spatially_uniform and len(data_4D.time) > 1:
            reference_pattern = sample_masked / unique_values[0]  # Normalize to create a pattern
            reference_pattern[reference_pattern == 0] = 0  # Ensure zeros stay zeros
            
            threshold = round(len(data_4D.time)*0.05) # 5% of the time series
            
            # Check a few random timesteps for efficiency (checking all could be slow for large datasets)
            check_indices = np.linspace(1, len(data_4D.time)-1, min(threshold, len(data_4D.time)-1)).astype(int)
            for idx in check_indices:
                check_ts = data_4D.isel(time=idx).values * mask
                if np.sum(check_ts) == 0:  # Skip zero-sum timesteps
                    continue
                    
                # Create normalized pattern
                check_nonzero = check_ts[check_ts > 0]
                if len(np.unique(check_nonzero)) > 1:
                    is_spatially_uniform = False
                    break
                
                check_pattern = check_ts / check_nonzero[0]
                check_pattern[check_pattern == 0] = 0
                
                # Compare patterns (allowing for small floating point differences)
                if not np.allclose(reference_pattern, check_pattern, rtol=1e-5, equal_nan=True):
                    is_spatially_uniform = False
                    break
        
        # Initialize result array
        result_4D = xr.DataArray(
            data=np.zeros((len(time), len(y), len(x))),
            coords=[time, y, x],
            dims=["time", "y", "x"]
        )
        
        # ---- Use pysheds method for flow accumulation (fast in-memory processing)
        logging.info(f"Processing runoff accumulation for lake {lake_id}: Using pysheds method")

        # Load flow directions - aligned to the same grid as lakarr
        direc, _, _, _ = toolbox.load_to_numpy(
            geographic.watershed_box_buff_direc,
            src_crs=geographic.crs_proj,
            base_path=geographic.watershed_dem,  # same reference as lakarr
            dst_crs=geographic.crs_proj)

        # Check compatibility of sizes with lakarr
        if direc.shape != lakarr.shape:
            logging.warning(f"Flow direction shape mismatch: {direc.shape} vs {lakarr.shape}")
            from scipy.ndimage import zoom
            scale_y = lakarr.shape[0] / direc.shape[0]
            scale_x = lakarr.shape[1] / direc.shape[1]
            direc = zoom(direc, (scale_y, scale_x), order=0)  # order=0 to preserve directions
            logging.info(f"Flow directions resized to {direc.shape}")

        # Cancel flow direction in lake outlets to ensure accumulation
        # Here we consider that the runoff can accumulate over the lake (in
        # order to compute the accumulated runoff value), but it can not leave the lake.
        for l in self.ij_outlet_by_lake:  # for each lake on the watershed
            (i_, j_) = self.ij_outlet_by_lake[l]
            direc[i_, j_] = 0

        # Create a pysheds.grid object with flow directions
        direc_raster = Raster(direc)
        direc_raster.crs = geographic.crs_proj
        direc_raster.nodata = -1  # geographic.nodata
        direc_raster.affine = Affine(
            geographic.resolution_x, 0, geographic.xmin,
            0, geographic.resolution_y, geographic.ymax)
        grid = Grid.from_raster(direc_raster, data_name='direc')

        # Specify directional mapping (D8 WhiteBox Tools system)
        dirmap = (128, 1, 2, 4, 8, 16, 32, 64)

        # ---- PYSHEDS OPTIMIZED METHOD for spatially uniform runoff
        if is_spatially_uniform:
            logging.info(f"Detected spatially uniform runoff - using optimized method for lake {lake_id}")

            # Create unit weights (1.0 everywhere except lakes, normalized)
            unit_weights = mask.astype(float)
            unit_weights_norm = unit_weights / unit_weights.sum() if unit_weights.sum() > 0 else unit_weights

            # Create unit weights raster
            unit_weights_raster = Raster(unit_weights_norm)
            unit_weights_raster.crs = geographic.crs_proj
            unit_weights_raster.nodata = geographic.nodata
            unit_weights_raster.affine = Affine(
                geographic.resolution_x, 0, geographic.xmin,
                0, geographic.resolution_y, geographic.ymax)

            # Calculate unit flow accumulation pattern ONCE
            unit_acc = grid.accumulation(direc_raster, weights=unit_weights_raster, dirmap=dirmap)
            unit_acc_array = np.array(grid.view(unit_acc))

            # Process each time step by scaling the unit accumulation pattern
            for i, t in enumerate(data_4D.time):
                if i % 25 == 0 or i == len(data_4D.time) - 1:
                    logging.info(f"Processing lake {lake_id}: step {i+1:3d}/{len(data_4D.time)} (optimized)")

                # Get total runoff for current time step
                weights = data_4D.loc[{'time': t}].copy(deep=True)
                total_runoff = weights.sum().item()

                # Scale unit accumulation by total runoff
                result_4D.loc[{'time': t}] = unit_acc_array * total_runoff

        # ---- PYSHEDS STANDARD METHOD for spatially variable runoff
        else:
            logging.info(f"Detected spatially variable runoff - using standard method for lake {lake_id}")

            # Process each time step with full accumulation calculation
            for i, t in enumerate(data_4D.time):
                logging.info(f"Processing lake {lake_id}: step {i+1:3d}/{len(data_4D.time)} (standard)")

                # Create a pysheds.raster object with runoff values
                weights = data_4D.loc[{'time': t}].copy(deep=True)

                # Skip if no runoff for this timestep
                if weights.sum().item() == 0:
                    result_4D.loc[{'time': t}] = np.zeros_like(weights.values)
                    continue

                # Runoff values are normalized into weights
                weights_norm = weights / weights.sum()  # normalize
                weights_raster = Raster(weights_norm.values)
                weights_raster.crs = geographic.crs_proj
                weights_raster.nodata = geographic.nodata
                weights_raster.affine = Affine(
                    geographic.resolution_x, 0, geographic.xmin,
                    0, geographic.resolution_y, geographic.ymax)

                # Calculate flow accumulation based on flow directions weighted by runoff values
                acc = grid.accumulation(direc_raster, weights=weights_raster, dirmap=dirmap)

                # Remove the normalization to obtain the absolute accumulated values
                acc_denorm = acc * weights.sum().item()  # denormalize
                result_4D.loc[{'time': t}] = np.array(grid.view(acc_denorm))

        # ---- POST-PROCESSING
        # Replace nan values with 0
        result_4D = result_4D.fillna(0)
        
        # ---- Export to a netcdf file in the pre-processing folder
        data_ds = result_4D.to_dataset(name='acc_runoff')
        # Attributes
        data_ds.rio.write_crs(geographic.crs_proj, inplace=True)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                        'long_name': 'x coordinate of projection',
                        'units': 'Meter'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                        'long_name': 'y coordinate of projection',
                        'units': 'Meter'}
        main_var = list(data_ds.data_vars)[0]
        data_ds[main_var].attrs = {'standard_name': 'runoff',
                                'long_name': 'surface runoff',
                                'units': units}
        data_ds.to_netcdf(os.path.join(self.data_folder, f'accumulated_runoff_{lake_id}.nc'))
        
        # ---- Extract the time series in the lake outlet cells into a pandas.Series
        # Get outlet coordinates of the current lake
        (i, j) = self.ij_outlet_by_lake[lake_id]
        data_pd = result_4D.isel(x=j, y=i)
        
        data_pd = data_pd.drop(['x', 'y']).to_dataframe(name='acc_runoff') # convert xr.dataarray to pd.dataframe
        data_pd = data_pd['acc_runoff']
        
        return data_pd
        
    #%% DISPLAY PLOT

    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)


    #%% BATHYMETRY OPTIMIZATION

    def _load_reference_table(self, path):
        """
        Load reference bathymetry table from CSV file.

        Parameters
        ----------
        path : str
            Path to CSV file

        Returns
        -------
        df : pd.DataFrame
            DataFrame with columns: elevation, volume, and optionally surface
        has_surface : bool
            True if surface column is present
        """
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(path, sep=sep)
                if df.shape[1] > 1:
                    break
            except Exception:
                continue

        df.columns = df.columns.str.lower().str.strip()

        # Find columns with flexible naming
        def find_col(colnames):
            for alias in colnames:
                if alias in df.columns:
                    return alias
            return None

        elev = find_col(["elevation", "altitude", "height", "z"])
        vol = find_col(["volume", "vol"])
        surf = find_col(["surface", "area", "surf"])

        if elev is None or vol is None:
            raise ValueError("Reference table must contain elevation and volume columns")

        # Convert string numbers with commas to float
        for col in filter(None, [elev, vol, surf]):
            df[col] = df[col].astype(str).str.replace(",", ".").astype(float)

        df = df.dropna(subset=[elev, vol]).sort_values(elev).reset_index(drop=True)
        df = df.rename(columns={elev: "elevation", vol: "volume"})

        has_surface = surf is not None
        if has_surface:
            df = df.rename(columns={surf: "surface"})

        return df, has_surface


    def _compute_volume_curve(self, dem, mask, cell_area, levels, weights=None):
        """
        Compute volume curve for given elevation levels.

        Parameters
        ----------
        dem : np.ndarray
            Digital elevation model
        mask : np.ndarray
            Boolean mask of lake area
        cell_area : float
            Area of each cell in m²
        levels : np.ndarray
            Elevation levels to evaluate
        weights : np.ndarray, optional
            Fractional coverage weights for each cell

        Returns
        -------
        volumes : np.ndarray
            Volumes at each elevation level
        """
        elev = dem[mask]
        w = weights[mask] if weights is not None else np.ones_like(elev)

        volumes = []
        for z in levels:
            depth = np.maximum(0.0, z - elev)
            volumes.append((depth * w).sum() * cell_area)

        return np.asarray(volumes, dtype=np.float64)


    def _compute_surface_curve(self, dem, mask, cell_area, levels, weights=None):
        """
        Compute surface area curve for given elevation levels.

        Parameters
        ----------
        dem : np.ndarray
            Digital elevation model
        mask : np.ndarray
            Boolean mask of lake area
        cell_area : float
            Area of each cell in m²
        levels : np.ndarray
            Elevation levels to evaluate
        weights : np.ndarray, optional
            Fractional coverage weights for each cell

        Returns
        -------
        surfaces : np.ndarray
            Surface areas at each elevation level
        """
        elev = dem[mask]
        w = weights[mask] if weights is not None else np.ones_like(elev)

        surfaces = []
        for z in levels:
            surfaces.append(w[elev < z].sum() * cell_area)

        return np.asarray(surfaces, dtype=np.float64)


    def _fit_bathymetry(self, dem, mask, cell_area, ref_df, weights, has_surface, params):
        """
        Iteratively adjust DEM to match reference volume/surface curves.

        Parameters
        ----------
        dem : np.ndarray
            Initial digital elevation model
        mask : np.ndarray
            Boolean mask of lake area
        cell_area : float
            Area of each cell in m²
        ref_df : pd.DataFrame
            Reference table with elevation, volume, and optionally surface
        weights : np.ndarray
            Fractional coverage weights for each cell
        has_surface : bool
            Whether to fit surface area in addition to volume
        params : dict
            Fitting parameters

        Returns
        -------
        fitted_dem : np.ndarray
            Adjusted DEM
        levels : np.ndarray
            Elevation levels used
        vol_fit : np.ndarray
            Final fitted volumes
        vol_ref : np.ndarray
            Reference volumes
        surf_fit : np.ndarray or None
            Final fitted surfaces (if has_surface=True)
        surf_ref : np.ndarray or None
            Reference surfaces (if has_surface=True)
        """
        # Extract parameters with defaults
        max_elev = params.get('max_elev', ref_df['elevation'].max())
        max_iter = params.get('max_iter', 80)
        step_init = params.get('step_init', 0.3)
        max_step = params.get('max_step', 1.2)
        backtrack = params.get('backtrack', 6)
        retries = params.get('retries', 3)
        rmse_stop = params.get('rmse_stop', 0.0)
        volume_weight = params.get('volume_weight', 0.5)
        surface_weight = params.get('surface_weight', 0.5)
        nodata = params.get('nodata', -9999.0)

        levels = ref_df["elevation"].to_numpy(np.float32)

        # Prepare DEM
        dem = dem.copy().astype(np.float32)
        valid = mask & np.isfinite(dem) & (dem != nodata)
        dem[valid] = np.minimum(dem[valid], max_elev)
        w_full = np.where(valid, weights.astype(np.float32), 0.0)

        # Target curves
        target_vol = ref_df["volume"].to_numpy(np.float64)
        vol_scale = target_vol.max() or 1.0

        if has_surface:
            target_surf = ref_df["surface"].to_numpy(np.float64)
            surf_scale = target_surf.max() or 1.0
        else:
            surf_scale = 1.0

        # Initial state
        vol = self._compute_volume_curve(dem, valid, cell_area, levels, w_full)
        res_vol = (vol - target_vol) / vol_scale
        rmse_vol = np.sqrt(np.mean(res_vol**2)) * vol_scale

        if has_surface:
            surf = self._compute_surface_curve(dem, valid, cell_area, levels, w_full)
            res_surf = (surf - target_surf) / surf_scale
            rmse_surf = np.sqrt(np.mean(res_surf**2)) * surf_scale
            rmse = volume_weight * rmse_vol + surface_weight * rmse_surf
            logging.info(f"[Iter 00] RMSE_vol={rmse_vol:,.0f} m³, RMSE_surf={rmse_surf:,.0f} m², Combined={rmse:,.0f}")
        else:
            rmse = rmse_vol
            logging.info(f"[Iter 00] RMSE_vol={rmse_vol:,.0f} m³")

        step = step_init
        levels_count = len(levels)

        # Iterative optimization
        for it in range(1, max_iter + 1):
            improved = False

            for _retry in range(retries + 1):
                # Compute cumulative errors
                if levels_count > 1:
                    combo = res_vol * volume_weight
                    if has_surface:
                        combo += res_surf * surface_weight
                    cumsum = np.cumsum(combo[::-1])
                    cumulative = (cumsum / np.arange(1, levels_count + 1))[::-1][1:]
                else:
                    combo = res_vol * volume_weight
                    if has_surface:
                        combo += res_surf * surface_weight
                    cumulative = np.array([combo[0]])

                # Compute adjustments per elevation bin
                adjust = np.zeros_like(dem, dtype=np.float32)
                for i in range(levels_count - 1):
                    z0, z1 = levels[i], levels[i + 1]
                    in_bin = valid & (dem >= z0) & (dem < z1)
                    area_equiv = float(w_full[in_bin].sum())

                    if area_equiv <= 0:
                        continue

                    err = cumulative[i] * vol_scale
                    delta = (step * err) / (area_equiv * cell_area + 1e-12)
                    delta = float(np.clip(delta, -max_step, max_step))

                    if delta:
                        adjust[in_bin] += delta

                # Backtracking line search
                scale = 1.0
                for _back in range(backtrack):
                    trial = dem.copy()
                    trial[valid] = np.minimum(trial[valid] + scale * adjust[valid], max_elev)

                    t_vol = self._compute_volume_curve(trial, valid, cell_area, levels, w_full)
                    t_res_vol = (t_vol - target_vol) / vol_scale
                    t_rmse_vol = np.sqrt(np.mean(t_res_vol**2)) * vol_scale

                    if has_surface:
                        t_surf = self._compute_surface_curve(trial, valid, cell_area, levels, w_full)
                        t_res_surf = (t_surf - target_surf) / surf_scale
                        t_rmse_surf = np.sqrt(np.mean(t_res_surf**2)) * surf_scale
                        t_rmse = volume_weight * t_rmse_vol + surface_weight * t_rmse_surf
                    else:
                        t_rmse = t_rmse_vol

                    if t_rmse <= rmse:
                        dem = trial
                        vol, res_vol, rmse_vol = t_vol, t_res_vol, t_rmse_vol
                        if has_surface:
                            surf, res_surf, rmse_surf = t_surf, t_res_surf, t_rmse_surf
                        rmse = t_rmse
                        improved = True
                        break

                    scale *= 0.5

                if improved:
                    if has_surface:
                        logging.info(f"[Iter {it:02d}] RMSE_vol={rmse_vol:,.0f} m³, RMSE_surf={rmse_surf:,.0f} m², Combined={rmse:,.0f} (step={step:.3f}, scale={scale:.3f})")
                    else:
                        logging.info(f"[Iter {it:02d}] RMSE_vol={rmse_vol:,.0f} m³ (step={step:.3f}, scale={scale:.3f})")
                    break

                step *= 0.5

            if not improved:
                logging.info(f"[Iter {it:02d}] No improvement - stopping")
                break

            if rmse_stop > 0 and rmse <= rmse_stop:
                logging.info("Convergence threshold reached")
                break

        final_surf = surf if has_surface else None
        return dem, levels, vol, target_vol, final_surf, target_surf if has_surface else None


    def _compute_metrics(self, sim, ref):
        """
        Compute statistical metrics between simulated and reference curves.

        Parameters
        ----------
        sim : np.ndarray
            Simulated values
        ref : np.ndarray
            Reference values

        Returns
        -------
        metrics : dict
            Dictionary with rmse, mae, rel (relative error %), and r2
        """
        res = sim - ref
        rmse = np.sqrt(np.mean(res**2))
        mae = np.mean(np.abs(res))
        rel = rmse / (np.mean(ref) or 1) * 100
        ss_res = np.sum(res**2)
        ss_tot = np.sum((ref - np.mean(ref)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot else np.nan

        return {'rmse': rmse, 'mae': mae, 'rel': rel, 'r2': r2}


#%% NOTES
