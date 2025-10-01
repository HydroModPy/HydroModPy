# -*- coding: utf-8 -*-
"""
Created on Tue Jun 24 10:57:33 2025

@author: delarueo


from plt to vtk
"""

import numpy as np
import pyvista as pv

def parse_ascii_plt(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
    
    # Assuming the format:
    # VARIABLES = "X" "Y" "Z" "Variable1" ...
    # ZONE T="Zone 1", I=..., J=..., K=...
    # Followed by data in columns
    
    # Parse header
    var_line = next(line for line in lines if 'VARIABLES' in line)
    variables = [v.strip('" ') for v in var_line.split('=')[1].split('"') if v.strip()]
    
    # Find where data starts
    data_start = next(i for i, line in enumerate(lines) if line.strip().replace('.', '').replace('-', '').replace('E', '').replace('+', '').replace(' ', '').isdigit())
    
    data = np.loadtxt(lines[data_start:])
    return variables, data

def write_vtk_from_plt(plt_file, vtk_file):
    variables, data = parse_ascii_plt(plt_file)
    x, y, z = data[:, 0], data[:, 1], data[:, 2]
    
    points = np.column_stack((x, y, z))
    point_cloud = pv.PolyData(points)
    
    for i, var in enumerate(variables[3:]):
        point_cloud.point_data[var] = data[:, i+3]
    
    point_cloud.save(vtk_file)
    print(f"Saved VTK file to: {vtk_file}")

# Example usage
write_vtk_from_plt("input.plt", "output.vtk")
