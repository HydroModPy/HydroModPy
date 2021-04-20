#!/usr/bin/env python3

from topogen import Topo
import os
import sys
import util

folder = 'topo_steps'
if len(sys.argv) > 1:
    folder = sys.argv[1]
folder = os.path.join(util.fspath, folder)
if not os.path.isdir(folder):
    os.mkdir(folder)

nsteps = 10
topo = Topo(max_time=4e6, steps=500, out_steps=nsteps)

for i in range(nsteps):
    topo.export(os.path.join(folder, 'T{:d}.tif'.format(i+1)), os.path.join(folder, 'T{:d}_area.tif'.format(i+1)), os.path.join(folder, 'T{:d}_slope.tif'.format(i+1)), step=i)
