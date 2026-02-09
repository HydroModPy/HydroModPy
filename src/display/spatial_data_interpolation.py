# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

# %% LIBRAIRIES

# Python
import pandas as pd
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
# Hydromodpy
from tools.toolbox import crs_reprojection
# Flopy
import flopy


# %% CLASS


class SpatialDataInterpolation():

    """ 
    TODO@TB: Description WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self):
        """
        Initialize method. 

        Parameters
        ----------
        """
        
    def from_csv_file(self,
                      chron_fpath: str,
                      pos_fpath: str,
                      sgrid: object,
                      interpolation_method: str = 'linear',
                      dateheader_chron: str = 'date',
                      dateformat_chron: str = '%Y-%m-%d %H:%M:%S',
                      colsep_chron: str = '\t',
                      xheader_map_pos: str  = 'X',
                      yheader_map_pos: str  = 'Y',
                      idheader_map_pos: str = 'id',
                      crs_map_pos: str      = None,
                      colsep_map_pos: str   = '\t'):
                        
        # Data chronicles
        tdata = pd.read_csv(chron_fpath, sep = colsep_chron, index_col=dateheader_chron)
        tdata.index = pd.to_datetime(tdata.index, format = dateformat_chron) 
        
        # location of data points
        mappos = pd.read_csv(pos_fpath, sep = colsep_map_pos)
        
        # === FORMATING
        # formate station map coordinates as npoints-by-2 (2D map) list 
        # of coordinates 
        mapcoord = mappos[[xheader_map_pos,yheader_map_pos]].to_numpy()
        # station map crs reprojection to master crs (if necessary)
        mapcoord[:,0], mapcoord[:,1]= crs_reprojection(xini    = mapcoord[:,0],
                                                                            yini    = mapcoord[:,1],
                                                                            crs_in  = crs_map_pos,
                                                                            crs_out = sgrid.crs.srs)
        mappos[xheader_map_pos] = mapcoord[:,0]
        mappos[yheader_map_pos] = mapcoord[:,1]
        # retrieve x/y coordinates for each well in data chronicle
        points = np.zeros((len(tdata.columns.values),2))
        i = 0
        for well in tdata:
            # get x/y position of wells as model col/row number
            x = mappos[xheader_map_pos][mappos[idheader_map_pos]==well].to_numpy()[0]
            y = mappos[yheader_map_pos][mappos[idheader_map_pos]==well].to_numpy()[0]
            points[i,0] = x
            points[i,1] = y
            i = i+1
        # formate spatial grid cell coordinates
        xyzccenters = sgrid.xyzcellcenters
        xcenters    = xyzccenters[0]
        ycenters    = xyzccenters[1]
        
        # interpolation for each time step
        all_rasters = np.zeros((len(tdata.index),len(xcenters[:,0]),len(xcenters[0,:])))
        for i in list(range(len(tdata.index))):
            values = tdata.values[i,:]
            all_rasters[i,:,:] = griddata(points, values, (xcenters, ycenters), method=interpolation_method)

        
        date_array = tdata.index
        return all_rasters,date_array
        

    
      

# %% NOTES
# TODO@TB: methods descriptions