# -*- coding: utf-8 -*-
"""
Created on Tue Oct 19 17:28:38 2021

@author: Alexandre Gauvain
"""
from vedo import *
from vedo.applications import Browser, FreeHandCutPlotter
import numpy as np
file2 = 'C:/Users/alexa/Dropbox/HP_Article_Data/Data/output_files/VTU_Pathlines.vtk'
mesh5 = Mesh(file2)


plt = Plotter(N=1, axes=dict(xtitle='m', ytitle='m', ztitle='m', yzGrid=False),
              bg2='lb', size=(1920,1080)) # screen size
#Pathlines
vmax = max(mesh5.pointdata['Time'])
mesh5.cmap('jet',input_array='Time',vmax=vmax/100).lw(10)
mesh5.addScalarBar()
mesh5.scale([1,1,20])
mesh5.renderLinesAsTubes(value=True)

x = mesh5.lines()
length = max(map(len, x))
y=np.array([xi+[None]*(length-len(xi)) for xi in x])
number_of_rows = y.shape[0]
random_indices = np.random.choice(number_of_rows, size=35000, replace=False)
y1 = y[random_indices, :].flatten()
pts =  y1[y1 != np.array(None)]
mesh5.deletePoints(pts)

plt.show(mesh5, interactive=1)