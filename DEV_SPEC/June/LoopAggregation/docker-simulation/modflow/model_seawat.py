import math
import flopy
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from osgeo import gdal
import flopy.mt3d as mt3
import flopy.seawat as swt
from get_geological_structure import get_geological_structure as ggs

def model_seawat(filename,modelfolder, modelname):
    model_name = modelname+'_swt'
    swtexe_name = filename+'swt_v4'

    nwt_mf = flopy.modflow.Modflow.load(modelfolder+modelname+'.nam',model_ws=modelfolder, verbose=False, check=False)
    nwt_dis = flopy.modflow.ModflowDis.load(modelfolder+modelname+'.dis', nwt_mf)
    nwt_bas = flopy.modflow.ModflowBas.load(modelfolder+modelname+'.bas', nwt_mf)
    nwt_upw = flopy.modflow.ModflowUpw.load(modelfolder+modelname+'.upw', nwt_mf, check=False)
    nwt_rch = flopy.modflow.ModflowRch.load(modelfolder+modelname+'.rch', nwt_mf)
    nwt_drn = flopy.modflow.ModflowDrn.load(modelfolder + modelname + '.drn', nwt_mf)

    ml = flopy.modflow.Modflow(model_name, version='mf2005', exe_name=swtexe_name, model_ws=modelfolder)
    discret = flopy.modflow.ModflowDis(ml, nrow=nwt_dis.nrow, ncol=nwt_dis.ncol, nlay=nwt_dis.nlay, delr=nwt_dis.delr.array,
                            delc=nwt_dis.delc.array,top=nwt_dis.top.array, botm=nwt_dis.botm.array,
                            laycbd=nwt_dis.laycbd.array, nper=nwt_dis.nper, perlen=nwt_dis.perlen,
                            nstp=nwt_dis.nstp.array, steady=nwt_dis.steady.array)

    bas = flopy.modflow.ModflowBas(ml, ibound=nwt_bas.ibound.array, strt=nwt_bas.strt.array)
    lpf = flopy.modflow.ModflowLpf(ml, hk=nwt_upw.hk.array, vka=nwt_upw.hk.array, ss=1e-5, sy=0.2,
                        vkcb=nwt_upw.vkcb.array, laytyp=nwt_upw.laytyp.array, layavg=nwt_upw.layavg.array)
    drn = flopy.modflow.ModflowDrn(ml, stress_period_data=nwt_drn.stress_period_data)
    rch = flopy.modflow.ModflowRch(ml,rech=nwt_rch.rech.array[0,0])
    stress_period_data = {}
    for kper in range(nwt_dis.nper):
        kstp = nwt_dis.nstp.array[kper]
        stress_period_data[(kper, kstp - 1)] = ['save head','save drawdown','save budget']
    oc = flopy.modflow.ModflowOc(ml, stress_period_data=stress_period_data)
    oc.reset_budgetunit(fname=model_name + '.cbc')
    pcg= flopy.modflow.ModflowPcg(ml, hclose=1.0e-5, rclose=3.0e-3, mxiter=100, iter1=50)
    ml.write_input()

    # seawat input
    ndecay = 4
    ssz = np.ones((nwt_dis.nlay, nwt_dis.nrow, nwt_dis.ncol), np.float) * 0.35
    icbund = np.ones((nwt_dis.nlay, nwt_dis.nrow, nwt_dis.ncol), np.float)
    for i in range (0, nwt_dis.nlay):
        icbund[i][nwt_bas.ibound.array[0] == -1] = -1
    sconc = np.zeros((nwt_dis.nlay, nwt_dis.nrow, nwt_dis.ncol), np.float)
    sconc[icbund == 1]= 0. / 3. * .025 * 1000. / .7143
    sconc[icbund == -1] = 3. / 3. * .025 * 1000. / .7143
    itype = mt3.Mt3dSsm.itype_dict()
    ssm_data = {}
    for ip in range(0, nwt_dis.nper):
        ssmlist = []
        for k in range (0, nwt_dis.nlay):
            for i in range (0, nwt_dis.nrow):
                for j in range (0, nwt_dis.ncol):
                    if icbund[k, i , j] == -1:
                        ssmlist.append([k, i, j, 35., itype['BAS6']])
        ssm_data[ip] = ssmlist

    # Create the basic MT3DMS model structure
    mt = mt3.Mt3dms(model_name, 'nam_mt3dms', ml, model_ws=modelfolder)  # Coupled to modflow model 'mf'
    adv = mt3.Mt3dAdv(mt, mixelm=0,percel=0.5,nadvfd=0, nplane=4,mxpart=1e7,itrack=2,dceps=1e-4,npl=16,nph=16,npmin=8, npmax=256)
    btn = mt3.Mt3dBtn(mt, icbund=icbund, prsity=ssz, ncomp=1, sconc=sconc, ifmtcn=-1,chkmas=False, nprobs=10, nprmas=10, dt0=0, ttsmult=2.0,nprs=0, timprs=None, mxstrn=1e8)
    dsp = mt3.Mt3dDsp(mt, al=0., trpt=1., trpv=1., dmcoef=0.)
    gcg = mt3.Mt3dGcg(mt, mxiter=1, iter1=200, isolve=3, cclose=1e-4)
    ssm = mt3.Mt3dSsm(mt, stress_period_data=ssm_data)
    mt.write_input()
    # Create the SEAWAT model structure
    mswt = swt.Seawat(model_name, 'nam_swt', ml, mt,
                      exe_name=swtexe_name, model_ws=modelfolder)  # Coupled to modflow model mf and mt3dms model mt
    vdf = swt.SeawatVdf(mswt, iwtable=0, densemin=0, densemax=0, denseref=1000., denseslp=0.7143, firstdt=1e-3)
    mswt.write_input()
    ml.run_model(silent=False)
    # Run SEAWAT
    m = mswt.run_model(silent=False)



