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
    
    def __init__(self, gap=10):

    diff = last - first
    half = (first + last) / 2
    df = pd.DataFrame()
    
    compt = 0
    while (diff > ((gap/100) * half)):
        half = (first + last) / 2
        hyd_cond = half * recharge
        
        run modflow
        matrix modflow
        results modflow
        call class Streams
            indicator, mean_sim_to_obs, mean_obs_to_sim
        
        if indicator > 0: # condition > 1
            first = half
        else:
            last = half
            
        diff = last - first
        
        print('==> Simulation : '+str(compt))            
        print('    Ecart = '+str(round(diff,2)))
        print('    K/R = '+str(round(half, 2)))
        print('    Condition = '+str(condition))
        print('    Gap = '+str(round((gap/100) * half, 2)))
        
        df.loc[compt,'KR'] = round(half, 4)
        df.loc[compt,'K'] = round(hyd_cond, 4)
        df.loc[compt,'Sflow'] = round(mean_sim_to_obs, 4)
        df.loc[compt,'Oflow'] = round(mean_obs_to_sim, 4)
        df.loc[compt,'Cond'] = round(condition, 4)    
        
        compt += 1
    
    df.to_csv(os.path.join(simulations_folder, '_dichotomy_'+type_river+'.csv'), sep=';', index=True)