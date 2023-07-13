# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Python
import numpy as np
import whitebox
wbt = whitebox.WhiteboxTools()
# wbt.set_compress_rasters(True)
wbt.verbose = False

#%% CLASS

class Hydraulic:

    #%% INIT
    
    def __init__(self, 
                 nrow: int, ncol: int,
                 box_dem: str,
                 nlay_init: int = 1,
                 hyd_cond_init: float = 8.64,
                 cond_drain_init: float = 864000,
                 porosity_init: float = 0.1, 
                 thick_init: float = 50.,
                 bottom_init: float = None,
                 cond_decay_init: float = 0.,
                 poro_decay_init: float = 0.,
                 lay_decay_init: float = 1.,
                 verti_cond_init = None):
        
        print('Init hydraulic module to set model parameter')
        
        self.box_dem = box_dem
        self.nlay = nlay_init
        self.hyd_cond = np.ones((nrow, ncol)) * hyd_cond_init
        self.cond_drain = np.ones((nrow, ncol)) * cond_drain_init
        self.porosity = np.ones((nrow, ncol)) * porosity_init
        self.thick = thick_init
        self.calib_zones = np.ones((nrow, ncol))
        self.bottom = bottom_init
        self.cond_decay = cond_decay_init
        self.poro_decay = poro_decay_init
        self.lay_decay = lay_decay_init
            
    #%% UPDATE LATERAL HOMOGENEOUS
    
    def update_nlay(self, nlay_value: float):

        self.nlay = nlay_value
        
    def update_hyd_cond(self, hyd_cond_value: float):
        
        self.hyd_cond = np.ones(np.shape(self.hyd_cond)) * hyd_cond_value
        
    def update_porosity(self, porosity_value: float):
        
        self.porosity = np.ones(np.shape(self.porosity)) * porosity_value
        
    def update_thick(self, thick_value: float):

        self.thick =  thick_value
            
    def update_bottom(self, bottom_value: float):
        
        self.bottom = bottom_value
    
    def update_cond_decay(self, cond_decay_value: float):
        
        self.cond_decay =  cond_decay_value
    
    def update_poro_decay(self, poro_decay_value: float):
        
        self.poro_decay =  poro_decay_value    
    
    def update_lay_decay(self, thick_exp_value: float):
        
        self.thick_exp =  thick_exp_value
    
    def update_cond_drain(self, cond_drain_value: float):
        
        self.cond_drain = cond_drain_value
    
    def update_cond_vertical(self, verti_cond_value: list):
        
        self.verti_cond = verti_cond_value   # None or [ [1e-5, [0, 20]],
                                             #           [1e-6, [20,80]] ]
    
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
        shapefile must be with different features.
        Field must be "CALIB_ZONE" = 1,2,3,4
        """
        
        from os.path import dirname
        import os
        import imageio
        # import rasterio
        # import matplotlib.pyplot as plt
        
        output = os.path.join(dirname(self.box_dem), 'out_raster_zones.tif')
        
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
    
    def update_hyd_cond_from_calib_zones(self, num_zone: int, hyd_cond_value: float):
        """
        
        Updates :attr:`hyd_cond` with a value :data:`hyd_cond_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`

        :param num_zone: the zone number
        :param hyd_cond_value: hydraulic conductivy of the aquifer.
        
        """
        
        self.hyd_cond[self.calib_zones==num_zone] = hyd_cond_value
    
    def update_porosity_from_calib_zones(self, num_zone: int, porosity_value: float):
        """
        
        Updates :attr:`porosity` with a value :data:`porosity_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`

        :param num_zone: the zone number
        :param porosity_value: porosity of the aquifer.
        
        """
        
        self.porosity[self.calib_zones==num_zone] = porosity_value
        
    def update_thickness_from_calib_zones(self, num_zone: int, thick_value: float):
        """
        
        Updates :attr:`thickness` with a value :data:`thickness_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`

        :param num_zone: the zone number
        :param thickness_value: thickness of the aquifer.
        
        """
        
        self.thick[self.calib_zones==num_zone] = thick_value
        
    def update_hyd_cond_with_geology(self, geology_code, geology_array, hyd_cond_values):
        """
        
        Updates :attr:`hyd_cond` with values in :data:`hyd_cond_values` at the location of the :data:`geology_code` in the :data:`geology_array`

        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param hyd_cond_values: hydraulic conductivity values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type hyd_cond_values: :class:`list of float`   
        
        """
        
        self.hyd_cond = np.ones(np.shape(self.hyd_cond))
        for i in range(0,len(geology_code)):
            self.hyd_cond[geology_array==geology_code[i]] = hyd_cond_values[i]
    
    def update_porosity_with_geology(self, geology_code, geology_array, porosity_values):
        """
        
        Updates :attr:`porosity` with values in :data:`porosity_values` at the location of the :data:`geology_code` in the :data:`geology_array`

        :param geology_code: list of geology entities.
        :type geology_code: :class:`list of int`
        :param geology_array: localisation of the geology entities in the DEM.
        :type geology_array: :class:`numpy.ndarray(int)`
        :param porosity_values: hydraulic conductivity values for each geology code. Must be the same lenght of :data:`geology_code`.
        :type porosity_values: :class:`list of float` 
        
        """
        
        self.porosity = np.ones(np.shape(self.porosity))
        for i in range(0,len(geology_code)):
            self.porosity[geology_array==geology_code[i]] = porosity_values[i]
        
#%% NOTES
        