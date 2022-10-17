# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import copy as copy
import numpy as np     
import pandas as pd                            
from scipy.optimize import minimize, Bounds
import time
import datetime

from calibration import global_parameters as gp                          
from calibration import calib_basis as calbas

import matplotlib.pyplot as plt
from calibration import tools_figures_additional as figadd        

#%% CLASS

class CalibrationDichotomy(calbas.CalibrationBasis):
    
    #%% INIT
    
    def __init__(self, calib_basis=None, gap=10):
        
        self.gap = gap
        
        # Affectation of parent class 
        if(calib_basis!=None): 
            self.update_calibbasis(calib_basis)
        
        self.recharge = self.watershed.forcing.recharge
        
        # print(self.recharge)
    
    #%% UPDATE
    
    def update_calibbasis(self,calib_basis): 
        """
        Updates parent class CalibrationBasis with calib_basis
        
        Arguments
        ---------
        calib_basis: CalibrationBasis
            Base Class Calibration Problem
        
        """
        super(CalibrationDichotomy,self).__dict__.update(calib_basis.__dict__)
    
    #%% PERFORM
    
    def perform(self):
        dichotomy_results = self.__Dichotomy()
        return dichotomy_results
    
    #%% METHOD
    
    def __Dichotomy(self):
        
        params_xyz = []
        
        p_min =  self.params.p_min[0]
        p_max =  self.params.p_max[0]
        print(p_min, p_max)
        
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        
        df = pd.DataFrame()
                
        # name = 'exp_' + str(len(self.params.name)) + 'p_res_'
        now = datetime.datetime.now()
        # name = name + now.strftime("%d_%m_%Y_%Hh%M") 
        name = self.param_ident + '_' + now.strftime("%Y-%m-%d_%Hh%Mm%Ss") 
        obj_function = []
        params_values = []
        
        compt = 0
        
        while (diff > ((self.gap/100) * half)):
            half = (p_min + p_max) / 2
            
            # hyd_cond = half * self.recharge # if K/R in calib_params.csv
            hyd_cond = half.copy() # if K in calib_params.csv
            kr = hyd_cond / self.recharge
            
            params_xyz.append(hyd_cond)
            indicator = self.objective_function([hyd_cond])
            
            obs = self.data_obs['streams'][-1]
            sim = self.data_sim['streams'][-1]
            
            if sim > obs:
                p_min = half
            if sim < obs:
                p_max = half
                
            diff = p_max - p_min
            
            print('==> Simulation : '+str(compt))
            print('    K/R = '+str(round(kr, 4)))
            print('    Gap = '+str(round((self.gap/100) * kr, 4)))
            print('    Indicator = '+str(round(indicator, 4)))

            df.loc[compt,'KR'] = round(kr, 4)
            df.loc[compt,'K'] = round(hyd_cond, 4)
            df.loc[compt,'Obs'] = round(obs, 4)
            df.loc[compt,'Sim'] = round(sim, 4)
            df.loc[compt,'Indicator'] = round(indicator, 4)
            
            compt += 1
            
            params_values.append(hyd_cond)
            obj_function.append(indicator)
            
        # figadd.figure_init(xlab=self.params.name[0],ylab="",figname='objective function 1D of ' + self.params.name[0])
        # plt.plot(params_values, obj_function)
        # plt.yscale("log")
        # if self.params.name[0] == 'k':
        #     plt.xscale("log")
        
        df.to_csv(self.directory_results+'/'+'_dicothomy'+'.csv', sep=';')
        
        self.write_results(name, obj_function, params_values, params_xyz)
        
        return indicator
        
#%% NOTES

