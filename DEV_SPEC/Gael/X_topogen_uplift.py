#!/usr/bin/env python3

from topogen import Topo
import numpy as np
import os
import util
import sys

try:
    from mpi4py import MPI
    use_mpi = True
except ImportError:
    use_mpi = False

if use_mpi:
    comm = MPI.COMM_WORLD
    r = comm.Get_rank()
    s = comm.Get_size()

folder = 'topo_uplift'
if len(sys.argv) > 1:
    folder = sys.argv[1]
folder = os.path.join(util.fspath, folder)
if not os.path.isdir(folder):
    os.mkdir(folder)

uplifts = np.logspace(-4, -2, 9)

for i, U in enumerate(uplifts):
    if use_mpi and i%s != r:
        continue
    print('U{:d}'.format(i+1), U)
    sys.stdout.flush()
    topo = Topo(max_time=4e6, steps=5000, uplift_rate=U, verbose=False)
    topo.export(os.path.join(folder, 'U{:d}T.tif'.format(i+1)), os.path.join(folder, 'U{:d}D.tif'.format(i+1)), os.path.join(folder, 'U{:d}S.tif'.format(i+1)))
