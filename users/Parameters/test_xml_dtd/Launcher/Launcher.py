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

sys.path.append(os.path.abspath('../../Parameters'))
sys.path.append(os.path.abspath('../Libraries/Library1'))
sys.path.append(os.path.abspath('../Libraries/Library2'))

import ParametersGroup as pg
import Library1 as l1
import Library2 as l2



def launcher(paramgroup): 
    print('\nLauncher is the Root Level of the program')
    print('\tValue of type in launcher ', paramgroup.getparam('type').getvalue())    



if __name__ == "__main__":
    
    # Initialization of Reference ParametersGroup
    file_ref = "Parameters_Reference/prog_master_reference.xml"
    # ref = pg.ParametersGroup(file_ref)   
    # Loads User ParametersGroup
    file_usr = "Parameters_Reference/prog_user.xml"
    # usr = pg.ParametersGroup(file_usr)   
    # Results folder
    folder_res = "../../../../../results/test_launcher"
    # Merges the two structures and affects default_values to values when necessary
    paramgroup = pg.ParametersGroup.merge_diff(file_ref,file_usr,pg.EXPLOPT.REPLACE,folder_res)[0]
    
    # Output full xml parameter structure
    paramgroup.write(pg.folder_of_file_new("prog_master_result.xml",folder_res))
    
    # Call of root function "launcher" with the corresponding parametergroup and not more
    launcher(paramgroup.getgroup('launcher'))
    
    # Callint library1 function with the parametersgroup corresponding
    l1.library1(paramgroup.getgroup('libraries').getgroup('library1'))
    # Callint library2 function with the parametersgroup corresponding
    l2.library2(paramgroup.getgroup('libraries').getgroup('library2'))

    # Access to groups and params from root
    paramgroup.getgroup('libraries::library2')
    paramgroup.getparam('libraries::library2::param2')

    # Call directly from the root the parameter at the end of a leaf
    print('\nCalling leaf parameter param 1 of library 2 from the root\n\t\tParameter param2 ', 
          paramgroup.getgroup('libraries').getgroup('library2').getparam('param2').getvalue())

    # Error messages
    print('\nError Messages')
    paramgroup.getgroup('group_error')
    paramgroup.getgroup('libraries').getgroup('group_error')
    paramgroup.getgroup('libraries').getgroup('library2').getparam('param_error')
    
    