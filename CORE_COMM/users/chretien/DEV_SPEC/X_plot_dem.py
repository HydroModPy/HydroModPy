#!/usr/bin/env python3

import util
import sys
import os
import slope
from osgeo import gdal
import matplotlib.pyplot as plt
import numpy as np
from functools import partial

def courant(fname_dem, fname_dis):
    dem_obj = gdal.Open(fname_dem)
    dem = dem_obj.ReadAsArray()
    gt = dem_obj.GetGeoTransform()
    dx = abs(gt[1]*gt[5] - gt[2]*gt[4]) ** 0.5
    dis = gdal.Open(fname_dis).ReadAsArray()
    slp = slope.slope_down_d8(dem, spacing=dx)

    meta = dem_obj.GetMetadata()
    def get_field(field, default=0., dtype=float):
        if field in meta:
            return dtype(meta[field])
        else:
            return default

    U = get_field('uplift_rate', 1e-3)
    K = get_field('k_coef', 2e-6)
    m = get_field('area_exp', 0.6)
    n = get_field('slope_exp', 1.5)
    Smax = get_field('slope_limit', 0.5)
    dt = get_field('dt', 800.)

    #U = 1e-3
    #K = 2e-6
    #m = 0.6
    #n = 1.5
    #Smax = 0.5
    #dx = 125.
    #dt = 4e4

    midlength = (dem.size**0.5) / 2 * dx
    print(dt/dx * U**(1-1/n) * K**(1/n) * midlength**(2*m/n))

    erospeed = K * dis**m * slp**n
    advspeed = K * dis**m * slp**(n-1)
    courant = advspeed * dt / dx
    plt.subplot(1,2,1)
    plt.imshow(erospeed)
    plt.title('Erosion speed')
    plt.colorbar(orientation='horizontal')
    plt.subplot(1,2,2)
    plt.imshow(courant)
    plt.title('Courant number')
    plt.colorbar(orientation='horizontal')

def dem_pdf(*fnames, log=False):
    for fname in fnames:
        name = os.path.splitext(os.path.split(fname)[1])[0]
        if isinstance(log, str):
            log = log.lower() == 'true'
        dem = gdal.Open(os.path.expanduser(fname)).ReadAsArray()
        nbins = 50
        if log:
            bins = np.geomspace(dem[dem>0.].min(), dem.max(), nbins+1)
            bincenter = np.sqrt(bins[:-1]*bins[1:])
        else:
            bins = np.linspace(dem.min(), dem.max(), nbins+1)
            bincenter = (bins[:-1]+bins[1:]) / 2
        prob = np.histogram(dem, bins=bins, density=True) [0]
        plt.plot(bincenter, prob, label=name)#, s=5, edgecolor='none')
    if log:
        plt.xscale('log')
    plt.yscale('log')
    plt.legend()

functions = {
    'courant': courant,
    'dem_pdf': partial(dem_pdf, log=False),
    'dem_pdf_log': partial(dem_pdf, log=True),
}

if __name__ == '__main__':
    import sys

    f = sys.argv[1]
    functions[f](*sys.argv[2:])
    plt.tight_layout()
    plt.show()
