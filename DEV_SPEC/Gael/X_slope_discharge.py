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

A0 = 1e4
A1 = 1e8

Xmod = [A0, (U/K)**(1/m) * Smax**(-n/m), A1]
Ymod = [Smax, Smax, (U/K)**(1/n) * A1**(-m/n)]

plt.scatter(dis, slp, s=1)
plt.plot(Xmod, Ymod, linestyle='--', c='#ff7f0e')
plt.xlabel('Drainage area')
plt.xscale('log')
plt.xlim((1e4, 1e8))
plt.ylabel('Slope')
plt.yscale('log')
plt.ylim((1e-2, 1e0))
plt.tight_layout()

if len(sys.argv) < 3:
    plt.show()
else:
    plt.savefig(os.path.expanduser(sys.argv[2]), dpi=200)
