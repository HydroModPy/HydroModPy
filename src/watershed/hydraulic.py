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

#%% LIBRAIRIES

# Python
import numpy as np
import whitebox
from os.path import dirname
import os
import imageio
wbt = whitebox.WhiteboxTools()
# wbt.set_compress_rasters(True)
wbt.verbose = False

#%% CLASS

class Hydraulic:
    """
    Update hydraulic properties of the groundwater flow model.
    """
    
    def __init__(self, 
                 box_dem: str,
                 nrow: int,
                 ncol: int,
                 nlay_init: int=1,
                 hk_init: float=8.64,
                 cond_drain_init: float=864000,
                 sy_init: float=0.1,
                 ss_init: float=1e-5,
                 thick_init: float=50.,
                 bottom_init: float=None,
                 hk_decay_init: float=0.,
                 sy_decay_init: float=0.,
                 ss_decay_init: float=0.,
                 lay_decay_init: float=1.,
                 verti_hk_init=None,
                 verti_sy_init=None,
                 verti_ss_init=None,
                 vka_init: float=1.,
                 ):
        """
        Parameters
        ----------
        nrow : int
            Number of rows of the model domain obtained from raster in geographic.
        ncol : int
            Number of columns of the model domain obtained from raster in geographic.
        box_dem : str
            Path raster of maximal buffer extent of the model domain generated from geographic.
        nlay_init : int, optional
            Initial value.
            Vertical layer of the mesh. The default is 1.
        hyd_cond_init : float, optional
            Initial value.
            Hydraulic conductivity of the aaquifer. The default is 8.64 in [m/d].
        cond_drain_init : float, optional
            Initial value.
            Conductance value for the drain package applied on top. 
            Considering a cell resolution of 100*100m, The default is 864000 [m3/day].
        porosity_init : float, optional
            Initial value.
            Porosity (specific yield) of the aquifer. The default is 10%.
        ss_init : float, optional
            Initial value.
            Specifc storage of the aquifer. The default is 1e-5 (1/day).
        thick_init : float, optional
            Initial value.
            Constant aquifer thickness valid if bottom_init is None. The default is 50.
        bottom_init : float, optional
            Initial value.
            Apply a flat bottom at the aquifer from a elevation value. The default is None.
        cond_decay_init : float, optional
            Initial value.    
            Ratio to modify the hydraulic conductivity exponentially decreasing whit depth. The default is 0.
        poro_decay_init : float, optional
            Initial value.
            Ratio to modify the porosity (specific yield : sy) exponentially decreasing whit depth. The default is 0.
        ss_decay_init : float, optional
            Initial value.
            Ratio to modify the porosity (specific storage : ss) exponentially decreasing whit depth. The default is 0.
        lay_decay_init : float, optional
            Initial value.
            Modify vertical layer thickness exponentially decreasing whit depth. The default is 1.
        verti_cond_init : list, optional
            Initial value.
            Depth-dependent hydraulic conductivity. The default is None.
        verti_poro_init : list, optional
            Initial value.
            Depth-dependent porosity. The default is None.
        """
        print('Init hydraulic module to set model parameter')
        
        self.box_dem = box_dem
        self.nrow = nrow
        self.ncol = ncol
        self.nlay = nlay_init
        self.hk_grid = hk_init
        self.cond_drain = cond_drain_init
        self.sy_value = sy_init
        self.ss_value = ss_init
        self.thick = thick_init
        self.bottom = bottom_init
        self.hk_decay = hk_decay_init
        self.sy_decay = sy_decay_init
        self.ss_decay = ss_decay_init
        self.lay_decay = lay_decay_init
        self.verti_hk = verti_hk_init 
        self.verti_sy = verti_sy_init
        self.verti_ss = verti_ss_init
        self.calib_zones = np.ones((nlay_init, nrow, ncol))

    #%% UPDATE LATERAL HOMOGENEOUS
    
    def update_nlay(self, nlay_value: int):
        """
        Parameters
        ----------
        nlay_value : int
            Number of vertical layer of the aquifer model mesh.
        """
        self.nlay = nlay_value
        
    def update_hk(self, hk_value: float):
        """
        Parameters
        ----------
        hyd_cond_value : float
            Hydraulic conductivity of the aquifer model.
        """
        self.hk_value = hk_value
    
    def update_vka(self, vka_value: float):
        """
        Parameters
        ----------
        vka : float
            Vertical hydraulic conductivity or the ratio of horizontal to vertical hydraulic conductivity of the aquifer model.
        """
        self.vka = vka_value
    
    def update_sy(self, sy_value: float):
        """
        Parameters
        ----------
        porosity_value : float
            Porosity (specifc yield) of the aquifer model.
        """
        self.sy_value = sy_value
    
    def update_ss(self, ss_value: float):
        """
        Parameters
        ----------
        ss_value : float
            Specific storage of the aquifer model.
        """
        self.ss_value = ss_value    
    
    def update_thick(self, thick_value: float):
        """
        Parameters
        ----------
        thick_value : float
            Constant thickness of the aquifer model.
        """
        self.thick =  thick_value
            
    def update_bottom(self, bottom_value: float):
        """
        Parameters
        ----------
        bottom_value : float
            Elevation of the flat bottom of the aquifer model.
        """
        self.bottom = bottom_value
    
    def update_hk_decay(self, hk_decay_value: float, kmin_value: float, hklog_tranf: bool):
        """
        Parameters
        ----------
        cond_decay_value : float
            Exponential decay ratio of hydraulic conductivity.
            For z=50, if cond_decay_value=1/50, K0 divide by 2.7 at 50m.
            K = K0 * np.exp(-cond_decay_value*z)
        """
        self.hk_decay =  [hk_decay_value, kmin_value, hklog_tranf] 
    
    def update_sy_decay(self, sy_decay_value: float, symin_value: float, sylog_tranf: bool):
        """
        Parameters
        ----------
        poro_decay_value : float
            Exponential decay ratio of porosity (specific storage : sy).
            For z=50, if cond_decay_value=1/50, K0 divide by 2.7 at 50m.
            Sy = Sy0 * np.exp(-poro_decay_value*z)
        """
        self.sy_decay = [sy_decay_value, symin_value, sylog_tranf]
    
    def update_ss_decay(self, ss_decay_value: float, ssmin_value: float, sslog_tranf: bool):
        """
        Parameters
        ----------
        ss_decay_value : float
            Exponential decay ratio of porosity (specific storage : ss).
            For z=50, if cond_decay_value=1/50, K0 divide by 2.7 at 50m.
            Sy = Sy0 * np.exp(-poro_decay_value*z)
        """
        self.ss_decay =  [ss_decay_value, ssmin_value, sslog_tranf]  
    
    def update_lay_decay(self, lay_decay_value: float or int):
        """
        Parameters
        ----------
        thick_exp_value : float
            Exponential decay ratio of vertical layer mesh thickness increasing with depath.
            The default value without decay is 1.
        """
        self.lay_decay = lay_decay_value
    
    def update_cond_drain(self, cond_drain_value: float):
        """
        Parameters
        ----------
        cond_drain_value : float
            Drain conductance value at the surface of the aquifer model.
        """
        self.cond_drain = cond_drain_value
    
    def update_hk_vertical(self, verti_hk_value: list):
        """
        Parameters
        ----------
        verti_cond_value : list
            List of hydraulic conductivity values with associated vertical depth.
        """
        self.verti_hk = verti_hk_value   # None or [ [1e-5, [0, 20]],
                                             #           [1e-6, [20,80]] ]
    
    def update_sy_vertical(self, verti_sy_value: list):
        """
        Parameters
        ----------
        verti_poro_value : list
            List of porosity (specific yield) values with associated vertical depth.
        """
        self.verti_sy = verti_sy_value   # None or [ [0.5/100, [0, 20]],
                                             #           [0/100, [20,80]] ]
    
    def update_ss_vertical(self, verti_ss_value: list):
        """
        Parameters
        ----------
        verti_poro_value : list
            List of porosity (specific storage) values with associated vertical depth.
        """
        self.verti_ss = verti_ss_value   # None or [ [0.5/100, [0, 20]],
                                             #           [0/100, [20,80]] ]
    
    #%% UPDATE LATERAL HETEROGENEOUS
        
    def update_calib_zones(self, zones: np.ndarray):
        """
        Updates the :attr:`calib_zones` zone number with :data:`zone`. 
        The array values must be :class:`int` and start at 1.
        :param zones: localisation of the calibration zones in the DEM.        
        """

        self.calib_zones = zones

    def update_calib_zones_from_shp(self, shp_path, default_zone = 1):
        """
        Shapefile must be with different features.
        Field must be "CALIB_ZONE" = 1,2,3,4
        """
        output = os.path.join(dirname(self.box_dem), 'calib_raster_zones.tif')
        
        wbt.vector_polygons_to_raster(
            shp_path, 
            output, 
            field="FID", #Field name should be changed , error : thread 'main' panicked at 'Error: Specified field is greater than the number of fields.'
            nodata=default_zone, 
            cell_size=None, 
            base=self.box_dem)
        
        raster_load = imageio.imread(output)
        raster_load[raster_load==-99999] = default_zone

        # src = rasterio.open(output)
        # plt.imshow(src.read(1), cmap='pink')
        # plt.show()
        
        self.calib_zones = raster_load
    
    def update_hk_from_calib_zones(self, num_zone: int, hk_value: float):
        """        
        Updates :attr:`hyd_cond` with a value :data:`hyd_cond_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param hyd_cond_value: hydraulic conductivy of the aquifer.        
        """        
        self.hk_value = np.ones(self.row, self.col)
        self.hk_value[self.calib_zones==num_zone] = hk_value
        self.hk_value = np.tile(self.hk_value, (self.nlay, 1, 1))
    
    def update_sy_from_calib_zones(self, num_zone: int, sy_value: float):
        """
        Updates :attr:`porosity` with a value :data:`porosity_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param porosity_value: porosity of the aquifer.        
        """       
        self.sy_value = np.ones(self.row, self.col)
        self.sy_value[self.calib_zones==num_zone] = sy_value
        self.sy_value = np.tile(self.sy_value, (self.nlay, 1, 1))
        
    def update_thick_from_calib_zones(self, num_zone: int, thick_value: float):
        """
        Updates :attr:`thickness` with a value :data:`thickness_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param thickness_value: thickness of the aquifer.        
        """
        self.thick[self.calib_zones==num_zone] = thick_value
        
    def update_hk_with_geology(self, geology_code, geology_array, hk_values):
        """
        Updates :attr:`hyd_cond` with values in :data:`hyd_cond_values` at the location of the :data:`geology_code` in the :data:`geology_array`
        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param hyd_cond_values: hydraulic conductivity values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type hyd_cond_values: :class:`list of float`           
        """
        self.hk_value = np.ones(self.row, self.col)
        for i in range(0,len(geology_code)):
            self.hk_value[geology_array==geology_code[i]] = hk_values[i]
        self.hk_value = np.tile(self.hk_value, (self.nlay, 1, 1))
    
    def update_sy_with_geology(self, geology_code, geology_array, sy_values):
        """
        Updates :attr:`porosity` with values in :data:`porosity_values` at the location of the :data:`geology_code` in the :data:`geology_array`
        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param porosity_values: hydraulic conductivity values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type porosity_values: :class:`list of float`         
        """        
        self.sy_value = np.ones(self.row, self.col)
        for i in range(0,len(geology_code)):
            self.sy_value[geology_array==geology_code[i]] = sy_values[i]
        self.sy_value = np.tile(self.sy_value, (self.nlay, 1, 1))

#%% NOTES
        