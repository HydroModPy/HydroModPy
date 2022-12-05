#!/usr/bin/env python3

from osgeo import gdal
import numpy as np
import matplotlib.pyplot as plt
import os
import slope

def plot_slope_discharge(dem_file, dis_file):
    dem_obj = gdal.Open(os.path.expanduser(dem_file))
    dem = dem_obj.ReadAsArray()
    gt = dem_obj.GetGeoTransform()
    spacing = np.sqrt(np.abs(gt[1]*gt[5] - gt[2]*gt[4]))
    print(spacing)

    dis_obj = gdal.Open(os.path.expanduser(dis_file))
    dis_nodata = dis_obj.GetRasterBand(1).GetNoDataValue()
    dis = dis_obj.ReadAsArray()
    isvalid = (dis != dis_nodata) & (dis > 0.0)
    dis = dis[isvalid]
    dem_nodata = dem_obj.GetRasterBand(1).GetNoDataValue()
    slp = slope.slope_down_d8(dem, spacing=spacing, nodata=dem_nodata)[isvalid]
    print(dem_nodata, slp.max(), slp.mean())

    nbins = 100
    bins = np.geomspace(dis.min(), dis.max(), nbins+1)
    bins[-1] += 1

    binref = np.digitize(dis, bins) - 1
    bincount = np.zeros(nbins)
    binsum = np.zeros(nbins)

    for i, n in enumerate(binref):
        bincount[n] += 1
        binsum[n] += slp[i]
        #if n == 250:
            #print(slp[i])
    #print(binsum[250]/bincount[250])

    name = os.path.splitext(os.path.split(dem_file)[1])[0]

    bincenter = np.sqrt(bins[:-1]*bins[1:])
    plt.plot(bincenter, binsum/bincount, label=name)

if __name__ == '__main__':
    import sys
    args = sys.argv[1:]
    n = len(args) // 2

    for i in range(n):
        dem, dis = args[2*i:2*i+2]
        print(dem)
        plot_slope_discharge(dem, dis)
    plt.xlabel('Catchment area')
    plt.ylabel('Slope')
    plt.xscale('log')
    plt.yscale('log')
    plt.legend()
    plt.show()
