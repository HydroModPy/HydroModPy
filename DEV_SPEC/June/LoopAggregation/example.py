import os, sys
lib_path = os.path.abspath(os.path.join(__file__, 'docker_simulation', 'modflow', 'custom_utils'))
sys.path.append(lib_path)

from docker_simulation.modflow.custom_utils import InputFileManipulation
from docker_simulation.modflow import settings_model
from docker_simulation.modflow import ErrorComput

### Definition of parameters' values
approx=0
rate=5000
chronicle=12
site=2
ref=False

### Creation of the input file (input data for the simulation) for the corresponding 
### parameters (approximation rate, chronicle, type of approximation, etc)

#InputFileManipulation.generate_custom_input_file(model_name=None, approx=0, rate=5000, chronicle=12, steady=False)

### Launching the modflow simulation with the corresponding input file

#settings_model.setting(permeability=8.64, time=0, geology=0, theta=0.1, input_file=None, step=1, ref=ref, chronicle=chronicle, approx=approx, rate=rate, rep=False, steady=False, site=site)

### Computation of the H indicator (acceptability metrics)
