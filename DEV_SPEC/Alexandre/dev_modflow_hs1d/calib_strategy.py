# coding:utf-8

import os
import sys
import pandas as pd

class CalibStrategies:
    """
    A class used to find the best strategies to calibrate the hydraulic parameters

    Attributes
    ----------
    params: Python object
        contains the set of parameters    
    BV : Python object
        contains the informations of observed data
    
    Returns
    ----------
    names : list of str
        the name of each parameter

    Methods
    -------
    check_strategies(BV)
        check if the strategies written in the "strategies_to_calibrate" settings file  are correct with respect to the parameters write in the "params_to_calibrate" settings file 

    create_strategies(BV)
        Create and save parameters
    
    """
    
    def __init__(self, BV, params):
        """
        Constructor
        
        Parameters
        ----------
        params: Python object
            contains the set of parameters
        BV : Python object
            contains the informations of observed data
        """
        
        self.strategies = []
        self.observed_data = []
        self.params = params
        
        self.check_strategies(BV)
        #self.create_strategies(BV)
        
    def check_strategies(self, BV):
        #load strategies
        self.strategies = pd.read_csv(BV.settings_folder + '/strategies_to_calibrate.csv')
        
        
        #Observed data
        if ('streams_array' in BV.hydrology.__dir__()) == True:
            self.observed_data.append('streams')
        if len(BV.piezometry.codes_bss) > 0:
            self.observed_data.append('piezometry')
        
    def create_strategies(self, BV):
        """
        Load hydraulic parameters
        
        Parameters
        ----------
        params: Python object
            contains the set of parameters
        BV : Python object
            contains the informations of observed data
        """
        
        #Strategies
        if ('streams' in self.observed_data) and ('k' in self.params.list):
            self.strategies.append('hom_streams_k')
        if ('streams' in self.observed_data) and (len([x for x in self.params.names if x.startswith('k')]) > 1):
            self.strategies.append('het_streams_k')
        if ('piezometry' in self.observed_data) and (len([x for x in self.params.names if x.startswith('k')]) > 1):
            self.strategies.append('het_piezometry_k')
        if ('piezometry' in self.observed_data) and ('k' in self.params.list):
            self.strategies.append('hom_piezometry_k')
        
        f = open(BV.modeling_data_folder + 'calibration_strategies.csv', 'w')
        ligne = ",".join(self.strategies) + "\n"
        f.write(ligne)
        f.close
        
        
        

