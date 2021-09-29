# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 14:52:56 2021

@author: Alexandre Gauvain
"""

#modules
import os

def create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)
        
# if os.path.isdir(output_directory) != True:
#     # Creates output dir if it does not already exist 
#     os.mkdir(output_directory)