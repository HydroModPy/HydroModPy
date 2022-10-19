#!/usr/bin/env python3

import numpy as np
from osgeo import osr
import json
import util
import sys

watershed, model_name, n = sys.argv[1:4]
n = int(n)

desc = {'watershed': watershed, 'model_name': model_name}
data = util.load_data(**desc)
meta = util.load_meta(**desc)

gt = meta['projection']['geodata']
crs = meta['projection']['crs']
projected = False
if crs[:5] == 'EPSG:':
    crs_in = osr.SpatialReference()
    crs_in.ImportFromEPSG(int(crs[5:]))
    crs_out = osr.SpatialReference()
    crs_out.ImportFromEPSG(4326)
    trans = osr.CoordinateTransformation(crs_in, crs_out)

path_index = data['path_index']
path = data['path']

name = 'lines_{}_{}'.format(watershed, model_name)

features = []
main_obj = {'type': 'FeatureCollection',
            'name': name,
            'features': features,
}

dem = data['ztop']
xorigin = gt[0]
yorigin = gt[3] + dem.shape[1]*gt[4] + dem.shape[0]*gt[5]

for i in np.random.choice(path_index.shape[0], size=n, replace=False):
    i0, i1 = path_index[i]
    ipath = path[i0:i1]

    p0 = ipath[0]
    dist = 0.
    for p1 in ipath[1:]:
        dist += ((p1['x']-p0['x'])**2 + (p1['y']-p0['y'])**2 + (p1['z']-p0['z'])**2)**.5
        p0 = p1

    coordinates = []
    for p in ipath:
        lat, lon, alt = trans.TransformPoint(xorigin+p['x'], yorigin+p['y'])
        coordinates.append([float(lon), float(lat)])

    feature = {'type': 'Feature',
               'geometry': {
                   'type': 'LineString',
                   'coordinates': coordinates,
                },
               'properties': {
                   'id': int(i),
                   'length': float(dist),
                   'time': float(ipath[-1]['time']),
                },
    }

    features.append(feature)

filename = name + '.geojson'
with open(filename, 'w') as f:
    json.dump(main_obj, f)
