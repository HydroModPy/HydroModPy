# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé

"""

#%% MODULES

from os.path import dirname, abspath
import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Current Directory stored in DIR 
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)

from examples.a_given import example1_hydromodpy

#%% REF PATH

# Current Directory stored in DIR 
tests_path = dirname(abspath(__file__))
sys.path.append(tests_path)

#%% OUT PATH

####################################################

user = 'Ronan'

# Path where the results will be stored (SHOULD BE SPECIFIED BY THE USER)
if user == 'Jean-Raynald':
    out_path = "D:/results/HydroModPy/"
if user == 'Alexandre':
    out_path = "C:/Users/alexa/Dropbox/HydroModPy/"
if user == 'Martin':
    out_path = r'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
if user == 'Ronan':
    out_path = 'D:/Users/abherve/TESTS/'
    
####################################################

#%% LAUNCH TEST

# Launch this code in the "tests" folder

example1_hydromodpy.run_example(out_path, regression_test=True)

#%% CHECK RESULTS

# from deepdiff import DeepDiff
# diff = DeepDiff(r_npy, o_npy)
# print(diff)

# Launcch this code in the "tests" folder

ref_path_sim = os.path.join(tests_path, 'Example/results_simulations/test/_watershed/')
out_path_sim = os.path.join(out_path, 'Example/results_simulations/test/_watershed/')

r_npy = np.load(os.path.join(ref_path_sim, 'watertable_elevation.npy'), allow_pickle=True).item()
o_npy = np.load(os.path.join(out_path_sim, 'watertable_elevation.npy'), allow_pickle=True).item()

if r_npy[0].all() == o_npy[0].all():
    print('The .npy file results are similar')

r_csv = pd.read_csv(os.path.join(ref_path_sim,'_simulated_results.csv'), sep=';')
o_csv = pd.read_csv(os.path.join(out_path_sim,'_simulated_results.csv'), sep=';')

comp = r_csv.compare(o_csv, keep_shape=True, keep_equal=True)
# print(comp)
if all(r_csv==o_csv) == True:
    print('The .csv file results are similar')

#%% NOTES

# import os
# import glob
# import filecmp

# comparison = []
# for each in glob.glob('D:/Users/abherve/TESTS/Test/**'):
#     for each1 in glob.glob('D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/tests/Test/**'):
#         if os.path.basename(each) == os.path.basename(each1):
#             comparison.append(filecmp.cmp(each, each1))

# print(comparison)
