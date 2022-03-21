# coding:utf-8
import math
import flopy
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from osgeo import gdal
import flopy.utils.binaryfile as bf
# Custom imports
from . import get_geological_structure as ggs



def model_modflow(input_file, file_name, model_name, model_folder, coord, tdis, geo, permea, thick, port, porosity, ref):
    print("file_name : ", file_name)
    print("model_name : ", model_name)
    print("model_folder : ", model_folder)
    mf1 = flopy.modflow.Modflow(model_name, exe_name=file_name + 'mfnwt', version='mfnwt',listunit=2, verbose=False, model_ws=model_folder)
    flopy.modflow.ModflowNwt(mf1, headtol=0.001, fluxtol=500, maxiterout=1000, thickfact=1e-05, linmeth=1,
                                   iprnwt=0,ibotav=0, options='COMPLEX')

    geot, geotx, geoty, demData, lay_wt, lay_ft, lay_kb, lay_kf, lay_kw, sea_earth, river = ggs.get_geological_structure(coord)
    demData[demData == -99999.0] = 0

    # number_cells = np.arange(start=0, stop=demData.shape[0] * demData.shape[1])
    # nb_cells = number_cells.reshape(demData.shape[0], demData.shape[1])
    file = pd.read_table(file_name + "data" + os.sep + input_file, delimiter="\t", header=0) #input_file
    ram = pd.read_table(file_name + "data"+os.sep+"RAM.csv", delimiter=";", header=0)
    sea_level = ram.NM_IGN[port-1]
    input_file = file.T.values

    if tdis == 0:
        # Time step parameters
        nper = input_file.shape[1]  # Number of model stress periods (the default is 1)
        perlen = input_file[1, :]  # An array of the stress period lengths.
        nstp = input_file[2, :]  # Number of time steps on each stress period (default is 1)
        nstp.astype(int)
        steady = input_file[3, :] == 1  # True : Study state | False : Transient state
    if tdis == 1 or tdis == 2 :
        nper = 1
        perlen = 1
        nstp = [1]
        steady = True

    # model domain and grid definition
    ztop = demData
    ztop[demData == -99999.0] = 100
    nlay = 6
    nrow = demData.shape[0]
    ncol = demData.shape[1]
    H=100
    lay_wt[lay_wt == 0] = 20
    lay_ft[lay_ft == 0] = 20
    zbot = np.ones((nlay, nrow, ncol))
    lay_wz = lay_wt/(nlay/3)
    for i in range (0,int(nlay/3)):
        for j in range (0,nrow):
            for k in range (0,ncol):
                zbot[i, j, k] = ztop[j, k] - (lay_wz[j,k]* (1 + i))
    lay_fz = lay_ft / (nlay / 3)
    for i in range(0, int(nlay / 3)):
        for j in range(0, nrow):
            for k in range(0, ncol):
                zbot[i + int(nlay / 3), j, k] = ztop[j, k] - lay_wt[j, k] - (lay_fz[j, k] * (1 + i))
    lay_bz = (H - lay_wt - lay_ft) / (nlay/3)
    lay_bz[lay_wt == 0] = 0
    for i in range (0, int(nlay/3)):
        for j in range (0,nrow):
            for k in range (0,ncol):
                zbot[i+int(nlay/3)*2,j,k]=ztop[j,k]-lay_wt[j,k]- lay_ft[j,k]-(lay_bz[j,k]*(1 + i))
    delr = geot[1]
    delc = abs(geot[5])
    xul=geotx[0]
    yul=geoty[0]

    if geo == 0 :
        zbot[0] = ztop - 10
        zbot[1] = ztop - 20
        zbot[2] = ztop - 40
        zbot[3] = ztop - 60
        zbot[4] = ztop - 80
        zbot[5] = np.min(zbot[4]) - 20
    if thick == 1:
        zbot[5] = np.min(zbot[5])

    # create discretization object
    flopy.modflow.ModflowDis(mf1, nlay, nrow, ncol, delr=delr, delc=delc, top=ztop, botm=zbot, itmuni=4, lenuni=2,
    nper=nper, perlen=perlen, nstp=nstp, steady=steady,xul=xul,yul=yul,proj4_str='EPSG:2154')

    # variable for the BAS package
    iboundData = np.ones((nlay, nrow, ncol))
    iboundData[0][demData == 0] = -1
    iboundData[0][demData <= sea_level] = -1

    strtData = np.ones((nlay, nrow, ncol))* ztop

    strtData[iboundData == -1] = sea_level

    flopy.modflow.ModflowBas(mf1, ibound=iboundData, strt=strtData, hnoflo=sea_level)

    # lpf package
    laywet = np.zeros(nlay)
    laytype = np.ones(nlay)
    hk = np.ones((nlay, nrow, ncol))
    if geo == 0:
        hk[0, :, :] = permea
        hk[1, :, :] = permea
        hk[2, :, :] = 0.000864
        hk[3, :, :] = 0.000864
        hk[4, :, :] = 0.000864
        hk[5, :, :] = 0.000864
    if geo == 1:
        lay_kw[demData == 0] = 0.1
        hk[0, :, :] = lay_kw * (60 * 60 * 24)
        hk[1, :, :] = lay_kw * (60 * 60 * 24)
        hk[2, :, :] = lay_kf * (60 * 60 * 24)
        hk[3, :, :] = lay_kf * (60 * 60 * 24)
        hk[4, :, :] = lay_kb * (60 * 60 * 24)
        hk[5, :, :] = lay_kb * (60 * 60 * 24)

    flopy.modflow.ModflowUpw(mf1, iphdry=1, hdry=-1e+30, laytyp=laytype, laywet=laywet, hk=hk,
                                   vka=hk, sy=porosity, noparcheck=False, extension='upw', unitnumber=31)

    rchData = {}
    if tdis == 0:
        if ref:
            input_file[4,0] = np.mean(input_file[4,:])
            #print("mean initialisation period : ", input_file[4,0])

        for kper in range(0, nper):
            rchData[kper] = float(input_file[4, kper])
    if tdis == 1:
        for kper in range(0, nper):
            rchData[kper] = np.mean(input_file[4, :])
    if tdis == 2:
        for kper in range(0, nper):
            rchData[kper] = np.min(input_file[4, :])

    flopy.modflow.ModflowRch(mf1, rech=rchData)

    # Drain package (DRN)
    drnData = np.zeros((nrow*ncol, 5))
    drn_i = 0
    drnData[:, 0] = 0 # layer
    for i in range (0,nrow):
        for j in range (0, ncol):
            drnData[drn_i, 1] = i #row
            drnData[drn_i, 2] = j #col
            drnData[drn_i, 3]= ztop[i, j]#elev
            drnData[drn_i, 4] =(hk[0, i, j]) * delr * delc / 1  #cond
            drn_i += 1
    lrcec= {0:drnData}
    flopy.modflow.ModflowDrn(mf1, stress_period_data=lrcec)

    # oc package
    stress_period_data = {}
    for kper in range(nper):
        kstp = nstp[kper]
        stress_period_data[(kper, kstp-1)] = ['save head']
                                            #'save budget',]
    flopy.modflow.ModflowOc(mf1, stress_period_data=stress_period_data, extension=['oc','hds','ddn','cbc','ibo'],
                                unitnumber=[14, 51, 52, 53, 0], compact=True)

    # write input files
    mf1.write_input()
    # run model
    mf1.run_model()

