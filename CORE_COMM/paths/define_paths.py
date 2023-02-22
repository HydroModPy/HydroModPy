# -*- coding: utf-8 -*-
"""
Created on Mon Oct 24 11:46:45 2022

@author: Martin Le Mesnil
"""

import os
import pandas as pd
import sys
from os.path import dirname, abspath

#Execute this file the the HydroModPy\CORE_COMM, soon HydroModPy only
DIR = dirname(dirname((abspath(__file__))))
print(DIR)
sys.path.append(DIR)

#Get user-specific HydroModPy root directory path
current_path = abspath(__file__)
idx = current_path.find('\define_paths.py')
HMP_root_path = current_path[:idx]
print(HMP_root_path)

#Get input data path from user input
input_path = input('Enter absolute path of existing input data folder: ')
# Example of input : D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/_HydroDataPy/
### Without ' '
while os.path.exists(input_path) == False:
    input_path = input('Please enter an existing input data path: ')
if input_path[-1] != '/':
    input_path = os.path.join(input_path, '/')

#Get output data path from user input
output_path = input('Enter absolute path of output data folder: ')
# Example of output : D:/Users/abherve/HYDROMODPY/
### Without ' '
if os.path.exists(output_path) == False:
    os.mkdir(output_path)
if output_path[-1] != '/':
    output_path = os.path.join(output_path, '/')

#Write paths to csv in HMP root directory (out of version control)
path_dict = {'in_path': [input_path], 'out_path': [output_path]}
path_df = pd.DataFrame(path_dict)
paths_file = os.path.join(HMP_root_path, 'HMP_paths.csv') #use parent directory?
path_df.to_csv(paths_file, sep=';', index=False)
