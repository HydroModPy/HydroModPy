# coding:utf-8

import os
import sys
import pandas as pd
from IPython.core.debugger import set_trace as st

class Params:
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
        
    Returns
    ----------

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
        BV : instance of watershed object
            data and structure of the watershed
        """
        
        self.names = []
        self.geo_codes = []
        self.types = []
        self.units = []
        
        self.create_params(BV)
        
    def create_params(self, BV):
        """
        Create hydraulic parameters
        
        Parameters
        ----------
        geology_code : list of int
            geological codes from geology python object
        folder : str
            the path where we save the params file
        """
        # reads parameter types to calibrate amont K,theta,e
        self.list = list(pd.read_csv(BV.modeling_data_folder + 'params_to_calibrate.csv'))
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
                for idunit in range(0, len(BV.geology.geology_code)):
                    self.names.append(paramtype+"_"+str(idunit))
                    self.geo_codes.append(BV.geology.geology_code[idunit])
                    if paramtype == 'k':
                        self.types.append('hydraulic conductivity')
                        self.units.append('m/s')
                    elif paramtype == 'theta':
                        self.types.append('porosity')
                        self.units.append('-')
                
        self.store = pd.DataFrame({'names': self.names,'geo_codes': self.geo_codes,'types': self.types, 'units': self.units})
        # JR: déplacer le fichier dans les résultats de la simulation
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
        
        
        