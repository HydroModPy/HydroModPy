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
    
    :ivar hyd_cond: initial value: par1
    :ivar porosity: initial value: par2
    """
    def __init__(self, nrow: int, ncol: int, hyd_cond_init: float = 8.64, porosity_init: float = 0.1, 
                 thickness_init: float = 50):
        """
        Constructor
        
        """
        self.hyd_cond: int = np.ones((nrow, ncol)) * hyd_cond_init
        self.porosity = np.ones((nrow, ncol)) * porosity_init
        self.thickness = thickness_init
        self.calib_zones = np.ones((nrow, ncol))
    
    def update_hyd_cond(self, hyd_cond_value):
        """
        Update the hydraulic conductivity with a constant value

        Parameters
        ----------
        hyd_cond_value : float
            hydraulic conductivy of the aquifer.
        """
        self.hyd_cond = np.ones(np.shape(self.hyd_cond)) * hyd_cond_value
    
    def update_porosity(self, porosity_value):
        """
        Update the porosity with a constant value

        Parameters
        ----------
        porosity_value : float
            porosity of the aquifer.
        """
        self.porosity = np.ones(np.shape(self.porosity)) * porosity_value
        
    def update_thickness(self, thickness_value):
        """
        Update the thickness with a constant value

        Parameters
        ----------
        thickness_value : float
            thickness of the aquifer.
        """
        self.thickness =  thickness_value
        
    def update_calib_zones(self, zones):
        """
        Update the calibration zone number. Must start at 1

        Parameters
        ----------
        zones : int 2D array
            localisation of the calibration zones in the DEM.

        """
        self.calib_zones = zones
        
    def update_hyd_cond_from_calib_zones(self, num_zone, hyd_cond_value):
        """
        Update the hydraulic conductivity with a constant value in zone

        Parameters
        ----------
        num_zone : int
            number of zone
        hyd_cond_value : float
            hydraulic conductivy of the aquifer.
        """
        self.hyd_cond[self.calib_zones==num_zone] = hyd_cond_value
    
    def update_porosity_from_calib_zones(self, num_zone, porosity_value):
        """
        Update the porosity with a constant value in zone

        Parameters
        ----------
        num_zone : int
            number of zone
        porosity_value : float
            porosity of the aquifer.
        """
        self.porosity[self.calib_zones==num_zone] = porosity_value
        
    def update_thickness_from_calib_zones(self, num_zone,thickness_value):
        """
        Update the thickness with a constant value in zone

        Parameters
        ----------
        num_zone : int
            number of zone
        thickness_value : float
            thickness of the aquifer.
        """
        self.thickness[self.calib_zones==num_zone] =   thickness_value
        
    def update_hyd_cond_with_geology(self, geology_code, geology_array, hyd_cond_values):
        """
        AG/JR 11/2021 : Voir comment généraliser avec la porosité
        Update the hydraulic conductivity for each geology entities

        Parameters
        ----------
        geology_code : int list or 1D array
            list of geology entities.
        geology_array : int 2D array
            localisation of the geology entities in the DEM.
        hyd_cond_values : float list (must be the same lenght of geology_code)
            hydraulic conductivity values for each geology code.
        """
        self.hyd_cond = np.ones(np.shape(self.hyd_cond))
        for i in range(0,len(geology_code)):
            self.hyd_cond[geology_array==geology_code[i]] = hyd_cond_values[i]
    
    def update_porosity_with_geology(self, geology_code, geology_array, porosity_values):
        """
        Update the porosity for each geology entities

        Parameters
        ----------
        geology_code : int list or 1D array
            list of geology entities.
        geology_array : int 2D array
            localisation fo the geology entities in the DEM.
        porosity_values : float list (must be the same lenght of geology_code)
            porosity values for each geology code.
        """
        self.porosity = np.ones(np.shape(self.porosity))
        for i in range(0,len(geology_code)):
            self.porosity[geology_array==geology_code[i]] = porosity_values[i]
        
        
        
        
        