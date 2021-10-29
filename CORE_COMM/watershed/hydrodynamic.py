# -*- coding: utf-8 -*-
"""
Created on Fri Oct 29 10:29:14 2021

@author: Alexandre Gauvain
"""

# Modules
import numpy as np

class Hydrodynamic:
    def __init__(self, nrow, ncol, hyd_cond_init = 8.64, porosity_init = 0.1, 
                 thickness_init = 50):
        """
        Constructor

        Parameters
        ----------
        nrow : int
            number of rows in the DEM.
        ncol : int
            number of columns in the DEM.
        hyd_cond_init : float, optional
            initial hydraulic conductivy of the aquifer. The default is 8.64.
        porosity_init : TYPE, optional
            initial porosity of the aquifer. The default is 0.1.
        thickness_init : TYPE, optional
            initial thickness of the aquifer. The default is 50.
        """
        self.hyd_cond = np.ones(nrow, ncol) * hyd_cond_init
        self.porosity = np.ones(nrow, ncol) * porosity_init
        self.thickness = np.ones(nrow, ncol) * thickness_init
    
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
        self.thickness = np.ones(np.shape(self.thickness)) * thickness_value
        
    def update_hyd_cond_with_geology(self, geology_code, geology_array, hyd_cond_values):
        """
        Update the hydraulic conductivity for each geology entities

        Parameters
        ----------
        geology_code : int list or 1D array
            list of geology entities.
        geology_array : int 2D array
            localisation fo the geology entities in the DEM.
        hyd_cond_values : float list (must be the same lenght of geology_code)
            hydraulic conductivity values for each geology code.
        """
        self.hyd_cond = np.ones(np.shape(self.hyd_cond))
        for i in range(0,len(geology_code)):
            self.hyd_cond[geology_array==geology_code[i]] == hyd_cond_values[i]
    
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
            self.porosity[geology_array==geology_code[i]] == porosity_values[i]
        
        
        
        
        