# -*- coding: utf-8 -*-
"""Time-series post-processing utilities for HydroModPy outputs.

This module reads the raster and vector products generated in the
``_postprocess`` tree of a simulation and converts them into CSV tables that
summarize the temporal evolution of the model at catchment scale. When
subbasins are available, the same aggregation is repeated for each one.

The class is report-oriented: it does not compute raw model results itself.
Instead, it loads arrays already written by earlier post-processing steps
(water table, seepage, drainage, particle tracking, and optional transport
products) and applies spatial reductions before export.

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
import rasterio
from os.path import dirname, abspath
import geopandas as gpd
import warnings

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger

#%% CLASS

logger = get_logger(__name__)
# Silence pandas masked-to-nan spam when handling masked arrays
warnings.filterwarnings("ignore", message=".*converting a masked element to nan.*")


class Timeseries:
    """Aggregate post-processed outputs into exported time-series tables.

    Instantiating this class immediately:

    1. locates and loads any available ``.npy`` grids and particle shapefiles,
    2. computes catchment-level summary metrics,
    3. optionally repeats the extraction for each configured subbasin,
    4. writes one CSV file per aggregation target.

    The constructor is intentionally side-effectful: object creation triggers
    the export workflow.
    """

    def __init__(self,
                 geographic: object,
                 model_modflow: object,
                 runoff=None,
                 model_modpath: int=None,
                 model_mt3dms: int=None,
                 suffix_name: int=None,
                 datetime_format: bool=True,
                 subbasin_results: bool=True,
                 intermittency_yearly:bool=False,
                 intermittency_monthly: bool=False,
                 intermittency_weekly: bool=False,
                 intermittency_daily: bool=False,
                 residence_times: bool=False,
                 concentration_seepage: bool=False,
                 mass_accumulated: bool=False):
        """Load available products and export time-series CSV files.

        Parameters
        ----------
        geographic : object
            Watershed description used for masks, DEM access, and optional
            subbasin discovery.
        model_modflow : object
            Flow model object providing the model name, output folder,
            recharge, and spatial resolution.
        runoff : float, pandas.Series, dict or None, optional
            Optional runoff forcing mirrored into the exported table. Scalars
            are treated as a single-step value, while dictionaries are reduced
            to one average per time step.
        model_modpath : object, optional
            Particle tracking model. When provided, residence-time metrics can
            be computed from the stored particle shapefile.
        model_mt3dms : object, optional
            Transport model. When provided, transport-related arrays are loaded
            if they exist in ``_postprocess``.
        suffix_name : str or None, optional
            Optional suffix appended to the exported CSV file name.
        datetime_format : bool, optional
            If ``True``, attempt to parse the time index as ``YYYY-mm-dd``
            dates before exporting. Otherwise, keep a numeric index.
        subbasin_results : bool, optional
            If ``True``, export one additional CSV per subbasin found in the
            stable workspace.
        intermittency_yearly : bool, optional
            Compute yearly perennial/intermittent area indicators from
            ``accumulation_flux``.
        intermittency_monthly : bool, optional
            Compute monthly perennial/intermittent area indicators from
            ``accumulation_flux``.
        intermittency_weekly : bool, optional
            Compute weekly perennial/intermittent area indicators from
            ``accumulation_flux``.
        intermittency_daily : bool, optional
            Compute daily perennial/intermittent area indicators from
            ``accumulation_flux``.
        residence_times : bool, optional
            If ``True``, export the mean residence time from particle tracking
            outputs.
        concentration_seepage : bool, optional
            Compatibility flag for workflows that expect seepage concentration
            reporting.
        mass_accumulated : bool, optional
            Compatibility flag for workflows that expect accumulated-mass
            reporting.

        Notes
        -----
        The constructor performs the full extraction immediately. It prepares
        the output folders, loads every available intermediate product, and
        writes CSV files as a side effect.
        """

        # Init parameters
        self.suffix_name = suffix_name

        self.geographic = geographic

        self.stable_folder = geographic.stable_folder
        self.simulations = geographic.simulations_folder

        self.model_name = model_modflow.model_name
        self.model_folder = model_modflow.model_folder

        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.tifs_file = os.path.join(self.full_path, '_postprocess', '_rasters')

        self.save_file = os.path.join(self.full_path, '_postprocess')
        if not os.path.exists(self.save_file):
            toolbox.create_folder(self.save_file)

        self.timeseries_file = os.path.join(self.save_file, '_timeseries')
        if not os.path.exists(self.timeseries_file):
            toolbox.create_folder(self.timeseries_file)

        self.recharge = model_modflow.recharge
        self.runoff = runoff

        self.intermittency_yearly = intermittency_yearly
        self.intermittency_monthly = intermittency_monthly
        self.intermittency_weekly = intermittency_weekly
        self.intermittency_daily = intermittency_daily

        self.residence_times = residence_times

        self.concentration_seepage = concentration_seepage
        self.mass_acumulated = mass_accumulated

        self.datetime_format = datetime_format

        # Normalize recharge so the exported table always starts from a
        # consistent time index and one value per time step.
        if isinstance(self.recharge,(int,float)) == True:
            time=[0]
            recharge = self.recharge
        if isinstance(self.recharge,(pd.Series)) == True:
            time = self.recharge.index
            recharge = self.recharge.values
        if isinstance(self.recharge,(dict)) == True:
            time = range(len(self.recharge))
            recharge = pd.Series(np.array(list(({k:np.nanmean(v) for k,v in self.recharge.items()}).values())), index=range(len(self.recharge)))

        # Normalize optional runoff with the same conventions as recharge.
        if self.runoff is not None and (not isinstance(self.runoff, pd.DataFrame) or not self.runoff.empty):
            if isinstance(self.runoff, (int, float)):
                time = [0]
                runoff = self.runoff
            elif isinstance(self.runoff, pd.Series):
                time = self.runoff.index
                runoff = self.runoff.values
            elif isinstance(self.runoff, dict):
                time = range(len(self.runoff))
                runoff = pd.Series(
                    np.array([np.nanmean(v) for v in self.runoff.values()]),
                    index=range(len(self.runoff))
                )
        else:
            runoff = recharge * np.nan

        # npy_list = []
        # for f in os.listdir(self.save_file):
        #      name, ext = os.path.splitext(f)
        #      if ext == '.npy':
        #          npy_list.append(name)

        # Load every post-processed grid opportunistically. Missing products are
        # expected for some workflows, so failures are ignored.

        try:
            self.watertable_elevation = np.load(os.path.join(self.save_file, 'watertable_elevation'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.watertable_depth = np.load(os.path.join(self.save_file, 'watertable_depth'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.seepage_areas = np.load(os.path.join(self.save_file, 'seepage_areas'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.outflow_drain = np.load(os.path.join(self.save_file, 'outflow_drain'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.groundwater_flux = np.load(os.path.join(self.save_file, 'groundwater_flux'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.groundwater_storage = np.load(os.path.join(self.save_file, 'groundwater_storage'+'.npy'), allow_pickle=True).item()
        except:
            pass
        try:
            self.accumulation_flux = np.load(os.path.join(self.save_file, 'accumulation_flux'+'.npy'), allow_pickle=True).item()
        except:
            pass
        if model_modpath != None:
            if model_modpath.track_dir == 'forward':
                type_dir = 'ending'
            else:
                type_dir = 'starting'
            try:
                self.shp_particles = gpd.read_file(os.path.join(self.save_file, '_particles', type_dir+'_weighted'+'.shp'))
            except:
                self.shp_particles = gpd.read_file(os.path.join(self.save_file, '_particles', type_dir+'.shp'))
                pass
        if model_mt3dms != None:
            try:
                self.concentration_seepage = np.load(os.path.join(self.save_file, 'concentration_seepage'+'.npy'), allow_pickle=True).item()
            except:
                pass
            try:
                self.mass_accumulated = np.load(os.path.join(self.save_file, 'mass_accumulated'+'.npy'), allow_pickle=True).item()
            except:
                pass

        # Export the main watershed summary first.
        with rasterio.open(self.geographic.watershed_dem) as src:
            dem_clip = src.read(1)

        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()
        self.resolution = model_modflow.resolution
        self.extract_results(dem_clip, time, recharge, runoff, self.timeseries_file)
        logger.info("Exported catchment time series to %s", self.timeseries_file)

        # Repeat the same extraction for each available subbasin mask.
        if subbasin_results == True:
            try:
                self.zones_folder = os.path.join(self.stable_folder, 'subbasin')
                self.zones_list = os.listdir(self.zones_folder)
                for zi, zone_name in enumerate(self.zones_list):
                    sub_file = os.path.join(self.full_path, '_subbasins', zone_name)
                    if not os.path.exists(sub_file):
                        toolbox.create_folder(sub_file)
                    try:
                        with rasterio.open(os.path.join(self.zones_folder, zone_name, 'watershed_dem.tif')) as src:
                            dem_clip = src.read(1)
                        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()
                        self.extract_results(dem_clip, time, recharge, runoff, sub_file)
                        logger.info("Exported time series for subbasin %s to %s", zi + 1, sub_file)
                    except:
                        pass
            except:
                pass

    #%% EXTRACT DATA AT THE CATCHMENT SCALE IN CSV

    def extract_results(self, dem_clip, time, recharge, runoff, timeseries_file):
        """Aggregate loaded products over one spatial mask and export them.

        Parameters
        ----------
        dem_clip : numpy.ndarray
            DEM raster used as the spatial support and mask for the aggregation
            target (either the full watershed or one subbasin).
        time : pandas.DatetimeIndex or list
            Time axis copied to the exported table.
        recharge : pandas.Series, numpy.ndarray or list
            Recharge values mirrored into the exported table.
        runoff : pandas.Series, numpy.ndarray, scalar or list
            Optional runoff values mirrored into the exported table.
        timeseries_file : str
            Output folder receiving the generated CSV file.

        Returns
        -------
        pandas.DataFrame or None
            The catchment-scale data frame when exporting the main watershed,
            otherwise ``None`` for subbasin exports.

        Notes
        -----
        The nested helpers below all follow the same contract: apply the DEM
        mask to a stored grid, then reduce it with a metric suited to the
        variable being exported (mean, sum, max, specific discharge, or
        percentage of active cells).
        """

        def calc_max(key, data_process, target_data, mask_data, cond_symb, value_masked):
            """Return the maximum value of one masked grid."""
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            calc = np.nanmax(masked)
            return calc

        def calc_mean(key, data_process, target_data, mask_data, cond_symb, value_masked):
            """Return the mean value of one masked grid."""
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            masked[masked<0] = 0 ### ATTENTION
            masked[masked<-1] = np.nan ### ATTENTION
            calc = np.nanmean(masked)
            return calc

        def calc_sum(key, data_process, target_data, mask_data, cond_symb, value_masked, resolution):
            """Return the spatial sum of one masked grid."""
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            calc = (np.nansum(masked))
            return calc

        def calc_qspe(key, data_process, target_data, mask_data, cond_symb, value_masked, resolution):
            """Return the area-normalized sum of one masked grid."""
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            cell = masked.count()
            calc = (np.nansum(masked) / (cell * resolution**2))
            return calc

        def calc_percent(key, data_process, target_data, mask_data, cond_symb, value_masked):
            """Return the percentage of active cells in one masked grid."""
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            cell = masked.count()
            count = (masked > 0).sum()
            calc = (count/cell) * 100
            return calc

        # Seed the exported table with the forcing series so every later metric
        # aligns on the same index.
        self.mfdata = pd.DataFrame({"date": time, "recharge": recharge}, index=range(len(time)))

        try:
            self.mfdata['runoff'] = runoff
        except:
            pass

        # Append one column per available post-processed product.
        ### watertable_elevation
        try:
            for key in self.watertable_elevation:
                calc = calc_mean(key, 'watertable_elevation', self.watertable_elevation, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'watertable_elevation'] = calc
        except:
            pass

        ### watertable_depth
        try:
            for key in self.watertable_depth:
                calc = calc_mean(key, 'watertable_depth', self.watertable_depth, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'watertable_depth'] = calc
        except:
            pass

        ### seepage_areas
        try:
            for key in self.seepage_areas:
                calc = calc_percent(key, 'seepage_areas', self.seepage_areas, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'seepage_areas'] = calc
        except:
            pass

        ### outflow_drain
        try:
            for key in self.outflow_drain:
                calc = calc_qspe(key, 'outflow_drain', self.outflow_drain, dem_clip, '==', self.geographic.nodata, self.resolution)
                self.mfdata.loc[key,'outflow_drain'] = calc
        except:
            pass

        ### groundwater_flux
        try:
            for key in self.groundwater_flux:
                calc = calc_mean(key, 'groundwater_flux', self.groundwater_flux, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'groundwater_flux'] = calc
        except:
            pass

        ### groundwater_storage
        try:
            for key in self.groundwater_storage:
                calc = calc_sum(key, 'groundwater_storage', self.groundwater_storage, dem_clip, '==', self.geographic.nodata, self.resolution)
                self.mfdata.loc[key,'groundwater_storage'] = calc
        except:
            pass

        ### accumulation_flux
        try:
            for key in self.accumulation_flux:
                calc = calc_max(key, 'accumulation_flux', self.accumulation_flux, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'accumulation_flux'] = calc
        except:
            pass

        ### concentration_seepage
        try:
            for key in self.concentration_seepage:
                calc = calc_mean(key, 'concentration_seepage', self.concentration_seepage, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'concentration_seepage'] = calc
        except:
            pass

        ### mass_accumualted
        try:
            for key in self.mass_accumulated:
                calc = calc_max(key, 'mass_accumulated', self.mass_accumulated, dem_clip, '==', self.geographic.nodata)
                self.mfdata.loc[key,'mass_accumulated'] = calc
        except:
            pass

        # Intermittency modes classify wetted cells over fixed temporal blocks.
        ### intermittency_saturation
        if self.intermittency_yearly == True:
            try:
                if len(self.accumulation_flux)>=1:
                    inf = 0
                    sup = 1
                    step = int(round(len(self.accumulation_flux)/1))
                    compt=0
                    for i in range(step):
                        logger.debug('Computing yearly intermittency: %d / %d', i, step)
                        interv = list(self.accumulation_flux.items())[inf:sup]
                        for key in range(len(interv)):
                            mask = dem_clip.copy()
                            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                        zero = self.accumulation_flux[0] * 0
                        for j in range(len(interv)):
                            tempo = interv[j].copy()
                            tempo[tempo>0] = 1
                            zero = zero + tempo
                        days_flux = zero.copy()
                        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                        for k in range(len(interv)):
                            tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                            tempo[days_flux<1] = 0
                            tempo[days_flux==1] = 1
                            tempo = np.ma.masked_where(interv[k]<=0, tempo)
                            surflow = (((tempo >= 0).sum()) / self.cell) * 100
                            perenn = (((tempo == 1).sum()) / self.cell) * 100
                            intermit = (((tempo == 0).sum()) / self.cell) * 100
                            self.mfdata.loc[compt,'total_areas'] = surflow
                            self.mfdata.loc[compt,'perenn_areas'] = perenn
                            self.mfdata.loc[compt,'intermit_areas'] = intermit
                            compt+=1
                        inf+=1
                        sup+=1
            except:
                pass

        # The monthly mode follows the same logic with 12-step windows.
        ### intermittency_saturation
        if self.intermittency_monthly == True:
            try:
                if len(self.accumulation_flux)>=12:
                    inf = 0
                    sup = 12
                    step = int(round(len(self.accumulation_flux)/12))
                    compt=0
                    for i in range(step):
                        logger.debug('Computing monthly intermittency: %d / %d', i, step)
                        interv = list(self.accumulation_flux.items())[inf:sup]
                        for key in range(len(interv)):
                            mask = dem_clip.copy()
                            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                        zero = self.accumulation_flux[0] * 0
                        for j in range(len(interv)):
                            tempo = interv[j].copy()
                            tempo[tempo>0] = 1
                            zero = zero + tempo
                        days_flux = zero.copy()
                        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                        for k in range(len(interv)):
                            tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                            tempo[days_flux<12] = 0
                            tempo[days_flux==12] = 1
                            tempo = np.ma.masked_where(interv[k]<=0, tempo)
                            surflow = (((tempo >= 0).sum()) / self.cell) * 100
                            perenn = (((tempo == 1).sum()) / self.cell) * 100
                            intermit = (((tempo == 0).sum()) / self.cell) * 100
                            self.mfdata.loc[compt,'total_areas'] = surflow
                            self.mfdata.loc[compt,'perenn_areas'] = perenn
                            self.mfdata.loc[compt,'intermit_areas'] = intermit
                            compt+=1
                        inf+=12
                        sup+=12
            except:
                pass

        if self.intermittency_weekly == True:
            try:
                if len(self.accumulation_flux)>=52:
                    inf = 0
                    sup = 52
                    step = int(round(len(self.accumulation_flux)/52))
                    compt=0
                    for i in range(step):
                        logger.debug('Computing weekly intermittency: %d / %d', i, step)
                        interv = list(self.accumulation_flux.items())[inf:sup]
                        for key in range(len(interv)):
                            mask = dem_clip.copy()
                            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                        zero = self.accumulation_flux[0] * 0
                        for j in range(len(interv)):
                            tempo = interv[j].copy()
                            tempo[tempo>0] = 1
                            zero = zero + tempo
                        days_flux = zero.copy()
                        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                        for k in range(len(interv)):
                            tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                            tempo[days_flux<52] = 0
                            tempo[days_flux==52] = 1
                            tempo = np.ma.masked_where(interv[k]<=0, tempo)
                            surflow = (((tempo >= 0).sum()) / self.cell) * 100
                            perenn = (((tempo == 1).sum()) / self.cell) * 100
                            intermit = (((tempo == 0).sum()) / self.cell) * 100
                            self.mfdata.loc[compt,'total_areas'] = surflow
                            self.mfdata.loc[compt,'perenn_areas'] = perenn
                            self.mfdata.loc[compt,'intermit_areas'] = intermit
                            compt+=1
                        inf+=52
                        sup+=52
            except:
                pass

        if self.intermittency_daily == True:
            try:
                if len(self.accumulation_flux)>=365:
                    inf = 0
                    sup = 365
                    step = int(round(len(self.accumulation_flux)/365))
                    compt=0
                    for i in range(step):
                        logger.debug('Computing daily intermittency: %d / %d', i, step)
                        interv = list(self.accumulation_flux.items())[inf:sup]
                        for key in range(len(interv)):
                            mask = dem_clip.copy()
                            interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                        zero = self.accumulation_flux[0] * 0
                        for j in range(len(interv)):
                            tempo = interv[j].copy()
                            tempo[tempo>0] = 1
                            zero = zero + tempo
                        days_flux = zero.copy()
                        days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                        days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
                        for k in range(len(interv)):
                            tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                            tempo[days_flux<365] = 0
                            tempo[days_flux==365] = 1
                            tempo = np.ma.masked_where(interv[k]<=0, tempo)
                            surflow = (((tempo >= 0).sum()) / self.cell) * 100
                            perenn = (((tempo == 1).sum()) / self.cell) * 100
                            intermit = (((tempo == 0).sum()) / self.cell) * 100
                            self.mfdata.loc[compt,'total_areas'] = surflow
                            self.mfdata.loc[compt,'perenn_areas'] = perenn
                            self.mfdata.loc[compt,'intermit_areas'] = intermit
                            compt+=1
                        inf+=365
                        sup+=365
            except:
                pass

        # Residence time is a scalar summary derived from the particle shapefile.
        ### residence_times
        if self.residence_times == True:
            try:
                for key in [0]:
                    try:
                        shp_frame = gpd.read_file(self.geographic.watershed_shp)
                        self.shp_particles = self.shp_particles.clip(shp_frame)
                    except:
                        pass
                    try:
                        calc = np.nanmean(self.shp_particles['time_win'])
                    except:
                        calc = np.nanmean(self.shp_particles['time'])
                        pass
                    self.mfdata.loc[key,'residence_times'] = calc
            except:
                pass

        # Finalize index formatting and write the CSV file for this mask.
        ### save files
        if self.datetime_format==True:
            try:
                self.mfdata['date'] = pd.to_datetime(time, format='%Y-%m-%d')
            except:
                self.mfdata['date'] = np.arange(0,len(self.mfdata),1)
                pass
        self.mfdata = self.mfdata.set_index(['date'])
        if self.suffix_name == None:
            self.mfdata.to_csv(timeseries_file + '/_simulated_timeseries.csv', sep=';')
        else:
            self.mfdata.to_csv(timeseries_file + '/_simulated_timeseries'+'_'+self.suffix_name+'.csv', sep=';')

        if timeseries_file == self.timeseries_file:
            return self.mfdata

#%% NOTES
