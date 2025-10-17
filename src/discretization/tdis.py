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
import numpy as np
import pandas as pd
import datetime
# Flopy
from flopy.discretization.modeltime import ModelTime
# Hydromodpy
from tools import Process


#%% CLASS

class TDis(Process):
    """
    WIP
    """
    
    def __init__(self, 
                 name: str = 'tdis',
                 output_name: str = 'tdis'):
        """
        WIP
        
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs. 
        """
        super().__init__(name, output_name)
        
        # Default time unit
        self.set_iptpar(itmuni = 'd') #TODO@TB unit system not implemented yet - all in days
        # Default simulation: steady state simulation
        self.set_iptpar(sim_state = 'steady', 
                        genmtd    = 'synthetic_regular',
                        nper      = 1)   # Number of time periods        
        # Default parameters for loading list of date as csv file (optional)
        self.set_iptpar(dateformat = '%Y-%m-%d %H:%M:%S',
                        colsep     = '\t') 
        # Default advanced parameters
        self.set_advpar(nstp           = 1, # Number of time steps in each stress period
                        tsmult         = 1, # Time step multiplier
                        firstpersteady = True) # first period will be steady-state
        
    
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv: dict = {}):
        """
        Extract and store input data from files / shared environment.
        """
        # import external data
        genmtd = self.get_iptpar['genmtd']
        if genmtd == 'from_csv' or genmtd == 'from_csv_shrenv':
            if genmtd == 'from_csv':
                datefilepath = self.get_iptpar['datefilepath']
            if genmtd == 'from_csv_shrenv':
                datefilenam  = self.get_shrpar['datefilepath']
                datefilepath = self.get_envar(shrenv,datefilenam)
            dateheader   = self.get_iptpar['dateheader']
            colsep       = self.get_iptpar['colsep']
            dateformat   = self.get_iptpar['dateformat']
            
            df = pd.read_csv(datefilepath,
                             sep = colsep)
            df[dateheader] = pd.to_datetime(df[dateheader], 
                                            format = dateformat) 
            datelist = df[dateheader]
            self._set_csdpar(datelist = datelist)
        elif genmtd == 'from_datelist_shrenv':
            # WIP@TB: load dataframe from shrenv; need unit & format control
            print('Not implemented yet.')
            # datelistnam = self.get_shrpar['datelist_path']
            # datelist = self.get_envar(shrenv,datelistnam)            
            # self.set_csdpar(datelist = datelist)
            
        self._isPreprocessed = True
        
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # generate time grid as flopy ModelTime class
        output = self._tgrid_generation()
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
        
    
    #%%% TIME DISCRETIZATION

    def _tgrid_generation(self):
        nstp           = self.get_advpar['nstp']
        tsmult         = self.get_advpar['tsmult']
        # period length array: each time period i has duration perlen[i] of 
        # unit time_units
        start_datetime, time_units, perlen = self._get_period_lengths()
        # simulation state array: each time period i is either steady-state 
        # (steady_state[i]==True) or transient (steady_state[i]==False)
        steady_state = self._get_sim_state_array(perlen)
        # default values for advanced ModelTime parameters: see ModelTime 
        # documentation
        if isinstance(nstp,int): 
            nstp = np.full(len(perlen),nstp)        
        if isinstance(tsmult,(int,float)): 
            tsmult = np.full(len(perlen),tsmult)
        # storage as dict (format requierements from ModelTime class)
        period_data = {}
        period_data.update({'perlen':perlen})
        period_data.update({'nstp'  :nstp})
        period_data.update({'tsmult':tsmult})
        # instanciation of ModelTime class from flopy
        tgrid = ModelTime(period_data    = period_data,
                          time_units     = time_units,
                          start_datetime = start_datetime,
                          steady_state   = steady_state) 
        
        return tgrid
    
    
    def _get_period_lengths(self):
        genmtd         = self.get_iptpar['genmtd']
        start_datetime = self.get_iptpar.get('start_datetime')
        end_datetime   = self.get_iptpar.get('end_datetime')
        time_units     = self.get_iptpar['itmuni']
        datelist       = self.get_csdpar.get('datelist')
        nper           = self.get_iptpar['nper']
        lenper         = self.get_iptpar.get('lenper')
                
        # case time discretization is a synthetic series of same-duration 
        # periods
        if genmtd == 'synthetic_regular':
            if start_datetime is None: start_datetime = pd.to_datetime(0)
            if lenper         is None: lenper = 1
            deltat   = np.full(nper,lenper)
            deltat   = pd.to_timedelta(deltat,unit=time_units)
            perlen   = deltat.total_seconds().values  
            perlen   = perlen / 86400 # WIP@TB: values converted into float days
        # case time discretization is given by a dataframe of dates
        elif genmtd == 'from_csv'        or \
             genmtd == 'from_csv_shrenv' or \
             genmtd == 'from_datelist_shrenv':
            if start_datetime is None: start_datetime = datelist.iloc[0]
            if end_datetime   is None: end_datetime   = datelist.iloc[-1]
            datelist = datelist[(datelist >= start_datetime)]
            datelist = datelist[(datelist <= end_datetime)]
            deltat   = datelist.iloc[1:].reset_index(drop=True) - datelist.iloc[0:-1].reset_index(drop=True)
            deltat   = pd.to_timedelta(deltat.values)
            perlen   = deltat.total_seconds().values  
            perlen   = perlen / 86400 # WIP: values converted into float days        
        
        return start_datetime, time_units, perlen
    
    
    def _get_sim_state_array(self,perlen): 
        sim_state       = self.get_iptpar['sim_state']
        firststepsteady = self.get_advpar['firstpersteady']
        
        if sim_state   == 'steady':
            steady_state = np.ones(len(perlen),dtype=bool)
        elif sim_state == 'transient':
            steady_state = np.zeros(len(perlen),dtype=bool)
            if firststepsteady is True:
                steady_state[0] = True
          
        return steady_state
        
    
#%% NOTES: TODO@TB: Outputs only in days; implement loading from shrenv 
#          dataframe; decouple with steady/transient state?
