# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 10:06:46 2022

@author: ronan
"""

# Modules
import flopy
import numpy as np
import os
import pandas as pd
import sys
import imageio
from os.path import dirname, abspath
from osgeo import gdal
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from glob import glob

import flopy.utils.binaryfile as fpu

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from tools import toolbox

#%% Extract results

class Results:
    def __init__(self, geographic, recharge=250, actual_date=True, model_name='modflow_model', start='1960-01-01', time_step='M',
                 stable_folder=os.path.join(os.path.dirname(os.getcwd()), 'results_stable'),
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'results_simulation')):
        self.geographic = geographic
        self.model_name = model_name
        self.stable_folder = stable_folder
        self.model_folder = model_folder
        self.start = start
        self.time_step = time_step
        self.actual_date = actual_date
        self.recharge = recharge
       
        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.save_file = os.path.join(self.full_path, '_watershed')
              
        bv = gdal.Open(self.geographic.watershed)
        geodata = bv.GetGeoTransform()
        self.dem = bv.GetRasterBand(1).ReadAsArray()
        self.resolution = geodata[1]
    
        if self.actual_date==True:            
            if self.time_step=='Y':
                freq = 'Y'
            if self.time_step=='M':
                freq = 'M'
            if self.time_step=='D':
                freq = 'D'
            if isinstance(self.recharge,(int,float)) == True:
                time = toolbox.date_range(self.start, 1, freq)
            else:
                time = toolbox.date_range(self.start, len(self.recharge), freq)
                recharge = self.recharge.values
        else:
            if isinstance(self.recharge,(int,float)) == True:
                time=[0]
                recharge = self.recharge
            else:
                time = np.array(range(len(self.recharge)))
                recharge = self.recharge.values
               
        npy_list = [] 
        for f in os.listdir(self.save_file):
             name, ext = os.path.splitext(f)
             if ext == '.npy':
                 npy_list.append(name)
                
        self.watertable_elevation = np.load(os.path.join(self.save_file, 'watertable_elevation'+'.npy'), allow_pickle=True).item()
        self.watertable_depth = np.load(os.path.join(self.save_file, 'watertable_depth'+'.npy'), allow_pickle=True).item()
        self.seepage_areas = np.load(os.path.join(self.save_file, 'seepage_areas'+'.npy'), allow_pickle=True).item() 
        self.outflow_drain = np.load(os.path.join(self.save_file, 'outflow_drain'+'.npy'), allow_pickle=True).item()
        self.groundwater_flux = np.load(os.path.join(self.save_file, 'groundwater_flux'+'.npy'), allow_pickle=True).item()
        self.specific_discharge = np.load(os.path.join(self.save_file, 'specific_discharge'+'.npy'), allow_pickle=True).item()
        self.accumulation_flux = np.load(os.path.join(self.save_file, 'accumulation_flux'+'.npy'), allow_pickle=True).item()
      
        dem_clip = imageio.imread(self.geographic.watershed_dem)
        self.extract_results(dem_clip, time, recharge, self.save_file)
       
        try:
            self.zones_folder = os.path.join(self.stable_folder, 'subbasin')
            self.zones_list = os.listdir(self.zones_folder)
            for zone_name in self.zones_list:
                  save_file = os.path.join(self.full_path, '_subbasins', zone_name)
                  toolbox.create_folder(save_file) 
                  dem_clip = imageio.imread(os.path.join(self.zones_folder, zone_name, 'watershed_dem.tif'))
                  self.extract_results(dem_clip, time, recharge, save_file)
        except:
            pass
    
    def extract_results(self, dem_clip, time, recharge, save_file):
        
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
            cell = masked.count()
            calc = (np.nansum(masked) / (cell * resolution**2))
            return calc
        
        def calc_percent(key, data_process, target_data, mask_data, cond_symb, value_masked):
            masked = toolbox.mask_by_dem(target_data[key], mask_data, cond_symb, value_masked)
            cell = masked.count()
            count = (masked > 0).sum()
            calc = (count/cell) * 100
            return calc   
        
        self.mfdata = pd.DataFrame({"date": time, "recharge": recharge}, index=range(len(time)))
        
        if self.actual_date==True:
            self.mfdata['date'] = pd.to_datetime(time, format='%Y-%m-%d')

        for key in self.watertable_elevation:
            calc = calc_mean(key, 'watertable_elevation', self.watertable_elevation, dem_clip, '==', -99999)
            self.mfdata.loc[key,'watertable_elevation'] = calc
            
        for key in self.watertable_depth:
            calc = calc_mean(key, 'watertable_depth', self.watertable_depth, dem_clip, '==', -99999)
            self.mfdata.loc[key,'watertable_depth'] = calc

        for key in self.seepage_areas:
            calc = calc_percent(key, 'seepage_areas', self.seepage_areas, dem_clip, '==', -99999)
            self.mfdata.loc[key,'seepage_areas'] = calc

        for key in self.outflow_drain:
            calc = calc_sum(key, 'outflow_drain', self.outflow_drain, dem_clip, '==', -99999, self.resolution)
            self.mfdata.loc[key,'outflow_drain'] = calc

        for key in self.groundwater_flux:
            calc = calc_mean(key, 'groundwater_flux', self.groundwater_flux, dem_clip, '==', -99999)  
            self.mfdata.loc[key,'groundwater_flux'] = calc
            
        for key in self.specific_discharge:
            calc = calc_mean(key, 'specific_discharge', self.specific_discharge, dem_clip, '==', -99999)  
            self.mfdata.loc[key,'specific_discharge'] = calc
            
        for key in self.accumulation_flux:
            calc = calc_max(key, 'accumulation_flux', self.accumulation_flux, dem_clip, '==', -99999)  
            self.mfdata.loc[key,'accumulation_flux'] = calc

        self.mfdata = self.mfdata.set_index(['date'])
        # self.mfdata = self.mfdata.round(2)
        self.mfdata = self.mfdata.applymap(lambda x: "%.5e" % (x))
        self.mfdata.to_csv(save_file + '/_simulated_results.csv', sep=';')

#%% Notes

# def bla (self, npy_list, zones_list):
#     for npy in npy_list:
#         x = np.load(os.path.join(self.save_file, npy+'.npy'), allow_pickle=True).item()
#         for key in x:
#             for zone in zones_list:
#                 toolbox.create_folder(os.path.join(self.simulations_folder, '_zones', zone)) 
#                 dem_clip = imageio.imread(os.path.join(self.zones_folder, zone, 'watershed_dem.tif'))
#                 masked = toolbox.mask_by_dem(x[key], dem_clip, '==', -99999)
#                 calc = np.nanmean(masked)
#                 return key, calc

#%% Compare obs
"""
    def compar_discharge_chronic(self):
                
        ### OBSERVED DISCHARGE
        
        chronic_path = os.path.join(self.hydrology_path, 'chronics')        
        obs_files = os.listdir(chronic_path)
        
        if (self.outlet_type=='hydrometric'):
            # Waterhed
            basin_area = tif_features.basin_area(self.dem_clip, self.dem_clip, '==', -99999, self.resolution)
            obs_file = [x for x in obs_files if x.split('_')[3] == self.watershed_name]
            obs_file = obs_file[0]
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';')
        
        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'hydrometric']
            for mask_name in mask_list:
                x=2
                subasin_folder = os.path.join(self.subbasins_folder, mask_name)
                sub = gdal.Open(os.path.join(subasin_folder,'subbasin.tif'))
                dem_mask = sub.GetRasterBand(1).ReadAsArray()
                basin_area = tif_features.basin_area(dem_mask, dem_mask, '!=', 1, self.resolution)
                station_name = mask_name.split('_')[3]
                for x in obs_files:
                    try:
                        cond_split = x.split('_')[2]
                    except:
                        continue
                    if cond_split == station_name:
                        obs_file = x
                # obs_file = obs_file[0]
        
        print(obs_file)
        obs_path = os.path.join(chronic_path, obs_file)
        obs_data = pd.read_csv(obs_path, names = ['year','month','day','disch'], 
                               sep='\s+', header = None, parse_dates=True) # sep='\s+'
        time = pd.to_datetime(obs_data[['year','month','day']]) # create datetime
        time = time.sort_values()
        obs = pd.Series(obs_data['disch']) # create series discharge
        obs = obs*24*60*60 #m3/j
        obs_data = pd.DataFrame({'date':time, 'disch':obs}) # dataframe
        obs_data['disch_norm'] = obs_data['disch'] / (60 * 1000000) # m/j ==> area to add
        obs_data = obs_data.set_index('date')
        
        if self.time_step=='monthly':
            obs_data = obs_data.resample('M').sum()
        
        obs = np.array(obs_data['disch_norm'].values)
        
        ### SIMULATED DISCHARGE  
        
        if (self.outlet_type=='hydrometric'):
            # Waterhed
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
            sim_data = sim_data.set_index('date')
            sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
            
            sim = np.array(sim_data['outflow_drain'].values)
            
            df_stats = pd.DataFrame(columns=['RMSE', 'nRMSE', 'NSE', 'NSElog', 'BAL', 'MARE', 'KGE'])
            try:
                list_stats = serie_transf.efficiency_criteria(sim, obs)
            except:
                print('list_stats = None')            
            df_stats = df.append(list_stats)
            df_stats.to_csv(os.path.join(self.save_file, '_efficiency_criteria.csv'), sep=';')
            
        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'hydrometric']
            for mask_name in mask_list:
                masked_file = os.path.join(self.masked_folder, mask_name)
                sim_path = os.path.join(masked_file, '_simulated_chronics.csv')
                sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
                sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
                sim_data = sim_data.set_index('date')
                
                sim = np.array(sim_data['outflow_drain'].values)
                
                df_stats = pd.DataFrame(columns=['RMSE', 'nRMSE', 'NSE', 'NSElog', 'BAL', 'MARE', 'KGE'])
                try:
                    list_stats = serie_transf.efficiency_criteria(sim, obs)
                except:
                    print('list_stats = None')
                    list_stats = None
                df_stats.loc[len(df_stats)] = list_stats
                df_stats.to_csv(os.path.join(masked_file, '_efficiency_criteria.csv'), sep=';')

                return obs_data, sim_data, df_stats, mask_name
                
    def compar_saturation_chronic(self):
        
        obs_data = np.nan
        df_stats = np.nan
        
        ### SIMULATED SATURATION
        
        if (self.outlet_type=='onde'):
            # Waterhed
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
            sim_data = sim_data.set_index('date')
            sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
            
            sim = np.array(sim_data['seepage_areas'].values)

        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'onde']
            for mask_name in mask_list:
                masked_file = os.path.join(self.masked_folder, mask_name)
                sim_path = os.path.join(masked_file, '_simulated_chronics.csv')
                sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
                sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
                sim_data = sim_data.set_index('date')
                
                sim = np.array(sim_data['seepage_areas'].values)
                
                fig, ax = plt.subplots(1,1, figsize=(5,3))
                ax.plot(sim_data['seepage_areas'], color='red')
                ax.axhline(y=3, color='k', ls='--')
                ax.axhline(y=8, color='grey', ls='--')
                ax.set_ylim(-0.5, 25)
                ax.set_xlabel('Date')
                ax.set_ylabel('Saturation [%]')
                # ax.set_title(mask_name+'\n'+self.model_name)
                ax.set_title(mask_name.split('_')[3])
                ax.grid(True)
                yearsFmt = DateFormatter('%Y')
                ax.xaxis.set_major_formatter(yearsFmt)
                
            return obs_data, sim_data, df_stats, mask_name
"""