#!/usr/bin/env python3

import numpy as np
import util
from osgeo import gdal
import matplotlib.pyplot as plt
import os
import sys

for dem_path in sys.argv[1:]:
    name = os.path.splitext(os.path.basename(dem_path))[0]
    dem = gdal.Open(dem_path).ReadAsArray()
    val = np.sort(dem, axis=None)
    X = np.linspace(0, 1, dem.size)
    plt.plot(X, val, label=name)
plt.legend()
plt.show()
