# -*- coding: utf-8 -*-
"""
Created on Sun Feb 27 23:27:48 2022

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
#%%Claibration analytique
from tools import toolbox

# It's also possible to use the reduced notation by directly setting font.family:
plt.rcParams.update({
  "text.usetex": True,
  "font.family": "Helvetica"
})

fig = plt.figure(figsize=(10,10))
ax = plt.subplot(222)
ax1 = plt.subplot(221)
ax2 = plt.subplot(212)

name = ['01423X0044-F4','PzAC5','PzAC3','PzAC1','PzAC4','PzAC2']
colors = ['r','b','g','m','k','y']
x_mer = [465, 115, 480, 640,430,635]
Ltot = [1350,1050,1050,1050,1050,1050]
Lriv = [1300,300,730,600,600,650]
h_riv = ['-',4.32,4.23,4.42,4.3,4.25]
x_riv = [465,345,150,235,20,230] #345
Lres = [1030,430,'-','-','-','-'] #160
hriv = [6.51,4.3,'-','-','-','-'] #4.55

hmer = 0.48

hobs = [BV.piezometry.elevation['01423X0044_F4'].mean(),
        BV.piezometry.elevation['AC5'].mean(),
        BV.piezometry.elevation['AC3'].mean(),
        BV.piezometry.elevation['AC1'].mean(),
        BV.piezometry.elevation['AC4'].mean(),
        BV.piezometry.elevation['AC2'].mean()]

E = 30 #m
BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'D', sim_state='steady')
R = BV.forcing.recharge
L = 1000
x = np.linspace(0,L,L+1)
Kexp = np.linspace(-3,2,1000)
for i in range(0,len(name)):
    ind = []
    for k in Kexp:
        x = np.linspace(0,Ltot[i],Ltot[i]+1)
        h = np.sqrt((-R*x**2/10**(k))+(2*R*Ltot[i]*x/10**(k))+(E)**2)-(E-0.48)
        sim = h[x_mer[i]]
        obs = hobs[i]
        RMSE = np.sqrt(np.nanmean((sim-obs)**2))
        ind.append(RMSE)
    min_value = min(ind)
    idx = ind.index(min_value)
    print(name[i]+':'+str(Kexp[idx]))
    ax1.plot(Kexp,ind,c=colors[i], label=name[i], lw=2)
ax1.set_yscale('log')
ax1.set_xlabel(r'$K$ $(10^{X})$ $[m.j^{-1}]$')
ax1.set_ylabel('$RMSE$ $[-]$')
ax1.set_xlim(-2,2)
ax1.legend(loc='upper right',ncol=2,handletextpad=0.5)



y = []
y.append(BV.piezometry.elevation['01423X0044_F4'].resample('D').mean().values)
y.append(BV.piezometry.elevation['AC5'].resample('D').mean().values)
y.append(BV.piezometry.elevation['AC3'].resample('D').mean().values)
y.append(BV.piezometry.elevation['AC1'].resample('D').mean().values)
y.append(BV.piezometry.elevation['AC4'].resample('D').mean().values)
y.append(BV.piezometry.elevation['AC2'].resample('D').mean().values)
box=[]
for i in range (0,len(y)):
    bp = ax2.boxplot(y[i][~np.isnan(y[i])],positions=[x_mer[i]],widths=20, showfliers=False)
    box.append(bp["boxes"][0])
    for element in ['boxes', 'whiskers', 'fliers', 'means', 'medians', 'caps']:
        plt.setp(bp[element], color=colors[i], lw=2)
#ax2.legend(box, name)
ax2.set_xlim(0,700)
#plt.xticks(np.linspace(0,700,10+1),rotation=90)
no_samples = 700
x = np.linspace(0, no_samples, 700)
no_labels = int(np.floor(len(x) / 100))
label = [f'{i * no_samples / no_labels:.0f}' for i in range(no_labels+1)]
ax2.set_xticks(range(0,len(x)+1, 100))
ax2.set_xticklabels(label)
ax2.set_xlabel(r'$Distance$ $[m]$')
ax2.set_ylabel(r'$h$ $[m]$')
ax2.set_ylim(0,6)


hplot6 = np.sqrt((-R*x**2/6.01)+(2*R*1350*x/6.01)+(E)**2)-(E-0.48)
ax2.plot(x,hplot6,'-k',lw= 2, label=r'$h(K=6.01$ $m.j^{-1})$')
K1= 2.51
hplotn = np.sqrt((-R*x**2/K1)+(2*R*1050*x/K1)+(E)**2)-(E-0.48)
ax2.plot(x,hplotn,'--k',lw= 2, label=r'$h(K=2.51$ $m.j^{-1})$')
K1= 1.14
hplotn = np.sqrt((-R*x**2/K1)+(2*R*1050*x/K1)+(E)**2)-(E-0.48)
ax2.plot(x,hplotn,'-.k',lw= 2, label=r'$h(K=1.14$ $m.j^{-1})$')
ax2.legend(loc='best')


K = 6 #4.1
for i, color in enumerate(colors, start=0):
    h = np.sqrt((-R*x**2/K)+(2*R*Ltot[i]*x/K)+(E)**2)-(E-0.48)
    hsim = h[x_mer[i]]
    ax.plot(hobs[i],hsim,'o',color=color,markersize=15)
    if h_riv[i] != '-':
        h2 = np.sqrt((-R*x**2/K)+(2*R*Lriv[i]*x/K)+(E)**2)-(E-h_riv[i])
        ax.plot(hobs[i],h2[x_riv[i]],'^',color=color,markersize=15)
    '''
    if Lres[i] != '-':
        xres = np.linspace(0,int(Lres[i]),int(Lres[i]+1))
        hres = np.sqrt((E)**2-(((E)**2-(E+(hriv[i]-hmer))**2)*xres/Lres[i])+((R/K)*(Lres[i]-xres)*xres))-(E-0.48)
        h_piezo = hres[x_mer[i]]
        ax.plot(hobs[i],h_piezo,'s',color=color)
    '''
ax.plot(0,0,'ow', label='Sea boundary condition')
ax.plot(0,0,'^w', label='River boundary condition')
ax.plot([min(hobs)-1,max(hobs)+1],[min(hobs)-1,max(hobs)+1],'--k',lw=2, label='Line 1:1')
ax.set_xlabel(r'$\overline{h}_{obs}$ $[m]$')
ax.set_ylabel(r'$\overline{h}_{sim}$ $[m]$')
ax.set_xlim(2,6)
ax.set_ylim(0,6)
ax.legend(loc='best',handletextpad=0.5)
plt.tight_layout()

plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/calib_analytique.png',dpi=300, bbox_inches = "tight")