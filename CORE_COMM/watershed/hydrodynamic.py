# -*- coding: utf-8 -*-
"""
Created on Fri Oct 29 10:29:14 2021

@author: Alexandre Gauvain
"""

# Modules
import numpy as np

class Hydrodynamic:
    """
    class Hydrodynamic is used to specify the values of hydraulic conductivity,
    porosity and thickness of the modelised aquifer.
    
    :param nrow: number of rows in the DEM.
    :param ncol: number of columns in the DEM.
    :param hyd_cond_init: initial hydraulic conductivy of the aquifer. The default is 8.64.
    :param porosity_init: initial porosity of the aquifer. The default is 0.1.
    :param thickness_init: initial thickness of the aquifer. The default is 50.
    
    :ivar hyd_cond: (:data:`nrow`, :data:`ncol`) -- initial value: :data:`hyd_cond_init`
    :vartype hyd_cond: :class:`numpy.ndarray`
    :ivar porosity: (:data:`nrow`, :data:`ncol`) -- initial value: :data:`porosity_init`
    :vartype porosity: :class:`numpy.ndarray`
    :ivar thickness: initial value: :data:`thickness_init`
    :vartype thickness: :class:`int`
    :ivar calib_zones: (:data:`nrow`, :data:`ncol`) -- initial value: 1
    :vartype calib_zones: :class:`numpy.ndarray`
    
    :meta public:
    """
    def __init__(self, nrow: int, ncol: int, hyd_cond_init: float = 8.64, porosity_init: float = 0.1, 
                 thickness_init: float = 50.):
        """
        Constructor
        """
        self.hyd_cond = np.ones((nrow, ncol)) * hyd_cond_init
        self.porosity = np.ones((nrow, ncol)) * porosity_init
        self.thickness = thickness_init
        self.calib_zones = np.ones((nrow, ncol))
    
    def update_hyd_cond(self, hyd_cond_value: float):
        """
        Updates :attr:`hyd_cond` with a constant value :data:`hyd_cond_value`.
        
        :param hyd_cond_value: hydraulic conductivy of the aquifer.
        """
        self.hyd_cond = np.ones(np.shape(self.hyd_cond)) * hyd_cond_value
    
    def update_porosity(self, porosity_value: float):
        """
        Updates :attr:`porosity` with a constant value :data:`hyd_cond_value`.

        :param porosity_value: porosity of the aquifer.
        """
        self.porosity = np.ones(np.shape(self.porosity)) * porosity_value
        
    def update_thickness(self, thickness_value: float):
        """
        Updates the :attr:`thickness` with a constant value :data:`thickness_value`.

        :param thickness_value : thickness of the aquifer.
        """
        self.thickness =  thickness_value
        
    def update_calib_zones(self, zones: np.ndarray):
        """
        Updates the :attr:`calib_zones` zone number with :data:`zone`. 
        The array values must be :class:`int` and start at 1.

        :param zones: localisation of the calibration zones in the DEM.
        """
        self.calib_zones = zones
        
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
        
    def update_thickness_from_calib_zones(self, num_zone: int,thickness_value: float):
        """
        Updates :attr:`thickness` with a value :data:`thickness_value` at the location of the :data:`num_zone` in the :attr:`calib_zones`

        :param num_zone: the zone number
        :param thickness_value: thickness of the aquifer.
        """
        self.thickness[self.calib_zones==num_zone] =   thickness_value
        
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
        
        
        
        
        