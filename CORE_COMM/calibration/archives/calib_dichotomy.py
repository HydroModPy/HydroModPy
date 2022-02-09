# -*- coding: utf-8 -*-
"""
Created on

@author: Ronan Abhervé
"""

# self.masked_folder = os.path.join(self.simulations_folder, '_masked')
# file_adds.create_folder(self.masked_folder)

"""
méthode numérique de calibration: simplex, dichotomie...

function objectif définie vers un minimum
"""

import geopandas as gpd
from glob import glob
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import shutil
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

from tools import toolbox

class Dichotomy:
    def __init__(self, 
                 geographic, 
                 type_river='streams',
                 hydrology_stable=None,                 
                 simulations_folder=None):
        
        self.geographic = geographic
        self.type_river=type_river
        self.hydrology_stable=hydrology_stable
        self.simulations_folder=simulations_folder
        
        self.results_folder=os.path.join(self.simulations_folder, '_watershed/_tifs/')
        
        self.watershed_dem = geographic.watershed_dem
        self.watershed_shp = geographic.watershed_shp
        self.watershed_fill = geographic.watershed_fill
        self.watershed_direc = geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        
    def prepare_files(self):
        print ('Dichotomy calibration') 
        # Clip raw observed
        streams = self.hydrology_stable + self.type_river +'.shp'
        tif_streams = self.hydrology_stable + self.type_river + '.tif'
        wbt.vector_lines_to_raster(streams, tif_streams, field="FID", base=self.watershed_dem)
        pt_streams = self.hydrology_stable + self.type_river + '_pt.shp'
        wbt.raster_to_vector_points(tif_streams, pt_streams)
        # New folder results
        self.dichotomy_folder = os.path.join(self.simulations_folder, '_dichotomy')
        toolbox.create_folder(self.dichotomy_folder)
        # Observed buff data
        self.buff_tif_obs = os.path.join(self.hydrology_stable,self.type_river+'.tif')
        self.buff_pt_obs = os.path.join(self.hydrology_stable,self.type_river+'.shp')
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, True)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)  
        # Mask seepage simulation
        tif_sim = os.path.join(self.results_folder, 'seepage_areas_t(0).tif')
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

    def mean_distances(self):
        obs_to_sim = gpd.read_file(self.pt_obs_flow)
        obs_to_sim = obs_to_sim.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        obs_to_sim = obs_to_sim[obs_to_sim['distance'] >= 0]
        self.mean_obs_to_sim = np.nanmean(obs_to_sim['distance'])
        sim_to_obs = gpd.read_file(self.pt_sim_flow)
        sim_to_obs = sim_to_obs.rename(columns={'VALUE':'count', 'VALUE1':'distance'})
        sim_to_obs = sim_to_obs[sim_to_obs['distance'] >= 0]
        self.mean_sim_to_obs = np.nanmean(sim_to_obs['distance'])
        
        self.condition = round(self.mean_sim_to_obs / self.mean_obs_to_sim, 2)  
        return (self.mean_obs_to_sim, self.mean_sim_to_obs, self.condition)
    
"""
class run_het_calibration:
    def __init__(self,first=1, last=10000, gap=100, compt=0,
                 watershed='name', climatic=[8e-4], lay_number=1, thick=100, porosity=0.01,
                 type_obs='streams', type_time='s', sim_id='identify',
                 data_path=os.path.dirname(os.getcwd())+'\\data\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):

        self.first = first
        self.last = last
        self.gap = gap
        self.data_path = data_path
        self.out_path = out_path
        self.watershed = watershed
        self.gis_path = self.out_path + self.watershed + '/gis/'
        self.dem_model = self.gis_path + 'watershed_buff_dem.tif'
        self.geology = geo.structure(dem_path = self.dem_model, out_path=self.gis_path)
        self.climatic = np.asarray(climatic).mean()
        self.krval = (self.first + self.last) / 2
        self.hyd_cond = np.ones(np.shape(self.geology.geology_array))
        self.K_R = np.ones(np.shape(self.geology.geology_array))
        self.geol_to_KR = pd.DataFrame()
        for i in range (0, len(self.geology.geology_code)):
            self.geol_to_KR.loc[i,'code'] = int(self.geology.geology_code[i])
            #self.geol_to_KR.loc[i,'K/R'] = self.krval
            self.geol_to_KR.loc[i,'K/R first'] = self.first
            self.geol_to_KR.loc[i,'K/R last'] = self.last
            self.geol_to_KR.loc[i,'K/R half'] = (self.first + self.last) / 2 #self.first
            self.geol_to_KR.loc[i,'K/R difference'] = self.last - self.first
            self.geol_to_KR.loc[i,'K (m/j)'] = self.geol_to_KR.loc[i,'K/R half'] * self.climatic
            self.hyd_cond[self.geology.geology_array==self.geology.geology_code[i]] = self.geol_to_KR.loc[i,'K (m/j)']
            self.K_R[self.geology.geology_array==self.geology.geology_code[i]] = self.geol_to_KR.loc[i,'K/R half']
        self.lay_number = lay_number
        self.thick = thick
        self.porosity = porosity
        self.type_obs = type_obs
        self.type_time = type_time
        self.compt= compt

        self.sim_list = glob(self.out_path+self.watershed+'\\'+self.type_time+'*')
        if not self.sim_list:
            print('- Delete previous : '+'NO'+'\n')
        else:
            print('- Delete previous : '+'YES'+'\n')
        for folder in self.sim_list:
            shutil.rmtree(folder)
        self.difference = self.last - self.first
        self.df = []
        self.compt = 0
        self.idx=0
        self.code=0
        self.sim_id = self.type_time+'_het_'+\
                      self.watershed+'_'+\
                      str(self.lay_number)+'_'+\
                      str(self.thick)+'_'+\
                      str(self.porosity)
        self.het_dichotomy_loop()


    def het_dichotomy_loop(self):
        while not(all(self.geol_to_KR['K/R difference'] < self.gap)):
            if self.idx == len(self.geology.geology_code):
              self.idx = 0
            plt.figure()
            plt.imshow(self.hyd_cond)
            plt.colorbar()
            plt.show()
            print(self.geol_to_KR)
            self.het_calibration()
            #self.idx = (self.condition['ratio_dist']-1).abs().idxmax()
            #self.idx = (self.condition['sim_to_obs']).idxmax()
            #self.idx = (self.condition['ratio_dist']).abs().idxmax()
            self.code = self.condition['code'].loc[self.idx]
            print(self.code)

            if self.condition['ratio_dist'].loc[self.idx] > 1:
                self.geol_to_KR.loc[self.idx,'K/R first'] = self.geol_to_KR.loc[self.idx,'K/R half']
            else:
                self.geol_to_KR.loc[self.idx,'K/R last'] = self.geol_to_KR.loc[self.idx,'K/R half']
            self.geol_to_KR.loc[self.idx,'K/R difference'] = self.geol_to_KR.loc[self.idx,'K/R last'] - self.geol_to_KR.loc[self.idx,'K/R first']
            #print('    Ecart = '+'\n'+str(round(self.geol_to_KR['K/R difference'],2))+'\n')
            
            '''if self.geol_to_KR.loc[self.idx,'K/R difference'] < self.gap and np.abs((self.df[self.compt].loc[self.idx,'ratio_dist']-1))>0.5:
                                                                                                    self.geol_to_KR.loc[self.idx,'K/R first'] = self.first
                                                                                                    self.geol_to_KR.loc[self.idx,'K/R last'] = self.last
                                                                                                    self.geol_to_KR.loc[self.idx,'K/R half'] = (self.first + self.last) / 2 
                                                                                                    self.geol_to_KR.loc[self.idx,'K/R difference'] = self.last - self.first'''

            self.geol_to_KR.loc[self.idx,'K/R half'] = (self.geol_to_KR.loc[self.idx,'K/R last'] + self.geol_to_KR.loc[self.idx,'K/R first']) / 2
            self.geol_to_KR.loc[self.idx,'K (m/j)'] = self.geol_to_KR.loc[self.idx,'K/R half'] * self.climatic
            self.geol_to_KR.loc[self.idx,'K (m/s)'] = self.geol_to_KR.loc[self.idx,'K (m/j)'] / (24*60*60)
            self.hyd_cond[self.geology.geology_array==self.code] = self.geol_to_KR.loc[self.idx,'K (m/j)']
            self.K_R[self.geology.geology_array==self.code] = self.geol_to_KR.loc[self.idx,'K/R half']
            self.compt += 1
            self.idx += 1
            '''if self.geol_to_KR.loc[self.idx,'K/R difference'] < self.gap:
                                                  self.idx += 1'''
        for i in range (0, len(self.geology.geology_code)):
          if self.condition.loc[i,'ratio_dist'] == -9999:
            self.K_E[self.geology.geology_array==self.condition.loc[i,'code']] = -9999
            self.hyd_cond[self.geology.geology_array==self.condition.loc[i,'code']] = -9999 
        np.savetxt(self.gis_path+'hyd_cond.txt', self.hyd_cond)
        np.savetxt(self.gis_path+'K_R.txt', self.K_R)
        

        #self.save_name = self.watershed+'\\'+self.watershed+'_calibration.csv'
        #self.df.to_csv(self.out_path+self.save_name, sep='\t', index=True)

    def het_calibration(self):
        mod.modflow_model(dem_path=self.dem_model,
                          watershed=self.watershed, climatic=[self.climatic], lay_number=self.lay_number, 
                          thick=self.thick, hyd_cond=self.hyd_cond, porosity=self.porosity, coastal_aquifer =True,
                          model_name=self.sim_id,
                          model_folder=self.out_path)
        
        ext.extract_modflow(dem_path=self.dem_model,
                            watershed=self.watershed,
                            model_name=self.sim_id,
                            model_folder=self.out_path)
        
        cal.generate_distances(watershed=self.watershed, type_obs=self.type_obs, type_time=self.type_time,
                                sim_id=self.sim_id,
                                data_path=self.data_path,
                                out_path=self.out_path)
        
        self.store = cal.store_dataframe_het(self.geology, watershed=self.watershed, type_time=self.type_time, sim_id=self.sim_id,
                                                  out_path=self.out_path) 
        self.df.append(self.store.mean_dist_code)
        self.df[self.compt]
        self.df[self.compt]['K/R'] = self.geol_to_KR['K/R half']
        self.df[self.compt]['K'] = self.geol_to_KR['K (m/j)']
        '''
        self.df.loc[self.compt,'Kr'] = round(self.krval, 4)
        self.df.loc[self.compt,'K'] = round(self.hyd_cond, 4)
        self.df.loc[self.compt,'Sflow'] = round(self.store.sim_to_obs_mean, 4)
        self.df.loc[self.compt,'Oflow'] = round(self.store.obs_to_sim_mean, 4)
        '''
    
        self.condition = self.df[self.compt]
        
        print('==> Simulation : '+str(self.compt))
        print('    Parameters : '+self.sim_id)
        print(self.df[self.compt])
"""