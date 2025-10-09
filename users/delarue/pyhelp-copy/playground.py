# -*- coding: utf-8 -*-
"""
Created on Wed May 28 12:09:27 2025

@author: delarueo
"""
"""
Created on Wed Apr 23 15:21:15 2025
Modification: 2025-05-07
@author: delarueo

Extract from cerra alps data local cerra data
Debiased ?
Generate Help input files
statistic timeserie for each catchement
"""

import toolbox_newFuns_ as tb
import os

#%%

cerra_file = 'F:/_cerra_forecast/surface_net_solar_radiation/1984/1984_alps.nc'    

data = tb.CERRA(cerra_file)