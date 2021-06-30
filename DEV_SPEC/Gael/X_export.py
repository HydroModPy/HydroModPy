#!/usr/bin/env python3

import util
import numpy as np
from osgeo import gdal, osr
drv = gdal.GetDriverByName('GTiff')

class Exporter:
    def __init__(self, **desc):
        self.desc = desc
        self.data = util.load_data(**desc)
        self.meta = util.load_meta(**desc)

    def __call__(self, fname, *args, **kwargs):
        f = getattr(self, 'get_'+fname)
        return f(*args, **kwargs)

    def get_outflow(self, layer=0):
        layer = int(layer)
        return np.ma.masked_less_equal(self.data['outflow'][layer], 0.)

    def get_water_table(self):
        head = self.data['head']
        zbot = self.data['zbot']
        wt = head[-1]
        for n in range(head.shape[0]-2, -1, -1):
            headn = head[n]
            is_water = headn > zbot[n]
            wt[is_water] = headn[is_water]
        return np.ma.masked_array(wt, wt <= zbot[-1])

    def get_depth(self):
        return np.maximum(self.data['ztop'] - self.get_water_table(), 0.)

    def get_length(self):
        return self.data['path_length_3d']

    def get_time(self):
        return self.data['path_time']

    def make_tif(self, filename, data, nodata=-32767):
        data = np.ma.masked_values(data, nodata)
        raster = drv.Create(filename, data.shape[1], data.shape[0], 1, gdal.GDT_Float32)
        raster.SetGeoTransform(self.meta['projection']['geodata'])
        proj = self.meta['projection']['crs']
        if proj[:5] == 'EPSG:':
            proj = proj[5:]
        is_proj = True
        try:
            epsg = int(proj)
        except ValueError:
            is_proj = False
        if is_proj:
            crs = osr.SpatialReference()
            crs.ImportFromEPSG(epsg)
            raster.SetProjection(crs.ExportToWkt())
        band = raster.GetRasterBand(1)
        band.WriteArray(data.filled(nodata))
        band.SetNoDataValue(nodata)
        band.ComputeStatistics(True)
        band.FlushCache()

if __name__ == '__main__':
    import sys
    watershed, model_name = sys.argv[1:3]
    fargs = sys.argv[3:-1]
    path = sys.argv[-1]

    exp = Exporter(watershed=watershed, model_name=model_name)
    data = exp(*fargs)
    exp.make_tif(path, data)
