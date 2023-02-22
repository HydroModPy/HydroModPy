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

# Current Directory stored in DIR 
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)

from examples.a_given import example1_hydromodpy

#%% PATH TESTS

# Current Directory stored in DIR 
tests_path = dirname(abspath(__file__))
sys.path.append(tests_path)

#%% UPDATE REFERENCE

# Launch this code in the "tests" folder

if os.getcwd() != tests_path:
    os.chdir(tests_path)
    
out_path = tests_path

example1_hydromodpy.run_example(out_path, regression_test=True)

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
