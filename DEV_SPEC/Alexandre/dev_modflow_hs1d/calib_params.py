# coding:utf-8

import os
import sys
import pandas as pd
from IPython.core.debugger import set_trace as st

class Params:
    """
    A class used to create hydraulic parameters of the watershed

    Attributes
    ----------
    BV : Python object
            contains the informations of observed data
        
    Returns
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
    
    def __init__(self, BV):
        """
        Constructor
        
        Parameters
        ----------
        geology_code : list of int
            geological codes from geology python object
        folder : str
            the path where we save the params file
        """
        
        self.names = []
        self.geo_codes = []
        self.types = []
        self.units = []
        
        self.create_params(BV)
        
    def create_params(self, BV):
        """
        Load hydraulic parameters
        
        Parameters
        ----------
        geology_code : list of int
            geological codes from geology python object
        folder : str
            the path where we save the params file
        """
        self.list = list(pd.read_csv(BV.modeling_data_folder + 'params_to_calibrate.csv'))
        for i in self.list:
            for j in range(1, len(BV.geology.geology_code)+1):
                if i == 'k':
                    self.names.append(i+str(j))
                    self.geo_codes.append(BV.geology.geology_code[j-1])
                    self.types.append('hydraulic conductivity')
                    self.units.append('m/s')
                elif i == 'theta':
                    self.names.append(i+str(j))
                    self.geo_codes.append(BV.geology.geology_code[j-1])
                    self.types.append('porosity')
                    self.units.append('-')
            if i == 'e':
                self.names.append(i)
                self.geo_codes.append('-')
                self.types.append('thickness')
                self.units.append('m')
                
        self.store = pd.DataFrame({'names': self.names,'geo_codes': self.geo_codes,'types': self.types, 'units': self.units})
        self.store.to_csv(BV.modeling_data_folder + 'params.csv',header=False, index=False)
        
    
    def load_params(self):
        """
        Load hydraulic parameters

        Parameters
        ----------
        sound : str, optional
            The sound the animal makes (default is None)

        Returns
        ------
        NotImplementedError
            If no sound is set for the animal or passed in as a
            parameter.
        """
        
        
        