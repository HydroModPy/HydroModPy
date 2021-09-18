# -*- coding: utf-8 -*-
"""
Created on Mon Jul 20 13:29:56 2020

@author: Ronan
"""

from scipy.optimize import curve_fit
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

#%% 

def recharge_sinusoidal(path_h5, variable, scenario, period):
    
    def sinusoid(x,A,offset,omega,phase):
        return A*np.sin(omega*x+phase) + offset
    
    def get_p0(Y, period):
        A0 = (max(Y[0:period]) - min(Y[0:period]))/2
        offset0 = Y[0]
        phase0 = 0
        omega0 = 2.*np.pi/period
        return [A0, offset0, omega0, phase0]
    
    raw = pd.read_hdf(path_h5, variable+'/'+scenario)
    serie = raw.MEAN
    serie = serie.reset_index()
    X = serie.index
    Y = serie.values
    param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, period))
    param[0] = param[0] * 1 # Amplitude : max
    param[1] = param[1] * 1 # Offset : shift v
    param[2] = param[2] * 1 # Omega : cycles
    param[3] = param[3] * 1 # Phase : shift h
    sinus = sinusoid(X, *param)
    sinus = np.array(sinus)

    return serie, sinus


