# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import pandas as pd
import numpy as np
import os
from scipy.optimize import curve_fit

#%% CLASS

class Climatic:  
    """
    Class to initialize the climate forcing data (recharge, runoff).
    """
    
    def __init__(self, out_path: str=None):
        """
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs. 
        """    
        print('Init climatic module to set model parameter')
        
        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        self.drias_folder = os.path.join(out_path, 'results_stable/drias/')
        self.freq = None
        self.recharge = None
        self.runoff = None
        self.unit = None

    #%% UPDATE FROM OWN MANUAL DATA
    
    def update_recharge(self, values, sim_state):
        """
        Function to update recharge based on its own values.

        Parameters
        ----------
        values
            Recharge values, float or list of float.
        sim_state : str
            Select the simulation type, steady-state or transient.
        """   
        self.recharge = values # recharge
        if isinstance(values,(dict))==False:
            if sim_state == 'steady':
                self.recharge = np.mean(self.recharge)
                if isinstance(self.recharge,(int,float))==False:
                    self.recharge = self.recharge[0]
            
    def update_runoff(self, values, sim_state):
        """
        Function to update runoff based on its own values.

        Parameters
        ----------
        values
            Runoff values, float or list of float.
        sim_state : str
            Select the simulation type, steady-state or transient.
        """
        self.runoff = values # recharge
        if isinstance(values,(dict))==False:
            if sim_state == 'steady':
                self.runoff = np.mean(self.runoff)
                if isinstance(self.runoff,(int,float))==False:
                    self.runoff = self.runoff[0]
    
    def update_first_clim(self, first_clim):
        """
        Define the first value of the recharge list values.

        Parameters
        ----------
        first_clim
            Choice between a float, the mean or the first value in the list of values.
        """
        self.first_clim = first_clim # 'mean', 'first' or value
    
    #%% UPDATE FROM CREATED SYNTHETIC DATA
    
    def update_recharge_synthetic(self, rech, shape, years, start_date="2020-08", 
                                  freq=None, dis='normal'):
        """
        Create synthetic recharge values from mathematical function.

        Parameters
        ----------
        rech : float
            Total annual recharge requested by the user.
        shape : float
            Value to build the mathematical function.
        years : float
            Number of years to generate.
        start_date : str
            Year and month for the beginning. The default is "2020-08".
        freq : str
            Inform the time step requested ('D','M','Y'). The default is None.
        dis : str
            Distribution of the mathematical function. The default is 'normal'.
        """
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
        """
        Create synthetic recharge values from sinusoidal function.

        Parameters
        ----------
        serie
            Pandas series of the initial recharge values.
        period : str
            Inform the time step requested ('D','M').
        amplitude : float
            Control the mxaimal value of the sinusoidal function.
        offset : float
            Control the vertical shift of the sinusoidal function.
        omega : float
            Control the number of cycles of the sinusoidal function.
        phase : TYPE
            Control the horizontal shift of the sinusoidal function.
        """  
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
    
    def update_recharge_reanalysis(self, path_file, clim_mod, clim_sce, first_year, 
                                   last_year, time_step, sim_state=None):
        """
        Update the recharge from a hydrometeorological reanalysis at the France scale.

        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        clim_mod : str
            Label of the climatic model (e.g. 'REA').
        clim_sce : str
            Label of the scenario forecast model (e.g. 'historic').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        time_step : str
            Frequency of the period ('D','W','M','Y')
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """       
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['REC_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.recharge = climatic # recharge in meters
        self.recharge.index = self.recharge.asfreq(self.freq).index
        # self.recharge.index = self.recharge.index.to_period(self.freq)
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_reanalysis(self, path_file, clim_mod, clim_sce, first_year,
                                 last_year, time_step, sim_state=None):
        """
        Update the runoff from a hydrometeorological reanalysis at the France scale.

        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        clim_mod : str
            Label of the climatic model (e.g. 'REA').
        clim_sce : str
            Label of the scenario forecast model (e.g. 'historic').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """       
        self.freq = time_step
        climatic = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        climatic = climatic['RUN_'+clim_mod+'_'+clim_sce]
        climatic = climatic[(climatic.index.year >= first_year) & (climatic.index.year <= last_year)]
        self.runoff = climatic # recharge in meters
        self.runoff.index = self.runoff.asfreq(self.freq).index
        # self.runoff.index = self.runoff.index.to_period(self.freq)
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()

    #%% UPDATE FROM EXPLORE1 DATA SET
    
    # Adpated for :
    #       EXPLORE 2070 : SURFEX projections (downscaled from DAYON 2015)
    #       https://professionnels.ofb.fr/fr/node/44
    
    def update_recharge_explore1(self, path_file, clim_mod, clim_sce,
                                 first_year, last_year,
                                 time_step, sim_state=None):
        """
        Update the recharge from a hydrometeorological hydroclimatic projection EXPLORE1 at the France scale.
        Greenhouse effect scenarios: RCP2.6, RCP4.5, RCP6.0, RCP8.5.
        
        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        clim_mod : str
            Label of the climatic model (e.g. 'REA').
        clim_sce : str
            Label of the scenario forecast model (e.g. 'historic').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        time_step : str
            Frequency of the period ('D','W','M','Y')
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """   
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
        """
        Update the runoff from a hydrometeorological hydroclimatic projection EXPLORE1 at the France scale.
        Greenhouse effect scenarios: RCP2.6, RCP4.5, RCP6.0, RCP8.5.

        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        clim_mod : str
            Label of the climatic model (e.g. 'IPS1').
        clim_sce : str
            Label of the scenario forecast model (e.g. 'RPC8.5').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        time_step : str
            Frequency of the period ('D','W','M','Y')
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """   
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
    
    def update_recharge_explore2(self, path_file, gcm_mod, rcm_mod, sce_mod,
                                 first_year, last_year, sim_state=None):
        """
        Update the recharge from a hydrometeorological hydroclimatic projection EXPLORE2 at the France scale.
        Greenhouse effect scenarios: RCP2.6, RCP4.5, RCP6.0, RCP8.5.
        
        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        gcm__mod : str
            Label of the global climatic model (e.g. 'CNR').
        rcm_mod : str
            Label of the regional climatic model (e.g. 'ALA').
        clim_mod : str
            Label of the scenario forecast model (e.g. 'historic').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """  
        data = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.recharge = data['REC'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.recharge = self.recharge.mean()

    def update_runoff_explore2(self, path_file, gcm_mod, rcm_mod, sce_mod, first_year, last_year, sim_state=None):
        """
        Update the runoff from a hydrometeorological hydroclimatic projection EXPLORE2 at the France scale.
        Greenhouse effect scenarios: RCP2.6, RCP4.5, RCP6.0, RCP8.5.
        
        Parameters
        ----------
        path_file : str
            Path of the specific file .csv, generated by a specific climatics model.
        gcm__mod : str
            Label of the global climatic model (e.g. 'CNR').
        rcm_mod : str
            Label of the regional climatic model (e.g. 'ALA').
        clim_mod : str
            Label of the scenario forecast model (e.g. 'historic').
        first_year : int
            First year of selected period.
        last_year : int
            Last year of selected period.
        sim_state : TYPE, optional
            Select the simulation type, steady-state or transient.
        """  
        data = pd.read_csv(path_file, sep=';', index_col=0, parse_dates=True)
        data = data[(data.index.year >= first_year) & (data.index.year <= last_year)]
        self.runoff = data['RUN'+'_'+gcm_mod+'-'+rcm_mod+'_'+sce_mod] / 1000 # mm to m
        if sim_state == 'steady':
            self.runoff = self.runoff.mean()

    #%% SET DATA SET TO STEADY INPUTS
    
    def set_steady_recharge(self):
        """
        Calculate the mean of recharge time series for steady-state simulation.
        """
        self.recharge = self.recharge.mean()
        
    def set_steady_runoff(self):
        """
        Calculate the mean of runoff time series for steady-state simulation.
        """
        self.runoff = self.runoff.mean()
            
#%% NOTES
