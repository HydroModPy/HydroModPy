# coding: utf-8

import os, re
import numpy as np
from osgeo import gdal
import flopy
from flopy.export import vtk as fv
#import vtk
from workingFunctions import Functions
from get_geological_structure import get_geological_structure as ggs

def vtk_export_pathlines(modelname, modelfolder, coord):
    geot_p, geotx_p, geoty_p, demData_p, lay_wt_p, lay_ft_p, lay_kb_p, lay_kf_p, lay_kw_p, sea_earth_p, river_p = ggs(coord)
    cols = geotx_p.shape[0]
    rows = geoty_p.shape[0]
    ext = []
    xarr = [0, cols]
    yarr = [0, rows]

    for px in xarr:
        for py in yarr:
            x = geotx_p[0] + (px * geot_p[1]) + (py * geot_p[2])
            y = geoty_p[0] + (px * geot_p[4]) + (py * geot_p[5])
            ext.append([x, y])
    print('gt')
    pthobj = flopy.utils.PathlineFile(modelfolder+modelname+'.mppth')
    print('pthobj')
    pth_data = pthobj.get_alldata()
    print('pth_data')
    t_store = []
    x_store = []
    y_store = []
    z_store = []
    l_store = []
    v_store = []
    for i in range(0, pthobj.nid):
        Data = pth_data[i]
        x = [x for (x, y, z, t, l, a) in Data]
        z = [z for (x, y, z, t, l, a) in Data]
        y = [y for (x, y, z, t, l, a) in Data]
        t = [t for (x, y, z, t, l, a) in Data]
        l = [l for (x, y, z, t, l, a) in Data]
        t = np.asarray(t)
        t_store.append(t)
        l_store.append(l)
        y_store.append(y)
        x_store.append(x)
        z_store.append(z)
        a = 0
    nb_points = 0
    for i in range(0, np.alen(x_store)):
        nb_points = nb_points + np.alen(x_store[i])

    for i in range(0, np.alen(x_store)):
        for j in range(0, np.alen(x_store[i])):
            if j == 0:
                v_store.append(0)
            else:
                d = np.sqrt(((x_store[i][j] - x_store[i][j - 1]) ** 2) + ((y_store[i][j] - y_store[i][j - 1]) ** 2) + (
                            (z_store[i][j] - z_store[i][j - 1]) ** 2))
                if (t_store[i][j] - t_store[i][j - 1]) == 0:
                    v_store.append(0)
                else:
                    v = d / (t_store[i][j] - t_store[i][j - 1])
                    v_store.append(v)

    textoVtk = open(modelfolder+'output_files/VTU_Pathlines.vtk', 'w')
    # add header
    textoVtk.write('# vtk DataFile Version 2.0\n')
    textoVtk.write('Particles Pathlines Modpath\n')
    textoVtk.write('ASCII\n')
    textoVtk.write('DATASET POLYDATA\n')
    textoVtk.write('POINTS ' + str(nb_points) + ' float\n')
    for line in range(0, np.alen(x_store)):
        for particles in range(0, np.alen(x_store[line])):
            textoVtk.write(
                str(x_store[line][particles] + ext[1][0]) + ' ' + str(y_store[line][particles] + ext[1][1]) + ' ' + str(
                    z_store[line][particles]) + '\n')
    textoVtk.write('\n')
    textoVtk.write('LINES ' + str(np.alen(x_store)) + ' ' + str(nb_points + np.alen(x_store)) + '\n')
    nb = 0
    for i in range(0, np.alen(x_store)):
        textoVtk.write(str(np.alen(x_store[i])) + ' ')
        for j in range(0, np.alen(x_store[i])):
            textoVtk.write(str(nb) + ' ')
            nb = nb + 1
        textoVtk.write('\n')

    textoVtk.write('POINT_DATA ' + str(nb_points) + '\n')
    textoVtk.write('SCALARS Time float\n')
    textoVtk.write('LOOKUP_TABLE default\n')
    for i in range(0, np.alen(x_store)):
        for j in range(0, np.alen(x_store[i])):
            textoVtk.write(str(t_store[i][j]) + '\n')

    textoVtk.write('SCALARS Velocity float\n')
    textoVtk.write('LOOKUP_TABLE default\n')
    for i in range(0, np.alen(v_store)):
        textoVtk.write(str(v_store[i]) + '\n')
    textoVtk.close()