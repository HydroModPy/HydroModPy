# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import abc
import os

#HydroModPy modules
import modflow
import hs1d

#%% CLASS

class GroundwaterFlow(abc.ABC):
    
    #%% INIT
    
    def __init__(self, geographic, program = 'modflow',
                 climatic=8e-4, lay_number=1, thick=50,
                 bottom = None, thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, 
                 sea_level=None, cond_decay=0.,
                 time_step='daily', model_name='modflow_model', 
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe = os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):
        """
        
        Parameters
        ----------
        geographic : TYPE
            DESCRIPTION.
        program : TYPE, optional
            DESCRIPTION. The default is 'modflow'.
        climatic : TYPE, optional
            DESCRIPTION. The default is 8e-4.
        lay_number : TYPE, optional
            DESCRIPTION. The default is 1.
        thick : TYPE, optional
            DESCRIPTION. The default is 50.
        bottom : TYPE, optional
            DESCRIPTION. The default is None.
        thick_exp : TYPE, optional
            DESCRIPTION. The default is 1..
        hyd_cond : TYPE, optional
            DESCRIPTION. The default is 8.64e-2.
        porosity : TYPE, optional
            DESCRIPTION. The default is 0.01.
        sea_level : TYPE, optional
            DESCRIPTION. The default is None.
        cond_decay : TYPE, optional
            DESCRIPTION. The default is 0..
        time_step : TYPE, optional
            DESCRIPTION. The default is 'daily'.
        model_name : TYPE, optional
            DESCRIPTION. The default is 'modflow_model'.
        model_folder : TYPE, optional
            DESCRIPTION. The default is os.path.join(os.path.dirname(os.getcwd()), 'output').
        exe : TYPE, optional
            DESCRIPTION. The default is os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe').

        Returns
        -------
        None.

        """
        
        if program == 'modflow':
            modflow.Modflow(geographic,
                 climatic=climatic, lay_number=lay_number, thick=thick,
                 bottom = bottom, thick_exp=thick_exp, hyd_cond=hyd_cond, porosity=porosity, 
                 sea_level=sea_level, cond_decay=cond_decay,
                 time_step=time_step, model_name=model_name, 
                 model_folder=model_folder, 
                 exe = exe)
        if program == 'hs1d':
            hs1d

    #%% Abstract Base Class
    
    @abc.abstractmethod
    def pre_processing(self):
        """
        creates pre-processing files/variables

        """
        pass
    
    @abc.abstractmethod
    def processing(self):
        """
        runs groundwater flow model
        
        """
        pass
    
    @abc.abstractmethod
    def post_processing(self):
        """
        generates output files
        
        """
        pass
    
#%% NOTES