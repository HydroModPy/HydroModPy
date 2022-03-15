# -*- coding: utf-8 -*-
"""
Created on Sun Feb 27 23:30:22 2022

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


'''
01423X0044-F4:86.88382635251185
PzAC5:15.24695727017573
PzAC3:21.05345242766706
PzAC1:27.76153294436801
PzAC4:25.316484786313556
PzAC2:28.40883690183304
'''

name = [r'$01423X0044-F4$',r'$PzAC5$',r'$PzAC3$',r'$PzAC1$',r'$PzAC4$',r'$PzAC2$']
code = ['01423X0044_F4','AC5','AC3','AC1','AC4','AC2']
colors = ['r','b','g','m','k','y']
start = ['08/2015','08/2017','09/2017','08/2017','-','07/1/2017'] 
end = ['09/2015','10/2017','10/2017','09/2017','-','8/15/2017'] 
x_mer = [465, 115, 480, 640,430,635]
axis = [(0,0),(0,1),(0,2),(1,0),(1,2),(1,1)]
K= [86.88, 15.24, 86.88, 86.88, 86.88, 86.88]
K=[6,1,6,6,6,6]
phi = [13,8,12,9,0,1]
Awell = [0.25,1,0.4,0.15,0,0.10]
E = 30
n=0.025
A=3.05#3.05
T=14.76

fig , ax = plt.subplots(2,3,figsize=(12,8))
ns = []
for i in range (0, len(name)):
    if start[i] != '-':
        y = BV.piezometry.elevation[code[i]][start[i]:end[i]].resample('D').mean().values
        ax[axis[i]].plot(y,colors[i],label=name[i],lw=2)
        D = K[i]*E/n
        lc = np.sqrt(D*T/np.pi)
        t = np.linspace(0,len(y),len(y))
        t1 = t + phi[i]
        hmean = np.nanmean(y)
        h = hmean + (A/2*np.cos((2*np.pi*t1/T)-(x_mer[i]/lc)))* np.exp(-x_mer[i]/lc)
        
        w = 2*np.pi/T
        k = ((n*w)/(2*K[i]*(E+hmean)))**0.5
        h2 = hmean + (A/2*np.cos((w*t1)-(k*x_mer[i]))*np.exp(-k*x_mer[i]))
        htide = hmean + (A*np.cos(w*t1))
    
        
        ax[axis[i]].plot(t,h,'-k',alpha=0.5,lw=2, label=r'$h(x,\,t)$')
        #ax[axis[i]].plot(t,h2,'-r',alpha=0.5,lw=2, label=r'$h(x,\,t)$')
        #ax[axis[i]].plot(t,htide,'-b',alpha=0.5,lw=2, label=r'$h(x,\,t)$')
        amp = (np.nanmax(y) - np.nanmin(y))/4
        ax[axis[i]].set_ylim(np.nanmin(y)-amp/10,np.nanmax(y)+amp)
        ax[axis[i]].legend(loc='best',prop={'size': 12})
        if axis[i][0] ==1 or axis[i][1] ==2:
           ax[axis[i]].set_xlabel('$Time$ $[d]$')
        if axis[i][1] ==0:
           ax[axis[i]].set_ylabel('$h(x,t)$ $[m]$')
    else:
        fig.delaxes(ax[axis[i]])
    n1 = (K[i]*E*(np.log(Awell[i]/A))**2*T)/(x_mer[i]**2*np.pi)*100
    ns.append(n1)
    print(name[i],n1)
plt.savefig('C:/Users/alexa/Dropbox/PhD/_Thèse/Figure/calib_analytique_n.png',dpi=300, bbox_inches = "tight")



