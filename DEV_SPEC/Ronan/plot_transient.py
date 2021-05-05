# -*- coding: utf-8 -*-

import os
import sys
import numpy as np
import rasterio as rio
import rasterio.plot
import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff
import flopy.utils.postprocessing as pp
import topography
import climatic as clim
import pandas as pd
from glob import glob
import re
import deepdish as dd
import imageio
from osgeo import gdal
from hydroeval import *
from matplotlib.gridspec import GridSpec
import matplotlib.dates as mdates
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties

#%% Plot

mpl.style.use('classic')
# mpl.rcParams['backend'] = 'wxAgg'
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['axes.linewidth'] = 1.5
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
mpl.rcParams['axes.xmargin'] = 0.05
mpl.rcParams['axes.ymargin'] = 0.05
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.major.size'] = 5
mpl.rcParams['xtick.minor.size'] = 3
mpl.rcParams['xtick.major.width'] = 1.5
mpl.rcParams['xtick.minor.width'] = 1
mpl.rcParams['ytick.major.size'] = 5
mpl.rcParams['ytick.minor.size'] = 1.5
mpl.rcParams['ytick.major.width'] = 1.5
mpl.rcParams['ytick.minor.width'] = 1
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
mpl.rcParams['axes.formatter.offset_threshold'] = 7

smal = 8
intm = 15
medium = 18
large = 20
plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=large)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=intm)                   # fontsize of the tick labels
plt.rc('font', family='serif')
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

#%% Data

path_data = 'D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/congress_events/egu/extract_data/'

d = pd.date_range(start='01/01/'+str(1950), 
                  end='31/12/'+str(2099), freq='MS')

first = 1990
last = 1991

df_concat = pd.read_csv(path_data + 'concat_df.csv', sep='\t', index_col=0, parse_dates=True)
mask = (df_concat.index.year >= first) & (df_concat.index.year <= last)
df_concat = df_concat[mask]

#%% Path

path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/congress_events/egu/analysis_model/"
outlets = pd.read_csv(path+"_data/outlets_test.txt", sep='\t', header=None, engine='python')
            
#%% Discharge chronic

xy = pd.DataFrame()
df_stat = pd.DataFrame()

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet.iloc[:,1].values[0]

    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
        
    allf = sorted((glob(path + site + '/' + 'transient*')),
                  key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))
    
    if not os.path.exists(path + site + '/fig/'):
        os.makedirs(path + site + '/fig/')

    for item, simul in enumerate(allf): # to operate the script for each simulation
    
        print('Simulation : '+str(item)+' / '+str(len(allf)-1))
        
        # Name of models
        folder = simul
        name = simul.split('\\')[-1]
        modelname =  folder + '/modraw/' + name
        
        foldout = path + site + '/' + name + '/'
    
        df_chronic = pd.read_csv(foldout + 'df_chronic.csv', sep='\t')
        
        kr = str(re.findall(r'\d+\.\d+', name.split('_')[4])[0])
        k = str(re.findall(r'\d+\.\d+', name.split('_')[6])[0])
        n = str(re.findall(r'\d+\.\d+', name.split('_')[7])[0])
        e = str(re.findall(r'\d+\.\d+', name.split('_')[3])[0])
        
        obs = df_concat['cheze'+'_mmm']
        mod = df_chronic['drn'] + df_concat['old_run'+'_mmm'].values

        # idx_nan = np.argwhere(np.isnan(obs))
        # mod_nan = np.argwhere(np.isnan(mod))
        # obs = np.delete(obs, idx_nan)
        # mod = np.delete(mod, idx_nan)
        # obs = np.delete(obs, mod_nan)
        # mod = np.delete(mod, mod_nan)
        
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
        # months = mdates.MonthLocator(6)  # every month
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
        ax1.set_yticks(np.arange(0, obs.max()+10, 50))
                        
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
        # ax3.xaxis.set_minor_locator(months)
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
        # plt.close()
                
        outfig = path + site + '/fig/' + 'chronic/'
        if not os.path.exists(outfig):
            os.makedirs(outfig)
        fig.savefig(outfig + name + '.png', dpi=300, bbox_inches='tight')

    df_stat.to_csv(path + site + '/' + 'df_stat' + '.csv', sep="\t", index=True)
 
#%% Discharge nse

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet.iloc[:,1].values[0]

    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')

    df_stat = pd.read_csv(path + site + '/' + 'df_stat' + '.csv', sep="\t")

        # xy.loc[item, 'k'] = float(k)/30/24/3600
        # xy.loc[item, 'n'] = float(n)*100
        # xy.loc[item, 'nse'] = float(NSE)/100
        # xy.loc[item, 'nselog'] = float(NSElog)/100
        # xy.loc[item, 'kge'] = float(KGE)/100
        # xy.loc[item, 'seep'] = float(SEEP)/100

####
    fig, ax = plt.subplots(1,1,figsize=(4, 3))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    plt.xlabel("K [m/s]", labelpad=+15)
    plt.ylabel("n * e [m]", labelpad=+25)
    xy = xy.dropna()
    look = 'nselog'
    klist = xy.k
    porlist = (xy.n/100) * 30
    norm = mpl.colors.Normalize(vmin=0, vmax=1)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    # ax.set_yscale('log')
    position = fig.add_axes([0.92,0.2,0.03,0.6])
    cb = plt.colorbar(scat,cax=position)
    x1 = [-1,-0.5,0,0.5,1]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('NSE log', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]*100).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)
    pathfig = path + site + '/fig/' +  site + '_nselog'
    fig.savefig(pathfig + '.png', dpi=300, bbox_inches='tight')

####    
    fig, ax = plt.subplots(1,1,figsize=(4, 3))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    plt.xlabel("K [m/s]", labelpad=+15)
    plt.ylabel("n * e [m]", labelpad=+25)
    xy = xy.dropna()
    look = 'nse'
    klist = xy.k
    porlist = (xy.n/100) * 30
    norm = mpl.colors.Normalize(vmin=0, vmax=1)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    # ax.set_yscale('log')
    position = fig.add_axes([0.92,0.2,0.03,0.6])
    cb = plt.colorbar(scat,cax=position)
    x1 = [-1,-0.5,0,0.5,1]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('NSE', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]*100).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)
    pathfig = path + site + '/fig/' +  site + '_nse'
    fig.savefig(pathfig + '.png', dpi=300, bbox_inches='tight')

####
    fig, ax = plt.subplots(1,1,figsize=(4, 3))
    fig.add_subplot(111, frameon=False)
    plt.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    plt.xlabel("K [m/s]", labelpad=+15)
    plt.ylabel("n * e [m]", labelpad=+25)
    xy = xy.dropna()
    look = 'seep'
    klist = xy.k
    porlist = (xy.n/100) * 30
    norm = mpl.colors.Normalize(vmin=0, vmax=1)
    scat = ax.scatter(klist, porlist, marker='s', s=300, c=xy[look], cmap='jet', norm=norm)
    ax.set_xscale('log')
    # ax.set_yscale('log')
    position = fig.add_axes([0.92,0.2,0.03,0.6])
    cb = plt.colorbar(scat,cax=position)
    x1 = [-1,-0.5,0,0.5,1]
    cb.set_ticks(x1)
    cb.ax.tick_params(labelsize=15)
    cb.set_label('SEEPAGE', rotation=270, labelpad=20)
    cb.update_ticks()
    totxt = (xy[look]*100).values.round(0).astype(int).tolist()
    xy['txt'] = totxt
    for i in xy.index:
        ax.annotate(xy.txt[i],(klist[i], porlist[i]), family='sans-serif', fontsize=9, color='black', 
                    weight="bold", ha='center', va='center', clip_on=True, zorder=3)
    ax.set_title(site.upper())
    ax.grid(True)
    pathfig = path + site + '/fig/' +  site + '_seep'
    fig.savefig(pathfig + '.png', dpi=300, bbox_inches='tight')

#%%  Piezometry chronic

# for idx, serie in outlets.iterrows():
#     outlet = outlets.loc[[idx]]
#     site = outlet.iloc[:,1].values[0]
    
#     if site == 'garun':
            
#         dicparam = {}
        
#         allf = sorted((glob(path + site + '/' + 'transient*')),
#                       key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))
    
#         for item, simul in enumerate(allf): # to operate the script for each simulation
        
#             print('*******'+'Simulation : '+str(item)+' / '+str(len(allf)-1)+'********')
            
#             # Name of models
#             folder = simul
#             name = simul.split('\\')[-1]
#             modelname =  folder + '/modraw/' + name
            
#             foldout = path + site + '/' + name + '/'
        
#             dfp = pd.read_csv(foldout + 'dfp.csv', sep='\t')
            
#             statp = pd.read_csv(foldout + 'statp.csv', sep='\t')
        
#             kr = str(re.findall(r'\d+\.\d+', name.split('_')[4])[0])
#             k = str(re.findall(r'\d+\.\d+', name.split('_')[6])[0])
#             n = str(re.findall(r'\d+\.\d+', name.split('_')[7])[0])
        
#             # Parameters
#             years = mdates.YearLocator(1)   # every year
#             yearsmin = mdates.YearLocator(1)
#             months = mdates.MonthLocator()  # every month
#             years_fmt = mdates.DateFormatter('%Y')
#             months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        
#             # Figure configuration
#             fig = plt.figure(figsize=(12, 6))
#             gs = GridSpec(nrows=2, ncols=2, width_ratios=[3, 1], height_ratios=[1, 2])
#             ax1 = fig.add_subplot(gs[0, 0])
#             ax2 = fig.add_subplot(gs[0, 1])
#             ax3 = fig.add_subplot(gs[1, 0])
#             ax4 = fig.add_subplot(gs[1, 1])
            
#             d = df_concat.index
#             o = df_concat[nampiez+'_mbgs']
#             s = dfp[nampiez+'_k'+k+'_n'+n]
            
#             # Piezo mNGF
#             # ax1.plot(d, o, c='k', label='observed', lw=2)
#             ax1.plot(d, s, c='dodgerblue', 
#                     label='K='+k+'m/m'+' ; '+'n='+n+'%', lw=2)
#             ax1.axes.get_xaxis().set_visible(False)
#             ax1.legend(fontsize=10, prop=fontdic)
#             ax1.set_title('Water level (mNGF)' + ' - ' + nampiez + ' - ' + 'elevation : ' + str(alt) + ' m',
#                          pad=+15, size=15)    
#             ax1.grid(True)
#             if not o.isnull().all():
#                 ax1.set_yticks(np.arange(int(s.min())-4, 
#                                           int(s.max())+4, 
#                                           5))
            
#             # Stats
#             RMSE = statp.loc[item,'rmse']
#             NSE = statp.loc[item,'nse']
#             NSElog = statp.loc[item,'nselog']
#             BAL = statp.loc[item,'bal']
#             MARE = statp.loc[item,'mare']
#             KGE = statp.loc[item,'kge']
            
#             # Show stats
#             ax2.axes.xaxis.set_visible(False)
#             ax2.axes.yaxis.set_visible(False)
#             ax2.axis('off')
#             ax2.text(0, 0.45, 
#                       "NSE = " + '%.1f' % NSE + " %" + "\n" +
#                       "NSElog = " + '%.1f' % NSElog + " %" + "\n" +
#                       "KGE = " + '%.1f' % KGE + " %" + "\n" +
#                       "RMSE = " + '%.1f' % RMSE + " %" + "\n" +
#                       "MARE = " + '%.1f' % MARE + " %" + "\n" +
#                       "BAL = " + '%.1f' % BAL + " %",
#                       ha='left', va='center', fontsize=16, transform=ax2.transAxes)
            
#             # Piezo mBGS
#             ax3.plot(d, o, c='k', label='observed', lw=2)
#             ax3.plot(d, alt - s, c='dodgerblue', lw=2)
#             ax3.set_xlabel('Date', fontsize=20, fontproperties=fontprop)
#             ax3.set_ylabel('Water level (mBGS)', labelpad=10, fontsize=20, fontproperties=fontprop)
#             ax3.tick_params(axis='x', color='k')
#             ax3.tick_params(axis='y', colors='k')
#             # ax3.set_yscale('log')
#             ax3.xaxis.set_major_locator(years)
#             ax3.xaxis.set_minor_locator(yearsmin)
#             ax3.xaxis.set_minor_locator(months)
#             ax3.xaxis.set_major_formatter(years_fmt)
#             ax3.grid(True)
#             ax3.invert_yaxis()
#             # if not o.isnull().all():
#             #     ax3.set_yticks(np.arange(int(o.min())-2, 
#             #                           int(o.max())+4, 
#             #                           2))
            
#             # Observed vs simulated
#             ax4.plot(o, alt - s, 
#                      color='darkorange', marker='.', linestyle='None', lw=2)
#             ax4.set_ylabel('Simulated (mBGS)', fontproperties=fontprop)
#             ax4.set_xlabel('Observed (mBGS)', fontproperties=fontprop)
#             ax4.set_aspect('equal', adjustable='box')
#             # ax4.set_xscale('log')
#             # ax4.set_yscale('log')
#             ax4.grid(True)
#             maxi = np.maximum(np.nanmax(o),
#                               np.nanmax(alt - s))
#             mini = np.minimum(np.nanmin(o),
#                               np.nanmin(alt - s))
#             ax4.tick_params(axis='both', which='major', pad=10)
#             if not np.isnan(mini) & np.isnan(maxi):
#                 x1 = np.arange(round(mini),round(maxi)+1,2)
#                 ax4.set_xticks(x1)
#                 ax4.set_yticks(x1)
#                 ax4.set_ylim([mini, maxi])
#                 ax4.set_xlim([mini, maxi])
#             if not np.all(np.isnan(s)):
#                 ax4.plot((mini,maxi),(mini,maxi), color='k', ls='--')
            
#             plt.tight_layout()

#%% Notes

    # Out figure
outname = path + site + '/fig/' + 'indic/'
if not os.path.exists(outname):
    os.makedirs(outname)