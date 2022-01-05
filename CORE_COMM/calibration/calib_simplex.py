# -*- coding: utf-8 -*-
"""
Created on Wed Mar 24 20:35:54 2021

@author: Alexandre Gauvain
"""

import copy as copy
import numpy as np                                 
from scipy.optimize import minimize, Bounds
import time

from calibration import global_parameters as gp                          
from calibration import calib_basis as calbas


class CalibrationSimplex(calbas.CalibrationBasis): 
    """ 
    Simplex calibration method
    
    Inheritance
    -----------
    CalibrationBasis: 
        Base class for calibration containing the problem to calibrate
    
    Attributes
    ----------
    method: str
        Precise calibration method (simplex, simplex_init_multiples)
    __simplex_xatol: float
        Absolute Tolerance of simplex method
    __simplex_fatol: float
        Relative Tolerance of simplex method
    simplex_init_multiples_n: int
        Number of simplex problems to run 
    simplex_init_multiples_seed_rng: int
        Seed of the random number generator for the initial positions of the simplex
    
    Methods
    -------
    update_calibbasis(self,calib_basis): 
        Updates parent class CalibrationBasis with calib_basis
    perform(self): 
        Performs calibration with the selected method
    """
    
    def __init__(self,calibration_method,calib_basis=None,init_multiples_n=2,fuq_n=10):
        """ 
        Constructor
        
        Parameters 
        ----------
        calibration_method: str
            Precise calibration method (simplex, simplex_init_multiples)        
        """
        
        self.method = calibration_method
        # Simplex Parameters
        self.__simplex_xatol = 1e-4
        self.__simplex_fatol = 1e-4
        # Simplex multiple init point Parameters
        self.simplex_init_multiples_n = init_multiples_n
        self.simplex_init_multiples_seed_rng = 12345
        # forward_uncertainty_quantification parameters
        self.fuq_seed_rng = 123456
        self.fuq_n = fuq_n
        
        # Affectation of parent class 
        if(calib_basis!=None): 
            self.update_calibbasis(calib_basis)
    
    
    def update_calibbasis(self,calib_basis): 
        """
        Updates parent class CalibrationBasis with calib_basis
        
        Arguments
        ---------
        calib_basis: CalibrationBasis
            Base Class Calibration Problem
        
        """
        super(CalibrationSimplex,self).__dict__.update(calib_basis.__dict__)
    
    
    def perform(self):
        """
        Performs calibration with the selected method
            Monitor run time necessary
        
        Returns
        -------
        float
            Minimal value of objective function 
                
        """
        start = time.time()
        # Performs calibration with the right option
        if self.method == "Simplex" :
            lpm_results = self.__Simplex()
        elif self.method == "Simplex_init_multipes" :
            lpm_results = self.__Simplex_init_multipes()
        elif self.method == "forward_uncertainty_quantification" :
            lpm_results = self.__forward_uncertainty_quantification()
        else:
            print("option not defined in Simplex calibration method\t", self.method)
        end = time.time()
        self.time_perform = end - start
        return lpm_results
        
        
    def __Simplex(self,param=None):
        """ 
        Simplex calibration method
            Values and Errors stored in self.concentration_sampled.cv.values
            Tracer parameters 
        
        Arguments
        ---------
        param: array of floats
            Initial conditions of the simplex
            == None : initial parameters red from LPM file 
        
        Returns
        -------
        lpm_results (modification of lpm attribute)
            Optimal model found
        """

        # -----------------INITIALIZATION -------------------------
        # Initial value of parameters: Adapation to the type of LPM
        if (param==None):
            p0 = self.params.p_init
        else: 
            p0 = param
            
        bounds = []
        for i in range(0, len(self.params.name)):
            bounds.append((self.params.p_min[i],self.params.p_max[i]))
        print(bounds)
        # -----------------OPTIMIZATION FUNCTION ------------------
        # Minimization function: Simplex Method
        res = minimize(self.objective_function, p0, 
                method='nelder-mead', options={'xatol': self.__simplex_xatol, 'fatol': self.__simplex_fatol, 'disp': False}, bounds=bounds) # 'nelder-mead'
                # method='BFGS', options={'disp': True})
        
        print(p0, res)
        # -----------------POSTPROCESSING -------------------------
        # Stores the solution "res.x" provided by "minimize"  
        
        '''lpm_results = LPM_dist.LPMDist(lpm=self.lpm,c_names=self.concentration_sampled.names_dates())
        lpm_results.dist_append(self.lpm.p,
                             obj_function=np.sqrt(res.fun/len(self.concentration_sampled.cv)),
                             concentrations=self.tracers.convolution_perform(self.lpm),
                             param_in_bounds=self.lpm.param_within_bounds(self.lpm.p))'''
        
        # returns objective function 
        return res
     
        
    def __Simplex_init_multipes(self):
        """ 
        Simplex with multiple initiation points 
            Runs the Simplex method with multiple initial points 
        
        Arguments
        ---------
        
        Returns
        -------
        lpm_results: LPMDist
            Optimal models found
        """
        
        # Random Number Generator
        rng = np.random.default_rng(self.simplex_init_multiples_seed_rng)
        # Loop over the initial conditions for the parameters
        store = []
        for i in range(self.simplex_init_multiples_n):
            # Random choice of lpm in self.lpm
            self.lpm.random_uniform(rng=rng)
            # Performs optimization 
            store.append(self.__Simplex(param = self.lpm.get_parameters_to_array()))
        return store
        
    
    def __forward_uncertainty_quantification(self):
        """ 
        Forward_uncertainty_quantification strochastic sampling Algorihm
            to calibrate lpm accounting for uncertainty in the data 
        
        Calibration itself uses the classical Simplex algorithm
            
        Parameters
        ----------
        self.fuq_n: int
            number of concentration samples, of the order of 10^(1-3 * number of parameters)

        Returns
        -------
        self.lpm.p_dist (modification of attribute)
            All Optimal models found
            
       
        
        # Initialization of results structure
        lpm_results = LPM_dist.LPMDist(self.lpm,c_names=self.concentration_sampled.names_dates())
        # Surrogate calibration structure for the simplex method used for each of the sampled data set
        lpm_simplex = copy.deepcopy(self)
        # Calibration is performed with the classical Simplex algorithm
        lpm_simplex.method = "Simplex_init_multipes"
        # Initialization of random number generator      
        rng = np.random.default_rng(self.fuq_seed_rng)
        # Loop to sample the uncertainty range
        for i in range(self.fuq_n):
            # Samples randomly uncertainty in the data
            lpm_simplex.concentration_sampled = self.concentration_sampled.sample_concentrations_with_errors(rng)
            # Calibration with this set of concentrations
            lpm_results.append(lpm_simplex.__Simplex())
        return lpm_results
        """ 

    def write_parameters(self,file_name):
        """ 
        Writes parameters of calibration
        """
        data={}
        data['method']=self.method
        if self.method == "Simplex" or self.method == "Simplex_init_multipes" or self.method == "forward_uncertainty_quantification":
            data['xatol']=self.__simplex_xatol
            data['fatol']=self.__simplex_fatol
        if self.method == "Simplex_init_multipes" or self.method == "forward_uncertainty_quantification":
            data['init_mutiples']=self.simplex_init_multiples_n
        if self.method == "forward_uncertainty_quantification" :
            data['fuq_n'] = self.fuq_n         
        file = open(file_name,"w")
        for key, val in data.items():
            file.write(key+'\t'+str(val)+'\n')
        file.close()
        
        
    def write_results_spec(self,data):
        """
        Specific contribution of the daughter class to the calibration results
        
        Argumments
        ----------
        data: dictionary
            results to be stored
        
        """
        pass
