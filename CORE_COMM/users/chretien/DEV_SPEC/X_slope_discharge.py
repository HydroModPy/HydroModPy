#!/usr/bin/env python3

import util
import sys
import os
import slope
from osgeo import gdal
import matplotlib.pyplot as plt
import numpy as np

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

S0 = 3e-2 #1e-2
S1 = 7e-1 #1e0

Xmod = [A0, (U/K)**(1/m) * Smax**(-n/m), A1]
Ymod = [Smax, Smax, (U/K)**(1/n) * A1**(-m/n)]

fig = plt.figure(figsize=(6,6))
grid = fig.add_gridspec(2, 2, width_ratios=(5,1), height_ratios=(1,5))
mainplt = plt.subplot(grid[1,0])
plt.scatter(dis, slp, s=2, alpha=1.0, edgecolors='none', rasterized=True)
plt.plot(Xmod, Ymod, linestyle='--', c='#ff7f0e')
plt.xlabel('Drainage area')
plt.xscale('log')
plt.xlim((A0, A1))
plt.ylabel('Slope')
plt.yscale('log')
plt.ylim((S0, S1))

def logdensity(values, vmin=None, vmax=None, n=200):
    hist, bins = np.histogram(np.log(values), range=np.log((vmin, vmax)), density=True, bins=n)
    bins = np.exp((bins[:-1]+bins[1:])/2)
    return hist, bins

plt.subplot(grid[0,0], sharex=mainplt)
hist, bins = logdensity(dis, vmin=A0, vmax=A1)
plt.plot(bins, hist)
plt.fill_between(bins, 0, hist, alpha=0.35)
plt.grid(False)
plt.axis('off')

plt.subplot(grid[1,1], sharey=mainplt)
hist, bins = logdensity(slp, vmin=S0, vmax=S1)
plt.plot(hist, bins)
plt.fill_betweenx(bins, 0, hist, alpha=0.35)
plt.grid(False)
plt.axis('off')

plt.tight_layout()

if len(sys.argv) < 3:
    plt.show()
else:
    plt.savefig(os.path.expanduser(sys.argv[2]), dpi=300, transparent=True)
