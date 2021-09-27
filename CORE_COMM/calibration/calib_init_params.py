# coding:utf-8

import os
import sys
import pandas as pd
from IPython.core.debugger import set_trace as st
from datetime import datetime

class CalibInitParams:
    """
    A class used to identify hydraulic parameters of the watershed to calibrate

    Attributes
    ----------
    settings_path : str
        the path of the setting files

    Methods
    -------
        
    create_init_files()
        generate the setting files that will be complete by the user
    
    """
    
    def __init__(self, settings_path):
        """
        Constructor
        
        Parameters
        ----------        
        BV : instance of watershed object
            data and structure of the watershed
        """
        self.settings_path = settings_path
        self.create_init_setting_files()
    
    def create_init_setting_files(self):
        f = open(self.settings_path +'/params_to_calibrate.csv', 'a')
        f.close()
        f = open(self.settings_path +'/strategies_to_calibrate.csv', 'a')
        f.close()
        