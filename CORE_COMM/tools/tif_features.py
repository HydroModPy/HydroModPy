# -*- coding: utf-8 -*-
"""
Created on 

@author: Ronan Abhervé
"""

import numpy as np
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)

from tools import tif_masks

def basin_area(target_data, mask_data, cond_symb, value_masked, resolution):
    masked = tif_masks.mask_by_dem(target_data, mask_data, cond_symb, value_masked)
    cell = masked.count()
    area = (cell * resolution**2) / 1000000
    return area

