# Test

# Test STGrid
from flopy.discretization import StructuredGrid, UnstructuredGrid, VertexGrid
import os
import numpy as np
import rasterio
from hydromodpy.grid.sgrid_generation import SGrid_Generation

cfolder = os.path.dirname(os.path.realpath(__file__))

sgrid_generator = SGrid_Generation()
sgrid_generator.top_path = cfolder+'\watershed_box_buff_dem.tif'
sgrid_generator.lenuni = 'm'
sgrid_generator.crs = 'EPSG:2154'

sgrid_generator.lay_proportions = [0.1, 0.2, 0.3, 0.4]
sgrid_generator.nlay = 5
sgrid_generator.lay_decay = 2

sgrid_generator.genmtd_bot = 'constant_altitude'
sgrid_generator.zbot = -30

sgrid_generator.genmtd_lay = 'constant'
sgrid = sgrid_generator.run()
botm0 = sgrid.botm

sgrid_generator.genmtd_bot = 'constant_thickness'
sgrid_generator.thick = 200

sgrid_generator.genmtd_lay = 'decay'
sgrid = sgrid_generator.run()
botm1 = sgrid.botm

sgrid_generator.genmtd_lay = 'constant'
sgrid = sgrid_generator.run()
botm2 = sgrid.botm

sgrid_generator.genmtd_lay = 'list'
sgrid = sgrid_generator.run()
botm3 = sgrid.botm