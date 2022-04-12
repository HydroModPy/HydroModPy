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
        self.freq = None
        self.recharge = None
        self.runoff = None
        self.unit = None
    
    def update_recharge(self, values, sim_state):
        self.recharge = values # recharge
        if sim_state == 'steady':
            self.recharge = np.mean(self.recharge)
            
    def update_runoff(self, values, sim_state):
        self.runoff = values # recharge
        if sim_state == 'steady':
            self.runoff = np.mean(self.runoff)
    
    def update_synthetic_recharge(self, rech, shape, years, start_date= "2020-08", freq = None, dis='normal'):
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
        
    def update_sinusoid_recharge(self, serie, period, amplitude, offset, omega, phase):
        from scipy.optimize import curve_fit
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
    
    def update_recharge_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        self.freq = time_step
        climatic = pd.read_csv(self.data_folder+'_'+'REC'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        self.freq = time_step
        climatic = pd.read_csv(self.data_folder+'_'+'RUN'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        climatic = climatic[clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic/1000 # recharge in meters
        self.runoff.index = self.runoff.asfreq(self.freq).index
        # self.runoff.index = self.runoff.index.to_period(self.freq)
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()
        
    def update_effppt_surfex(self, clim_mod, clim_sce, first_year, last_year, time_step, sim_state=None):
        self.freq = time_step
        ppt = pd.read_csv(self.data_folder+'_'+'PPT'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        ppt = ppt[clim_mod+'_'+clim_sce]
        ppt = ppt[(ppt.index.year >= first_year) & (ppt.index.year <= last_year)]
        aet = pd.read_csv(self.data_folder+'_'+'ETP'+'_'+time_step+'.csv', sep=';', index_col=0, parse_dates=True)
        aet = aet[clim_mod+'_'+clim_sce]
        aet = aet[(aet.index.year >= first_year) & (aet.index.year <= last_year)]
        effppt = ppt - aet
        self.recharge = effppt/1000 # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        self.effppt = self.recharge.copy()
        self.pe_pos = self.effppt.clip(lower=0)
        self.pe_neg = self.effppt.clip(upper=0)
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()
            self.effppt = self.effppt.mean()
            self.pe_pos = self.pe_pos.clip(lower=0)
            self.pe_neg = self.pe_neg.clip(upper=0)
            
        
        
        
        
        
        