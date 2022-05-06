# -*- coding: utf-8 -*-
"""
Created on Mon Mar 14 15:40:57 2022

@author: Alexandre Gauvain
"""

#%% BV

# Download data on my Dropbox at this link: https://www.dropbox.com/sh/eidukc992nvi6jc/AAC0cwuwCnY7bDjiN57qwODva?dl=0
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
from watershed import watershed_root
#from calibration import calib_root


# Users
user_path = "Alexandre"

if user_path=="Alexandre":
    root_path= "C:/Users/alexa/Dropbox/HydroModPy/_data/"
    out_path = 'C:/Users/alexa/Dropbox/HydroModPy'
elif user_path=="Jean-Raynald":
    root_path= "C:/DATA/codes-gitlab-public/HydroModPy_data/"
    out_path = "C:/DATA/results/HydroModPy"
elif user_path=="Ronan":
    root_path= "D:/Users/abherve/HYDROMODPY/_data/"
    out_path = "D:/Users/abherve/HYDROMODPY"
else:
    print("Define a well-validated name of user")

load = True#False to build and save python object
watershed_name = 'Agon-Coutainville_5m' #'Saint-Germain-sur-Ay'Agon-Coutainville'Barneville-Carteret'Baie-du-cotentin'
watershed_shp = os.path.join(out_path, 'Agon-Coutainville', 'watershed.shp')
dem_path = root_path + "MNT_25m.tif"#'BDALTI_bzh_75m.tif' 
surfex_path =  root_path + 'SURFEX/Normandie_h5'
geology_path = root_path + 'GEOLOGY'
oceanic_path = root_path + 'OCEAN'
modflow_path = root_path + 'MODFLOW'
hydrology_path = root_path + 'HYDROLOGY'
types_obs = ['streams_fr']
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, 
                              out_path=out_path, modflow_path=modflow_path, load=load, from_shp= watershed_shp)

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')#

fact_cond = np.around(np.linspace(-5,-3,10),2)
MSL = np.around([BV.oceanic.MSL, 
       BV.oceanic.RMSL['RCP8.5']['median']['2030'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2050'].mean(),
       BV.oceanic.RMSL['RCP8.5']['median']['2100'].mean(),
       BV.oceanic.MSL+1,
       BV.oceanic.MSL+2],2)
Recharge = np.around([BV.forcing.recharge*0.3+BV.forcing.recharge,
            BV.forcing.recharge*0.2+BV.forcing.recharge,
            BV.forcing.recharge*0.1+BV.forcing.recharge,
            BV.forcing.recharge*0+BV.forcing.recharge,
            BV.forcing.recharge*-0.1+BV.forcing.recharge,
            BV.forcing.recharge*-0.2+BV.forcing.recharge,
            BV.forcing.recharge*-0.3+BV.forcing.recharge],5)

#%% Effet de la conductance
import flopy
import geopandas as gpd
import rasterio
import matplotlib as mpl
from rasterio.plot import show
from matplotlib_scalebar.scalebar import ScaleBar
from mpl_toolkits.axes_grid1 import make_axes_locatable
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

#matplotlib.rc('font', **font)

contour = gpd.read_file(BV.geographic.watershed_contour_shp)
dem = rasterio.open(BV.geographic.watershed_box_buff_dem)

AsA_store = []
T_store = []
A = np.sum(BV.geographic.dem_clip>-9999)

size = 5
fig, axs = plt.subplots(figsize=(size*2,3*(size*dem.height/dem.width)), dpi=300, constrained_layout=True)

ax3 = plt.subplot(321)
ax4 = plt.subplot(322)
ax5 = plt.subplot(323)
ax6 = plt.subplot(324)
ax7 = plt.subplot(325)
ax8 = plt.subplot(326)

tmin = 0
tmax = 60

cax = fig.add_axes([1.05, 0, 0.05, 1])

axs = [ax3,ax4,ax5,ax6,ax7,ax8]
for ax in axs:
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower center',
                        font_properties={'size': 20})
    ax.add_artist(scalebar)

for c in fact_cond:
    s = MSL[0]
    r = Recharge[3]
    ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(r)
    
    #Seepage 
    seepage_file = os.path.join(BV.simulations_folder,ident,'_watershed','seepage_areas.npy')
    seepage_area = np.load(seepage_file, allow_pickle=True).item()
    seepage_area[0][BV.geographic.dem_clip==-99999]=np.nan
    seepage_area[0][seepage_area[0]==0]=np.nan
    As = np.nansum(seepage_area[0])
    AsA_store.append(As/A)
    
    #Résidence Time
    res_time = np.zeros(np.shape(seepage_area[0]))*np.nan
    endobj = flopy.utils.EndpointFile(os.path.join(BV.simulations_folder,ident,ident+'.mpend'))
    e = endobj.get_alldata()
    for j in range(len(e)):
        res_time[e[j].i0,e[j].j0] = e[j].time/365
    T_store.append(np.nanmean(res_time))
    
    if c ==-3:
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax3, 
                     transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
        contour.plot(ax=ax3, lw=2, color='k', zorder=4, aspect="auto")
        contour.plot(ax=ax4, lw=2, color='k', zorder=4, aspect="auto")
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax4, 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
        ax3.text(0, 0.5, r'$C=10^{-3}$ $m^{2}.d^{-1}$',
                horizontalalignment='right',
                verticalalignment='center',fontsize=25,
                rotation='vertical',
                transform=ax3.transAxes)
        #ax3.set_title(r'$Seepage$ $areas$')
        #ax4.set_title(r'$Residence$ $times$')
    if c ==-4.11:
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax5, 
                     transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
        contour.plot(ax=ax5, lw=2, color='k', zorder=4, aspect="auto")
        contour.plot(ax=ax6, lw=2, color='k', zorder=4, aspect="auto")
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax6, 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
        ax5.text(0, 0.5, r'$C=10^{-4}$ $m^{2}.d^{-1}$',
                horizontalalignment='right',
                verticalalignment='center',fontsize=25,
                rotation='vertical',
                transform=ax5.transAxes)
    if c ==-5:
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax7, 
                     transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
        contour.plot(ax=ax7, lw=2, color='k', zorder=4, aspect="auto")
        contour.plot(ax=ax8, lw=2, color='k', zorder=4, aspect="auto")
        show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax8, 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
        ax7.text(0, 0.5, r'$C=10^{-5}$ $m^{2}.d^{-1}$',
                horizontalalignment='right',
                verticalalignment='center',fontsize=25,
                rotation='vertical',
                transform=ax7.transAxes)
#ax3.legend(title=r'$C$ $[m^{2}.d^{-1}]$',loc='lower right',prop={'size': 50})
cmap = mpl.cm.jet
norm = mpl.colors.Normalize(vmin=0, vmax=tmax)

cb1 = mpl.colorbar.ColorbarBase(cax, cmap=cmap,
                                norm=norm)
cb1.ax.tick_params(labelsize=20+10) 
cb1.set_label('Residence times [y]',font_properties={'size': 20+10})
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/maps_cond.png',dpi=300, bbox_inches = "tight")

fig, ax1 = plt.subplots(figsize=(4,5), dpi=300)  
ax2 = ax1.twinx()

ax2.spines['right'].set_color('b')
ax2.spines['left'].set_color('r')
ax1.plot(fact_cond,AsA_store,'.-r')
ax2.plot(fact_cond,T_store,'.-b')
ax2.tick_params(axis='y', labelcolor='b')
ax2.set_ylabel(r'$\tau$ $[y]$',c='b')
ax1.tick_params(axis='y', labelcolor='r')
ax1.set_ylabel(r'$A_{S}/A$ $[-]$',c='r') 
ax1.set_xlabel(r'$C$ $(10^{X})$ $[m^{2}.d^{-1}]$')
#fig.tight_layout()
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/fig_cond.png',dpi=300, bbox_inches = "tight")
            
#%% Effet de la recharge
import flopy
import geopandas as gpd
import rasterio
import matplotlib as mpl
from rasterio.plot import show
from matplotlib_scalebar.scalebar import ScaleBar
from mpl_toolkits.axes_grid1 import make_axes_locatable
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

#matplotlib.rc('font', **font)

contour = gpd.read_file(BV.geographic.watershed_contour_shp)
dem = rasterio.open(BV.geographic.watershed_box_buff_dem)


A = np.sum(BV.geographic.dem_clip>-9999)

size = 5
fig, axs = plt.subplots(figsize=(size*2,3*(size*dem.height/dem.width)), dpi=300, constrained_layout=True)

ax3 = plt.subplot(321)
ax4 = plt.subplot(322)
ax5 = plt.subplot(323)
ax6 = plt.subplot(324)
ax7 = plt.subplot(325)
ax8 = plt.subplot(326)

tmin = 0
tmax = 60

cax = fig.add_axes([1.05, 0, 0.05, 1])

axs = [ax3,ax4,ax5,ax6,ax7,ax8]
for ax in axs:
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower center',
                        font_properties={'size': 20})
    ax.add_artist(scalebar)

Recharge_Tstore = []
Recharge_AsAstore = []
for r in Recharge:
    AsA_store = []
    T_store = []
    for c in fact_cond:
        s = MSL[0]
        ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(r)
        
        #Seepage 
        seepage_file = os.path.join(BV.simulations_folder,ident,'_watershed','seepage_areas.npy')
        seepage_area = np.load(seepage_file, allow_pickle=True).item()
        seepage_area[0][BV.geographic.dem_clip==-99999]=np.nan
        seepage_area[0][seepage_area[0]==0]=np.nan
        As = np.nansum(seepage_area[0])
        AsA_store.append(As/A)
        
        #Résidence Time
        res_time = np.zeros(np.shape(seepage_area[0]))*np.nan
        endobj = flopy.utils.EndpointFile(os.path.join(BV.simulations_folder,ident,ident+'.mpend'))
        e = endobj.get_alldata()
        for j in range(len(e)):
            res_time[e[j].i0,e[j].j0] = e[j].time/365
        T_store.append(np.nanmean(res_time))
        
        if r == Recharge[0] and c == fact_cond[4]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax3, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax3, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax4, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax4, 
                         transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
            ax3.text(0, 0.5, r'$+30\%$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax3.transAxes)
            #ax3.set_title(r'$Seepage$ $areas$')
            #ax4.set_title(r'$Residence$ $times$')
        if r == Recharge[3] and c == fact_cond[4]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax5, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax5, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax6, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax6, 
                         transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
            ax5.text(0, 0.5, r'$R_{REF}$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax5.transAxes)
        if r == Recharge[6] and c == fact_cond[4]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax7, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax7, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax8, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, res_time), ax=ax8, 
                         transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=0, vmax=tmax)
            ax7.text(0, 0.5, r'$-30\%$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax7.transAxes)
    Recharge_Tstore.append(T_store)
    Recharge_AsAstore.append(AsA_store)
#ax3.legend(title=r'$C$ $[m^{2}.d^{-1}]$',loc='lower right',prop={'size': 50})
cmap = mpl.cm.jet
norm = mpl.colors.Normalize(vmin=0, vmax=tmax)
cb1 = mpl.colorbar.ColorbarBase(cax, cmap=cmap,
                                norm=norm)
cb1.ax.tick_params(labelsize=20+10) 
cb1.set_label('Residence times [y]',font_properties={'size': 20+10})
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/maps_rech.png',dpi=300, bbox_inches = "tight")

fig, (ax1,ax2) = plt.subplots(1,2,figsize=(10,5), dpi=300)  
#ax2 = ax1.twinx()
#ax2.spines['right'].set_color('b')
#ax2.spines['left'].set_color('r')

cmap = plt.cm.get_cmap('bwr')  # no need to preselect number of colors in this case
colors = cmap(np.linspace(0, 1, len(Recharge)))
bounds = np.arange(len(Recharge)+1)
norm = plt.matplotlib.colors.BoundaryNorm(bounds, cmap.N)
cax = fig.add_axes([0.95, 0.1, 0.02, 0.8])
cbar = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, ticks=bounds+0.5)
colors=colors[::-1]
ticks = ['$-30\%$','$-20\%$','$-10\%$','$R$','$+10\%$','$+20\%$','$+30\%$',]
cbar.set_ticklabels(ticks)

for i in range(len(Recharge)):
    if i ==3:
        ax1.plot(fact_cond,Recharge_AsAstore[i],'k')
        ax1.plot(fact_cond,Recharge_AsAstore[i],'o',color=colors[i])
        ax2.plot(fact_cond,Recharge_Tstore[i],'k')
        ax2.plot(fact_cond,Recharge_Tstore[i],'o',color=colors[i])
    else:
        ax1.plot(fact_cond,Recharge_AsAstore[i],'o-',color=colors[i])
        ax2.plot(fact_cond,Recharge_Tstore[i],'o-',color=colors[i])
ax2.tick_params(axis='y', labelcolor='k')
ax2.set_ylabel(r'$\tau$ $[y]$',c='k')
ax1.tick_params(axis='y', labelcolor='k')
ax1.set_ylabel(r'$A_{S}/A$ $[-]$',c='k') 
ax1.set_xlabel(r'$C$ $(10^{X})$ $[m^{2}.d^{-1}]$')
ax2.set_xlabel(r'$C$ $(10^{X})$ $[m^{2}.d^{-1}]$')
#fig.tight_layout()
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/fig_rech.png',dpi=300, bbox_inches = "tight")


#%% Effet du niveau marin
import flopy
import geopandas as gpd
import rasterio
import matplotlib as mpl
from rasterio.plot import show
from matplotlib_scalebar.scalebar import ScaleBar
from mpl_toolkits.axes_grid1 import make_axes_locatable
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

font = {'family' : 'normal',
        'weight' : 'bold',
        'size'   : 30}

#matplotlib.rc('font', **font)

contour = gpd.read_file(BV.geographic.watershed_contour_shp)
dem = rasterio.open(BV.geographic.watershed_box_buff_dem)


A = np.sum(BV.geographic.dem_clip>-9999)

size = 5
fig, axs = plt.subplots(figsize=(size*2,3*(size*dem.height/dem.width)), dpi=300, constrained_layout=True)

ax3 = plt.subplot(321)
ax4 = plt.subplot(322)
ax5 = plt.subplot(323)
ax6 = plt.subplot(324)
ax7 = plt.subplot(325)
ax8 = plt.subplot(326)

tmin = 0.0001
tmax = 1
cmap = 'plasma'

cax = fig.add_axes([1.05, 0, 0.05, 1])

axs = [ax3,ax4,ax5,ax6,ax7,ax8]
for ax in axs:
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower center',
                        font_properties={'size': 20})
    ax.add_artist(scalebar)

Recharge_Tstore = []
Recharge_AsAstore = []
for s in MSL:
    AsA_store = []
    T_store = []
    for c in fact_cond:
        r = Recharge[3]
        ident= 'mod_cond_'+str(c)+'_sea_'+str(s)+'_rech_'+str(r)
        
        #Seepage 
        seepage_file = os.path.join(BV.simulations_folder,ident,'_watershed','seepage_areas.npy')
        seepage_area = np.load(seepage_file, allow_pickle=True).item()
        seepage_area[0][BV.geographic.dem_clip==-99999]=np.nan
        seepage_area[0][seepage_area[0]==0]=np.nan
        As = np.nansum(seepage_area[0])
        AsA_store.append(As/A)
        
        #watertable depth
        idref ='mod_cond_'+str(c)+'_sea_'+str(MSL[0])+'_rech_'+str(r)
        ref_file = os.path.join(BV.simulations_folder,idref,'_watershed','watertable_elevation.npy')
        depth_file = os.path.join(BV.simulations_folder,ident,'_watershed','watertable_elevation.npy')
        depth_area = np.load(depth_file, allow_pickle=True).item()
        ref_area = np.load(ref_file, allow_pickle=True).item()
        depth_area[0] = depth_area[0]-ref_area[0]
        depth_area[0][depth_area[0]<tmin] = tmin
        depth_area[0][BV.geographic.dem_clip==-99999]=np.nan
        
        #Résidence Time
        '''
        res_time = np.zeros(np.shape(seepage_area[0]))*np.nan
        endobj = flopy.utils.EndpointFile(os.path.join(BV.simulations_folder,ident,ident+'.mpend'))
        e = endobj.get_alldata()
        for j in range(len(e)):
            res_time[e[j].i0,e[j].j0] = e[j].time/365
        T_store.append(np.nanmean(res_time))
        '''
        n=4
        if s == MSL[2] and c == fact_cond[n]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax3, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax3, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax4, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, depth_area[0]), ax=ax4, 
                         transform=dem.transform, cmap=cmap, alpha=1, zorder=2, aspect="auto", norm=mpl.colors.LogNorm(vmin=tmin, vmax=tmax))
            ax3.text(0, 0.5, r'$+0.64m$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax3.transAxes)
            #ax3.set_title(r'$Seepage$ $areas$')
            #ax4.set_title(r'$Residence$ $times$')
        if s == MSL[4] and c == fact_cond[n]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax5, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax5, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax6, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, depth_area[0]), ax=ax6, 
                         transform=dem.transform, cmap=cmap, alpha=1, zorder=2, aspect="auto", norm=mpl.colors.LogNorm(vmin=tmin, vmax=tmax))
            ax5.text(0, 0.5, r'$+1m$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax5.transAxes)
        if s == MSL[5] and c == fact_cond[n]:
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, seepage_area[0]), ax=ax7, 
                         transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto")
            contour.plot(ax=ax7, lw=2, color='k', zorder=4, aspect="auto")
            contour.plot(ax=ax8, lw=2, color='k', zorder=4, aspect="auto")
            show(np.ma.masked_where(BV.geographic.dem_clip<= 0, depth_area[0]), ax=ax8, 
                         transform=dem.transform, cmap=cmap, alpha=1, zorder=2, aspect="auto", norm=mpl.colors.LogNorm(vmin=tmin, vmax=tmax))
            ax7.text(0, 0.5, r'$+2m$',
                    horizontalalignment='right',
                    verticalalignment='center',fontsize=25,
                    rotation='vertical',
                    transform=ax7.transAxes)
    Recharge_Tstore.append(T_store)
    Recharge_AsAstore.append(AsA_store)
#ax3.legend(title=r'$C$ $[m^{2}.d^{-1}]$',loc='lower right',prop={'size': 50})
cmap = mpl.cm.get_cmap(cmap)
norm = mpl.colors.LogNorm(vmin=tmin, vmax=tmax)
cb1 = mpl.colorbar.ColorbarBase(cax, cmap=cmap,
                                norm=norm)
cb1.ax.tick_params(labelsize=20+10) 
cb1.set_label('$h_{sim} - h^{actual}_{sim}$ $[m]$',font_properties={'size': 20+10})
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/maps_sea.png',dpi=300, bbox_inches = "tight")

fig, ax1 = plt.subplots(1,1,figsize=(5,5), dpi=300)  
#ax2 = ax1.twinx()
#ax2.spines['right'].set_color('b')
#ax2.spines['left'].set_color('r')

cmap = plt.cm.get_cmap('Blues')  # no need to preselect number of colors in this case
colors = cmap(np.linspace(0, 1, len(MSL)))
bounds = np.arange(len(MSL)+1)
norm = plt.matplotlib.colors.BoundaryNorm(bounds, cmap.N)
cax = fig.add_axes([0.95, 0.1, 0.04, 0.8])
cbar = plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, ticks=bounds+0.5, label= '$h_{sea}$ $[m]$')
ticks = MSL
cbar.set_ticklabels(ticks)

for i in range(0,len(MSL)):
    if i == 3:
        y1=np.asarray(Recharge_AsAstore[i])-np.asarray(Recharge_AsAstore[0])
        y2=np.asarray(Recharge_AsAstore[2])-np.asarray(Recharge_AsAstore[0])
        ax1.plot(fact_cond,np.abs(y1)+y2,'o-',color=colors[i])
    else:
        ax1.plot(fact_cond,np.asarray(Recharge_AsAstore[i])-np.asarray(Recharge_AsAstore[0]),'o-',color=colors[i])

ax1.tick_params(axis='y', labelcolor='k')
ax1.set_ylabel(r'$(A_{S} - A^{actual}_{S})/A$ $[-]$',c='k') 
ax1.set_xlabel(r'$C$ $(10^{X})$ $[m^{2}.d^{-1}]$')
#fig.tight_layout()
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/fig_sea.png',dpi=300, bbox_inches = "tight")


            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            