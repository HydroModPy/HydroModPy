# coding:utf-8

import flopy
from flopy.export import vtk as fv
import os
import sys
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff
import numpy as np
import pandas as pd
from osgeo import gdal
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
from matplotlib import cm

def model_modpath(filename, modelname, modelfolder):
    a=os.path.exists(r''+modelfolder+modelname+'.nam')
    b=modelfolder+modelname+'.nam'
    mf1 = flopy.modflow.Modflow.load(modelname+'.nam',model_ws=modelfolder, verbose=False, check=False)
    dis = flopy.modflow.ModflowDis.load(modelfolder+modelname+'.dis', mf1)
    bas = flopy.modflow.ModflowBas.load(modelfolder+modelname+'.bas', mf1)
    lpf = flopy.modflow.ModflowLpf.load(modelfolder+modelname+'.lpf', mf1, check=False)
    nlay = mf1.nlay
    ncol = mf1.ncol
    nrow = mf1.nrow
    zbot = dis.botm.array
    laytype = lpf.laytyp.array
    iboundData = bas.ibound.array

    dis_file = '{}.dis'.format(modelfolder+mf1.name)
    head_file = '{}.hds'.format(modelfolder+mf1.name)
    bud_file = '{}.cbc'.format(modelfolder+mf1.name)

    mp = flopy.modpath.Modpath(modelname=mf1.name,model_ws=modelfolder, simfile_ext='mpsim', namefile_ext='mpnam', version='modpath',
                               exe_name=filename+'mp6.exe', modflowmodel=mf1, head_file=head_file, dis_file=dis_file, dis_unit=97, budget_file=bud_file)
    mp.dis_file = dis_file
    mp.head_file = head_file
    mp.budget_file = bud_file
    ptcol = 1
    ptrow = 1
    ifaces = [6]  # top face:6 ; bottom face:5 ; row face:3-4 ; column face:1-2

    # mp.write_input()

    sim = flopy.modpath.ModpathSim(model=mp, option_flags=[2, 1, 1, 1, 1, 2, 2, 1, 1, 1, 1, 1],
                                   group_placement=[[1, 1, 2, 0, 1, 1]])
    stl = flopy.modpath.mpsim.StartingLocationsFile(model=mp, inputstyle=1)
    stldata = flopy.modpath.mpsim.StartingLocationsFile.get_empty_starting_locations_data(npt=ncol * nrow)

    hds_1c = fpu.HeadFile(modelfolder+modelname+'.hds')
    # hds_1c = ff.FormattedHeadFile('model1.hds')
    head_1c = hds_1c.get_alldata(mflay=None)

    active_lay = np.ones((nlay, nrow, ncol))
    for i in range(0, nlay):
        h1 = head_1c[0][i]
        for j in range(0, nrow):
            for k in range(0, ncol):
                if h1[j][k] < zbot[i][j][k]:
                    active_lay[i][j][k] = 0

    lay_store = []
    j_store = []
    i_store = []
    for j in range(0, nrow):
        for k in range(0, ncol):
            i_store.append(j + 1)
            j_store.append(k + 1)
            for i in range(0, nlay):
                if active_lay[i][j][k] == 1:
                    lay_store.append(i + 1)
                    break
            if active_lay[nlay-1][j][k] == 0:
                lay_store.append(nlay)


    for i in range(0, len(lay_store)):
        stldata[i]['label'] = 'p' + str(i + 1)
        stldata[i]['k0'] = lay_store[i]
        stldata[i]['j0'] = j_store[i]
        stldata[i]['i0'] = i_store[i]
        stldata[i]['zloc0'] = 1
    stl.data = stldata

    mpbas = flopy.modpath.ModpathBas(mp, hnoflo=0.68, hdry=-1e+30, def_face_ct=0, laytyp=laytype, ibound=iboundData,
                                     prsity=0.3, prsityCB=0.3, extension='mpbas', unitnumber=86)

    mp.write_input()
    cwd = os.path.join(os.getcwd(), modelname)
    mpsf = '{}.mpsim'.format(modelfolder+mf1.name)
    mp_exe_name = 'mp6.exe'
    xstr = '{} {}'.format(mp_exe_name, mpsf)
    succes, buff = mp.run_model()
    #exstat = os.system(xstr)
    #if exstat != 0:
     #   print('MODPATH did not execute properly')
    #else:
     #   print('MODPATH executed properly')