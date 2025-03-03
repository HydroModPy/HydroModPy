# -*- coding: utf-8 -*-
"""
Created on Mon Sep 21 20:22:16 2020

@author: Quentin Courtois
"""

import netCDF4
import numpy as np

def load_hdf(netcfd, sub):
    """

    Parameters
    ----------
    fhdf : str
        name of the .nc file to load

    Returns
    -------
    VAR : np masked array
    all var

    """
    
    # variable names in netcdf

    if sub == 'ETP':
        name = 'etp'
    if sub == 'PPT':
        name = 'prcp'
    if sub == 'REC':
        name = 'drainage'
    if sub == 'RUN':
        name = 'runoff'
    if sub == 'TAS':
        name = 'tas'
        
    RtGrp = netCDF4.Dataset(netcfd, 'r', format='NETCDF4')
    VAR = RtGrp.variables[name][:]
    RtGrp.close()
        
    return VAR

def extract_values(VAR, x_cells, y_cells):
    """
    
    Parameters
    ----------
    VAR : np masked array
    all drains
    
    x_cells : list
    x coordinates of the wanted cells in DRN grid

    y_cells : list
    y coordinates of the wanted cells in DRN grid

    Returns
    -------
    var : nd.array
    var for wanted cells in the order of x_cells and y_cells

    """
    var = []
    for x, y in zip(x_cells, y_cells):
        var.append(VAR[:, x, y])
        
    var = np.array(var)
    
    var[var>1e+10] = np.nan
    
    return var