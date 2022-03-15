# -*- coding: utf-8 -*-
"""
Created on Sat Mar  5 00:37:27 2022

@author: Alexandre Gauvain
"""
import sys, os
from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
from watershed import watershed_root
#from calibration import calib_root



root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
load = True#False to build and save python object
watershed_name = 'Agon-Coutainville' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
watershed_shp = os.path.join(out_path, watershed_name, 'watershed.shp')
dem_path = root_path + "MNT_75m.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
types_obs = ['streams_fr']
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load, from_shp= watershed_shp)


#%%


BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 2010, last_year=2011, time_step = 'D', sim_state='transient')
climatic = BV.forcing.recharge

import flopy
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt



def run_model(model_name, exe,full_path,MSL = 0.48, L = 1300, top = 10, bot = -29.52, dsea = 465,
              delr = 1, delc = 1, nlay = 1, hyd_cond = 5.01, porosity = 0.28):
    mf = flopy.modflow.Modflow(model_name, exe_name=exe, version='mfnwt', listunit=2, 
                               verbose=False, model_ws=full_path)
    
    nwt = flopy.modflow.ModflowNwt(mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                   thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1, options='COMPLEX',
                                   Continue=False, backflag=0) # ibotav=0
    
    dem = np.ones((1,L))*top
    x=np.linspace(0,L-1,L)
    
    if isinstance(climatic,(int,float))==True:
        nper = 1
        perlen = 1
        nstp = [1]
        steady = True
        start_datetime = None
    else:
        start_datetime = climatic.index[0]
        steady = np.zeros(len(climatic),dtype=bool)
        steady[0] = True
        nstp = np.ones(len(climatic))
        nper = len(climatic)
        perlen = np.ones(len(climatic))
        if pd.infer_freq(climatic.index) != 'D':
            for i in range(1,len(climatic)):      
                dif = climatic.index[i]-climatic.index[i-1]
                perlen[i] = dif.days
    
    nrow = dem.shape[0]
    ncol = dem.shape[1]
    thick = top-bot
    laythick = thick/nlay
    zbot = np.ones((nlay, nrow, ncol))
    for i in range (1,nlay+1):
        zbot[i-1] = dem - (laythick*i)
    
    
    dis = flopy.modflow.ModflowDis(mf, nlay, nrow, ncol,delr=delr, delc=delc, top=dem, 
                                   botm=zbot, itmuni=4, lenuni=2, nper=nper, perlen=perlen, 
                                   nstp=nstp, steady=steady, start_datetime=start_datetime) 
        
    iboundData = np.ones((nlay, nrow, ncol))
    strtData = np.ones((nlay,nrow,ncol))*top     
    
    bas = flopy.modflow.ModflowBas(mf, ibound=iboundData, strt=strtData, hnoflo=-9999)
    
    # Constant Head package
    A=3.05
    T=14.76
    t=np.linspace(1,len(climatic),len(climatic))
    hsea = MSL + (A/2*np.cos((2*np.pi*t/T)))
    chdData = {}
    for kper in range(0, nper):
        chdKper = []
        if kper ==0:
            chdKper.append([0,0,0,MSL,MSL])
        else:
            chdKper.append([0,0,0,hsea[kper],hsea[kper]])
        chdData[kper] = chdKper
    
    chd = flopy.modflow.ModflowChd(mf, stress_period_data=chdData)
    
    #dis package
    laywet = np.zeros(nlay)
    laytype = np.ones(nlay)
    layvka = np.ones(nlay)*0
    
    
    hk = np.ones((nlay,nrow,ncol))*hyd_cond
    
    upw = flopy.modflow.ModflowUpw(mf, iphdry=1, hdry=-100, laytyp=laytype, laywet=laywet,chani=1, layvka=layvka, hk=hk,
                                           vka=1, sy=porosity,hani=1, noparcheck=False, extension='upw', unitnumber=31)
            
                    
    # rch package
    if not isinstance(climatic,(int,float)):
        climatic[climatic<0] = 0
        rchData = {}
        for kper in range(0, nper):
            if isinstance(climatic,(int,float)):
                rchData[kper] = climatic
            else:
                if kper == 0:
                    rchData[kper] = np.nanmean(climatic)
                else:
                    rchData[kper] = climatic[kper]
        rch = flopy.modflow.ModflowRch(mf, rech=rchData)
                    
    # Drain package (DRN)
    drnData = np.zeros((nrow*ncol, 5))
    compt = 0
    drnData[:, 0] = 0 # layer
    for i in range (0,nrow):
        for j in range (0, ncol):
            drnData[compt, 1] = i #row
            drnData[compt, 2] = j #col
            drnData[compt, 3]= dem[i, j]#elev
            drnData[compt, 4] = 0
            drnData[compt, 4] = hk[0, i, j]
            compt += 1
    lrcec= {0:drnData}
    #drn = flopy.modflow.ModflowDrn(mf, stress_period_data=lrcec)
    
    # oc package
    stress_period_data = {}
    for kper in range(nper):
        kstp = nstp[kper]
        stress_period_data[(kper, kstp-1)] = ['save head','save budget',]
    oc = flopy.modflow.ModflowOc(mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                    unitnumber=[14, 51, 52, 53, 0], compact=True)
    oc.reset_budgetunit(fname= model_name+'.cbc')
    
    mf.write_input()
    # run model
    succes , buff = mf.run_model(silent=False)# True without msg

model_name = ['model_2.5','model_25','model_2n']
exe = 'C:/Users/alexa/Dropbox/HydroModPy/_data/MODFLOW/bin/mfnwt.exe'
full_path = 'C:/Users/alexa/Dropbox/HydroModPy/_analytical'

L = 1300
dsea = 465    
porosity  = [0.025, 0.28]
n = np.ones((1,L))
n[0][0:dsea] = 0.025#np.logspace(np.log10(n0),np.log10(nL),dsea)
n[0][dsea:L] = 0.40
porosity.append(n)
bot = np.linspace(-1,-1,L)#-29.52
bot = bot[::-1]
hyd_cond = 60.01
for i in range (0,len(model_name)):
    run_model(model_name[i],exe,full_path,porosity=porosity[i], L=L, dsea=dsea,bot = bot,hyd_cond =hyd_cond)

import flopy.utils.binaryfile as fpu
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rc('text', usetex = True)
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

fig, ax = plt.subplots(1,2,figsize=(10,5))
ax1 = ax[0]
ax2 = ax[1]
colors=['r','k','g']
line = ['-','--','-.']
name = ['$n=2.5\%$','$n=28\%$','$n=2.5\%-n=28\%$']

for i in range (0,len(model_name)):
    head_file = os.path.join(full_path,model_name[i]+'.hds')
    head_fpu = fpu.HeadFile(head_file)
    head = head_fpu.get_alldata()
    time = np.linspace(0,len(head)-1,len(head))
    sm = plt.cm.ScalarMappable(cmap='jet', norm=matplotlib.colors.Normalize(vmin=365, vmax=len(head)))
    hpiezo = []
    compt = 0
    for t in time:
        hpiezo.append(head[int(t)][0][0][dsea])
        if compt==15:
            if i == 2:
                if t>365:
                    ax2.plot(head[int(t)][0][0],c=sm.to_rgba(t))
            compt = 0
        compt += 1
    ax2.plot(bot,c='k',lw=2)
    h = pd.DataFrame(data=hpiezo, index=climatic.index, columns=[name[i]])
    h.plot(ax=ax1, c=colors[i],lw = 1)
h = pd.DataFrame(data=BV.piezometry.elevation[BV.piezometry.codes_bss[0]]['2010':'2011'].values, index=climatic.index, columns=['$01423X0044\_F4$'])
h.plot(ax=ax1, c='b',lw=1)
plt.ylabel('$h$ $[m]$')
#BV.piezometry.elevation[BV.piezometry.codes_bss[0]]['2010':'2011'].plot(c='b',ax=ax,label=BV.piezometry.codes_bss[0])
#hobs.plot(c='b',ax=ax,label=BV.piezometry.codes_bss[0])
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/analysis_n.png',dpi=300, bbox_inches = "tight")




