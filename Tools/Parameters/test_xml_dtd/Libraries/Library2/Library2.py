# -*- coding: utf-8 -*-
"""
Created on Sat Jan  7 16:08:40 2023

@author: jdedreuz
"""

# -*- coding: utf-8 -*-
"""


"""

import ParametersGroup as pg


def library2(paramgroup): 
    print('\n\tLibrary 2 called within Libraries')
    print('\t\tParameter param2 ', paramgroup.getparam('param2').getvalue())

