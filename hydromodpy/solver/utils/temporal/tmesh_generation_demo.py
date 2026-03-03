# Test

# Test STGrid
import numpy as np
import rasterio
import os
from hydromodpy.grid.tmesh_generation import TMesh_Generation

cfolder = os.path.dirname(os.path.realpath(__file__))

tmesh_generator = TMesh_Generation()

tmesh_generator.genmtd = 'synthetic_regular'
tmesh_generator.itmuni     = 'd'
tmesh_generator.flow_regime  = 'steady'
tmesh_generator.nper       = 10
tmesh_generator.lenper     = 1
tmesh_generator.chron_path = os.path.join(cfolder,'rech_chronicles.csv')
tmesh_generator.chron_dateformat = '%d/%m/%Y'
tmesh_generator.chron_colsep     = '\t'
tmesh_generator.chron_time_col   = 'date'
tmesh_generator.firstpersteady   = True

tmesh1 = tmesh_generator.run()

###
tmesh_generator.genmtd = 'synthetic_regular'
tmesh_generator.itmuni     = 'd'
tmesh_generator.flow_regime  = 'transient'
tmesh_generator.nper       = 5
tmesh_generator.lenper     = 3
tmesh_generator.chron_path = os.path.join(cfolder,'rech_chronicles.csv')
tmesh_generator.chron_dateformat = '%d/%m/%Y'
tmesh_generator.chron_colsep     = '\t'
tmesh_generator.chron_time_col   = 'date'
tmesh_generator.firstpersteady   = False

tmesh2 = tmesh_generator.run()

###
tmesh_generator.genmtd = 'from_chron'
tmesh_generator.itmuni     = 'd'
tmesh_generator.flow_regime  = 'transient'
tmesh_generator.nper       = 100
tmesh_generator.lenper     = 3
tmesh_generator.chron_path = os.path.join(cfolder,'rech_chronicles.csv')
tmesh_generator.chron_dateformat = '%d/%m/%Y'
tmesh_generator.chron_colsep     = '\t'
tmesh_generator.chron_time_col   = 'date'
tmesh_generator.firstpersteady   = True

tmesh3 = tmesh_generator.run()
