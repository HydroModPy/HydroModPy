# -*- coding: utf-8 -*-
"""
Created on 

@author: Ronan Abhervé
"""

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)

def clip_tif(tif_path, shp_path, out_path, maintain_dimensions):
    wbt.clip_raster_to_polygon(tif_path, shp_path, out_path, maintain_dimensions=maintain_dimensions)


