'''Ronan'''


# Import libraries
import os
import pandas as pd
import numpy as np
import shutil

# Import modules
from glob import glob
import climatic as clim
import modflow as mod
import watershed as wat
import extract as ext
import calibration as cal

# Import outlets of watersheds
outlets = pd.read_csv("D:/PHD/4_model/MFLOW3D/github_calibration/_data/outlets_norm.txt", sep='\t', header=None, engine='python')

# If necessary import climate
climat = clim.surfex("D:/PHD/4_model/MFLOW3D/github_calibration/_data/climate.h5",
					 sim='ACC1', var='REC', sce='historic', resample='M')
rch_mean = climat.period_data.mean() * 30 / 1000

#%%

# Loop for some sites
def delimit_site(target, idx, site, snap):
    wat.extract_watershed(dem_path="D:/PHD/4_model/MFLOW3D/github_calibration/_data/topobat75m_norm.tif",
    							  out_path="D:/PHD/4_model/MFLOW3D/github_calibration/",
    							  outlet=target,
    							  snap_dist=snap, buff_dist=1000,
    							  tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\',
    							  save_dem=True)
    		
    cal.extract_observed(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
    							 watershed=site, type_obs='streams',
    							 tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')

# Launch models and calibration
def run_calibration(krval, compt):
    
    hydcond = krval * recharge
    simulation = time+'_'+\
                 site+'_'+\
                 str(lay)+'_'+\
                 str(thick)+'_'+\
                 str(round(krval,3))+'_'+\
                 str(round(recharge,3))+'_'+\
                 str(round(hydcond,3))+'_'+\
                 str(porosity)
                 
    mod.modflow_model(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\'+'watershed_buff_fill.tif',
                      model_folder="D:/PHD/4_model/MFLOW3D/github_calibration/",
                      watershed=site, model_name=simulation,
                      lay_number=lay, thick=thick, climatic=[recharge], hyd_cond=hydcond, porosity=porosity)
        
    ext.extract_modflow(dem_path=os.path.dirname(os.getcwd())+'\\tmp\\'+'watershed_buff_fill.tif',
                      watershed=site,
                      model_name=simulation,
                      model_folder="D:/PHD/4_model/MFLOW3D/github_calibration/")
    
    cal.generate_distances(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
                           watershed=site, sim_id=simulation,  type_time='s', type_obs='streams',
                           tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')
    
    store = cal.store_dataframe(dir_path="D:/PHD/4_model/MFLOW3D/github_calibration/", 
                                watershed=site, sim_id=simulation, type_time='s',
                                tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\')   
    
    df.loc[compt,'Kr'] = round(krval, 4)
    df.loc[compt,'K'] = round(hydcond/30/24/3600, 4)
    df.loc[compt,'Sflow'] = round(store.sim_to_obs_mean, 4)
    df.loc[compt,'Oflow'] = round(store.obs_to_sim_mean, 4)
    df.loc[compt,'Qflow'] = round(store.outflow,4)   
    
    condition = round(store.sim_to_obs_mean / store.obs_to_sim_mean, 2)
    
    print('==> Simulation : '+str(compt))
    print('    Parameters : '+simulation)
    print('    KR = '+str(round(krval, 2)))
    print('    Condition = '+str(condition))
    
    return condition

# Lauch dichotomy on K/R values
def dichotomy_loop(df, site, time, first, last, gap, lay, thick, recharge, porosity):

    difference = last - first
        
    compt = 0
    while difference > gap:
        half = (first + last) / 2
        condition = run_calibration(half, compt)
        if condition > 1:
            first = half
        else:
            last = half
        difference = last - first
        print('    Ecart = '+str(round(difference,2))+'\n')
        compt += 1
    
    save_name = site+'\\'+site+'_calibration.csv'
    df.to_csv("D:/PHD/4_model/MFLOW3D/github_calibration/"+save_name, sep='\t', index=True)
    
    # plt.scatter(df.Kr, df.Oflow)
    # plt.scatter(df.Kr, df.Sflow)

#%%

# Loop for each site modelized
for idx, serie in outlets.iterrows():
    
    # General parameters
    target = outlets.loc[[idx]]
    site = target[[0]].values[0][0]
    
    # Modflow parameters
    time = 's'
    lay = 1
    thick = 100
    recharge = 0.025
    porosity = 0.01
    
    # Dochotomy parameters
    first = 1
    last = 10000
    gap = 10
    
    # Generate site
    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
    snap = 500
    delimit_site(target, idx, site, snap)
    
    # Delete previous simulations
    sim_list = glob("D:/PHD/4_model/MFLOW3D/github_calibration/"+site+'\\'+'s*')
    if not sim_list:
        print('- Delete previous : '+'NO'+'\n')
    else:
        print('- Delete previous : '+'YES'+'\n')
    for folder in sim_list:
        shutil.rmtree(folder)
        
    # Run model and calibration with dichotomy
    df = pd.DataFrame()
    dichotomy_loop(df, site, time, first, last, gap, lay, thick, recharge, porosity)
    
#%%

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties

# Parameters plot : v2.0 to classic customized
# mpl.rcParams.update(mpl.rcParamsDefault)
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

# Parameters size plot
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

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

# Figure test
fig, ax = plt.subplots(figsize=(5,4))
colors = pl.cm.jet(np.linspace(0,1,8))
site_list = outlets[0]
for i, name in enumerate(site_list):
    path = "D:/PHD/4_model/MFLOW3D/github_calibration/"+name+'//'
    file = pd.read_csv(path+name+'_calibration.csv', sep='\t', header=0)
    
    ax.axhline(1, color='k', lw=1, ls='--', zorder=0)
    ax.scatter(file.Kr, (file.Sflow / file.Oflow), s=75, marker='o', edgecolor='k', lw=0.75, color=colors[i], label=name)
    ax.set_xscale('log')
    ax.legend(fontsize=7, prop=fontdic, frameon=False)
    ax.set_xlim(100,11000)
    ax.set_ylim(-0.2,3)
    ax.set_xlabel('K / R',  fontproperties=fontprop)
    ax.set_ylabel('Sflow / Oflow',  fontproperties=fontprop)
    ax.set_title('Test', fontproperties=fontprop)
    ax.grid(True)




