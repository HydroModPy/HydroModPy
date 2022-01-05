# -*- coding: utf-8 -*-
"""
Created on Mon Jul 20 13:29:56 2020

@author: Ronan
"""

from hydroeval import *
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def efficiency_criteria(sim, obs):
    RMSE = evaluator(rmse, sim, obs)
    nRMSE = RMSE[0] / obs.mean() # %
    NSE = evaluator(nse, sim, obs)
    NSElog = evaluator(nse, sim, obs, transform='log')
    BAL = (np.sum(sim)/np.sum(obs))
    MARE = evaluator(mare, sim, obs)
    KGEcomp = evaluator(kge, sim, obs) # and its three components (r, α, β)
    KGE = KGEcomp[0]
    return [RMSE[0], nRMSE, NSE[0], NSElog[0], BAL, MARE[0], KGE[0]]

def date_range(first, last, freq):
    time = pd.date_range(str(first),str(last+1),freq=freq)
    return time

