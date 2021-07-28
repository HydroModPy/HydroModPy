#!/usr/bin/env python3

from modflowsim import MfModel
import os
import sys
import numpy as np

try:
    from mpi4py import MPI
    use_mpi = True
except ImportError:
    use_mpi = False

if use_mpi:
    comm = MPI.COMM_WORLD
    r = comm.Get_rank()
    s = comm.Get_size()
    i = 0

Klist = [5e-7, 1e-6, 2e-6]
Dlist = [1/50, 1/30, 1/20, 1/13]
R = 2e-8

thick_factor = 8.
nlay = 10
thick_exp = 1.25
layer_min_thick = 5.

dem_path = sys.argv[1]
dem_name = os.path.splitext(os.path.split(dem_path)[1])[0]

for Kn, K in enumerate(Klist):
    for Dn, D in enumerate(Dlist):
        if Dn < 3:
            continue
        if use_mpi:
            i += 1
            if i%s != r:
                continue

        model_name = 'K{:d}D{:d}'.format(Kn+1, Dn+1)
        print(model_name)
        sys.stdout.flush()
        thick = thick_factor / D
        nlay = int(np.log(1-thick*(1-thick_exp)/layer_min_thick) / np.log(thick_exp))

        model = MfModel(dem_path, watershed=dem_name, model_name=model_name, climatic=[R], lay_number=nlay, hyd_cond=K, cond_decay=D, thick=thick, thick_exp=thick_exp, exe='mfnwt')
        model.export_data()
