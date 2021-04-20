#!/usr/bin/env python3

from modflowsim import MfModel
import numpy as np
import sys
import os

recharges = np.logspace(-10, -5, 16)

for dem_path in sys.argv[1:]:
    watershed = os.path.splitext(os.path.basename(dem_path))[0]
    K = 1e-6

    for R, rech in enumerate(recharges, start=1):
        model_name = "R{:d}".format(R)
        print(watershed, model_name)
        model = MfModel(dem_path, watershed=watershed, model_name=model_name, climatic=[rech], lay_number=1, bottom=-100., hyd_cond=K, exe='mfnwt')

        model.export_data()
