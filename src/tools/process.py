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

from abc import abstractmethod

# %% CLASS

class Process:

    """ 
    TODO@TB: WIP - Description

    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'default',
                 output_name: str = 'default'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        self._name   = name
        self._output_name   = output_name
        self._iptpar = {}
        self._shrpar = {}
        self._advpar = {}
        self._csdpar = {}       
        self._isPreprocessed = False
        self.clear_csdpar_option = True 
                
    # %%% SETTER AND GETTER
    @property
    def get_name(self):
        return self._name

    def set_name(self, value: str):
        self._name = value
        
    @property
    def get_output_name(self):
        return self._output_name

    def set_output_name(self, value: str):
        self._output_name = value
    
    @property
    def get_iptpar(self):
        return self._iptpar

    def set_iptpar(self, **kwargs):
        self._iptpar.update(kwargs)
        self.clear_csdpar()
    
    @property
    def get_shrpar(self):
        return self._shrpar

    def set_shrpar(self, **kwargs):
        self._shrpar.update(kwargs)
        self.clear_csdpar()
    
    @property
    def get_advpar(self):
        return self._advpar

    def set_advpar(self, **kwargs):
        self._advpar.update(kwargs)
        self.clear_csdpar()
        
    @property
    def get_csdpar(self):
        return self._csdpar
    
    def _set_csdpar(self, **kwargs):
        self._csdpar.update(kwargs)
    
    def clear_csdpar(self):
        self._csdpar = {}
        self._isPreprocessed = False
    
    @property
    def get_isPreprocessed(self):
        return self._isPreprocessed     
        
    def get_envar(self, 
                  shrenv: dict, 
                  varnamls: (str,list)):
        if isinstance(varnamls,str):
            var = shrenv.get(varnamls) 
        else:
            for i in range(len(varnamls)):
                if i == 0:
                    var = shrenv.get(varnamls[i])
                else:
                    var = var.get(varnamls[i])
                if var is None: break
        return var
    
    # %%% EXPORT AND IMPORT
    def load_xml(self,**kwargs):
        # @TB Placeholder for loading parameters from xml file
        print('Functionality not implemented yet.')
              
    def save_xml(self,**kwargs):
        # @TB Placeholder for saving parameters as xml file
        print('Functionality not implemented yet.')
        
    # %%% ABSTRACT METHODS TO BE IMPLEMENTED BY CHILD CLASSES
    @abstractmethod
    def preprocessing(self,shrenv: dict={}):
        """
        Ready the class for processing.
        Extract and store input data from files / shared environment.
        """
        self._isPreprocessed = True
        
    @abstractmethod
    def processing(self,shrenv: dict = {}):
        """Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self._name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar
        # update shared environment with process outputs    
        return shrenv

# %% NOTES
