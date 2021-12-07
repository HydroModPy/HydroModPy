# coding:utf-8

import pandas as pd
import numpy as np
import os 

class Forcing:
    def __init__(self, out_path):
        '''
        Constructor
        
        Parameters
        ----------
        out_path : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        '''
        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        self.recharge = None
        self.runoff = None
    
    def update_recharge(self, values, sim_state):
        self.recharge = values # recharge
        if sim_state == 'steady':
            self.recharge = np.mean(self.recharge)
    
    def update_synthetic_recharge(self, rech, shape, years, start_date= "2020-08", freq = None, dis='normal'):
        days = years*365
        date = pd.date_range(start_date, periods=days)
        t = np.linspace(1,365,365)
        time = []
        for y in range(0,years):
            time = np.concatenate((time,t))
        mean = 180
        if dis == 'inverse-gaussian':
            pdf = (((mean*shape)/(2*np.pi*time**3))**0.5*np.exp(-(shape*(time-mean)**2)/(2*mean*time)))*rech
        if dis == 'normal':
            pdf = ((1/(shape*np.sqrt(2*np.pi)))*np.exp(-((time-mean)**2/(2*shape**2))))*rech
        if dis == 'uniform':
            pdf = np.zeros(len(time)) 
            pdf[(time >= (mean-(shape/2))) & (time < ((shape/2)+mean))] = rech/shape
        self.recharge = pd.Series(data = pdf, index=date)
        if freq != None:
            self.recharge = self.recharge.resample(freq).sum()
    
    def update_recharge_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state):
        climatic = pd.read_csv(self.data_folder+'_'+'REC'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic/1000 # recharge
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state):
        climatic = pd.read_csv(self.data_folder+'_'+'RUN'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic/1000  
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
        
        
        
        
        
        
        
        
        