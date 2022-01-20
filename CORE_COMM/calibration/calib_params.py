# -*- coding: utf-8 -*-
"""
Created on Fri Nov 12 10:53:03 2021

@author: Alexandre Gauvain
"""
import sys
import pandas as pd
import numpy as np
import re
       

class CalibParams(): 
    def __init__(self, file_name, watershed):
        """ 
        Constructor
        
        Arguments
        --------- 
        """
        # Parameter Values
        self.name = []
        # Parameter Units 
        self.u = []
        # Bounds of parameters
        self.p_init = []
        self.p_min = []
        self.p_max = []
        
        #load param values
        self.load_param_values(file_name)
        #check if watershed.hydrodynamic.calib_zones matches with Parameter names
        self.check_param_values(watershed)
        #Convert hydraulic conductivity values to log values
        self.convert_k_lin_to_log()

    def load_param_values(self, file_name):
        """ 
        Loads parameter file 
            From file called calib_params.csv
        File structure
            params, init_values, lower_bounds, higher_bounds, units
        File example
            k1, 8.60, 86, 0.0086, m/j
            k2, 0.086, 86, 0.0086, m/j
            theta1, 0.1, 0.01, 0.2, -
            e1, 30, 10, 100, m
        Parameters codes
            k : hydraulic conuctivity
            theta : porosity
            e : thickness
        Argument
        --------
        file_name : str
            Name of the file
        """
        # Loads file in which parameters are stored   
        temp = pd.read_csv(file_name,header=0)
        # Affects param_values to the distribution
        self.name = temp.params.values
        self.u = temp.units.values
        self.p_init = temp.init_values.values
        self.p_min =  temp.lower_bounds.values
        self.p_max =  temp.higher_bounds.values
        self.p = temp.init_values.values
        
        
    def linear_to_log(self, lin_values):
        log_values = np.log10(lin_values)
        return log_values
    
    def log_to_linear(self, log_values):
        lin_values = 10**(log_values)
        return lin_values
    
    def check_param_values(self, watershed):
        self.num_zone = [int(re.search(r'\d+', name).group()) for name in self.name]
        zones = np.intersect1d(self.num_zone,self.num_zone)
        zones_array = np.intersect1d(watershed.hydrodynamic.calib_zones, watershed.hydrodynamic.calib_zones)
        if len(zones) == len(zones_array):
            if sum(zones) == sum(zones_array): 
                pass
        else:
            sys.exit("watershed.hydrodynamic.calib_zones (ex: 1, 2) must be have the same number zones of calibrated parameters (ex: k1 , k2) in calib_params.csv")
        
    def convert_k_lin_to_log(self):
        for i in range(0, len(self.name)):
            if self.name[i][0] == 'k':
                self.p_init[i] = self.linear_to_log(self.p_init[i])
                self.p_min[i] =  self.linear_to_log(self.p_min[i])
                self.p_max[i] =  self.linear_to_log(self.p_max[i])
                self.u[i] = self.u[i] + str(' (log)')
    
    def random_uniform(self,rng=None):
        """ 
        Random uniform generation of lpm 
            Modifies self with unifom random generation of parameters 
            Parameters are drawn from get_param_interval()
        """
        # Gets parameter range
        res=(self.p_min, self.p_max); pmin = res[0]; pmax = res[1]
        # Generation of parameter within the range 
        if(rng==None):
            rng = np.random.default_rng()
        param=[]
        for i in range(0,len(pmin)):
            param.append(pmin[i] + (pmax[i] - pmin[i]) * rng.random())
        # Loads parameters in self
        self.p_init = param
    