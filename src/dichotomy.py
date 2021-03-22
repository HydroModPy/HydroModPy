# -*- coding: utf-8 -*-

import os
import pandas as pd
import numpy as np
import shutil
from glob import glob
import modflow as mod
import watershed as wat
import extract as ext
import calibration as cal

class delimit_size:
    def __init__(self, dem_path='path.tif', watershed='name', outlet=pd.DataFrame(),
                 snap_dist=100, buff_dist=1000, save_dem=True, type_obs='streams',
                 data_path = os.path.dirname(os.getcwd())+'\\data\\',
                 tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):
        self.dem_path = dem_path
        self.watershed = watershed
        self.outlet = outlet
        self.snap_dist = snap_dist
        self.buff_dist = buff_dist
        self.save_dem = save_dem
        self.type_obs = type_obs
        self.data_path = data_path
        self.tmp_path = tmp_path
        self.out_path = out_path

        wat.extract_watershed(dem_path=self.dem_path, outlet=self.outlet, 
                              snap_dist=self.snap_dist, buff_dist=self.buff_dist,
                              tmp_path=self.tmp_path,
                              save_dem=self.save_dem, out_path=self.out_path)
        
        cal.extract_observed(watershed=self.watershed, type_obs=self.type_obs,
                             data_path=self.data_path,
                             tmp_path=self.tmp_path,
                             out_path=self.out_path)
                
class run_calibration:
    def __init__(self, krval=500, compt=0, df=pd.DataFrame(),
                 watershed='name',
                 climatic=[8e-4], lay_number=1, thick=100, porosity=0.01,
                 type_obs='streams', type_time='s', sim_id='identify',
                 data_path=os.path.dirname(os.getcwd())+'\\data\\',
                 tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):

        self.data_path = data_path
        self.tmp_path = tmp_path
        self.out_path = out_path
        
        self.watershed = watershed
        self.dem_model = self.tmp_path + 'watershed_buff.tif'
        
        self.climatic = np.asarray(climatic).mean()
        self.lay_number = lay_number
        self.thick = thick
        self.porosity = porosity
        
        self.type_obs = type_obs
        self.type_time = type_time

        self.krval = krval
        self.compt= compt
        self.df = df
        self.hyd_cond = self.krval * self.climatic
        self.sim_id = self.type_time+'_'+\
                     self.watershed+'_'+\
                     str(self.lay_number)+'_'+\
                     str(self.thick)+'_'+\
                     str(round(self.krval,3))+'_'+\
                     str(round(self.climatic,3))+'_'+\
                     str(round(self.hyd_cond,3))+'_'+\
                     str(self.porosity)
                 
        mod.modflow_model(dem_path=self.dem_model,
                          watershed=self.watershed, climatic=[self.climatic], lay_number=self.lay_number, 
                          thick=self.thick, hyd_cond=self.hyd_cond, porosity=self.porosity,
                          model_name=self.sim_id,
                          model_folder=self.out_path)
        
        ext.extract_modflow(dem_path=self.dem_model,
                            watershed=self.watershed,
                            model_name=self.sim_id,
                            model_folder=self.out_path)
        
        cal.generate_distances(watershed=self.watershed, type_obs=self.type_obs, type_time=self.type_time,
                               sim_id=self.sim_id,
                               data_path=self.data_path,
                               tmp_path=self.tmp_path,
        					   out_path=self.out_path)
        
        self.store = cal.store_dataframe(watershed=self.watershed, type_time=self.type_time, sim_id=self.sim_id,
                                    tmp_path=self.tmp_path,
        					        out_path=self.out_path) 
        
        self.df.loc[self.compt,'Kr'] = round(self.krval, 4)
        self.df.loc[self.compt,'K'] = round(self.hyd_cond, 4)
        self.df.loc[self.compt,'Sflow'] = round(self.store.sim_to_obs_mean, 4)
        self.df.loc[self.compt,'Oflow'] = round(self.store.obs_to_sim_mean, 4)
        self.df.loc[self.compt,'Qflow'] = round(self.store.outflow,4)   
    
        self.condition = round(self.store.sim_to_obs_mean / self.store.obs_to_sim_mean, 2)
        
        print('==> Simulation : '+str(self.compt))
        print('    Parameters : '+self.sim_id)
        print('    KR = '+str(round(self.krval, 2)))
        print('    Condition = '+str(self.condition))

class dichotomy_loop:
    def __init__(self, first=1, last=10000, gap=100,
                 krval=500, compt=0, df=pd.DataFrame(),
                 watershed='name',
                 climatic=[8e-4], lay_number=1, thick=100, porosity=0.01,
                 type_obs='streams', type_time='s', sim_id='identify',
                 data_path=os.path.dirname(os.getcwd())+'\\data\\',
                 tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                 out_path=os.path.dirname(os.getcwd())+'\\output\\'):
        
        self.first = first
        self.last = last
        self.gap = gap
        
        self.data_path = data_path
        self.tmp_path = tmp_path
        self.out_path = out_path
        
        self.watershed = watershed
        self.dem_model = self.tmp_path + 'watershed_buff.tif'
        
        self.climatic = np.asarray(climatic).mean()
        self.lay_number = lay_number
        self.thick = thick
        self.porosity = porosity
        
        self.type_obs = type_obs
        self.type_time = type_time

        self.krval = krval
        self.compt= compt
        self.df = df
        self.hyd_cond = self.krval * self.climatic
        self.sim_id = self.type_time+'_'+\
                      self.watershed+'_'+\
                      str(self.lay_number)+'_'+\
                      str(self.thick)+'_'+\
                      str(round(self.krval,3))+'_'+\
                      str(round(self.climatic,3))+'_'+\
                      str(round(self.hyd_cond,3))+'_'+\
                      str(self.porosity)
        
        self.sim_list = glob(self.out_path+self.watershed+'\\'+self.type_time+'*')
        if not self.sim_list:
            print('- Delete previous : '+'NO'+'\n')
        else:
            print('- Delete previous : '+'YES'+'\n')
        for folder in self.sim_list:
            shutil.rmtree(folder)

        self.difference = self.last - self.first
        self.df = pd.DataFrame()
        self.compt = 0
        while (self.difference > self.gap):
            self.half = (self.first + self.last) / 2
            self.calibration = run_calibration(krval=self.half, compt=self.compt, df=self.df,
                                             watershed=self.watershed,
                                             climatic=self.climatic, lay_number=self.lay_number, thick=self.thick, porosity=self.porosity,
                                             type_obs=self.type_obs, type_time=self.type_time, sim_id=self.sim_id,
                                             data_path=self.data_path,
                                             tmp_path=self.tmp_path,
                                             out_path=self.out_path)
            self.condition = self.calibration.condition
            if self.condition > 1:
                self.first = self.half
            else:
                self.last = self.half
            self.difference = self.last - self.first
            print('    Ecart = '+str(round(self.difference,2))+'\n')
            self.compt += 1
        self.save_name = self.watershed+'\\'+self.watershed+'_calibration.csv'
        self.df.to_csv(self.out_path+self.save_name, sep='\t', index=True)
    