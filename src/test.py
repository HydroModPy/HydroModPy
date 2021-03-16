import os
import sys
import climatic as c
import modflow as m
climatic =  c.surfex('C:/Users/alexa/Documents/GitHub/surfex_extract/OUT/data.h5',resample='M')
m.modflow_model(dem_path='C:/Users/alexa/Documents/GitHub/HydroModPy/tmp/watershed_buff.tif', climatic=climatic.period_data, thick=50,  
		hyd_cond=0.0864, porosity=0.01)
