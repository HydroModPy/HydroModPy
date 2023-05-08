# -*- coding: utf-8 -*-
"""
Created on Sat Jan  7 16:08:40 2023

@author: jdedreuz
"""

# -*- coding: utf-8 -*-
"""


"""

import sys
import os
from os.path import dirname


def python_path_update(DIR):
    # Root directory name (should be )
    root_folder ="core_comm"
    # Test to confirm that current folder is CORE_COMM
    if (DIR.split(os.sep)[-1]!=root_folder): 
        print("Error detected in the root folder path, Aborts to avoid wrong executions")
        print("Current Folder is", DIR)
        print("Adds folder from Environment Variable")
        folder = os.path.join(os.getenv("HYDROMODPY_ROOT").replace('/',os.sep),"HydroModPy","CORE_COMM")
        print(folder)
    else: 
        folder = DIR
        
    # APPENDS ROOT FOLDER 
    sys.path.append(folder)

    # HYDROMODPY TOOLS
    sys.path.append(os.path.join(dirname(folder),"Tools","Parameters","Parameters"))
    
    return folder
    


