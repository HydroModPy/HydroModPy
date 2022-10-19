# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

#HydroModPy modules
import os
from calibration import calib_basis, calib_simplex, calib_dichotomy, calib_exploration
from tools import toolbox

#%% CLASS

class Calibration():
    
    #%% INIT
    
    def __init__(self, params_file, watershed, observations = ['streams']):
        """
        
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

        """
        
        self.watershed = watershed
        self.file_name = params_file
        self.observations = observations
        
        self.calibration_folder = os.path.join(self.watershed.watershed_folder, 'results_calibration')
        if not os.path.exists(self.calibration_folder):
            toolbox.create_folder(self.calibration_folder)
    
    #%% EXPLORATION
    
    def exploration(self, resolution=10, parallel=False):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations, self.calibration_folder)
        exploration = calib_exploration.CalibrationExploration(basis, resolution=resolution, parallel=parallel)
        exploration.perform()
    
    #%% SIMPLEX
    
    def simplex(self, init_multiples_n=1):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations, self.calibration_folder)
        if init_multiples_n == 1:
            simplex = calib_simplex.CalibrationSimplex('Simplex', basis)
            res = simplex.perform()
        else:
            simplex = calib_simplex.CalibrationSimplex('Simplex_init_multipes', basis, init_multiples_n=init_multiples_n)
            res = simplex.perform()
        return res
    
    #%% DICHOTOMY
    
    def dichotomy(self, gap=10):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations, self.calibration_folder)
        dichotomy = calib_dichotomy.CalibrationDichotomy(basis, gap=gap)
        dichotomy.perform()   
        
    #%% METROPOLIS HASTINGS
    
    def metropolis_hastings(self):
        basis = calib_basis.CalibrationBasis(self.file_name, self.watershed, self.observations, self.calibration_folder)
    
#%% NOTES
        
