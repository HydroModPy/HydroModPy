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
    
    def __init__(self, BV):
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
        self.params = []
        
        self.load_strategies()
        self.check_strategies(BV)
        #self.create_strategies(BV)
    def load_strategies(self):
        """
        Create "strategies" attribute
        """
        self.strategies = pd.read_csv('calib_strats.csv')
        
    def check_strategies(self, BV):
        """
        Checks if the strategies are possbile
        """
        for calib in range(0, len(self.strategies)):
            if self.strategies['observed_data'][calib] == 'streams':
                if ('streams_array' in BV.hydrology.__dir__()) == True:
                    if self.strategies['homogeneous_heterogeneous'][calib] == 'homogeneous':
                        self.params.add('k')
                        self.params.add('e')
                    if self.strategies['homogeneous_heterogeneous'][calib] == 'heterogeneous':
                        self.params.add('k')
                        self.params.add('e')
                        self.params
                else:
                    self.strategies.drop[calib]
                    print('Using steams to calibrate is not possible')
            if self.strategies['observed_data'][calib] == 'piezometry':
                if len(BV.piezometry.codes_bss) > 0:
                    pass
                else:
                    self.strategies.drop[calib]
                    print('Using piezometry to calibrate is not possible')
                
                
            if self.strategies['homogeneous_heterogeneous'][calib] == 'homogeneous':
            
            if self.strategies['homogeneous_heterogeneous'][calib] == 'heterogeneous':
                
            if self.strategies['state'][calib] == 'steady':
                
            if self.strategies['state'][calib] == 'transient':
        #Observed data
        if ('streams_array' in BV.hydrology.__dir__()) == True:
            self.observed_data.append('streams')
        if len(BV.piezometry.codes_bss) > 0:
            self.observed_data.append('piezometry')
    
    def save_params()
        
        

