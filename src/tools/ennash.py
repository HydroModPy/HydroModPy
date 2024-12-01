# -*- coding: utf-8 -*-
"""
Created on Fri Jul  5 08:57:21 2024

@author: roquesc
"""

import numpy as np

#%% ennash function
def ennash(observed, simulated):
    """ Calculate the Nash-Sutcliffe efficiency coefficient """
    return 1 - np.sum((observed - simulated) ** 2) / np.sum((observed - np.mean(observed)) ** 2)