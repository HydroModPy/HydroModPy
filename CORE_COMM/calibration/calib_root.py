# -*- coding: utf-8 -*-
"""
Created on Wed Nov 17 12:42:06 2021

@author: Alexandre Gauvain
"""
#Modules

#HydroModPy modules
from calibration import calib_basis, calib_simplex, calib_dichotomy


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
    
    def exploration(self,resolution=100):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations)
        basis.build_objective_function(resolution = resolution)
    
    def simplex(self, init_multiples_n=1):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations)
        if init_multiples_n == 1:
            simplex = calib_simplex.CalibrationSimplex('Simplex', basis)
            res = simplex.perform()
        else:
            simplex = calib_simplex.CalibrationSimplex('Simplex_init_multipes', basis, init_multiples_n=init_multiples_n)
            res = simplex.perform()
        return res
    
    def metropolis_hastings(self):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations)
    
    def dichotomy(self, gap=10):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations)
        dichotomy = calib_dichotomy.CalibrationDichotomy(basis, gap=gap)
        res = dichotomy.perform()
        

    