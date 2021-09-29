# -*- coding: utf-8 -*-
"""
Created on Mon Jul 20 13:29:56 2020

@author: Ronan
"""

from hydroeval import *
from scipy.optimize import curve_fit
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def efficiency_criteria(sim, obs):
    RMSE = evaluator(rmse, sim, obs)
    NSE = evaluator(nse, sim, obs)
    NSElog = evaluator(nse, sim, obs, transform='log')
    BAL = (np.sum(sim)/np.sum(obs))
    MARE = evaluator(mare, sim, obs)
    KGEcomp = evaluator(kge, sim, obs) # and its three components (r, α, β)
    KGE = KGEcomp[0]
    return [RMSE[0], NSE[0], NSElog[0], BAL, MARE[0], KGE[0]]


def date_range(first, last, freq):
    time = pd.date_range(str(first),str(last+1),freq=freq)
    return time

def create_sinusoidal(serie, period,
                      amplitude, offset, omega, phase):
    
    def sinusoid(x, A , offset, omega, phase):
        return A*np.sin(omega*x+phase) + offset
    
    def get_p0(Y, T):
        A0 = (max(Y[0:T]) - min(Y[0:T]))/2
        offset0 = Y[0]
        phase0 = 0
        omega0 = 2.*np.pi/T
        return [A0, offset0, omega0, phase0]
    
    if period=='daily':
        T=365
    if period=='monthly':
        T=12
        
    X = serie.index
    Y = serie[0]
    param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, T))
    param[0] = param[0] * amplitude # Amplitude : max
    param[1] = param[1] * offset # Offset : shift v
    param[2] = param[2] * omega # Omega : cycles
    param[3] = param[3] * phase # Phase : shift h
    sinus = sinusoid(X, *param)
    sinus = np.array(sinus)
    
    return sinus
