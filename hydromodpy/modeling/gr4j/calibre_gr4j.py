# -*- coding: utf-8 -*-
"""
Created on Fri Jul  5 08:59:08 2024

@author: roquesc
"""

import numpy as np
from scipy.optimize import least_squares
import sys
import os
from hydromodpy.tools import get_logger

# ROOT DIRECTORY

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
# root_dir = dirname(dirname(os.getcwd())) 
sys.path.append(root_dir)
cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
logger = get_logger(__name__)
logger.info("Root path directory is: %s", root_dir.upper())

# HYDROMODPY MODEULES

import hydromodpy
import importlib
importlib.reload(hydromodpy)
from hydromodpy.modeling.gr4j.gr4j_cal import gr4j_cal
from hydromodpy.modeling.gr4j.ennash import ennash


#%% Function calibre

def calibre_gr4j(modele, xdata, ydata, init, mini, maxi):
    if np.isnan(ydata).any():
        indicN = np.isnan(ydata)
        logger.warning(
            "Interpolated %.2f %% of target dataset due to NaN values",
            np.sum(indicN) / len(ydata) * 100,
        )
        indic = np.arange(len(ydata))
        ydata[indicN] = np.interp(indic[indicN], indic[~indicN], ydata[~indicN])
    
    # options = {'disp': True}
    
    if 'indices' not in xdata:
        xdata['indices'] = np.arange(len(xdata['p']))
    
    def model_fun_gr4j(par):
        input_data = {
            'p': xdata['p'],
            'etp': xdata['etp'],
            't': xdata['t'],
            'indices': xdata['indices'],
            'transform': xdata['transform'],
            'type': xdata['type'],
            'ratio': 1.0  # Add a default ratio if needed
        }
        return gr4j_cal(par, input_data)[0] - ydata
        #return - np.sqrt(np.mean((gr4j_cal(par, input_data)[0] - ydata) ** 2.0))
    
    result = least_squares(model_fun_gr4j, init, bounds=(mini, maxi))
    
    par = result.x
    resnorm = result.cost
    
    logger.info('GR4J calibration completed successfully')
    logger.info('Parameters: %s', par)
    
    qsim, out = gr4j_cal(par, xdata)
    nash = ennash(ydata, qsim)
    logger.info('Nash coefficient: %.4f', nash)
    
    bilan = np.mean(qsim) / np.mean(ydata)
    logger.info('Water balance ratio: %.4f', bilan)
    
    # plt.figure()
    # if len(xdata['indices']) == len(xdata['p']):
    #     plt.plot(xdata['date'], ydata, label='Observé')
    #     plt.plot(xdata['date'], qsim, 'r', label='Simulé')
    # else:
    #     plt.plot(xdata['date'], eval(f"{xdata['transform']}(out['Qsim'])"), 'r--', label='Simulation complète')
    #     plt.plot(xdata['date'][xdata['indices']], qsim, 'ro', label='Simulation partielle')
    #     plt.plot(xdata['date'][xdata['indices']], ydata, 'bo', label='Observation partielle')
    
    # plt.legend()
    # plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    # plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    # plt.gcf().autofmt_xdate()
    # plt.show()
    
    return par, nash, bilan
