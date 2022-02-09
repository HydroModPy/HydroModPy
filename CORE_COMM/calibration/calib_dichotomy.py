# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 14:22:05 2022

@author: ronan
"""

import copy as copy
import numpy as np     
import pandas as pd                            
from scipy.optimize import minimize, Bounds
import time

from calibration import global_parameters as gp                          
from calibration import calib_basis as calbas

class CalibrationDichotomy(calbas.CalibrationBasis):
    
    def __init__(self, calib_basis=None, gap=10):
        
        self.gap = gap
        
        # Affectation of parent class 
        if(calib_basis!=None): 
            self.update_calibbasis(calib_basis)
            
        self.recharge = self.watershed.forcing.recharge
        # print(self.recharge)
        
    def update_calibbasis(self,calib_basis): 
        """
        Updates parent class CalibrationBasis with calib_basis
        
        Arguments
        ---------
        calib_basis: CalibrationBasis
            Base Class Calibration Problem
        
        """
        super(CalibrationDichotomy,self).__dict__.update(calib_basis.__dict__)
    
    def perform(self):
        dichotomy_results = self.__Dichotomy()
        return dichotomy_results
    
    def __Dichotomy(self):
        
        p_min =  self.params.p_min[0]
        p_max =  self.params.p_max[0]
        
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        
        df = pd.DataFrame()
                
        compt = 0
        
        while (diff > ((self.gap/100) * half)):
            half = (p_min + p_max) / 2
            
            # hyd_cond = half * self.recharge # if K/R in calib_params.csv
            hyd_cond = half.copy() # if K in calib_params.csv
            
            indicator = self.objective_function([hyd_cond])
            
            obs = self.data_obs['streams'][-1]
            sim = self.data_sim['streams'][-1]
            
            if sim > obs:
                p_min = half
            if sim < obs:
                p_max = half
                
            diff = p_max - p_min
            
            print('==> Simulation : '+str(compt))
            print('    K/R = '+str(round(half, 4)))
            print('    Gap = '+str(round((self.gap/100) * half, 4)))
            print('    Indicator = '+str(round(indicator, 4)))

            df.loc[compt,'KR'] = round(half, 4)
            df.loc[compt,'K'] = round(hyd_cond, 4)
            df.loc[compt,'Obs'] = round(obs, 4)
            df.loc[compt,'Sim'] = round(sim, 4)
            df.loc[compt,'Indicator'] = round(indicator, 4)
            
            compt += 1
        
        df.to_csv(self.directory_results+'/'+'_dicothomy'+'.csv', sep=';')
    
        return indicator
        