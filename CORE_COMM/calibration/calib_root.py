# -*- coding: utf-8 -*-
"""
Created on Wed Nov 17 12:42:06 2021

@author: Alexandre Gauvain
"""
#Modules

#HydroModPy modules
from calibration import calib_basis


class Calibration():
    def __init__(self, params_file, watershed, observations = ['streams']):
        '''
        A class to root calibration

        Parameters
        ----------
        params_file : str
            Path of the parameters file 
        watershed : watershed object
            Used to set the parameters and run model 
        observations : TYPE, optional
            DESCRIPTION. The default is ['streams'].

        Returns
        -------
        None.

        '''
        self.watershed = watershed
        self.file_name = params_file
        self.observations = observations
    
    def exploration(self,resolution=10000):
        method = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations)
        method.build_objective_function(resolution = resolution)
        
        
        