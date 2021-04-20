#!/usr/bin/env python3

from modpathsim import MpModel
import numpy as np
import sys
import os

recharges = np.logspace(-10, -5, 16)

for watershed in sys.argv[1:]:
    K = 1e-6

    for R, rech in enumerate(recharges, start=1):
        model_name = "R{:d}".format(R)
        print(watershed, model_name)
        model = MpModel(watershed=watershed, model_name=model_name, exe='mp6')

        model.export_data()
