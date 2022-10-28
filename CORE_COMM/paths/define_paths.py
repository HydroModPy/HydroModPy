# -*- coding: utf-8 -*-
"""
Created on Mon Oct 24 11:46:45 2022

@author: Martin Le Mesnil
"""

import os
import pandas as pd

#Get user-specific HydroModPy root directory path
current_path = __file__
idx = current_path.find('\core_comm\paths\define_paths.py') #only 'core_comm'? 3x dirname()?
HMP_root_path = current_path[:idx]

#Get input data path from user input
input_path = input('Enter absolute path of existing input data folder: ')
while os.path.exists(input_path) == False:
    input_path = input('Please enter an existing input data path: ')

#Get output data path from user input
output_path = input('Enter absolute path of output data folder: ')
if os.path.exists(output_path) == False:
    os.mkdir(output_path)

#Write paths to csv in HMP root directory (out of version control)
path_dict = {'in_path': [input_path], 'out_path': [output_path]}
path_df = pd.DataFrame(path_dict)
paths_file = os.path.join(HMP_root_path, 'HMP_paths.csv') #use parent directory?
path_df.to_csv(paths_file, sep=';', index=False)

