#!/usr/bin/env python3

import util
import sys
import os
import slope
from osgeo import gdal
import matplotlib.pyplot as plt

fname_dem = os.path.join(util.fspath, os.path.expanduser(sys.argv[1]))

folder, name = os.path.split(fname_dem)
fname_dis = os.path.join(folder, 'D'+name[1:])

dem = gdal.Open(fname_dem).ReadAsArray()
dis = gdal.Open(fname_dis).ReadAsArray()
slp = slope.slope_down_d8(dem, spacing=125)

U = 1e-3
K = 2e-6
m = 0.6
n = 1.5
Smax = 0.5
dx = 125.
dt = 4e4

erospeed = K * dis**m * slp**n
advspeed = K * dis**m * slp**(n-1)
courant = advspeed * dt / dx
plt.subplot(1,2,1)
plt.imshow(erospeed)
plt.colorbar(orientation='horizontal')
plt.subplot(1,2,2)
plt.imshow(courant)
plt.colorbar(orientation='horizontal')
plt.show()
