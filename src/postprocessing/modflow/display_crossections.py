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
# Hydromodpy
from tools import Process
# Flopy
import flopy


# %% CLASS


class DisplayCrossSections(Process):

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
    def __init__(self,
                 name: str = 'DispCS',
                 output_name: str = 'DispCS'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default hydraulic conductivity field generation: homogeneous field
        self.set_iptpar(genmtd_sdis = 'homogeneous',
                        value       = 8.6e-1,
                        lenuni      = 'm',
                        itmuni      = 'd')
 
        # Default option & path for master spatial discretization 
        self.set_iptpar(sgrid = 'from_shrenv')
        self.set_shrpar(sgrid = 'sdis')
        
        # Default option & path for data to display 
        self.set_iptpar(data = 'from_shrenv')
        self.set_shrpar(data = 'hk')
        
        # default parameters for plot options
        self.set_iptpar(colorscale_vmin   = 'default',
                        colorscale_vmax   = 'default',
                        masked_val        = -9999,
                        cross_layer       = 0,
                        cross_xline       = 0.5,
                        cross_yline       = 0.5,
                        colorscale_linlog = 'lin',
                        unit_display      = 'default',
                        dataname          = 'default')
        
        
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv):
        """
        Extract and store input data from files / shared environment.
        """
        # master spatial discretization from shared environment
        if self._iptpar['sgrid'] == 'from_shrenv':
            sgridnam = self.get_shrpar['sgrid']
            sgrid = self.get_envar(shrenv,sgridnam)
            self._set_csdpar(sgrid = sgrid)
        # data to display from shared environment
        if self._iptpar['data'] == 'from_shrenv':
            datanam = self.get_shrpar['data']
            data = self.get_envar(shrenv,datanam)
            self._set_csdpar(data = data)
            
        self._isPreprocessed = True
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # 3D matrix of hydraulic conductivities
        self._display()
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        
        return shrenv
        
    # %%% MATRIX GENERATION    
    def _display(self):
        """
        WIP - Description
        """
        # === PARAMETER EXTRACTION
        sgrid             = self.get_csdpar['sgrid']
        data              = self.get_csdpar['data']
        colorscale_vmin   = self.get_iptpar['colorscale_vmin']
        colorscale_vmax   = self.get_iptpar['colorscale_vmax']
        colorscale_linlog = self.get_iptpar['colorscale_linlog']
        masked_val        = self.get_iptpar['masked_val']
        cross_layer       = self.get_iptpar['cross_layer']
        cross_xline       = self.get_iptpar['cross_xline']
        cross_yline       = self.get_iptpar['cross_yline']
        unit_display      = self.get_iptpar['unit_display']
        dataname          = self.get_iptpar['dataname']
        # === DEFAULT VALUES
        if colorscale_vmin == 'default': colorscale_vmin = np.min(data)
        if colorscale_vmax == 'default': colorscale_vmax = np.max(data)
        if unit_display    == 'default': unit_display = 'no_unit_provided'
        if dataname        == 'default': dataname = self.get_shrpar['dataname']
        lenuni = sgrid.lenuni 
        if lenuni == 2: lenuni = 'm'
        # === DISPLAY
        fig, axs = plt.subplots(1, 2, figsize=(10,4), dpi=300)
        axs = axs.ravel()
        i = 0
        
        # --- Figure 1: elevation of top of selected layer
        top_botm = sgrid.top_botm
        elev = top_botm[0:-1,:,:]
        axs[i].set_title('Elevation of top of layer '+str(cross_layer)+' [m]', fontsize=12)
        
        modelxsect1 = flopy.plot.PlotMapView(modelgrid=sgrid, layer=cross_layer)
        imhk = modelxsect1.plot_array(elev, masked_values=[masked_val], cmap='terrain', alpha=0.5, lw=0.1, ax=axs[i])
        fig.colorbar(imhk)
        
        i = i+1
        
        # --- Figure 2: data values in selected layer
        axs[i].set_title('Layer '+str(cross_layer)+' '+dataname+' ['+unit_display+']', fontsize=12)
        
        modelxsect1 = flopy.plot.PlotMapView(modelgrid=sgrid, layer=cross_layer)
        if colorscale_linlog == 'log':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.LogNorm(vmin=colorscale_vmin, vmax=colorscale_vmax))
        elif colorscale_linlog == 'lin':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.Normalize(vmin=colorscale_vmin, vmax=colorscale_vmax))
        fig.colorbar(imhk)
        fig.tight_layout()
        
        plt.savefig('C:/Users/trist/Documents/research/Guidel/calibration/map_heterofull_Kh-best.jpg',
                    bbox_inches='tight')
        
        plt.show()
        
        
        # --- Figure 3: cross-section along selected row
        fig, axs = plt.subplots(1, 2, figsize=(14,4), dpi=300)
        axs = axs.ravel()
        i = 0
        row = int((sgrid.shape[1])*cross_yline)
        modelxsect1 = flopy.plot.PlotCrossSection(modelgrid=sgrid, line={'Row': row})
        if colorscale_linlog == 'log':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.LogNorm(vmin=colorscale_vmin, vmax=colorscale_vmax))
        elif colorscale_linlog == 'lin':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.Normalize(vmin=colorscale_vmin, vmax=colorscale_vmax))
        axs[i].set_title('West-East (Row), '+dataname+' ['+unit_display+']', fontsize=12)
        axs[i].set_xlabel('Distance ['+lenuni+']')
        axs[i].set_ylabel('Elevation ['+lenuni+']')
        fig.colorbar(imhk)
        i = i+1
        
        # --- Figure 4: cross-section along selected column
        col = int((sgrid.shape[0])*cross_xline)
        modelxsect1 = flopy.plot.PlotCrossSection(modelgrid=sgrid, line={'Column': col})
        if colorscale_linlog == 'log':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.LogNorm(vmin=colorscale_vmin, vmax=colorscale_vmax))
        elif colorscale_linlog == 'lin':
            imhk = modelxsect1.plot_array(data, masked_values=[masked_val], cmap='jet', alpha=0.5, lw=0.1, ax=axs[i],
                                          norm=mpl.colors.Normalize(vmin=colorscale_vmin, vmax=colorscale_vmax))
        axs[i].set_title('North-South (Column), '+dataname+' ['+unit_display+']', fontsize=12)
        axs[i].set_xlabel('Distance ['+lenuni+']')
        axs[i].set_ylabel('Elevation ['+lenuni+']')
        fig.colorbar(imhk)
        i = i+1
        
        fig.tight_layout()
        
        plt.savefig('C:/Users/trist/Documents/research/Guidel/calibration/crosssection_heterofull_Kh-best.jpg',
                    bbox_inches='tight')
        
        plt.show()
    
      

# %% NOTES
# TODO@TB: methods descriptions