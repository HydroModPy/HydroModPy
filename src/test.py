# -*- coding: utf-8 -*-


# Librairies
import os
import pandas as pd
import numpy as np
from glob import glob

# Modules
import climatic as clim
import dichotomy as dic
import watershed as wat

# Plots
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties   

#%% Only extract watersheds

outlets = pd.read_csv("D:/PHD/4_model/MFLOW3D/github_calibration/_data/outlets_normandie.txt", sep='\t', header=None, engine='python')

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet[[0]].values[0][0]
    wat.extract_watershed(dem_path="D:/PHD/4_model/MFLOW3D/github_calibration/_data/Bretagne.tif",
                          outlet=outlet,
                          snap_dist=750, buff_dist=1000, save_dem=True,
                          tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                          out_path="D:/PHD/4_model/MFLOW3D/github_calibration/")

#%% Test run dichotomy

recharge = clim.surfex("D:/PHD/4_model/MFLOW3D/github_calibration/_data/climate.h5", sim='ACC1', var='REC', sce='historic', resample='D').period_data.mean()
outlets = pd.read_csv("D:/PHD/4_model/MFLOW3D/github_calibration/_data/outlets_artisan.txt", sep='\t', header=None, engine='python')

for idx, serie in outlets.iterrows():
    
    outlet = outlets.loc[[idx]]
    site = outlet[[0]].values[0][0]
    
    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
    
    dic.delimit_size(dem_path="D:/PHD/4_model/MFLOW3D/github_calibration/_data/Bretagne.tif",
                     watershed=site, outlet=outlet,
                     snap_dist=750, buff_dist=1000, save_dem=True, type_obs='streams',
                     data_path = "D:/PHD/4_model/MFLOW3D/github_calibration/_data/",
                     tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                     out_path="D:/PHD/4_model/MFLOW3D/github_calibration/")
    
    dic.dichotomy_loop(first=1, last=10000, gap=10,
                       df=pd.DataFrame(),
                       watershed=site,
                       climatic=[recharge/1000], lay_number=1, thick=100, porosity=0.01,
                       type_obs='streams', type_time='s', sim_id='identify',
                       data_path = "D:/PHD/4_model/MFLOW3D/github_calibration/_data/",
                       tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
                       out_path="D:/PHD/4_model/MFLOW3D/github_calibration/")
   
#%% Parameters for plot

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
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
mpl.rcParams['axes.xmargin'] = 0.05
mpl.rcParams['axes.ymargin'] = 0.05
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
smal = 8
medium = 16
large = 20
plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=large)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

#%% Plot of calibration

cases = glob("D:/PHD/4_model/MFLOW3D/github_calibration/_data/"+'outlets*')

for case in cases:

    target = case.split("\\")[-1].split('.')[0]
    outlets = pd.read_csv("D:/PHD/4_model/MFLOW3D/github_calibration/_data/"+target+'.txt', sep='\t', header=None, engine='python')
    
    fig, axs = plt.subplots(1,2, figsize=(10,4))
    (ax1,ax2) = axs
    
    n = len(outlets)
    colors = pl.cm.jet(np.linspace(0,1,n))
    site_list = outlets[0]
    
    for i, name in enumerate(site_list):
        path = "D:/PHD/4_model/MFLOW3D/github_calibration/"+name+'//'
        file = pd.read_csv(path+name+'_calibration.csv', sep='\t', header=0)
        ax = ax1
        toplot = file.sort_values('Kr')
        ax.plot(toplot.Kr, (toplot.Sflow), lw=2, color=colors[i], label=name)
        ax.plot(toplot.Kr, (toplot.Oflow), ls='--', lw=2, color=colors[i])
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.legend(loc='upper left', frameon=False, prop=fontdic)
        ax.set_xlabel('K / R', fontproperties=fontprop)
        ax.set_ylabel('Sflow and Oflow', fontproperties=fontprop)
        ax.set_title('Cross '+target, fontproperties=fontprop)
        ax.grid(True)    
        x = np.array(file.Kr)
        y1 = np.array(file.Sflow)
        y2 = np.array(file.Oflow)
        ax.scatter(file.iloc[-1].Kr, file.iloc[-1].Sflow, s=75, marker='o', edgecolor='k', lw=0.75, color=colors[i], zorder=3)
        ax.set_xlim(10,11000)
        ax.set_ylim(10,1000)
    
        ax = ax2
        ax.axhline(1, color='k', lw=1, ls='--', zorder=0)
        ax.scatter(file.Kr, (file.Sflow / file.Oflow), s=75, marker='o', edgecolor='k', lw=0.75, color=colors[i], label=name)
        ax.set_xscale('log')
        ax.set_xlim(100,11000)
        ax.set_ylim(-0.2,3)
        ax.set_xlabel('K / R', fontproperties=fontprop)
        ax.set_ylabel('Sflow / Oflow', fontproperties=fontprop)
        ax.set_title('Criteria '+target, fontproperties=fontprop)
        ax.grid(True)
        mean = ((file.Sflow / file.Oflow))
        best = file.iloc[(mean-1).abs().argsort()[:1]]
        # best = df.loc[np.argmin(mean),'Kr']
        ax.axvline(x=best.Kr.values, ls='--', c=colors[i], zorder=0)
        
        plt.tight_layout()
        
        fig.savefig("D:/PHD/4_model/MFLOW3D/github_calibration/_figures/"+target+'.jpg', dpi=300)
        