# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
from typing import Union
import os
import rasterio
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
# wbt.set_compress_rasters(True)
wbt.verbose = False

logger = get_logger(__name__)

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
                 cond_drain_init: float=864000,
                 hk_init: float=8.64,
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
                 exdp_init: float=1.
                 ):
        """
        Parameters
        ----------
        box_dem : str
            Path raster of maximal buffer extent of the model domain generated from geographic.
        nrow : int
            Number of rows of the model domain obtained from raster in geographic.
        ncol : int
            Number of columns of the model domain obtained from raster in geographic.
        nlay_init : int, optional
            Initial value.
            Vertical layer of the mesh. The default is 1.
        cond_drain_init : float, optional
            Initial value.
            Conductance value for the drain package applied on top.
            Considering a cell resolution of 100*100m, The default is 864000 [m3/day].
        hk_init : float, optional
            Initial value.
            Hydraulic conductivity of the aaquifer. The default is 8.64 in [m/d].
        sy_init : float, optional
            Initial value.
            Specific yield of the aquifer. The default is 0.1 [-], so 10%.
        ss_init : float, optional
            Initial value.
            Specifc storage of the aquifer. The default is 1e-5 (1/day).
        thick_init : float, optional
            Initial value.
            Constant aquifer thickness activated if bottom_init is None. The default is 50 m.
        bottom_init : float, optional
            Initial value.
            Apply a flat bottom at the aquifer from a elevation value. The default is None.
        hk_decay_init : float, optional
            Initial value.
            Alpha decay to modify the hydraulic conductivity exponentially decreasing whit depth (e.g. 1/30m). The default is 0.
        sy_decay_init : float, optional
            Initial value.
            Alpha decay to modify the specific yield exponentially decreasing whit depth (e.g. 1/60m). The default is 0.
        ss_decay_init : float, optional
            Initial value.
            Alpha decay to modify the specific storage exponentially decreasing whit depth (e.g. 1/120m). The default is 0.
        lay_decay_init : float, optional
            Initial value.
            Modify vertical layer thickness exponentially decreasing whith depth. The default is 1 (no change).
        verti_hk_init : list, optional
            Initial value.
            Apply hydraulic conductivity values between different thickness. The default is None.
        verti_sy_init : list, optional
            Initial value.
            Apply specific yield values between different thickness. The default is None.
        verti_ss_init : list, optional
            Initial value.
            Apply specific storage values between different thickness. The default is None.
        vka_init : list, optional
            Initial value.
            Ratio of horizontal to vertical hydraulic conductivity. The default is 1.
        """
        logger.info('Initializing hydraulic module for parameter setup')
        
        self.box_dem = box_dem
        
        self.thick = thick_init
        self.bottom = bottom_init
        
        self.nrow = nrow
        self.ncol = ncol
        self.nlay = nlay_init
        self.lay_decay = lay_decay_init
        
        self.hk_value = hk_init
        self.sy_value = sy_init
        self.ss_value = ss_init
        
        self.hk_grid = np.ones((self.nrow, self.ncol))
        self.sy_grid = np.ones((self.nrow, self.ncol))
        self.calib_zones = np.ones((self.nrow, self.ncol))

        self.hk_decay = hk_decay_init
        self.sy_decay = sy_decay_init
        self.ss_decay = ss_decay_init

        self.verti_hk = verti_hk_init 
        self.verti_sy = verti_sy_init
        self.verti_ss = verti_ss_init

        self.cond_drain = cond_drain_init
        
        self.vka = vka_init
        self.exdp = exdp_init
        
        self.update_hk_decay()
        self.update_sy_decay()
        self.update_ss_decay()

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
            Ratio of horizontal to vertical hydraulic conductivity.
        """
        self.vka = vka_value
    
        
    def update_exdp(self, exdp_value: float):
        """
        Parameters
        ----------
        exdp : float
            Extinction depth from the surface of the evapotranspiration.
        """
        self.exdp = exdp_value
    
    def update_sy(self, sy_value: float):
        """
        Parameters
        ----------
        sy_value : float
            Sspecifc yield of the aquifer model.
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
             Flat bottom elevation of the aquifer model.
        """
        self.bottom = bottom_value
    
    def update_hk_decay(self, hk_decay_value: float=0, min_value: float=None, log_transf: bool=False, grad_elev: list=[]):
        """
        Parameters
        ----------
        hk_decay_value : float
            Exponential decay ratio of hydraulic conductivity K.
            For z=50m, if hk_decay_value=1/50, Kmax (or K0) divide by 2.7 at 50m.
            K(z) = Kmax*np.exp(-hk_decay_value*z)
        min_value : float
            If not None, the exponential decay stop until this minimal value Kmin.
            K(z) = Kmin-(Kmax-Kmin)*np.exp(-hk_decay_value*z)
        log_transf : bool
            If True, the log transform is applied to the formulation.
            log(K(z)) = log(Kmin)-(log(Kmax)-log(Kmin))*np.exp(-hk_decay_value*z)
        """
        self.hk_decay =  [hk_decay_value, min_value, log_transf, grad_elev]
    
    def update_sy_decay(self, sy_decay_value: float=0, min_value: float=None, log_transf: bool=False, grad_elev: list=[]):
        """
        Parameters
        ----------
        sy_decay_value : float
            Idem por specific yield. See 'update_hk_decay'.
        """
        self.sy_decay = [sy_decay_value, min_value, log_transf, grad_elev]
    
    def update_ss_decay(self, ss_decay_value: float=0, min_value: float=None, log_transf: bool=False, grad_elev: list=[]):
        """
        Parameters
        ----------
        ss_decay_value : float
            Idem por specific stotage. See 'update_hk_decay'.
        """
        self.ss_decay =  [ss_decay_value, min_value, log_transf, grad_elev]
    
    def update_lay_decay(self, lay_decay_value: Union[float, int]):
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
        verti_hk_value : list
            List of hydraulic conductivity values with associated vertical depth.
            For example: [ [1, [0, 20]], [0.5, [20,80]] ]
            1 m/d between 0 and 20 m depth, and 0.5 m/d between 20 and 80 m depth.
        """
        self.verti_hk = verti_hk_value   # None or [ [1e-5, [0, 20]],
                                             #           [1e-6, [20,80]] ]
    
    def update_sy_vertical(self, verti_sy_value: list):
        """
        Parameters
        ----------
        verti_sy_value : list
            Idem for specific yield. See 'update_hk_vertical'.
        """
        self.verti_sy = verti_sy_value   # None or [ [0.5/100, [0, 20]],
                                             #           [0/100, [20,80]] ]
    
    def update_ss_vertical(self, verti_ss_value: list):
        """
        Parameters
        ----------
        verti_ss_value : list
            Idem for specific storage. See 'update_hk_vertical'.
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

    def update_calib_zones_from_shp(self, shp_path, default_zone=1):
        """
        Shapefile must be with different features.
        Field must be "CALIB_ZONE" = 1,2,3,4
        """
        output = os.path.join(dirname(self.box_dem), 'calib_raster_zones.tif')
        
        wbt.vector_polygons_to_raster(
            shp_path, 
            output, 
            field="FID", #Field name should be changed , error : thread 'main' panicked at 'Error: Specified field is greater than the number of fields.'
            # nodata=default_zone,
            cell_size=None, 
            base=self.box_dem)
        
        with rasterio.open(output) as src:
            raster_load = src.read(1)
        raster_load[raster_load<=-9999] = default_zone
        
        self.calib_zones = raster_load
    
    def update_hk_from_calib_zones(self, num_zone: int, hk_value: float):
        """        
        Updates :attr:`hk_value` with a value :data:`hk_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param hk_value: hydraulic conductivy of the aquifer.        
        """        
        self.hk_grid[self.calib_zones==num_zone] = hk_value
        # self.hk_grid = np.tile(self.hk_grid, (self.nlay, 1, 1))
        self.hk_value = self.hk_grid.copy()
    
    def update_sy_from_calib_zones(self, num_zone: int, sy_value: float):
        """
        Updates :attr:`sy_value` with a value :data:`sy_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param sy_value: porosity of the aquifer.        
        """       
        self.sy_grid[self.calib_zones==num_zone] = sy_value
        # self.sy_grid = np.tile(self.sy_grid, (self.nlay, 1, 1))
        self.sy_value = self.sy_grid.copy()
        
    def update_thick_from_calib_zones(self, num_zone: int, thick_value: float):
        """
        Updates :attr:`thickness` with a value :data:`thickness_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`
        :param num_zone: the zone number
        :param thickness_value: thickness of the aquifer.        
        """
        self.thick[self.calib_zones==num_zone] = thick_value
        
    def update_hk_with_geology(self, geology_code, geology_array, hk_values):
        """
        Updates :attr:`hk_value` with values in :data:`hk_values` at the location of the :data:`geology_code` in the :data:`geology_array`
        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param hk_values: hydraulic conductivity values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type hk_values: :class:`list of float`           
        """
        self.hk_value = np.ones((self.nrow, self.ncol))
        for i in range(0,len(geology_code)):
            self.hk_value[geology_array==geology_code[i]] = hk_values[i]
        self.hk_value = np.tile(self.hk_value, (self.nlay, 1, 1))
    
    def update_sy_with_geology(self, geology_code, geology_array, sy_values):
        """
        Updates :attr:`sy_value` with values in :data:`sy_values` at the location of the :data:`geology_code` in the :data:`geology_array`
        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param sy_values: specific yields values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type sy_values: :class:`list of float`         
        """        
        self.sy_value = np.ones((self.nrow, self.ncol))
        for i in range(0,len(geology_code)):
            self.sy_value[geology_array==geology_code[i]] = sy_values[i]
        self.sy_value = np.tile(self.sy_value, (self.nlay, 1, 1))

#%% NOTES
        
