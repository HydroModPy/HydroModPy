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
from matplotlib import colors
import shutil
from mpl_toolkits.axes_grid1 import make_axes_locatable
import imageio
import geopandas as gpd

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

#%% Path

path = "D:/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/congress_events/egu/analysis_model/"
outlets = pd.read_csv(path+"_data/outlets_test.txt", sep='\t', header=None, engine='python')

#%% h5 generation

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet.iloc[:,1].values[0]
    
    print('#################### SITE '+str(idx)+' : '+site.upper()+' ####################')
    
    # Dem
    dem_path = path + site + '/gis/' + 'watershed_dem.tif'
    pix = 75
    maskdata = imageio.imread(dem_path)

    # Simulations    
    allf = sorted((glob(path + site + '/' + 'transient*')),
                  key=lambda x:float(re.findall(r'\d+', x.split('\\')[-1].split('_')[4])[0]))
            
    for item, simul in enumerate(allf): # to operate the script for each simulation
    
        print('Simulation : '+str(item)+' / '+str(len(allf)-1))
        
        # Name of models
        folder = simul
        name = simul.split('\\')[-1]
        modelname =  folder + '/modraw/' + name
        
        # Choice saving
        foldout = "D:/LOCAL/MODEL/" + site + '/' + name + '/'
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
            dicoseep[iplot] = seep
            dicodrn[iplot] = drn_drain[0]
            dicoq[iplot] = q[0]
            dicowt[iplot] = head_tr[0]
        
        # Save dictionnary
        dd.io.save(foldout+'seep.h5', dicoseep)
        dd.io.save(foldout+'wt.h5', dicowt)
        dd.io.save(foldout+'drn.h5', dicodrn)
        dd.io.save(foldout+'q.h5', dicoq)

#%% Extract values

df_chronic = pd.DataFrame()

for idx, serie in outlets.iterrows():
    outlet = outlets.loc[[idx]]
    site = outlet.iloc[:,1].values[0]
    
    # Remove figures
    allr = glob(path + site + '/fig/' + 'streams/')
    for f in allr:
        shutil.rmtree(f)
    
    # Dem
    dem_path = path + site + '/gis/' + 'watershed_dem.tif'
    pix = 75
    maskdata = imageio.imread(dem_path)
    
    # Import shp
    contour = gpd.read_file(path + site + '/gis/' + 'watershed_contour.shp')
    bounds = contour.geometry.total_bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    
    # Cmap
    cmap1 = colors.ListedColormap(['grey'])
    cmap2 = colors.ListedColormap(['dodgerblue'])

    # Simulations    
    allf = sorted((glob(path + site + '/' + 'transient*')),
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
        e = str(re.findall(r'\d+\.\d+', name.split('_')[3])[0])
        
        fold = "D:/LOCAL/MODEL/" + site + '/' + name + '/'
                
        dicodrn = dd.io.load(fold+'/'+'drn.h5')
        dicoseep = dd.io.load(fold+'/'+'seep.h5')
        dicowt = dd.io.load(fold+'/'+'wt.h5')
        dicoq = dd.io.load(fold+'/'+'q.h5')
    
        foldout = path + site + '/' + name + '/'
        
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
            
            # Out figure
            outname = path + site + '/fig/' + 'sepp/'
            if not os.path.exists(outname):
                os.makedirs(outname)
            
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
                # plt.close()            
                fig.savefig(outname+'outflow_'+idd+'.png', dpi=300, bbox_inches='tight')
                    
        df_chronic.to_csv(foldout + 'df_chronic' + '.csv', sep="\t", index=True)
    
#%% Piezometry

# dempath = gdal.Open(dem_path)
# demdata = dempath.ReadAsArray()

# piez = pd.read_csv(path + '_data/'+'coord_piezometers.txt',
#                          names=['name','X','Y','alt'],
#                                   sep='\t+', header = None,
#                                   parse_dates=True,
#                                   decimal=".", engine='python')
# id_piez = 0
# nampiez, xpiez, ypiez, alt = (piez.loc[id_piez,'name'],
#                               piez.loc[id_piez,'X'],
#                               piez.loc[id_piez,'Y'],
#                               piez.loc[id_piez,'alt'])

# def pixel_from_coord(dx,dy):
#     px = dempath.GetGeoTransform()[0]
#     py = dempath.GetGeoTransform()[3]
#     rx = dempath.GetGeoTransform()[1]
#     ry = dempath.GetGeoTransform()[5]
#     ulx, xres, xskew, uly, yskew, yres  = dempath.GetGeoTransform()
#     lrx = px + (dempath.RasterXSize * xres)
#     lry = py + (dempath.RasterYSize * yres)
#     xpiez_pix = (dx - px) / rx
#     ypiez_pix = (dy - lry) / abs(ry)
#     return xpiez_pix * pix, ypiez_pix * pix

# xpiez_pix, ypiez_pix = pixel_from_coord(xpiez,ypiez)
# find_xpiez = xpiez_pix / pix
# find_ypiez = demdata.shape[0] - (ypiez_pix / pix)

#     wt = dicowt[iplot]
#     masked = np.ma.masked_array(wt, mask=maskdata==-99999)
#     dfp.loc[iplot,nampiez+'_k'+k+'_n'+n] = masked[int(round(find_ypiez)),int(round(find_xpiez))]

# filenames = glob(path + site + '/' + name + '/' + 'streams/' + '*.png')
# images = []
# for filename in filenames:
#     images.append(imageio.imread(filename))
#     imageio.mimsave(path + site + '/' + name + '/' + 'streams/' + 'movie.gif', images, duration=1, loop=0.5)

#     obs = np.array(df_concat[nampiez+'_mbgs'].values)
#     mod = np.array(dfp[nampiez+'_k'+k+'_n'+n].values)
#     idx_nan = np.argwhere(np.isnan(obs))
#     obs = np.delete(obs, idx_nan)
#     mod = np.delete(mod, idx_nan)
    
#     RMSE = evaluator(rmse, mod, obs)
#     NSE = evaluator(nse, mod, obs)*100
#     NSElog = evaluator(nse, mod, obs, transform='log')*100
#     BAL = (np.sum(mod)/np.sum(obs))*100
#     MARE = evaluator(mare, mod, obs)*100
#     KGEcomp = evaluator(kge, mod, obs)*100 # and its three components (r, α, β)
#     KGE = KGEcomp[0]
    
#     statp.loc[item, 'kr'] = float(k)
#     statp.loc[item, 'k'] = float(k)
#     statp.loc[item, 'n'] = float(n)
#     statp.loc[item, 'rmse'] = RMSE
#     statp.loc[item, 'nse'] = NSE
#     statp.loc[item, 'nselog'] = NSElog
#     statp.loc[item, 'bal'] = BAL
#     statp.loc[item, 'mare'] = MARE
#     statp.loc[item, 'kge'] = KGE

#     statp.to_csv(foldout + 'statp' + '.csv', sep="\t", index=True)
#     dfp.to_csv(foldout + 'dfp' + '.csv', sep="\t", index=True)
