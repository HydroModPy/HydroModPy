# -*- coding: utf-8 -*-
"""
Created on Mon Mar 24 10:39:27 2025

@author: delarueo
chat gpt

"""

import os
import shutil

def reproduce_folder_structure(source_dir, target_dir, file_criteria=None):
    """
    Reproduces the folder structure from source_dir to target_dir.
    Optionally copies files that match the file_criteria to the new location.
    
    :param source_dir: The source directory to copy structure from.
    :param target_dir: The target directory where the structure will be created.
    :param file_criteria: Function that returns a boolean indicating if a file matches the criteria (default is None).
    """
    for root, dirs, files in os.walk(source_dir):
        # Reproduce the folder structure
        relative_path = os.path.relpath(root, source_dir)
        target_folder = os.path.join(target_dir, relative_path)
        os.makedirs(target_folder, exist_ok=True)
        
        # Check and copy the files matching the criteria
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if file_criteria and file_criteria(file_name):  # Only copy if it matches the criteria
                target_file_path = os.path.join(target_folder, file_name)
                shutil.copy(file_path, target_file_path)
                print(f"Copied: {file_path} -> {target_file_path}")

# Example usage:
source_directory = 'F:/_cerra_forecast/'
target_directory = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'

# Define file criteria (e.g., copy only .txt files)
def file_criteria(file_name):
    
    test = any([file_name.endswith('.txt'),
                file_name.endswith('_grid.nc'),
                file_name.endswith('_alps.nc')])   
    return test

reproduce_folder_structure(source_directory, target_directory, file_criteria)