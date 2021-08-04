# coding:utf-8

import os
import sys
import pandas as pd
from IPython.core.debugger import set_trace as st
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
    CreateParams(geology_code, folder)
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
            else: 
                # Loops on id units of the watershed
                for idunit in range(0, len(geology_code)):
                    self.names.append(paramtype+"_"+str(idunit))
                    self.geo_codes.append(geology_code[idunit])
                    if paramtype == 'k':
                        self.types.append('hydraulic conductivity')
                        self.units.append('m/s')
                    elif paramtype == 'theta':
                        self.types.append('porosity')
                        self.units.append('-')
                
        self.store = pd.DataFrame({'names': self.names,'geo_codes': self.geo_codes,'types': self.types, 'units': self.units})

        now = datetime.now()
        dt_string = now.strftime("%Y_%m_%d-%H_%M")
        self.results_path = results_folder +'/'+ dt_string
        if not os.path.exists(self.results_path):
            os.makedirs(self.results_path)
        
        self.store.to_csv(self.results_path + '/params.csv',header=False, index=False)
        
        
        
        