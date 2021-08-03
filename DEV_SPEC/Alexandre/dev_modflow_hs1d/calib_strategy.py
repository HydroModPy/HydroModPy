# coding:utf-8

import os
import sys
import pandas as pd

class Strategies:
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
    create_strategies(geology_code, folder)
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
        
        self.create_strategies(BV)
        
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
        #Observed data
        if ('streams_array' in BV.hydrology.__dir__()) == True:
            self.observed_data.append('streams')
        if len(BV.piezometry.codes_bss) > 0:
            self.observed_data.append('piezometry')
        
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
        
        
        

