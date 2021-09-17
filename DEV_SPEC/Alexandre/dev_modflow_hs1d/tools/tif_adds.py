# -*- coding: utf-8 -*-
"""
Created on 

@author: Ronan Abhervé
"""

import rasterio as rio

def export_tif(base_dem_path, data_to_tif, data_nodata_val, data_tif_path):
    # Open base dem
    with rio.open(base_dem_path) as src:
        ras_data = src.read()
        ras_nodata = src.nodatavals
        ras_dtype = src.dtypes
        ras_meta = src.profile
    # Type of data
    data_dtype = data_to_tif.dtype
    # Change base dem from data
    ras_meta['dtype'] = data_dtype
    ras_meta['nodata'] = data_nodata_val
    # Create new data raster with base dem size
    with rio.open(data_tif_path, 'w', **ras_meta) as dst:
        dst.write(data_to_tif, 1)
