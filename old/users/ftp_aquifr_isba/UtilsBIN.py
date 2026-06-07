# -*- coding: utf-8 -*-
"""
Created on Mon Feb 22 2021

@author: Alexandre Gauvain 
"""

import numpy as np
import pandas as pd

def extract_bin(surfex, sim, var, sce):
    """
    Parameters
    ----------
    surfex : surfex object
    sim : list of simulations
    var : list of variables
    sce : list of scenarios

    Returns
    -------
    chronic : np masked array
    """
    # variable names in binary
    if var == 'REC':
        var_name = 'DRAIN'
    if var == 'RUN':
        var_name = 'RUNOFF'
    if sce == 'RCP2.6':
        sce_name = 'RCP26'
    if sce == 'RCP4.5':
        sce_name = 'RCP45'
    if sce == 'RCP8.5':
        sce_name = 'RCP85'

    if sce != 'historic':
        year_start = 2005
        date_start = '2005-08-01'
        year_end = 2100
        date_end = '2100-07-31'

    if sce == 'historic':
        year_start = 1950
        date_start = '1951-08-01'
        year_end = 2010
        date_end =  '2010-07-31'   

    times = pd.date_range(start=date_start, end=date_end)
    VAR_data = pd.DataFrame([], columns=surfex.cells_list).apply(pd.to_numeric)
    folder = surfex.fold_data + sim +'/'+ var + '/' + sce + '/'
    for date in np.linspace(year_start,year_end-1,year_end-year_start,dtype=int):
        if sce != 'historic':
            file = var_name+'_'+sim+'_'+sce_name+'_'+str(date)+'_'+str(date+1)+'.bin'
        else:
            file = var_name+'_'+sim+'_'+str(date)+'_'+str(date+1)+'.bin'
        VAR = np.fromfile(folder+file,'>f4') #codec <f4 to open the binary files
        VAR = VAR.reshape((int(len(VAR)/9892),9892))
        VAR_cells = extract_values(VAR, surfex.cells_list)
        VAR_data = VAR_data.append(VAR_cells, ignore_index=True)
    chronic = pd.DataFrame(VAR_data, columns=surfex.cells_list).apply(pd.to_numeric)
    chronic['englobe'] = VAR_data.mean(axis=1) # mean to study site zone
    chronic['date'] = pd.Series(times)
    chronic = chronic.set_index('date')
    return chronic

def extract_values(VAR, cells_list):
    """
    
    Parameters
    ----------
    VAR : np masked array
    all values
    
    cells_list : list

    Returns
    -------
    var : nd.array
    var for wanted cells in the order of x_cells and y_cells

    """
    var=[]
    for i in cells_list:
        var.append(VAR[:, i-1])     
    var = np.array(var)
    var[var>1e+10] = np.nan
    var = pd.DataFrame(var.T, columns=cells_list).apply(pd.to_numeric)
    return var