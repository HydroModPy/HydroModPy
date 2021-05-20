#!/usr/bin/env python3

from whitebox import WhiteboxTools
import os

wbt = WhiteboxTools()

def generate_drainage(dem_path):
    dirname, filename = os.path.split(os.path.expanduser(dem_path))
    prefix, ext = os.path.splitext(filename)

    smooth_path = '{}_smooth{}'.format(prefix, ext)
    breach_path = '{}_breach{}'.format(prefix, ext)
    rivers_path = '{}_rivers{}'.format(prefix, ext)
    slope_path = '{}_slope{}'.format(prefix, ext)

    wbt.set_working_dir(dirname)
    wbt.feature_preserving_smoothing(dem_path, smooth_path, filter=9)
    wbt.breach_depressions(smooth_path, breach_path)
    wbt.d_inf_flow_accumulation(breach_path, rivers_path, out_type='ca')

    wbt.average_flowpath_slope(breach_path, slope_path)

if __name__ == '__main__':
    import sys
    generate_drainage(sys.argv[1])
