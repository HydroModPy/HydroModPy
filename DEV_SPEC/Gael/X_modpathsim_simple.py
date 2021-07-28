#!/usr/bin/env python3

from modpathsim import MpModel
import sys

watershed, model_name = sys.argv[1:3]

model = MpModel(watershed=watershed, model_name=model_name, exe='mp6', verbose=False)

model.export_data()
