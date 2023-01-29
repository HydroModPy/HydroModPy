# -*- coding: utf-8 -*-
"""
Created on Sat Jan  7 16:08:40 2023

@author: jdedreuz
"""

# -*- coding: utf-8 -*-
"""


"""

import ParametersGroup as pg


def library1(paramgroup): 
    print('\n\tLibrary 1 called within Libraries')
    print('\t\tParameter param1 ', paramgroup.getparam('param1').getvalue())

