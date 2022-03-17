# -*- coding: utf-8 -*-
"""
Created on Fri Nov 12 10:57:47 2021

@author: Alexandre Gauvain
"""
#Modules
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os, sys
import glob
import hydroeval as he
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
#HydroModPy tools
from tools import toolbox

class Streams:
    def __init__(self, 
                 watershed, 
                 hydrology_stable=None,
                 calibration_folder=None):
        
        self.geographic = watershed.geographic
        self.hydrology = watershed.hydrology
        self.calibration_folder = calibration_folder
        
        self.results_folder=os.path.join(self.calibration_folder, '_watershed')
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        
    def prepare_files(self):
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, '_streams')
        toolbox.create_folder(self.dichotomy_folder)
        # Observed buff data
        self.buff_tif_obs = self.hydrology.tif_streams
        self.buff_pt_obs = self.hydrology.streams
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, True)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)  
        # Mask seepage simulation
        tif_sim = os.path.join(self.results_folder,'_tifs', 'seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, True)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
       
    def sim_to_obs(self):
        # Distance of sim
        self.dist_sim_obs = os.path.join(self.dichotomy_folder, 'dist_sim_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_sim_obs)        
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)        
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)        
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)       
        # Extra
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_sim_obs, self.pt_sim_flow)
    
    def obs_to_sim(self):
        # Distance of sim
        self.dist_obs_sim = os.path.join(self.dichotomy_folder, 'dist_obs_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_obs_sim)   
        # Obsflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        # Extra
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_obs_sim, self.pt_obs_flow)

    def get_indicator(self):
        obs_to_sim = gpd.read_file(self.pt_obs_flow)
        obs_to_sim = obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        obs_to_sim = obs_to_sim[obs_to_sim['distance'] >= 0]
        self.mean_obs_to_sim = np.nanmean(obs_to_sim['distance'])
        sim_to_obs = gpd.read_file(self.pt_sim_flow)
        sim_to_obs = sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        sim_to_obs = sim_to_obs[sim_to_obs['distance'] >= 0]
        self.mean_sim_to_obs = np.nanmean(sim_to_obs['distance'])
        
        indicator = (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
        return indicator, self.mean_obs_to_sim, self.mean_sim_to_obs

class Piezometry:
    def __init__(self, watershed, model, param_folder):
        self.watershed = watershed
        self.model = model
        self.param_folder = param_folder
        
        self.load_modeling_data()
        self.compare_sim_obs_data()
    
    def load_modeling_data(self):
        self.watertable_elevation = np.load(os.path.join(self.param_folder, self.model ,'_watershed', 'watertable_elevation.npy'), allow_pickle=True).item()
        
    def compare_sim_obs_data(self):
        self.store_indicator = []
        if isinstance(self.watershed.forcing.recharge, float) == False:
            try:
                # df = self.watershed.piezometry.elevation.resample(self.watershed.forcing.freq).mean()
                df = self.watershed.piezometry.elevation.resample(pd.infer_freq(self.watershed.forcing.recharge.index)).mean()
                #df.index = df.index.to_period(self.watershed.forcing.freq)
            except:
                sys.exit('watershed.forcing.recharge must be a chronicle Dataframe with date as index.')
            
            # Continue Data
            for j in range(0,len(self.watershed.piezometry.codes_bss)):
                sim=[]
                for i in range(0,len(self.watertable_elevation)):
                    sim.append(self.watertable_elevation[i][self.watershed.piezometry.y_iloc[j],self.watershed.piezometry.x_iloc[j]])
                df_sim = pd.Series(sim, index=self.watershed.forcing.recharge.index, name='sim_' + self.watershed.piezometry.codes_bss[j])
                df = df.merge(df_sim, left_index=True, right_index=True)
                    
                y0 = df[self.watershed.piezometry.codes_bss[j]].values
                y1 = df['sim_' + self.watershed.piezometry.codes_bss[j]].values
                
                #if j == 0:
                    #fig, ax = plt.subplots()
                    #df[self.watershed.piezometry.codes_bss[j]].plot(ax=ax)
                    #df['sim_' + self.watershed.piezometry.codes_bss[j]].plot(ax=ax)
                #plt.plot(y0,y0-y1)

                ER = np.nansum(y0-y1)  # error 
                ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
                RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
                PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
                MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error 
                BAL = (np.sum(y1)/np.sum(y0))*100 # balance
                MSE = np.nanmean((y0-y1)**2) # mean square error 
                RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
                NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency                               
                MARE = he.evaluator(he.mare, y1, y0)[0] # mean absolute relative error 
                KGE = he.evaluator(he.kge, y1, y0)[0][0] # kling-gupta efficiency (r, α, β)
                PBIAS  = he.evaluator(he.pbias, y1, y0)[0] # percent bias
                NSElog = he.evaluator(he.nse, y1, y0, transform='log')[0] # nash–sutcliffe efficiency log

                self.store_indicator.append(RMSE)
                            
            self.y0 = df[[col for col in df if not col.startswith('sim_')]]
            self.y1 = df[[col for col in df if col.startswith('sim_')]]
            
            #Discrete Data
            y0 = []
            y1 = []
            for j in range(0,len(self.watershed.piezometry.elevation_discrete)):
                y0.append(self.watershed.piezometry.elevation_discrete[j])
                date = self.watershed.piezometry.date_discrete[j]
                dt = pd.to_datetime(date)
                sim = []
                for i in range(0,len(self.watertable_elevation)):
                    sim.append(self.watertable_elevation[i][self.watershed.piezometry.y_iloc_discrete[j],self.watershed.piezometry.x_iloc_discrete[j]])
                df_sim = pd.Series(sim, index=self.watershed.forcing.recharge.index, name='sim' )
                y1.append(df_sim[df_sim.index.month == dt.month].mean())
            RMSE = np.sqrt(np.nanmean((np.asarray(y0)-np.asarray(y1))**2))
            self.store_indicator.append(RMSE)
                
        if isinstance(self.watershed.forcing.recharge, float) == True:
            self.y0 = self.watershed.piezometry.elevation.mean().values.tolist()
            self.y1 = []
            for j in range(0,len(self.watershed.piezometry.codes_bss)):
                self.y1.append(self.watertable_elevation[0][self.watershed.piezometry.y_iloc[j],self.watershed.piezometry.x_iloc[j]])
            for j in range(0,len(self.watershed.piezometry.elevation_discrete)):
                self.y0.append(self.watershed.piezometry.elevation_discrete[j])
                self.y1.append(self.watertable_elevation[0][self.watershed.piezometry.y_iloc_discrete[j],self.watershed.piezometry.x_iloc_discrete[j]])
            self.y0 = np.array(self.y0)
            self.y1 = np.array(self.y1)
            '''
            dy = np.nansum(self.y0-self.y1)  #error 
            abs_dy = np.nansum(np.abs(self.y0-self.y1))  #absolute error 
            relerr = np.nansum(np.abs(self.y0-self.y1)/self.y0) #relative error 
            pererr = np.nansum(np.abs(self.y0-self.y1)/self.y0*100) #percentage error 
            mean_err = np.nanmean(np.abs(self.y0-self.y1)) #mean absolute error 
            MSE = np.nanmean((self.y0-self.y1)**2) ;    #Mean square error '''
            RMSE = np.sqrt(np.nanmean((self.y0-self.y1)**2))  #Root mean square error 
            self.store_indicator.append(RMSE)
            
    def get_indicator(self):
        indicator = np.nanmean(self.store_indicator)
        return indicator, self.y0, self.y1
    
class Hydrometry:
    def __init__(self, watershed, model, param_folder):
        self.watershed = watershed
        self.model = model
        self.param_folder = param_folder
        
        self.load_modeling_data()
        self.compare_sim_obs_data()
    
    def load_modeling_data(self):
        sim_path = os.path.join(self.param_folder, self.model, '_watershed', '_simulated_results.csv')
        sim = pd.read_csv(sim_path, sep=';', parse_dates=True, index_col=0)
        self.outflow_drain = sim.outflow_drain
        # add successive subbasins
        
    def compare_sim_obs_data(self):
        self.store_indicator = []
        indicator_path = os.path.join(self.param_folder, self.model, '_watershed', '_listing_indicator.csv')
        if not os.path.exists(indicator_path):
            self.listing_indicator = pd.DataFrame(columns=
                                                  ['ER','ABSER','RELER','PERER',
                                                   'MAE','BAL','MSE','RMSE','MARE',
                                                   'KGE','PBIAS','NSE','NSElog'])
        else:
            self.listing_indicator = pd.read_csv(indicator_path, sep=';')
            self.listing_indicator = self.listing_indicator.iloc[: , 1:]
            
        if len(self.watershed.forcing.recharge) > 1:
            c_path = os.path.join(self.watershed.stable_folder, 'hydrometry')
            codes_path = glob.glob(os.path.join(c_path, 'Hydrometric_*'))
            # codes = os.listdir(c_path)
            codes = []
            for i in os.listdir(c_path):
                if os.path.isfile(os.path.join(c_path,i)) and 'Hydrometric_' in i:
                    codes.append(i)
            if codes != []:
                for j in range(0,len(codes)):
                    code = codes[j].split('_')[1]
                    area = float(codes[j].split('_')[4])
                    
                    df = pd.read_csv(codes_path[j], sep=';', parse_dates=True, index_col=0)
                    df = df.resample('M').mean()
                    df = df * 24 * 3600 # m3/j
                    df = df / (area * 1000000) # m/j
                    df.columns = [code]
                    
                    df_runoff = self.watershed.forcing.runoff.values
                    
                    df_sim = self.outflow_drain.copy()
                    df_sim = df_sim.rename('sim_' + code)
                    df_sim = df_sim + df_runoff
                    
                    df = df.merge(df_sim, left_index=True, right_index=True)
    
                    y0 = df[code].values
                    y1 = df['sim_' + code].values
            
                    ER = np.nansum(y0-y1) # error 
                    ABSER = np.nansum(np.abs(y0-y1))  # absolute error 
                    RELER = np.nansum(np.abs(y0-y1)/y0) # relative error 
                    PERER = np.nansum(np.abs(y0-y1)/y0*100) # percentage error 
                    MAE = np.nanmean(np.abs(y0-y1)) # mean absolute error
                    BAL = (np.sum(y1)/np.sum(y0))*100 # balance
                    MSE = np.nanmean((y0-y1)**2) # mean square error 
                    RMSE = np.sqrt(np.nanmean((y0-y1)**2)) # root mean square error 
                    MARE = he.evaluator(he.mare, y1, y0)[0] # mean absolute relative error 
                    KGE = he.evaluator(he.kge, y1, y0)[0][0] # kling-gupta efficiency (r, α, β)
                    PBIAS  = he.evaluator(he.pbias, y1, y0)[0] # percent bias
                    NSE = 1-( np.sum((y1-y0)**2) / np.sum((y0-np.mean(y0))**2) ) # nash–sutcliffe efficiency (add '1-' ==> actual NSE)
                    NSElog = he.evaluator(he.nse, y1, y0, transform='log')[0] # nash–sutcliffe efficiency log
                    
                    self.store_indicator.append(NSElog)
                    
                    liste_ind = [ER,ABSER,RELER,PERER,MAE,BAL,MSE,RMSE,MARE,KGE,PBIAS,NSE,NSElog]
                    self.listing_indicator.loc[len(self.listing_indicator)] = liste_ind
                                                                                
                self.y0 = df[[col for col in df if not col.startswith('sim_')]]
                self.y1 = df[[col for col in df if col.startswith('sim_')]]
                
                self.listing_indicator.to_csv(os.path.join(self.param_folder, self.model, 
                                                            '_watershed', '_listing_indicator.csv'), sep=';')
    def get_indicator(self):
        indicator = self.store_indicator
        criteria = self.listing_indicator
        return indicator, self.y0, self.y1, criteria
    
class Intermittency:
    def __init__(self, watershed, model, param_folder):
        self.watershed = watershed
        self.model = model
        self.param_folder = param_folder
        
        self.load_modeling_data()
        self.compare_sim_obs_data()
    
    def load_modeling_data(self):
        sim_path = os.path.join(self.param_folder, self.model, '_watershed', '_simulated_results.csv')
        sim = pd.read_csv(sim_path, sep=';', parse_dates=True, index_col=0)
        self.seepage_areas = sim.seepage_areas
        # add successive subbasins
        
    def compare_sim_obs_data(self):
        code = 'CODE'
        df = self.seepage_areas.copy()
        df = df.rename('sim_' + code)
        y1 = df['sim_' + code].values
        self.y1 = df[[col for col in df if col.startswith('sim_')]]

    def get_indicator(self):
        return self.y1