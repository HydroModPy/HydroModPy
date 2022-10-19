# -*- coding: utf-8 -*-

#%% Tools

# Librairies
import pandas as pd
import numpy as np
from glob import glob
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
import shutil
import sys
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
import imageio
import flopy
import re
import geopandas as gpd
import deepdish as dd
import os
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp
from matplotlib import colors
from mpl_toolkits.axes_grid1 import make_axes_locatable
from hydroeval import *
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from matplotlib.font_manager import FontProperties   

#%% Connect

git = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
sys.path.append(git+"src/")
import watershed as wat
import extract as ext
import modflow as mod

#%% Input

path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/DEV_SPEC/Clement/transient/"
outlets = pd.read_csv(path+"outlets_test.txt", sep='\t', header=None, engine='python')
store = "C:/Users/LocalAdmin/Downloads/test_transient/"

#%% Generate watershed

# Loop for each sites
for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    station = site
    
    print('#################### WATERSHED '+str(idx)+' : '+site.upper()+' ####################')

    wat.extract_watershed(dem_path=path + 'Bretagne.tif',
                          outlet=outlet,
                          snap_dist=snap, buff_dist=1000, save_gis=True,
                          tmp_path=git+'tmp/',
                          out_path=store)

#%% Fct to run only modflow

def settings(time, k, n, e, r, outlet):
        
        type_time = time
        site = outlet[0].values[0]
        lay_number = 1
        thick = e
        climatic = r / 1000 # m/m
        hyd_cond = k * 3600 * 24 * 30 # m/m
        if type(climatic) == float:
            krval = hyd_cond / climatic
            mean = climatic
        else:
            krval = hyd_cond / climatic.mean()
            mean = climatic.mean()
        porosity = n / 100
        dem_path = store + site + '/gis/' + 'watershed_buff_dem.tif'
                
        sim_id = type_time+'_'+\
                    site+'_'+\
                    str(lay_number)+'_'+\
                    str(thick)+'_'+\
                    str(round(krval, 3))+'_'+\
                    str(round(mean, 3))+'_'+\
                    str(round(hyd_cond,3))+'_'+\
                    str(round(porosity,3))
        
        if time == 'steady':
            climatic = [climatic]
        
        mod.modflow_model(dem_path, 
                          watershed=site, 
                          climatic=climatic, 
                          lay_number=lay_number, 
                          thick=thick, 
                          bottom=None, 
                          hyd_cond=hyd_cond, 
                          porosity=porosity,
                          coastal_aquifer=False,
                          time_step='monthly',
                          model_name=sim_id, 
                          model_folder=store,
                          exe=git+'bin/'+'mfnwt.exe')
        
        if time == 'steady':
            ext.extract_modflow(dem_path, 
                                watershed=site, 
                                model_name=sim_id, 
                                model_folder=store)
    
#%% Launch transient

hyd_cond_list = np.geomspace(1e-5,1e-5,1) # m/s
porosity_list = np.linspace(0.1,0.1,1) # %
thick_list = np.linspace(100,100,1) # m

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    station = site

    # Open recharge csv
    df_concat = pd.read_csv(path + 'df_concat.csv', sep='\t', index_col=0, parse_dates=True)
    df_concat = df_concat[(df_concat.index.year >= 1950) & (df_concat.index.year <= 2100)]
    
    # Extract chronic
    first = df_concat[station + '_mmm'].first_valid_index().year
    last = df_concat[station + '_mmm'].last_valid_index().year
    
    first = 1995
    last = 2005
    mask = (df_concat.index.year >= first) & (df_concat.index.year <= last)
    df_concat = df_concat[mask]
    
    # Choice scenario
    sce = 'rea'
    recharge = df_concat['rec_mmm_'+sce]
    recharge = recharge[recharge.index.notnull()]
    rech = recharge
    
    plt.plot(recharge, label=site)
    plt.legend()
    
    print('#################### TRANSIENT '+str(idx)+' : '+site.upper()+' ####################')
    
    # Deelete previous simulations        
    allm = glob(store + site + '/' + 'transient*')
    for f in allm:
        shutil.rmtree(f)

    # Loop for each variable
    for var1 in range (0, len(hyd_cond_list)): # permit to fix k
        for var2 in range (0, len(porosity_list)): # permit to fix porosity
            for var3 in range (0, len(thick_list)): # permit to fix porosity
            
                    print('k = '+str('{:.3e}'.format(hyd_cond_list[var1]))+' - '+
                          'n = '+str(round(porosity_list[var2],3))+' - '+
                          'e = '+str(thick_list[var3].round(3)))
                    
                    # Launch modflow
                    settings('transient', hyd_cond_list[var1], porosity_list[var2], thick_list[var3], rech, outlet)

#%% Extract h5

typ = 'transient'

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    station = site
    
    print('#################### H5 '+str(idx)+' : '+site.upper()+' ####################')
    
    # Dem
    dem_path = store + site + '/gis/' + 'watershed_dem.tif'
    pix = 75
    maskdata = imageio.imread(dem_path)

    # Import simulation paths
    allf = sorted((glob(store + site + '/' + typ + '*')),
                  key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))
    
    # Loop by simulation
    for item, simul in enumerate(allf): # to operate the script for each simulation
    
        print('Simulation : '+str(item)+' / '+str(len(allf)-1))
        
        # Name of models
        folder = simul
        name = simul.split('\\')[-1]
        modelname =  folder + '/modraw/' + name
        
        # Choice saving
        foldout = store + site + '/' + name + '/'
        if not os.path.exists(foldout):
            os.makedirs(foldout)

        # Load packs
        mf1 = flopy.modflow.Modflow.load(modelname + '.nam', verbose=False, check=False, load_only=["bas6", "dis"])
        bas = flopy.modflow.ModflowBas.load(modelname + '.bas', mf1)
        dis = flopy.modflow.ModflowDis.load(modelname + '.dis', mf1)
        rchbase = flopy.modflow.ModflowRch.load(modelname + '.rch', mf1)
        upwbase = flopy.modflow.ModflowUpw.load(modelname + '.upw', mf1)
        
        # Extract parameters
        nlay = dis.nlay
        thick = int(re.findall(r'\d+', name.split('_')[4])[0]) # !!!
        hk = upwbase.hk[0,0,0]
        rech = rchbase.rech[0][0,0]
        sy = upwbase.sy[0,0,0]
        top_model = mf1.dis.top
        bot_model = mf1.dis.botm
    
        # Additionnal parameters
        ncol = dis.ncol
        nrow = dis.nrow
        nlay = dis.nlay
        nper = dis.nper
        nstp = dis.nstp
        kper = np.arange(0,nper,1) # ==> time
        kstp = nstp[kper] - 1
    
        # Load head
        head_fpu = fpu.HeadFile(modelname+'.hds')
        head_all = head_fpu.get_alldata() # mflay=None
        head_data = head_fpu.get_data()
        head_data_mask = np.ma.masked_array(head_data, mask=(head_data==-9999))
        min_head = np.min(head_data_mask)
        max_head = np.max(head_data_mask)
        head_save = head_data.copy()
        
        head_save[0][maskdata==-99999] = np.nan
        head_save[0][head_save[0]==-99999] = np.nan

        # Load times
        
        times = head_fpu.get_times()
        kstpkper = head_fpu.get_kstpkper()
    
        # Select times
        mytimes = times
        
        # Dictionary
        dicoseep = {}
        dicodrn = {}
        dicoq = {}
        dicowt = {}
        
        # Loop by times
        for iplot, time in enumerate(mytimes):
            
            print('     Time : ', iplot)
            
            # Watertable
            head_tr = head_fpu.get_data(totim=time)
            head_tr = maskdata - head_tr
            head_tr[0][maskdata==-99999] = np.nan
            
            # Load general fluxes
            cbb = fpu.CellBudgetFile(modelname + '.cbc')
            kstpkper = (kstp[iplot], kper[iplot])
            fff = cbb.get_data(text='FLOW RIGHT FACE', kstpkper=kstpkper, totim=time)[0]
            frf = cbb.get_data(text='FLOW FRONT FACE', kstpkper=kstpkper, totim=time)[0]
            if nlay > 1:
                flf = cbb.get_data(text='FLOW LOWER FACE', kstpkper=kstpkper, totim=time)[0]
                Q = np.sqrt(frf**2 + fff**2, flf**2)
            if nlay ==1:
                Q = np.sqrt(frf**2 + fff**2)
                
            # Load Darcy fluxes
            qx,qy,qz = pp.get_specific_discharge(mf1, modelname + '.cbc')
            q = np.sqrt(qx**2 + qy**2 + qz**2)
            q[0][maskdata==-99999] = np.nan
            
            # Extract drain outflow
            drn_drain = np.ones((1, dis.nrow, dis.ncol))
            drain = cbb.get_data(text='DRAINS', kstpkper=kstpkper, totim=time)
            sim = 0
            count = 0
            for i in range(0, dis.nrow):
                for j in range(0, dis.ncol):
                    drn_drain[sim, i, j] = np.abs(drain[0][count][1])
                    count = count + 1
            drn_drain[drn_drain == 0] = 0 # quantity of drain m3/m
            drn_drain[0][maskdata==-99999] = np.nan
            
            # # Extract seepage area
            seep = maskdata-head_tr[0]
            seep[seep > 0] = 0
            seep[seep <= 0] = 1
            seep[maskdata==-99999] = np.nan
            
            # Store in dictionaries
            dicodrn[iplot] = drn_drain[0]
            dicowt[iplot] = head_tr[0]
            dicoseep[iplot] = seep
            dicoq[iplot] = q[0]
            
        # Save dictionnary
        dd.io.save(foldout+'drn.h5', dicodrn)
        dd.io.save(foldout+'wt.h5', dicowt)
        dd.io.save(foldout+'seep.h5', dicoseep)
        dd.io.save(foldout+'q.h5', dicoq)

#%% Extract chronic

df_chronic = pd.DataFrame()

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    station = site
    
    # Open recharge csv
    df_concat = pd.read_csv(path + 'df_concat.csv', sep='\t', index_col=0, parse_dates=True)
    df_concat = df_concat[(df_concat.index.year >= 1950) & (df_concat.index.year <= 2100)]
    
    # Extract chronic
    first = df_concat[station + '_mmm'].first_valid_index().year
    last = df_concat[station + '_mmm'].last_valid_index().year
    
    first = 1995
    last = 2005
    mask = (df_concat.index.year >= first) & (df_concat.index.year <= last)
    df_concat = df_concat[mask]
        
    # Dem
    dem_path = store + site + '/gis/' + 'watershed_dem.tif'
    pix = 75
    maskdata = imageio.imread(dem_path)
    toplot = np.ma.masked_array(maskdata, mask=maskdata==-99999)
    plt.imshow(toplot, cmap='terrain')
    plt.savefig(foldout+'dem.png', dpi=300, bbox_inches='tight')
    
    # Import shp
    contour = gpd.read_file(store + site + '/gis/' + 'watershed_contour.shp')
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    
    # Cmap
    cmap1 = colors.ListedColormap(['grey'])
    cmap2 = colors.ListedColormap(['dodgerblue'])

    # Simulations    
    allf = sorted((glob(store + site + '/' + typ + '*')),
                  key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))

    for item, simul in enumerate(allf): # to operate the script for each simulation
    
        print('Simulation : '+site+' '+str(item)+' / '+str(len(allf)-1))
        
        # Name of models
        folder = simul
        name = simul.split('\\')[-1]
        modelname =  folder + '/modraw/' + name
        
        kr = str(re.findall(r'\d+\.\d+', name.split('_')[4])[0])
        k = str(re.findall(r'\d+\.\d+', name.split('_')[6])[0])
        n = str(re.findall(r'\d+\.\d+', name.split('_')[7])[0])
        e = str(re.findall(r'\d+', name.split('_')[3])[0])

        foldout = store + site + '/' + name + '/'
                        
        dicodrn = dd.io.load(foldout+'/'+'drn.h5')
        dicowt = dd.io.load(foldout+'/'+'wt.h5')
        dicoseep = dd.io.load(foldout+'/'+'seep.h5')
        dicoq = dd.io.load(foldout+'/'+'q.h5')
        
        idd = '_k'+k+'_n'+n+'_e'+e
        
        # Loop time
        for iplot in dicodrn.keys():
            print('     Time : ', iplot)
            
            raw = dicodrn[iplot]
            if raw.shape != maskdata.shape :
                maskdata = np.resize(maskdata, (raw.shape[0],raw.shape[1]))

            masked = np.ma.masked_array(raw, mask=maskdata==-99999)
            
            # Outflow total
            cell = masked.count()
            Qmod = (np.nansum(masked) / (cell * 75**2)) * 1000 # mm/m
            df_chronic.loc[iplot,'drn'] = Qmod
            
            # Seepage proportion
            count = (masked > 0).sum()
            df_chronic.loc[iplot,'seep'] = (count/cell) * 100
            
            # Watertable mean
            df_chronic.loc[iplot,'wt'] = np.nanmean(dicowt[iplot])
            
            # Darcy flux
            df_chronic.loc[iplot,'q'] = np.nanmean(dicoq[iplot])
            
            # Figure streams
            if iplot==0:
                fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                ax.imshow(np.ma.masked_array(maskdata, mask=maskdata==-99999), cmap=cmap1)
                masked = np.ma.masked_array(masked, mask=masked<=0)
                im = ax.imshow((masked / 75**2)*1000, vmin=0, vmax=150)
                kstr = "{:.1e}".format(float(k)/30/24/3600)
                nstr = float(n)*100
                estr = e
                sim = 'K='+str(kstr)+' ; '+'n='+str(round(nstr,3))+' ; '+'e='+str(estr)
                ax.set_title(sim, fontsize=10)
                divider = make_axes_locatable(ax)
                cax = divider.append_axes('right', size='2%', pad=0.05)
                cb = fig.colorbar(im, cax=cax, orientation='vertical')
                x1 = [0,25,50,75,100,125,150]
                cb.set_ticks(x1)
                cb.ax.tick_params(labelsize=10)
                cb.set_label('Flux [mm/m]', fontsize=10, rotation=270, labelpad=20)
                cb.update_ticks()
                fig.savefig(foldout+'outflow.png', dpi=300, bbox_inches='tight')
            
            # Long !
            fig, ax = plt.subplots(1, 1, figsize=(4,4), dpi=300)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            ax.imshow(np.ma.masked_array(maskdata, mask=maskdata==-99999), cmap=cmap1)
            masked = np.ma.masked_array(masked, mask=masked<=0)
            im = ax.imshow(masked, cmap=colors.ListedColormap(['red']))
            date = str(df_concat.index[iplot])[0:10]
            ax.set_title('TIME : '+date, fontsize=10)
            if not os.path.exists(foldout+'seep/'):
                os.makedirs(foldout+'seep/')  
            fig.savefig(foldout+'seep/'+'seep_'+str(date)+'.png', dpi=300, bbox_inches='tight')
            plt.close()  
            
        df_chronic.to_csv(foldout + 'df_' + typ + '.csv', sep="\t", index=True)

filenames = glob(foldout + 'seep/' + '*.png')  
images = []
for filename in filenames:
    images.append(imageio.imread(filename))
    imageio.mimsave(foldout + 'beat.gif', images, duration=1, loop=1)

#%% Parameters plots

# Parameters plot : v2.0 to classic customized
# mpl.style.use('default')
# mpl.rcParams.update(mpl.rcParamsDefault)

# # # Classic
mpl.style.use('classic')
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers'
# mpl.rcParams['axes.autolimit_mode'] = 'round_numbers' # 'data' 
mpl.rcParams['axes.xmargin'] = 0.1
mpl.rcParams['axes.ymargin'] = 0.1
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.top'] = True
mpl.rcParams['ytick.right'] = True
mpl.rcParams['legend.numpoints'] = 1
mpl.rcParams['legend.scatterpoints'] = 1
mpl.rcParams['legend.edgecolor'] = 'grey'
mpl.rcParams['date.autoformatter.year'] = '%Y'
mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'

# Parameters size plot
smal = 8
medium = 16
large = 20

plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=medium)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
plt.rcParams["font.family"] = "serif"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

#%% Plot discharge chronic

sce = 'rea'
typ = 'transient'

first = 1995
last = 2005

for idx, serie in outlets.iterrows():
        
    outlet = outlets.loc[[idx]]
    
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    
    station = site

    # Open recharge csv
    df_concat = pd.read_csv(path + 'df_concat.csv', sep='\t', index_col=0, parse_dates=True)
    df_concat = df_concat[(df_concat.index.year >= first) & (df_concat.index.year <= last)]
            
    xy = pd.DataFrame()
    df_stat = pd.DataFrame()

    print('#################### PLOT '+str(idx)+' : '+site.upper()+' ####################')
        
    allf = sorted((glob(store + site + '/' + typ + '*')),
                  key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))

    for item, simul in enumerate(allf): # to operate the script for each simulation
    
        print('Simulation : '+str(item)+' / '+str(len(allf)-1))
        
        # Name of models
        folder = simul
        name = simul.split('\\')[-1]
        modelname =  folder + '/modraw/' + name
        
        foldout = store + site + '/' + name + '/'
    
        df_chronic = pd.read_csv(foldout + 'df_'+typ+'.csv', sep='\t')
        
        kr = str(re.findall(r'\d+\.\d+', name.split('_')[4])[0])
        k = str(re.findall(r'\d+\.\d+', name.split('_')[6])[0])
        n = str(re.findall(r'\d+\.\d+', name.split('_')[7])[0])
        e = str(re.findall(r'\d+', name.split('_')[3])[0])
        
        obs = df_concat[station+'_mmm']
        mod = df_chronic['drn'] + df_concat['run'+'_mmm_'+sce].values

        # idx_nan = np.argwhere(np.isnan(obs))
        # obs = np.delete(obs, idx_nan)
        # mod = np.delete(mod, idx_nan)
        
        obs = np.array(obs)
        mod = np.array(mod)
        
        if obs.shape == mod.shape:

            RMSE = evaluator(rmse, mod, obs)
            NSE = evaluator(nse, mod, obs)*100
            NSElog = evaluator(nse, mod, obs, transform='log')*100
            BAL = (np.sum(mod)/np.sum(obs))*100
            MARE = evaluator(mare, mod, obs)*100
            KGEcomp = evaluator(kge, mod, obs)*100 # and its three components (r, α, β)
            KGE = KGEcomp[0]
            SEEP = df_chronic['seep'].values.mean()
            WT = df_chronic['wt'].values.mean()
        
        df_stat.loc[item, 'kr'] = float(kr)
        df_stat.loc[item, 'k'] = float(k)
        df_stat.loc[item, 'n'] = float(n)
        df_stat.loc[item, 'e'] = float(e)
        df_stat.loc[item, 'rmse'] = RMSE
        df_stat.loc[item, 'nse'] = NSE
        df_stat.loc[item, 'nselog'] = NSElog
        df_stat.loc[item, 'bal'] = BAL
        df_stat.loc[item, 'mare'] = MARE
        df_stat.loc[item, 'kge'] = KGE
        df_stat.loc[item, 'seep'] = SEEP
        df_stat.loc[item, 'wt'] = WT
        
        # Parameters
        years = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        months = mdates.MonthLocator(6)  # every month
        years_fmt = mdates.DateFormatter('%Y')
        months_fmt = mdates.DateFormatter('%m') #b = name of month ?
                
        # Figure configuration
        fig = plt.figure(figsize=(12, 6))
        gs = GridSpec(nrows=2, ncols=2, width_ratios=[3, 1], height_ratios=[1, 2])
        ax1 = fig.add_subplot(gs[0, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 0])
        ax4 = fig.add_subplot(gs[1, 1])
        
        # Discharge no log
        d = df_concat.index
        
        ax1.plot(d, obs, c='k', label='observed', lw=2)
        ax1.plot(d, mod, c='red', label='modeled', lw=2)
        ax1.axes.get_xaxis().set_visible(False)
        ax1.legend(fontsize=10, prop=fontdic)
        
        kstr = "{:.1e}".format(float(k)/30/24/3600)
        nstr = round(float(n)*100,3)
        estr = e
        
        ax1.set_title(site.upper() + '  - '  + 'K='+str(kstr)+'m/s'+' ; '+
                                               'n='+str(nstr)+'%'+' ; '+ 
                                               'e='+str(estr)+'m',
                      pad=+15, size=15)
        
        ax1.grid(True)
        ax1.set_yticks(np.arange(0, np.nanmax(obs)+10, 100))
                        
        # Show stats
        ax2.axes.xaxis.set_visible(False)
        ax2.axes.yaxis.set_visible(False)
        ax2.axis('off')
        ax2.text(0, 0.5, 
                  "NSE = " + '%.1f' % NSE + " %" + "\n" +
                  "NSElog = " + '%.1f' % NSElog + " %" + "\n" +
                  "KGE = " + '%.1f' % KGE + " %" + "\n" +
                  "RMSE = " + '%.1f' % RMSE + " %" + "\n" +
                  "MARE = " + '%.1f' % MARE + " %" + "\n" +
                  "BAL = " + '%.1f' % BAL + " %" + "\n" +
                  "SEEP = " + '%.1f' % SEEP + " %" + "\n" +
                  "WT = " + '%.1f' % WT + " m",
                  ha='left', va='center', fontsize=16, transform=ax2.transAxes)
        
        # Discharge log
        ax3.plot(d, obs, c='k', label='observed', lw=2)
        ax3.plot(d, mod, c='red', lw=2)
        ax3.set_xlabel('Date', fontsize=20, fontproperties=fontprop)
        ax3.set_ylabel('Discharge (mm/m)', labelpad=10, fontsize=20, fontproperties=fontprop)
        ax3.tick_params(axis='x', color='k')
        ax3.tick_params(axis='y', colors='k')
        ax3.set_yscale('log')
        ax3.xaxis.set_major_locator(years)
        ax3.xaxis.set_minor_locator(yearsmin)
        ax3.xaxis.set_minor_locator(months)
        ax3.xaxis.set_major_formatter(years_fmt)
        ax3.grid(True)
        
        # Observed vs simulated
        ax4.plot(obs, mod, color='forestgreen', marker='.', linestyle='None', lw=2)
        ax4.set_ylabel('Simulated (mm/m)', fontproperties=fontprop)
        ax4.set_xlabel('Observed (mm/m)', fontproperties=fontprop)
        ax4.set_aspect('equal', adjustable='box')
        ax4.set_xscale('log')
        ax4.set_yscale('log')
        ax4.grid(True)
        maxi = np.maximum(np.nanmax(obs),np.nanmax(mod))
        mini = np.minimum(np.nanmin(obs),np.nanmin(mod))
        if mini == 0.0:
            mini = 0.01
        if not np.isnan(maxi):
            ax4.set_ylim([mini, maxi])
            ax4.set_xlim([mini, maxi])
        if not np.all(np.isnan(mod)):
            ax4.plot((mini,maxi),(mini,maxi), color='k', ls='-')

        plt.tight_layout()

        fig.savefig(store + site + '/' + name + '/' + 'chronic.png', dpi=300, bbox_inches='tight')

    df_stat.to_csv(store + site + '/' + 'df_stat' + '.csv', sep="\t", index=True)

#%% Plot calibration estimate

for idx, serie in outlets.iterrows():
        
    outlet = outlets.loc[[idx]]
    
    site = outlet[0].values[0]
    snap = outlet[3].values[0]
    
    station = site

    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')

    df_stat = pd.read_csv(store + site + '/' + 'df_stat' + '.csv', sep="\t")

    xy = df_stat.dropna()

    fig, axs = plt.subplots(2,2,figsize=(10, 8))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    axs = axs.ravel()
    
    ax = axs[0]
    ax.set_xlabel("K [m/s]", labelpad=+15)
    ax.set_ylabel("n * e [m]", labelpad=+25)
    look = 'nse'
    klist = xy.k / 30 / 24 / 3600
    porlist = (xy.n) * xy.e
    norm = mpl.colors.Normalize(vmin=0, vmax=100)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    divider = make_axes_locatable(ax)
    position = divider.append_axes('right', size='2.5%', pad=0.05)
    cb = plt.colorbar(scat,cax=position)
    x1 = [0,50,100]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('NSE [%]', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)
    
    ax = axs[1]
    ax.set_xlabel("K [m/s]", labelpad=+15)
    ax.set_ylabel("n * e [m]", labelpad=+25)
    look = 'nselog'
    klist = xy.k / 30 / 24 / 3600
    porlist = (xy.n) * xy.e
    norm = mpl.colors.Normalize(vmin=0, vmax=100)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    divider = make_axes_locatable(ax)
    position = divider.append_axes('right', size='2.5%', pad=0.05)
    cb = plt.colorbar(scat,cax=position)
    x1 = [0,50,100]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('NSE log [%]', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)

    ax = axs[2]
    ax.set_xlabel("K [m/s]", labelpad=+15)
    ax.set_ylabel("n * e [m]", labelpad=+25)
    look = 'seep'
    klist = xy.k / 30 / 24 / 3600
    porlist = (xy.n) * xy.e
    norm = mpl.colors.Normalize(vmin=0, vmax=100)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    divider = make_axes_locatable(ax)
    position = divider.append_axes('right', size='2.5%', pad=0.05)
    cb = plt.colorbar(scat,cax=position)
    x1 = [0,50,100]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('SEEPAGE [%]', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)
    
    ax = axs[3]
    ax.set_xlabel("K [m/s]", labelpad=+15)
    ax.set_ylabel("n * e [m]", labelpad=+25)
    look = 'wt'
    klist = xy.k / 30 / 24 / 3600
    porlist = (xy.n) * xy.e
    norm = mpl.colors.Normalize(vmin=0, vmax=20)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    divider = make_axes_locatable(ax)
    position = divider.append_axes('right', size='2.5%', pad=0.05)
    cb = plt.colorbar(scat,cax=position)
    x1 = [round(xy.wt.min(),1), round(xy.wt.max(),1)]
    cb.ax.tick_params(labelsize=15)
    cb.set_label('WATERTABLE [m]', rotation=270, labelpad=20)
    totxt = (xy[look]).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)    
    
    plt.tight_layout()
    
    fig.savefig(store + site + '/' + name + '/' + 'calibration.png', dpi=300, bbox_inches='tight')

#%% Notes
