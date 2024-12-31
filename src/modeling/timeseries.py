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
import flopy
import numpy as np
import os
import pandas as pd
import sys
try:
    import imageio.v2 as imageio
except:
    import imageio
from os.path import dirname, abspath
from osgeo import gdal
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import glob
import geopandas as gpd
import flopy.utils.binaryfile as fpu

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from tools import toolbox

#%% CLASS

class Timeseries:
    """
    Extract timeseries results from rasters and shapefiles created.
    """
    
    def __init__(self,
                 geographic: object,
                 model_modflow: object,
                 model_modpath: object,
                 datetime_format: bool=True,
                 subbasin_results: bool=True,
                 intermittency_monthly:bool=False,
                 intermittency_weekly:bool=False,
                 intermittency_daily:bool=False):
        """
        Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        model_modflow : object
            MODFLOW model object.
        model_modpath : object
            MODPATH model object.
        actual_date : bool, optional
            Indicate if the model is actual time referenced with datetime. The default is True.
        subbasin_results : bool, optional
            Indicated if simulation results need to be created at subassins scale. The default is True.
        freq_time : str, optional
            Time frequency of the .csv file. The default is 'D'.
        """
        
        # Init parameters
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
        self.runoff = model_modflow.runoff
        
        self.intermittency_monthly = intermittency_monthly
        self.intermittency_weekly = intermittency_weekly
        self.intermittency_daily = intermittency_daily
        
        self.datetime_format = datetime_format
        
        ### Recharge management to initiate the .csv file results
        
        if isinstance(self.recharge,(int,float)) == True:
            time=[0]
            recharge = self.recharge
        if isinstance(self.recharge,(pd.Series)) == True:
            time = self.recharge.index
            recharge = self.recharge.values
        if isinstance(self.recharge,(dict)) == True:
            time = range(len(self.recharge))
            recharge = pd.Series(np.array(list(({k:np.nanmean(v) for k,v in self.recharge.items()}).values())), index=range(len(self.recharge)))
            
        ### Runoff management to fill the .csv file results
        if self.runoff != None:
            if isinstance(self.runoff,(int,float)) == True:
                time=[0]
                runoff = self.runoff
            if isinstance(self.runoff,(pd.Series)) == True:
                time = self.runoff.index
                runoff = self.runoff.values
            if isinstance(self.runoff,(dict)) == True:
                time = range(len(self.runoff))
                runoff = pd.Series(np.array(list(({k:np.nanmean(v) for k,v in self.runoff.items()}).values())), index=range(len(self.runoff)))
        else:
            runoff = recharge*np.nan
        
        # npy_list = [] 
        # for f in os.listdir(self.save_file):
        #      name, ext = os.path.splitext(f)
        #      if ext == '.npy':
        #          npy_list.append(name)
        
        ### Open .npy files if they exist
        
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
            self.saturated_storage = np.load(os.path.join(self.save_file, 'saturated_storage'+'.npy'), allow_pickle=True).item()
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
                self.residence_times = gpd.read_file(os.path.join(self.save_file, '_particles', type_dir+'_weighted'+'.shp'))
            except:
                self.residence_times = gpd.read_file(os.path.join(self.save_file, '_particles', type_dir+'.shp'))
                pass
                
        ### For total catchment
        dem_clip = imageio.imread(self.geographic.watershed_dem)
        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()
        self.resolution = model_modflow.resolution
        self.extract_results(dem_clip, time, recharge, runoff, self.timeseries_file)
        print('  ','Export results as timeseries')

        ### For sub-catchments
        if subbasin_results == True:
            try:
                self.zones_folder = os.path.join(self.stable_folder, 'subbasin')
                self.zones_list = os.listdir(self.zones_folder)
                for zi, zone_name in enumerate(self.zones_list):
                    sub_file = os.path.join(self.full_path, '_subbasins', zone_name)
                    if not os.path.exists(sub_file):
                        toolbox.create_folder(sub_file) 
                    try:
                        dem_clip = imageio.imread(os.path.join(self.zones_folder, zone_name, 'watershed_dem.tif'))
                        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()                        
                        self.extract_results(dem_clip, time, recharge, runoff, sub_file)
                        print('  ','Export results for subbasin'+str(zi+1))
                    except:
                        pass
            except:
                pass
    
    #%% EXTRACT DATA AT THE CATCHMENT SCLAE IN CSV
    
    def extract_results(self, dem_clip, time, recharge, runoff, timeseries_file):
        """
        Calculate catchment-scale values and save them in a data frame (.csv)..

        Parameters
        ----------
        dem_clip : 2D matrix
            Masked raster data of the model domain (watershed).
        time : DatetimeIndex or list
            Index for time.
        recharge : Series or list
            Values of recharge input.
        timeseries_file : str
            Path folder to save .csv file results.
        """
                
        def calc_max(key, data_process, target_data, mask_data, cond_symb, value_masked):
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            calc = np.nanmax(masked)
            return calc
        
        def calc_mean(key, data_process, target_data, mask_data, cond_symb, value_masked):
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            calc = np.nanmean(masked)
            return calc
        
        def calc_sum(key, data_process, target_data, mask_data, cond_symb, value_masked, resolution):
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            calc = (np.nansum(masked))
            return calc
        
        def calc_qspe(key, data_process, target_data, mask_data, cond_symb, value_masked, resolution):
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            cell = masked.count()
            calc = (np.nansum(masked) / (cell * resolution**2))
            return calc
                
        def calc_percent(key, data_process, target_data, mask_data, cond_symb, value_masked):            
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            cell = masked.count()
            count = (masked > 0).sum()
            calc = (count/cell) * 100
            return calc
        
        ### Create the initial dataframe file
        self.mfdata = pd.DataFrame({"date": time, "recharge": recharge}, index=range(len(time)))
        
        try:
            self.mfdata['runoff'] = runoff
        except:
            pass
                
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
            for key in self.saturated_storage:
                calc = calc_sum(key, 'saturated_storage', self.saturated_storage, dem_clip, '==', self.geographic.nodata, self.resolution)
                self.mfdata.loc[key,'saturated_storage'] = calc
        except:
            pass
        
        ### accumulation_flux
        try:
            for key in self.accumulation_flux:
                calc = calc_max(key, 'accumulation_flux', self.accumulation_flux, dem_clip, '==', self.geographic.nodata)  
                self.mfdata.loc[key,'accumulation_flux'] = calc
        except:
            pass
        
        ### intermittency_saturation
        if self.intermittency_monthly == True:
            try:
                if len(self.accumulation_flux)>=12:
                    inf = 0
                    sup = 12
                    step = int(round(len(self.accumulation_flux)/12))
                    compt=0            
                    for i in range(step):
                        # print('Compute intermittency: '+str(i)+' / '+str((step)))
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
        
        if self.intermittency_daily == True:
            try:
                if len(self.accumulation_flux)>=52:
                    inf = 0
                    sup = 52
                    step = int(round(len(self.accumulation_flux)/52))
                    compt=0            
                    for i in range(step):
                        # print('Compute intermittency: '+str(i)+' / '+str((step)))
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
                        # print('Compute intermittency: '+str(i)+' / '+str((step)))
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
        
        ### residence_times
        try:
            for key in ["1970-01-01"]:
                try:
                    shp_frame = gpd.read_file(self.geographic.watershed_shp)
                    self.residence_times = self.residence_times.clip(shp_frame)
                except:
                    pass
                try:
                    calc = np.nanmean(self.residence_times['time_win'])
                except:
                    calc = np.nanmean(self.residence_times['time'])
                    pass
                self.mfdata.loc[key,'residence_times'] = calc
        except:
            pass
        
        ### save files
        if self.datetime_format==True:
            self.mfdata['date'] = pd.to_datetime(time, format='%Y-%m-%d')
        self.mfdata = self.mfdata.set_index(['date'])
        self.mfdata.to_csv(timeseries_file + '/_simulated_timeseries.csv', sep=';')
        
        if timeseries_file == self.timeseries_file:
            return self.mfdata
        
#%% NOTES
