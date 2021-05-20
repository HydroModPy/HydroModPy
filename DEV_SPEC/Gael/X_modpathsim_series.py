#!/usr/bin/env python3

from modpathsim import MpModel
import numpy as np
import sys
import os

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

recharges = np.logspace(-10, -5, 16)

for watershed in sys.argv[1:]:
    K = 1e-6

    for R, rech in enumerate(recharges, start=1):
        if use_mpi:
            i += 1
            if i%s != r:
                continue
        model_name = "R{:d}".format(R)
        print(watershed, model_name)
        sys.stdout.flush()
        model = MpModel(watershed=watershed, model_name=model_name, exe='mp6', verbose=False)

        model.export_data()
