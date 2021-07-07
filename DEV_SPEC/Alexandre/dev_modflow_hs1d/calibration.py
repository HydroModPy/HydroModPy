# -*- coding: utf-8 -*-

import os
import sys
import geopandas as gpd
import pandas as pd
import numpy as np
import imageio
import shutil
import topography
from glob import glob
import modflow as mod
import extract as ext
import calibration as cal
import geology as geo
import matplotlib.pyplot as plt
from scipy.optimize import fsolve
from scipy.optimize import minimize, Bounds

from IPython.core.debugger import set_trace as st
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
def my_callback(value):
    my_callback = 0
wbt.set_default_callback(my_callback)

class run_stream_het_calibration:
    def __init__(self, geographic, geology, climatic, folder, sea_level=None, first=1, 
        last=10000, gap=10, lay_number=1, thick=50, porosity=0.01,
        type_obs='streams', type_time='s', exe='/bin/mfnwt.exe'):

        krval = (first + last)/2
        self.hyd_cond = np.ones(np.shape(geology.geology_array))
        self.K_R = np.ones(np.shape(geology.geology_array))
        geol_to_KR = pd.DataFrame()

        for i in range (0, len(geology.geology_code)):
            geol_to_KR.loc[i,'code'] = int(geology.geology_code[i])
            #self.geol_to_KR.loc[i,'K/R'] = self.krval
            geol_to_KR.loc[i,'K/R first'] = first
            geol_to_KR.loc[i,'K/R last'] = last
            geol_to_KR.loc[i,'K/R half'] = (first + last) / 2 #self.first
            geol_to_KR.loc[i,'K/R difference'] = last - first
            geol_to_KR.loc[i,'K (m/j)'] = geol_to_KR.loc[i,'K/R half'] * climatic
            self.hyd_cond[geology.geology_array==geology.geology_code[i]] = geol_to_KR.loc[i,'K (m/j)']
            self.K_R[geology.geology_array==geology.geology_code[i]] = geol_to_KR.loc[i,'K/R half']

        df = []
        idx=0
        compt = 0
        
        geology.geology_code = [1,2]
        for i in geology.geology_code:
            if i ==1:
                geology.geology_array[geology.geology_array<1000] = i
                geology.geology_array_clip[geology.geology_array_clip<1000] = i
            if i ==2:
                geology.geology_array[geology.geology_array>=1000] = i
                geology.geology_array_clip[geology.geology_array_clip>=1000] = i
        
        lb = -4
        ub = 4
        start = np.ones(len(geology.geology_code)) * -1#((lb + ub) / 2)
        bds =[]
        for i in range(0,len(geology.geology_code)):
            bds.append(Bounds(lb,ub))
        root = minimize(self.func, start.tolist(),args=(geographic, geology, climatic, lay_number, thick, sea_level, folder, exe),
            method='Nelder-Mead', bounds=Bounds(lb,ub))
        st()
    
    def func(self, Klog, geographic, geology, climatic, lay_number, thick, sea_level, folder, exe):
        K = 10 ** Klog
        for i in range (0, len(geology.geology_code)):
                self.hyd_cond[geology.geology_array==geology.geology_code[i]] = K[i]

        print(Klog)
        '''plt.figure(figsize=(2,2))
                                plt.imshow(self.hyd_cond)
                                plt.show()'''
        mod.run_model(geographic, watershed='sim_modflow', 
            climatic=climatic, lay_number=lay_number, thick=thick,
            hyd_cond=self.hyd_cond, sea_level = sea_level, model_name='stream_calibration', 
            model_folder= folder , 
            exe= exe)

        mod.extract_model(geographic, 
            watershed='sim_modflow', model_name='stream_calibration', model_folder=folder,
            param=True, watertable=True, seepage=True, gwflux=True, outflow=True, spedisch=True)
        generate_distances(folder, geographic, type_obs='streams')
        df = store_dataframe_het(folder, geographic, geology, type_obs='streams')
        print(df.mean_dist_code)
        test = np.abs(np.asarray(df.mean_dist_code['ratio_dist'])-1)**2 #np.log(ratio)
        #test = np.log10(np.abs(np.asarray(df.mean_dist_code['ratio_dist']))**2)
        print(np.sum(test))
        return np.sum(test)


        '''while not(all(geol_to_KR['K/R difference'] < gap)):
                                    if idx == len(geology.geology_code):
                                      idx = 0
                                    plt.figure(figsize=(2,2))
                                    plt.imshow(self.hyd_cond)
                                    plt.show()
                                    print(geol_to_KR)
                        
                                    mod.run_model(geographic, watershed='sim_modflow', 
                                    climatic=climatic, lay_number=lay_number, thick=thick,
                                    hyd_cond=self.hyd_cond, sea_level = sea_level, model_name='stream_calibration', 
                                    model_folder= folder , 
                                    exe= exe)
                                
                                    mod.extract_model(geographic, 
                                    watershed='sim_modflow', model_name='stream_calibration', model_folder=folder,
                                    param=True, watertable=True, seepage=True, gwflux=True, outflow=True, spedisch=True)
                                
                                    generate_distances(folder, geographic, type_obs='streams')
                                    store = store_dataframe_het(folder, geographic, geology, type_obs='streams') 
                                    df.append(store.mean_dist_code)
                                    df[compt]
                                    df[compt]['K/R'] = geol_to_KR['K/R half']
                                    df[compt]['K'] = geol_to_KR['K (m/j)']
                            
                                    condition = df[compt]
                                
                                    print('==> Simulation : '+str(compt))
                                    #print('    Parameters : '+self.sim_id)
                                    print(df[compt])
                        
                                    #self.idx = (self.condition['ratio_dist']-1).abs().idxmax()
                                    #self.idx = (self.condition['sim_to_obs']).idxmax()
                                    #self.idx = (self.condition['ratio_dist']).abs().idxmax()
                                    code = condition['code'].loc[idx]
                                    print(code)
                        
                                    if condition['ratio_dist'].loc[idx] > 1:
                                        geol_to_KR.loc[idx,'K/R first'] = geol_to_KR.loc[idx,'K/R half']
                                    else:
                                        geol_to_KR.loc[idx,'K/R last'] = geol_to_KR.loc[idx,'K/R half']
                                    geol_to_KR.loc[idx,'K/R difference'] = geol_to_KR.loc[idx,'K/R last'] - geol_to_KR.loc[idx,'K/R first']
                                    #print('    Ecart = '+'\n'+str(round(self.geol_to_KR['K/R difference'],2))+'\n')
                                    
                        
                                    geol_to_KR.loc[idx,'K/R half'] = (geol_to_KR.loc[idx,'K/R last'] + geol_to_KR.loc[idx,'K/R first']) / 2
                                    geol_to_KR.loc[idx,'K (m/j)'] = geol_to_KR.loc[idx,'K/R half'] * climatic
                                    geol_to_KR.loc[idx,'K (m/s)'] = geol_to_KR.loc[idx,'K (m/j)'] / (24*60*60)
                                    self.hyd_cond[geology.geology_array==code] = geol_to_KR.loc[idx,'K (m/j)']
                                    self.K_R[geology.geology_array==code] = geol_to_KR.loc[idx,'K/R half']
                                    compt += 1
                                    idx += 1
                                    #if self.geol_to_KR.loc[self.idx,'K/R difference'] < self.gap:
                                    #                                     self.idx += 1
                                for i in range (0, len(geology.geology_code)):
                                  if condition.loc[i,'ratio_dist'] == -9999:
                                    self.K_R[geology.geology_array==condition.loc[i,'code']] = -9999
                                    self.hyd_cond[geology.geology_array==condition.loc[i,'code']] = -9999 
                        
                                #np.savetxt(self.gis_path+'hyd_cond.txt', self.hyd_cond)
                                #np.savetxt(self.gis_path+'K_R.txt', self.K_R)
                                #self.save_name = self.watershed+'\\'+self.watershed+'_calibration.csv'
                                #self.df.to_csv(self.out_path+self.save_name, sep='\t', index=True)'''

class generate_distances:
    def __init__(self, folder, geographic, type_obs='streams'):
        sim_fold = folder + '/sim_modflow/stream_calibration/'
        obs_path = folder + '/sim_modflow/stream_calibration/obs/'
        stream_fold = folder + '/data/hydrology/'
        if not os.path.exists(obs_path):
            os.makedirs(obs_path)
            
        watershed_shp = geographic.watershed_shp
        watershed_fill = geographic.watershed_fill
        watershed_direc = geographic.watershed_direc
        
        tif_obs = stream_fold + 'streams.tif'
        pt_obs = stream_fold + 'streams_pt.shp'
        tif_persist = stream_fold + 'persistent.tif'
        pt_persist = stream_fold + 'persistent_pt.shp'
        
        seep_sim = sim_fold + 'seepage.tif'
        seep_sim_mask = sim_fold + 'mask_seepage.tif'
        drn_sim = sim_fold + 'outflow.tif'
        drn_sim_mask = sim_fold + 'mask_outflow.tif'
        wt_sim = sim_fold + 'watertable.tif'
        wt_sim_mask = sim_fold + 'mask_watertable.tif'

        if type_obs == 'streams':
            obs_flow = sim_fold + 'obsflow.tif'
            wbt.trace_downslope_flowpaths(pt_obs, watershed_direc, obs_flow)
        if type_obs == 'persistent':
            obs_flow = sim_fold + 'obsflow.tif'
            wbt.trace_downslope_flowpaths(pt_persistent, watershed_direc, obs_flow)
        
        self.clip_sim(watershed_shp, seep_sim_mask, seep_sim, drn_sim, drn_sim_mask, wt_sim, wt_sim_mask)
        sim_flow, obs_flow = self.sim_to_obs(type_obs, sim_fold,geographic, obs_flow,seep_sim_mask, watershed_direc)
        self.obs_to_sim(sim_fold, geographic, sim_flow, obs_flow)

    def clip_sim(self, watershed_shp, seep_sim_mask, seep_sim, drn_sim, drn_sim_mask, wt_sim, wt_sim_mask):
        wbt.clip_raster_to_polygon(seep_sim, watershed_shp, seep_sim_mask)
        wbt.clip_raster_to_polygon(drn_sim, watershed_shp, drn_sim_mask)
        wbt.clip_raster_to_polygon(wt_sim, watershed_shp, wt_sim_mask)
        return self

    def sim_to_obs(self, type_obs, sim_fold,geographic, obs_flow,seep_sim_mask, watershed_direc):
        if type_obs == 'streams':
            dist_sim_obs = sim_fold + 'dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(geographic.watershed_fill, obs_flow, dist_sim_obs)  #tif_obs
        if type_obs == 'persistent':
            dist_sim_obs = sim_fold + 'dist_sim_obs.tif'
            wbt.downslope_distance_to_stream(geographic.watershed_fill, obs_flow, dist_sim_obs) #tif_persistent   
        sim_shp = sim_fold + 'sim.shp'
        wbt.raster_to_vector_points(seep_sim_mask, sim_shp)
        sim_flow = sim_fold + 'simflow.tif'
        wbt.trace_downslope_flowpaths(sim_shp, watershed_direc, sim_flow)
        pt_sim_flow = sim_fold + 'simflow.shp'
        wbt.raster_to_vector_points(sim_flow, pt_sim_flow)
        wbt.add_point_coordinates_to_table(pt_sim_flow)
        wbt.extract_raster_values_at_points(dist_sim_obs, pt_sim_flow)
        return sim_flow, obs_flow
                
    def obs_to_sim(self, sim_fold, geographic, sim_flow, obs_flow):
        dist_obs_sim = sim_fold + 'dist_obs_sim.tif'
        wbt.downslope_distance_to_stream(geographic.watershed_fill, sim_flow, dist_obs_sim)                
        pt_obs_flow = sim_fold + 'obsflow.shp'
        wbt.raster_to_vector_points(obs_flow, pt_obs_flow)
        wbt.add_point_coordinates_to_table(pt_obs_flow)
        wbt.extract_raster_values_at_points(dist_obs_sim, pt_obs_flow)
        return self

class store_dataframe:
    def __init__(self, folder, geographic, type_obs='streams'):
        sim_fold = folder + '/sim_modflow/stream_calibration/'
        obs_path = folder + '/sim_modflow/stream_calibration/obs/'
        if not os.path.exists(obs_path):
            os.makedirs(obs_path)

        watershed_fill = geographic.watershed_fill
        dem = topography.dem(geographic.watershed_fill) #fill
        
        pt_obs_flow = sim_fold + 'obsflow.shp'
        pt_sim_flow = sim_fold + 'simflow.shp'
        
        drn_sim_mask = sim_fold + 'mask_outflow.tif'
        
        self.mean_distances(pt_obs_flow, pt_sim_flow )
        self.mean_outflow(drn_sim_mask, dem, geographic)
        
    def mean_distances(self, pt_obs_flow, pt_sim_flow ):
        obs_to_sim = gpd.read_file(pt_obs_flow)
        obs_to_sim = obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        obs_to_sim = obs_to_sim[obs_to_sim['distance'] >= 0]
        obs_to_sim_mean = np.nanmean(obs_to_sim['distance'])
        sim_to_obs = gpd.read_file(pt_sim_flow)
        sim_to_obs = sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        sim_to_obs = sim_to_obs[sim_to_obs['distance'] >= 0]
        sim_to_obs_mean = np.nanmean(sim_to_obs['distance'])
        return self
    
    def mean_outflow(self,drn_sim_mask, dem, geographic):
        flux = imageio.imread(drn_sim_mask) # L/T
        flux = np.ma.masked_array(flux, mask=(dem.data==-99999))
        cell = flux.count()
        outflow = (np.nansum(flux) / (cell * geographic.resolution**2)) # M/T
        return self

class store_dataframe_het:
    def __init__(self, folder, geographic, geology, type_obs='streams'):
        sim_fold = folder + '/sim_modflow/stream_calibration/'
        obs_path = folder + '/sim_modflow/stream_calibration/obs/'
        if not os.path.exists(obs_path):
            os.makedirs(obs_path)

        watershed_fill = geographic.watershed_fill
        dem = topography.dem(geographic.watershed_fill)
        
        pt_obs_flow = sim_fold + 'obsflow.shp'
        pt_sim_flow = sim_fold + 'simflow.shp'

        dist_obs_sim = sim_fold + 'dist_obs_sim.tif'
        dist_sim_obs = sim_fold + 'dist_sim_obs.tif'
        obs_flow = sim_fold + 'obsflow.tif'
        sim_flow = sim_fold + 'simflow.tif'
        
        drn_sim_mask = sim_fold + 'mask_outflow.tif'
        
        self.mean_distances(dist_obs_sim, dist_sim_obs, obs_flow, sim_flow, geology)
        self.mean_outflow(drn_sim_mask, dem, geographic)
        
    def mean_distances(self,dist_obs_sim, dist_sim_obs, obs_flow, sim_flow, geology):
        obs_sim_dist = imageio.imread(dist_obs_sim)
        sim_obs_dist = imageio.imread(dist_sim_obs)
        obs = imageio.imread(obs_flow)
        sim = imageio.imread(sim_flow)
        obs_dist = np.zeros(np.shape(obs))*np.nan
        sim_dist = np.zeros(np.shape(sim))*np.nan
        obs_dist[obs>=0] = obs_sim_dist[obs>=0]
        sim_dist[sim>=0] = sim_obs_dist[sim>=0]
        sim_dist[sim_dist<0] = 0
        self.mean_dist_code = pd.DataFrame()
        compt = 0
        for i in range (0, len(geology.geology_code)):
            self.mean_dist_code.loc[compt,'code'] = int(geology.geology_code[i])
            self.mean_dist_code.loc[compt,'obs_to_sim'] = np.nanmean(obs_dist[geology.geology_array_clip==geology.geology_code[i]])
            self.mean_dist_code.loc[compt,'sim_to_obs'] = np.nanmean(sim_dist[geology.geology_array_clip==geology.geology_code[i]])
            compt += 1
        '''
        self.mean_dist_code.loc[compt+1,'code'] = 'all'
        self.mean_dist_code.loc[compt+1,'obs_to_sim'] = np.nanmean(obs_dist)
        self.mean_dist_code.loc[compt+1,'sim_to_obs'] = np.nanmean(sim_dist)
        '''
        self.mean_dist_code.loc[:,'ratio_dist']=self.mean_dist_code.loc[:,'sim_to_obs']/self.mean_dist_code.loc[:,'obs_to_sim'] 
        #self.mean_dist_code = self.mean_dist_code.replace([np.inf, -np.inf], np.nan)
        self.mean_dist_code = self.mean_dist_code.replace(np.nan, np.inf)
        '''self.obs_to_sim = gpd.read_file(self.pt_obs_flow)
                                self.obs_to_sim = self.obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
                                self.obs_to_sim = self.obs_to_sim[self.obs_to_sim['distance'] >= 0]
                                self.obs_to_sim_mean = np.nanmean(self.obs_to_sim['distance'])
                                self.sim_to_obs = gpd.read_file(self.pt_sim_flow)
                                self.sim_to_obs = self.sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
                                self.sim_to_obs = self.sim_to_obs[self.sim_to_obs['distance'] >= 0]
                                self.sim_to_obs_mean = np.nanmean(self.sim_to_obs['distance'])'''
        return self
    
    def mean_outflow(self, drn_sim_mask, dem, geographic):
        flux = imageio.imread(drn_sim_mask) # L/T
        flux = np.ma.masked_array(flux, mask=(dem.data<-1000))
        cell = flux.count()
        outflow = (np.nansum(flux) / (cell * geographic.resolution**2)) # M/T
        return self

    def figure(self,data):
        plt.figure()
        plt.imshow(data)
        plt.colorbar()
        plt.show()