# -*- coding: utf-8 -*-
"""
Created on 

@author: Ronan Abhervé
"""

import numpy as np
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

def clip_tif(tif_path, shp_path, out_path, maintain_dimensions):
    wbt.clip_raster_to_polygon(tif_path, shp_path, out_path, maintain_dimensions=maintain_dimensions)

def mask_by_dem(target_data, mask_data, cond_symb, value_masked):
    if cond_symb == '==':
        masked = np.ma.masked_array(target_data, mask=mask_data==value_masked)
    if cond_symb == '!=':
        masked = np.ma.masked_array(target_data, mask=mask_data!=value_masked)
    if cond_symb == '<=':
        masked = np.ma.masked_array(target_data, mask=mask_data<=value_masked)
    if cond_symb == '>=':
        masked = np.ma.masked_array(target_data, mask=mask_data>=value_masked)
    if cond_symb == '>':
        masked = np.ma.masked_array(target_data, mask=mask_data>value_masked)
    if cond_symb == '<':
        masked = np.ma.masked_array(target_data, mask=mask_data<value_masked)
    return masked

