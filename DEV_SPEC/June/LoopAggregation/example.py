import os, sys
lib_path = os.path.abspath(os.path.join(__file__, 'modflow', 'custom_utils'))
sys.path.append(lib_path)

from modflow.custom_utils import InputFileManipulation
from modflow import settings_model
from modflow import ErrorComput

### Definition of the values of the parameters
approx=0
rate=5000
chronicle=12
site=2
ref=False
perm=27.32
folder= None
steady=False


#########################################################################
# /!\ We assume that the reference simulation has already been run here #
#########################################################################

### Command for the reference simulation (without any approximation) => BE AWARE: Long time to compute
### JUST SOME INFORMATION about running the reference simulation
### NO NEED to run it as the output file have already been generated to spare some time
#settings_model.setting(permeability=perm, time=0, geology=0, theta=0.1, input_file=None, step=1, ref=True, chronicle=chronicle, approx=approx, rate=rate, rep=False, steady=False, site=site)

##### START HERE #####
### Creation of the input file (input data for the simulation) for the corresponding 
### parameters (approximation rate, chronicle, type of approximation, etc)

InputFileManipulation.generate_custom_input_file(model_name=None, approx=0, rate=5000, chronicle=12, steady=False)

### Launching the modflow simulation with the corresponding input file
## Execution time: ~2minutes
settings_model.setting(permeability=perm, time=0, geology=0, theta=0.1, input_file=None, step=1, ref=ref, chronicle=chronicle, approx=approx, rate=rate, rep=False, steady=False, site=site)

### Computation of the H indicator (acceptability metrics)

# Convert hds file of ref simulation into binary file (.npy) to load it faster during H computation
print("Conversion of ref Hds file starting...")
ErrorComput.topo_file(site_number=site, chronicle=chronicle, approx=approx, rate=rate, ref=True, folder=folder, steady=steady, permeability=perm)
print("Conversion of ref Hds file finished.")

## Pre-processing of H Computation: Analysis of site under study
print("Analysing catchment areas of the site under study...")
ErrorComput.dev_get_computed_bassin_Mask(site_number=site)
print("Analysis finished.")

## Actual Computation
## BE AWARE: TAKES QUITE SOME TIME TO EXECUTE: May be ~1or2hours
print("Computing of the H indicator starting...")
#ErrorComput.compute_h_error_by_interpolation(site_number=site, chronicle=chronicle, approx=approx, rate=rate, ref=ref, folder=folder, permeability=perm, steady=False, time_step=1)
print("Computation of H indicator finished.")