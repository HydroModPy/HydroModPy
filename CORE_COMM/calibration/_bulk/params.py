# -*- coding: utf-8 -*-
"""
Created on Fri Nov 12 10:53:03 2021

@author: Alexandre Gauvain
"""

# coding:utf-8

import os
import pandas as pd
from datetime import datetime

class CalibParams:
    """
    A class used to identify hydraulic parameters of the watershed to calibrate

    Attributes
    ----------
    names : list of str
        the name of each parameter
    geo_codes : list of str
        the geological code of each parameter
    types : list of str
        the type of each parameter
    units : list of str
        the unit of each parameter

    Methods
    -------
    createparams(geology_code, folder)
        Create and save parameters
    
    """
    
    def __init__(self, settings_folder, results_folder, geology_code=None):
        """
        Constructor
        
        Parameters
        ----------        
        geology_code : list of int
            geological codes from geology python object
        settings_path : str
            the path of the setting files
        results_path : str
            the path of the result files
        """
        
        self.names = []
        self.geo_codes = []
        self.types = []
        self.units = []
        self.lbound = []
        self.ubound = []
        self.init_value = []
        self.create_params(settings_folder, results_folder, geology_code)
    
    def create_params(self, settings_folder, results_folder, geology_code):
        """
        Create hydraulic parameters
        
        Parameters
        ----------
        geology_code : list of int
            geological codes from geology python object
        settings_path : str
            the path of the setting files
        results_path : str
            the path of the result files
        """
        # reads parameter types to calibrate amont K,theta,e
        self.list = list(pd.read_csv(settings_folder + '/params_to_calibrate.csv'))
        # checks that the list is made up of correct strings
        for paramtype in self.list:
            if paramtype == 'e':
                # Only 1 thickness for the whole model so far to avoid any mesh generation issue with discontinuous thicknesses
                self.names.append(paramtype)
                self.geo_codes.append('-')
                self.types.append('thickness')
                self.units.append('m')
                self.lbound.append(10)
                self.ubound.append(1000)
                self.init_value.append(500)
            else: 
                # Loops on id units of the watershed
                for idunit in range(0, len(geology_code)):
                    self.names.append(paramtype+"_"+str(idunit))
                    self.geo_codes.append(geology_code[idunit])
                    if paramtype == 'k':
                        self.types.append('hydraulic conductivity')
                        self.units.append('m/s')
                        self.lbound.append(0.01)
                        self.ubound.append(0.0000001)
                        self.init_value.append(0.0001)
                    elif paramtype == 'theta':
                        self.types.append('porosity')
                        self.units.append('-')
                        self.lbound.append(0.01)
                        self.ubound.append(0.5)
                        self.init_value.append(0.1)
                
        self.store = pd.DataFrame({'names': self.names,'geo_codes': self.geo_codes,'types': self.types, 'units': self.units, 'lbounds': self.lbound, 'ubounds':self.ubound, 'init_values': self.init_value})
    
    def save_params(self,results_folder):
        now = datetime.now()
        dt_string = now.strftime("%Y_%m_%d-%H_%M")
        self.results_path = results_folder +'/'+ dt_string
        if not os.path.exists(self.results_path):
            os.makedirs(self.results_path)
        
        self.store.to_csv(self.results_path + '/params.csv',header=False, index=False)
        
        
        
        