# -*- coding: utf-8 -*-
"""
Created on Fri Jul  5 07:52:29 2024

@author: roquesc
"""

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d


#%% ETP Turc
def etp_turc(latitude, dates, temperature, henso):
    # Constants
    latN = np.array([30, 40, 50, 60])
    
    Igatab = np.array([
        [508, 364, 222, 87.5],
        [624, 495, 360, 215],
        [764, 673, 562, 432],
        [880, 833, 764, 676],
        [950, 944, 920, 880],
        [972, 985, 983, 970],
        [955, 958, 938, 908],
        [891, 858, 800, 728],
        [788, 710, 607, 487],
        [658, 536, 404, 262],
        [528, 390, 246, 111],
        [469, 323, 180, 55.5]
    ])
    
    dureetab = np.array([
        [10.45, 9.71, 8.58, 6.78],
        [11.09, 10.64, 10.07, 9.11],
        [12, 11.96, 11.90, 11.81],
        [12.9, 13.26, 13.77, 14.61],
        [13.71, 14.39, 15.46, 17.18],
        [14.07, 14.96, 16.33, 18.73],
        [13.85, 14.68, 15.86, 17.97],
        [13.21, 13.72, 14.49, 15.58],
        [12.36, 12.46, 12.63, 12.89],
        [11.45, 11.15, 10.77, 10.14],
        [10.67, 10, 9.08, 7.58],
        [10.23, 9.39, 8.15, 6.3]
    ])
    
    nbjours = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    nbjourscumul = np.hstack(([0], np.cumsum(nbjours)))
    
    # Interpolation to the desired latitude
    Iga_interp = interp1d(latN, Igatab.T, axis=0, kind='linear', fill_value="extrapolate")
    duree_interp = interp1d(latN, dureetab.T, axis=0, kind='linear', fill_value="extrapolate")
    
    Iga = Iga_interp(latitude)
    duree = duree_interp(latitude)
    
    # Temporal interpolation
    Iga = np.hstack((Iga[-1], Iga, Iga[0]))
    duree = np.hstack((duree[-1], duree, duree[0]))
    
    jjj = np.hstack(([-15], 15 + np.cumsum(nbjours), [15 + np.sum(nbjours) + 15]))
    
    # Program main part
    ETP = np.full(len(temperature), np.nan)
    
    # Transform the date to the day number in the year
    dates = pd.to_datetime(dates)
    jourdumois = dates.day
    joursecoules = nbjourscumul[dates.month - 1]
    jjjtemp = jourdumois + joursecoules
    
    # Interpolate the constants to the requested days
    Iga_func = interp1d(jjj, Iga, kind='linear', fill_value="extrapolate")
    duree_func = interp1d(jjj, duree, kind='linear', fill_value="extrapolate")
    
    Igatemp = Iga_func(jjjtemp)
    dureetemp = duree_func(jjjtemp)
    
    # ETP Turc formulation
    Rg = Igatemp * (0.18 + 0.62 * henso / dureetemp)
    ETP = 0.013 * temperature / (temperature + 15) * (Rg + 50)
    
    # Case of negative temperatures -> define ETP=0
    ETP[temperature <= 0] = 0
    
    return ETP