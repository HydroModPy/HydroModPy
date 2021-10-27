# coding: utf-8

import os, re
import numpy as np
import pandas as pd
from osgeo import gdal
import flopy
from flopy.export import vtk as fv
import vtk
from workingFunctions import Functions
from get_geological_structure import get_geological_structure as ggs

modelfolder = 'H:/Users/gauvain/DEM/Guidel/'
modelname = 'Guidel1'
mf1 = flopy.modflow.Modflow()
dis = flopy.modflow.ModflowDis.load(modelfolder+modelname+'.dis',mf1)

cols = dis.ncol
rows = dis.nrow

piezos =['xyPSR1','xyPSR2','xyPSR15','xyPZ15','xyPZ16','xyPZ17','xyPZ19','xyPZ21','xyPZ26']

textoVtk = open(modelfolder + 'output_files/VTU_Pathlines.vtk', 'w')
# add header
textoVtk.write('# vtk DataFile Version 2.0\n')
textoVtk.write('Particles Pathlines Modpath\n')
textoVtk.write('ASCII\n')
textoVtk.write('DATASET POLYDATA\n')
textoVtk.write('POINTS ' + '18' + ' float\n')
for i in range(0, np.alen(piezos)):
    piezo = pd.read_table(modelfolder+piezos[i]+'.txt', header=None)
    x=(int(piezo._values[1]))*10
    y=(rows-int(piezo._values[0]))*10
    z=dis.top[int(piezo._values[0,0])-1,int(piezo._values[1,0])-1]+1
    d=dis.top[int(piezo._values[0,0])-1, int(piezo._values[1,0])-1]-piezo._values[2,0]
    textoVtk.write(str(x) + ' ' + str(y) + ' ' + str(z) + '\n')
    textoVtk.write(str(x) + ' ' + str(y) + ' ' + str(d) + '\n')
textoVtk.write('\n')
textoVtk.write('LINES ' + '9' + ' ' + '27' + '\n')
nb = 0
for i in range(0, np.alen(piezos)):
    textoVtk.write('2' + ' ')
    textoVtk.write(str(nb) + ' ')
    nb = nb + 1
    textoVtk.write(str(nb) + ' ')
    nb = nb + 1
    textoVtk.write('\n')

textoVtk.write('POINT_DATA ' + '18' + '\n')
textoVtk.close()