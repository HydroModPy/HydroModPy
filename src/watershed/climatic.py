# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ROOT

import pandas as pd
import numpy as np
import os
from scipy.optimize import curve_fit

#%% CLASS

class Climatic:

    #%% INIT
    
    def __init__(self, out_path):
        
        print('Init climatic module to set model parameter')
        
        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        self.drias_folder = os.path.join(out_path, 'results_stable/drias/')
        self.freq = None
        self.recharge = None
        self.runoff = None
        self.unit = None

    #%% UPDATE FROM OWN MANUAL DATA
    
    def update_recharge(self, values, sim_state):

        self.recharge = values # recharge
        if sim_state == 'steady':
            self.recharge = np.mean(self.recharge)
            if isinstance(self.recharge,(int,float))==False:
                self.recharge = self.recharge[0]
            
    def update_runoff(self, values, sim_state):

        self.runoff = values # recharge
        if sim_state == 'steady':
            self.runoff = np.mean(self.runoff)
            if isinstance(self.runoff,(int,float))==False:
                self.runoff = self.runoff[0]
    
    def update_first_clim(self, first_clim):

        self.first_clim = first_clim # 'mean', 'first' or value
    
    #%% UPDATE FROM CREATED SYNTHETIC DATA
    
    def update_recharge_synthetic(self, rech, shape, years, start_date= "2020-08", freq = None, dis='normal'):
        
        self.freq = freq
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
            self.recharge = self.recharge.resample(self.freq).mean()
        
    def update_recharge_sinusoid(self, serie, period, amplitude, offset, omega, phase):
        
        def sinusoid(x, A , offset, omega, phase):
            return A*np.sin(omega*x+phase) + offset
        def get_p0(Y, T):
            A0 = (max(Y[0:T]) - min(Y[0:T]))/2
            offset0 = Y[0]
            phase0 = 0
            omega0 = 2.*np.pi/T
            return [A0, offset0, omega0, phase0]
        if period=='D':
            T=365
        if period=='M':
            T=12
        date = serie.index
        serie = serie.reset_index(drop=True)
        X = serie.index
        Y = serie.values
        param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, T))
        param[0] = param[0] * amplitude # Amplitude : max
        param[1] = param[1] * offset # Offset : shift v
        param[2] = param[2] * omega # Omega : cycles
        param[3] = param[3] * phase # Phase : shift h
        sinus = sinusoid(X, *param)
        self.recharge = pd.Series(data = sinus, index=date)
        self.recharge[self.recharge < 0] = 0

    #%% UPDATE FROM REANALYSIS DATA SET
    
    # Adpated for :
    #       Historical reanalysis SAFRAN-SURFEX
    #       https://rmets.onlinelibrary.wiley.com/doi/10.1002/joc.2003
    
    def update_recharge_reanalysis(self, path_file, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):

        self.freq = time_step
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['REC_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_reanalysis(self, path_file, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        
        self.freq = time_step
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['RUN_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic/1000 # recharge in meters
        self.runoff.index = self.runoff.asfreq(self.freq).index
        # self.runoff.index = self.runoff.index.to_period(self.freq)
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()

    #%% UPDATE FROM EXPLORE1 DATA SET
    
    # Adpated for :
    #       EXPLORE 2070 : SURFEX projections (downscaled from DAYON 2015)
    #       https://professionnels.ofb.fr/fr/node/44
    
    def update_recharge_explore1(self, path_file, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):

        self.freq = time_step
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['REC_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_explore1(self, path_file, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        
        self.freq = time_step
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['RUN_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic/1000 # recharge in meters
        self.runoff.index = self.runoff.asfreq(self.freq).index
        # self.runoff.index = self.runoff.index.to_period(self.freq)
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
            
    #%% UPDATE FROM EXPLORE2 DATA SET
    
    # Adpated for :
    #       EXPLORE2-2021-SIM2 : SURFEX projections (available on DRIAS website)
    #       https://professionnels.ofb.fr/fr/node/1244
    
    def update_recharge_explore2(self, path_file, gcm_mod, rcm_mod, sce_mod, first_year, last_year, sim_state=None):
        
        data = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.recharge = data['REC'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_explore2(self, path_file, gcm_mod, rcm_mod, sce_mod, first_year, last_year, sim_state=None):
        
        data = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.runoff = data['RUN'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
            
#%% NOTES

