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

name = ['01423X0044-F4','PzAC5','PzAC3','PzAC1','PzAC4','PzAC2']
colors = ['r','b','g','m','k','y']
x_mer = [465, 115, 480, 640,430,635]
x_mer = [400, 200, 300, 640,430,635]

y1 = BV.piezometry.elevation['01423X0044_F4']['08/2015':'10/2015'].resample('D').mean().values
y2 = BV.piezometry.elevation['AC5']['08/2017':'10/2017'].resample('D').mean().values
y3 = BV.piezometry.elevation['AC3']['09/2017':'11/2017'].resample('D').mean().values
y4 = BV.piezometry.elevation['AC1']['07/2017':'9/2017'].resample('D').mean().values

fig , ax = plt.subplots(2,2,figsize=(10,10))

ax[0,0].plot(y1,'r',label='01423X0044-F4',lw=2)
ax[0,1].plot(y2,'b',label='AC5',lw=2)
ax[1,0].plot(y3,'g',label='AC3',lw=2)
ax[1,1].plot(y4,'m',label='AC1',lw=2)

h1 = np.nanmean(y1)
h2 = np.nanmean(y2)
h3 = np.nanmean(y3)
h4 = np.nanmean(y4)

t = np.linspace(0,len(y1),len(y1))
A=3.05
T=14.76

K=6
E = 30

P=0.03
D = K*E/P
lc = np.sqrt(D*T/np.pi)
t1 = t+1
h = h1 + (A/2*np.cos((2*np.pi*t1/T)-(x_mer[0]/lc)))* np.exp(-x_mer[0]/lc)
ax[0,0].plot(t,h,'-k')

#P=0.01
D = K*E/P
lc = np.sqrt(D*T/np.pi)
t2 = t+7
h = h2 + (A/2*np.cos((2*np.pi*t2/T)-(x_mer[1]/lc)))* np.exp(-x_mer[1]/lc)
ax[0,1].plot(t,h,'-k')

#P=0.05
D = K*E/P
lc = np.sqrt(D*T/np.pi)
t3 = t+11
h = h3 + (A/2*np.cos((2*np.pi*t3/T)-(x_mer[2]/lc)))* np.exp(-x_mer[2]/lc)
ax[1,0].plot(t,h,'-k')

#P=0.05
D =K*E/P
lc = np.sqrt(D*T/np.pi)
t4 = t+11
h = h4 + (A/2*np.cos((2*np.pi*t4/T)-(x_mer[3]/lc)))* np.exp(-x_mer[3]/lc)
ax[1,1].plot(t,h,'-k')


ax[0,0].legend()
ax[0,1].legend()
ax[1,0].legend()
ax[1,1].legend()





