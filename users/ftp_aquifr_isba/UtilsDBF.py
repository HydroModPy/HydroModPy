# -*- coding: utf-8 -*-
"""
Created on Mon Sep 21 20:21:53 2020

@author: Quentin Courtois
"""
import dbfread
import numpy as np

def build_grid(dbf):
    """
    
    Parameters
    ----------
    dbf : loadead DBF table
    loaded surfex dbf table
    
    Returns
    -------
    
    meshgrid : dict
    
        XGrid : ndarray
        X coordinates of the grid
        
        YGrid : ndarray
        Y coordinates of the grid
        
        X : ndarray
        x coordinates of all the cells
        
        Y : ndarry
        y coordinates of all the cells
    """
    

    #List of coordinates    
    X = [float(record['Xlamb']) for record in dbf.records]
    Y = [float(record['Ylamb']) for record in dbf.records]
    
    #Grid of unique coordinates
    Xun = np.sort(np.unique(X))
    Yun = np.sort(np.unique(Y))
    
    XGrid, YGrid = np.meshgrid(Xun, Yun)
    
    meshgrid = {}
    meshgrid['XGrid'] = XGrid
    meshgrid['YGrid'] = YGrid
    meshgrid['X'] = X
    meshgrid['Y'] = Y
    
    return meshgrid

def identify_cell(meshgrid, cells_id, surfex_ids):
    
    """
    Parameters
    ----------
    
    meshgrid : dict
    
    cells_id : list
    ids of wanted cells
    
    surfex_ids : list
    list of cells ids in the surfex meshgrid
    
    Returns
    -------
    
    x : list
    x coordinate in the grid of the wanted cells
    
    y : list
    y coordinate in the grid of the wanted cells
    
    
    """
    
    cells = []
    for ids in cells_id:
        cells.append(np.where(ids == np.array(surfex_ids))[0].tolist()[0])
    
    x = []
    y = []
    for ids in cells:
        ct = np.where(((meshgrid['X'][ids] == meshgrid['XGrid']) & (meshgrid['Y'][ids] == meshgrid['YGrid'])))
        x.append(ct[0].tolist()[0])
        y.append(ct[1].tolist()[0])
    
    return x, y

def build_ids_list(dbf):
    """
    
    Parameters
    ----------
    dbf : loadead DBF table
    loaded surfex dbf table
    
    Returns
    -------
    list of cells ids
    
    """
    
    return [int(record['ET_ID']) for record in dbf.records]

def load_dbf(file):
    """

    Parameters
    ----------
    file : str
        Name of the .dbf file to open

    Returns
    -------
    DBF instance of file
    """

    return dbfread.DBF(file, load=True)


