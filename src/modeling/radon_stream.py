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

import os
import pandas as pd
import numpy as np
import math
import imageio
import tempfile
import time
import flopy
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# HydroModPy
from tools import toolbox


# %% CLASS


class Radon_stream:

    """ 
    WIP
    Attributes
    ----------

    Methods
    -------

    """

    # %% INITIALIZATION
    def __init__(self):
        """
        Initialize method. 

        Parameters
        ----------
        """
        # Radioactive decay half-life
        # @TB in days; should be checked for homogeneity
        self.rdhalf_life = 3.82
        self.nodata_val = -99999.0

    # %% PREPROCESSING STREAM REACTIVE TRANSPORT MODULE 
   
    def preprocessing(self,
                      streams: object,
                      rn_gw: object,
                      geographic: object,
                      gerate: float=93,   # air-water exchange rate in d-1
                      vstream: float=17280 # Stream flow rate in m/d-1
                      ):
        
        self.nrow = rn_gw.nrow
        self.ncol = rn_gw.ncol
        self.nlay = rn_gw.nlay
        self.geographic = geographic
        
        ##### Parameter spatialization
        ##### @TB: placeholder while waiting for general spatialization of 
        ##### parameters in HMP
        # Air-water exchange rate
        self.gerate_ras = np.zeros((self.nrow,self.ncol))+gerate
        # Stream flow rate
        self.vstream_ras = np.zeros((self.nrow,self.ncol))+vstream
        # Stream travel distance from cell to cell
        dstream = self.geographic.resolution * (1 + math.sqrt(2)) / 2
        self.dstream_ras = np.zeros((self.nrow,self.ncol))+dstream
        # Rn radioactive decay rate
        rdrate = np.log(2) / self.rdhalf_life
        self.rdrate_ras = np.zeros((self.nrow,self.ncol))+rdrate
        #####
        
        # Cell-specific groundwater discharge into surface water
        self.disflow_rast = imageio.imread(streams.discharge_rast_path)
        
        # Cumulated groundwater discharge into surface water
        self.cumdisflow_rast = streams.cumulated_discharge(streams.geographic,
                                                           streams.discharge_rast_path)        
        # Groundwater Rn outflow concentrations
        zmap_min = np.zeros((self.nrow,self.ncol))-9999
        zmap_max = np.zeros((self.nrow,self.ncol))+9999
        conc_df = rn_gw.get_concentrations_from_zlayers(conc_pos='ending',zmap_min=zmap_min,zmap_max=zmap_max)
        conc_rast = np.zeros((self.nrow,self.ncol))
        conc_rast[conc_df['i'].to_numpy(),conc_df['j'].to_numpy()] = conc_df['mean'].to_numpy()
        self.disconc_rast=conc_rast
    
    # %% PROCESSING GROUNDWATER REACTIVE TRANSPORT MODULE  
    def processing(self):
        
        print('Starting Radon Reactive Transport Simulation for Streams... ')
        start_time = time.time()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            restemp_rast_path = os.path.join(temp_dir, '_restemp.tif')
            
            ### Loading (= Mass) ###
            load_rast_path = os.path.join(temp_dir, '_load_t(xxx).tif')
            # Groundwater Rn outflow: from concentration to mass
            dismass_rast = np.multiply(self.disflow_rast, self.disconc_rast)
            dismass_rast[dismass_rast<0] = 0
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               dismass_rast, 
                               load_rast_path, 
                               self.nodata_val)
            
            ### Efficiency ###
            eff_rast_path = os.path.join(temp_dir, '_eff_t(xxx).tif')#
            # Efficiency raster: get the mass fraction of Rn effectively transfered
            # from one stream cell to the next, accounting for losses due to 
            # radioactive decay and gas exchange with atmosphere
            eff_rast = np.divide(self.dstream_ras, self.vstream_ras) 
            eff_rast = np.multiply(eff_rast, self.gerate_ras + self.rdrate_ras)
            eff_rast = np.exp(-eff_rast)
            eff_rast[eff_rast<0] = 0
            self.eff_rast = eff_rast
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               eff_rast, 
                               eff_rast_path, 
                               self.nodata_val)
                
            ### Adsorption ###
            abs_rast_path = os.path.join(temp_dir, '_abs_t(xxx).tif')
            im = eff_rast * 0
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               im, 
                               abs_rast_path, 
                               self.nodata_val)
            
            # Mass accumulation with d8massflux
            wbt.d8_mass_flux(self.geographic.watershed_buff_fill,
                             load_rast_path, 
                             eff_rast_path,
                             abs_rast_path, 
                             restemp_rast_path)
            
            # Convert from mass to concentration
            cumdismass_rast = imageio.imread(restemp_rast_path)
            conc_rast = np.divide(cumdismass_rast,self.cumdisflow_rast)
            
            # Clean result raster
            conc_rast[conc_rast<0] = self.nodata_val
        
            self.conc_rast = conc_rast
            
       
        
        print('Normal termination of simulation. Ellapsed run time: '+str(round(time.time() - start_time,1))+'s')
        

# %% NOTES
