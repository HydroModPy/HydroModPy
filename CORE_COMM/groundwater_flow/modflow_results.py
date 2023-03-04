# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

# Modules
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

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from tools import toolbox

#%% CLASS

class Results:
    
    #%% INIT
    
    def __init__(self, geographic, recharge=250, runoff=25, actual_date=True, model_name='modflow_model',
                 stable_folder=os.path.join(os.path.dirname(os.getcwd()), 'results_stable'),
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'results_simulation')):
        
        self.geographic = geographic
        self.model_name = model_name
        self.stable_folder = stable_folder
        self.model_folder = model_folder
        self.actual_date = actual_date
        self.recharge = recharge
        self.runoff = runoff
       
        self.full_path = os.path.join(self.model_folder, self.model_name)
        self.save_file = os.path.join(self.full_path, '_watershed')
        toolbox.create_folder(self.save_file)
        
        # freq = pd.infer_freq(self.recharge.index)
    
        if self.actual_date==True:            
            if isinstance(self.recharge,(int,float)) == True:
                time=[0]
            else:
                time = self.recharge.index
                recharge = self.recharge.squeeze().values
                runoff = self.runoff.squeeze().values
        else:
            if isinstance(self.recharge,(int,float)) == True:
                time=[0]
                recharge = self.recharge
                runoff = self.runoff
            else:
                time = np.array(range(len(self.recharge)))
                recharge = self.recharge.squeeze().values
                runoff = self.runoff.squeeze().values
               
        npy_list = [] 
        for f in os.listdir(self.save_file):
             name, ext = os.path.splitext(f)
             if ext == '.npy':
                 npy_list.append(name)
        
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
            self.specific_discharge = np.load(os.path.join(self.save_file, 'specific_discharge'+'.npy'), allow_pickle=True).item() 
        except:
            pass
        try:
            self.accumulation_flux = np.load(os.path.join(self.save_file, 'accumulation_flux'+'.npy'), allow_pickle=True).item()
        except:
            pass  
        try:
            self.perenn_intermit_shp = sorted(glob.glob(os.path.join(self.save_file,'_surfaceflow','tracept_*.shp')), key=os.path.getmtime)
        except:
            pass
        try:
            self.groundwater_storage = np.load(os.path.join(self.save_file, 'groundwater_storage'+'.npy'), allow_pickle=True).item()
        except:
            pass 
        try:
            self.residence_times = np.load(os.path.join(self.save_file, 'residence_times'+'.npy'), allow_pickle=True).item()
        except:
            pass 
        
        subbasin = False
        dem_clip = imageio.imread(self.geographic.watershed_dem)
        self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()
        bv = gdal.Open(self.geographic.watershed_dem)
        geodata = bv.GetGeoTransform()
        self.resolution = geodata[1]
        self.extract_results(dem_clip, time, recharge, runoff, self.save_file)
       
        try:
            subbasin = True
            self.zones_folder = os.path.join(self.stable_folder, 'subbasin')
            self.zones_list = os.listdir(self.zones_folder)
            for zone_name in self.zones_list:
                  save_file = os.path.join(self.full_path, '_subbasins', zone_name)
                  toolbox.create_folder(save_file) 
                  dem_clip = imageio.imread(os.path.join(self.zones_folder, zone_name, 'watershed_dem.tif'))
                  self.cell = np.ma.masked_array(dem_clip, mask=(dem_clip<0)).count()
                  self.extract_results(dem_clip, time, recharge, runoff, save_file)
        except:
            pass
    
    #%% EXTRACT DATA AT THE CATCHMENT SCLAE IN CSV
    
    def extract_results(self, dem_clip, time, recharge, runoff, save_file):
        
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
        
        self.mfdata = pd.DataFrame({"date": time, "recharge": recharge, "runoff": runoff}, 
                                   index=range(len(time)))
        
        if self.actual_date==True:
            self.mfdata['date'] = pd.to_datetime(time, format='%Y-%m-%d')
        
        try:
            for key in self.watertable_elevation:
                calc = calc_mean(key, 'watertable_elevation', self.watertable_elevation, dem_clip, '==', -99999)
                self.mfdata.loc[key,'watertable_elevation'] = calc
        except:
            pass
        
        try:
            for key in self.watertable_depth:
                calc = calc_mean(key, 'watertable_depth', self.watertable_depth, dem_clip, '==', -99999)
                self.mfdata.loc[key,'watertable_depth'] = calc
        except:
            pass
        
        try:
            for key in self.seepage_areas:
                calc = calc_percent(key, 'seepage_areas', self.seepage_areas, dem_clip, '==', -99999)
                self.mfdata.loc[key,'seepage_areas'] = calc
        except:
            pass    
        
        try:
            for key in self.outflow_drain:
                calc = calc_sum(key, 'outflow_drain', self.outflow_drain, dem_clip, '==', -99999, self.resolution)
                self.mfdata.loc[key,'outflow_drain'] = calc
        except:
            pass
        
        try:
            for key in self.groundwater_flux:
                calc = calc_mean(key, 'groundwater_flux', self.groundwater_flux, dem_clip, '==', -99999)  
                self.mfdata.loc[key,'groundwater_flux'] = calc
        except:
            pass
        
        try:
            for key in self.specific_discharge:
                calc = calc_mean(key, 'specific_discharge', self.specific_discharge, dem_clip, '==', -99999)  
                self.mfdata.loc[key,'specific_discharge'] = calc
        except:
            pass
            
        try:
            for key in self.accumulation_flux:
                calc = calc_max(key, 'accumulation_flux', self.accumulation_flux, dem_clip, '==', -99999)  
                self.mfdata.loc[key,'accumulation_flux'] = calc
        except:
            pass
        
        try:
            for key in self.groundwater_storage:
                calc = calc_max(self.groundwater_storage[key])
                self.mfdata.loc[key,'groundwater_storage'] = calc
        except:
            pass
        
        try:
            for key in self.residence_times:
                calc = calc_max(key, 'residence_times', self.residence_times, dem_clip, '==', -99999)  
                self.mfdata.loc[key,'residence_times'] = calc
        except:
            pass
        
        try:
            for idx, key in enumerate(self.perenn_intermit_shp):
                file = gpd.read_file(key)
                surflow = ((file['Persistanc'] >= 0).sum() / self.cell) * 100
                perenn = ((file['Persistanc'] == 1).sum() / self.cell) * 100
                intermit = ((file['Persistanc'] == 0).sum() / self.cell) * 100
                self.mfdata.loc[idx,'perenn_areas'] = perenn
                self.mfdata.loc[idx,'intermit_areas'] = intermit
                self.mfdata.loc[idx,'surflow_areas'] = surflow
        except:
            pass
        
        try:            
            inf = 0
            sup = 12
            step = int(round(len(self.accumulation_flux)/12))
            compt=0
            
            for i in range(step):
                print('Intermittency: '+str(i)+' / '+str((step)))
                interv = list(self.accumulation_flux.items())[inf:sup]
                # print(interv)
                
                for key in range(len(interv)):
                    # key = tupl[0]
                    # print(key)
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
                    self.mfdata.loc[compt,'perenn_areas'] = perenn
                    self.mfdata.loc[compt,'intermit_areas'] = intermit
                    self.mfdata.loc[compt,'surflow_areas'] = surflow
                    
                    compt+=1
                    
                inf+=12
                sup+=12     
        except:
            pass

        self.mfdata = self.mfdata.set_index(['date'])
        # self.mfdata = self.mfdata.round(2)
        self.mfdata = self.mfdata.applymap(lambda x: "%.5e" % (x))
        self.mfdata.to_csv(save_file + '/_simulated_results.csv', sep=';')
        
        return self.mfdata
        
#%% NOTES

