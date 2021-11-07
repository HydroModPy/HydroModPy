# coding:utf-8

import pandas as pd
import os 
import sys
from os.path import dirname, abspath

class Forcing:
    
    def __init__(self, out_path):

        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        
        self.recharge = None
        self.runoff = None
        
    def update_recharge(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state):
        climatic = pd.read_csv(self.data_folder+'_'+'REC'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic # recharge
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state):
        climatic = pd.read_csv(self.data_folder+'_'+'RUN'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic  
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
        
        
        
        
        
        
        
        
        