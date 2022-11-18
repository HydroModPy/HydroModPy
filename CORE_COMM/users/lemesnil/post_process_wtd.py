# -*- coding: utf-8 -*-
"""
Created on Tue Nov 15 10:56:21 2022

@author: Martin Le Mesnil
"""

#%% Paths

watershed_name = 'Saint-Germain-sur-Ay'
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
sim_name = '20202100_MPICCLRCP85_15112022190253'

out_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% Watertable depth processing
import os
import matplotlib.pyplot as plt
import numpy as np

path = os.path.join(simulations_folder, sim_name, '_watershed', 'watertable_depth.npy')
wt_depth = np.load(path, allow_pickle=True).item()

for t in range(len(wt_depth)):
    wt_depth[t][wt_depth[t]==-9999] = np.nan


mapp = plt.imshow(wt_depth[10000])
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.show()

south = len(wt_depth[0]) #75m
east = len(wt_depth[0][0]) #75m   
duration = len(wt_depth) #1d

matrix_wtd = np.ones((south,east,duration))*np.nan
for t in range(duration):
    matrix_wtd[:,:,t] = wt_depth[t]

#%% Spatial indicators 2020-2100

rast_min = np.amin(matrix_wtd,2)
rast_max = np.amax(matrix_wtd,2)
rast_mean = np.mean(matrix_wtd,2)

rast_f30 = np.ones((south,east))*np.nan
rast_f3 = np.ones((south,east))*np.nan
for i in range(south):
    for j in range(east):
        c30 = c3 = 0
        for t in range(duration):
            if matrix_wtd[i,j,t] <= 0.3:
                c30 += 1
            if matrix_wtd[i,j,t] <= 0.03:
                c3 += 1
        rast_f30[i,j] = c30/duration*100
        rast_f3[i,j] = c3/duration*100


plt.figure(dpi=300)
mapp = plt.imshow(rast_f30)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm ')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm ')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth')
plt.show()


#%% Spatial indicators 2030 (2027-2033)
import datetime

days_2030 =  datetime.datetime(2033, 12, 31) - datetime.datetime(2027, 1, 1)
n_days_2030 = days_2030.days
matrix_wtd_2030 = np.ones((south,east,n_days_2030))*np.nan

start_2030 = datetime.datetime(2027, 1, 1) - datetime.datetime(2020, 1, 1)
idx_start_2030 = start_2030.days
idx_2030 = []
for t in range(n_days_2030):
    idx_2030.append(idx_start_2030+t)

i=0
for t in idx_2030:
    matrix_wtd_2030[:,:,i] = matrix_wtd[:,:,t]
    i += 1

rast_min_2030 = np.amin(matrix_wtd_2030,2)
rast_max_2030 = np.amax(matrix_wtd_2030,2)
rast_mean_2030 = np.mean(matrix_wtd_2030,2)

rast_f250_2030 = np.ones((south,east))*np.nan
rast_f50_2030 = np.ones((south,east))*np.nan
rast_f30_2030 = np.ones((south,east))*np.nan
rast_f3_2030 = np.ones((south,east))*np.nan

for i in range(south):
    for j in range(east):
        c250 = 0
        c50 = 0
        c30 = 0
        c3 = 0
        for t in range(n_days_2030):
            if matrix_wtd_2030[i,j,t] <= 0.03:
                c250 += 1
                c50 += 1
                c30 += 1
                c3 += 1
            elif matrix_wtd_2030[i,j,t] <= 0.3:
                c250 += 1
                c50 += 1
                c30 += 1
            elif matrix_wtd_2030[i,j,t] <= 0.5:
                c250 += 1
                c50 += 1
            elif matrix_wtd_2030[i,j,t] <= 2.5:
                c250 += 1
            
        rast_f250_2030[i,j] = c250/n_days_2030*100
        rast_f50_2030[i,j] = c50/n_days_2030*100
        rast_f30_2030[i,j] = c30/n_days_2030*100
        rast_f3_2030[i,j] = c3/n_days_2030*100


plt.figure(dpi=300)
mapp = plt.imshow(rast_f250_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2030)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth (2030 horizon)')
plt.show()


#%% Spatial indicators 2050 (2047-2053)
import datetime

days_2050 =  datetime.datetime(2053, 12, 31) - datetime.datetime(2047, 1, 1)
n_days_2050 = days_2050.days
matrix_wtd_2050 = np.ones((south,east,n_days_2050))*np.nan

start_2050 = datetime.datetime(2047, 1, 1) - datetime.datetime(2020, 1, 1)
idx_start_2050 = start_2050.days
idx_2050 = []
for t in range(n_days_2050):
    idx_2050.append(idx_start_2050+t)

i=0
for t in idx_2050:
    matrix_wtd_2050[:,:,i] = matrix_wtd[:,:,t]
    i += 1

rast_min_2050 = np.amin(matrix_wtd_2050,2)
rast_max_2050 = np.amax(matrix_wtd_2050,2)
rast_mean_2050 = np.mean(matrix_wtd_2050,2)

rast_f250_2050 = np.ones((south,east))*np.nan
rast_f50_2050 = np.ones((south,east))*np.nan
rast_f30_2050 = np.ones((south,east))*np.nan
rast_f3_2050 = np.ones((south,east))*np.nan

for i in range(south):
    for j in range(east):
        c250 = 0
        c50 = 0
        c30 = 0
        c3 = 0
        for t in range(n_days_2050):
            if matrix_wtd_2050[i,j,t] <= 0.03:
                c250 += 1
                c50 += 1
                c30 += 1
                c3 += 1
            elif matrix_wtd_2050[i,j,t] <= 0.3:
                c250 += 1
                c50 += 1
                c30 += 1
            elif matrix_wtd_2050[i,j,t] <= 0.5:
                c250 += 1
                c50 += 1
            elif matrix_wtd_2050[i,j,t] <= 2.5:
                c250 += 1
            
        rast_f250_2050[i,j] = c250/n_days_2050*100
        rast_f50_2050[i,j] = c50/n_days_2050*100
        rast_f30_2050[i,j] = c30/n_days_2050*100
        rast_f3_2050[i,j] = c3/n_days_2050*100


plt.figure(dpi=300)
mapp = plt.imshow(rast_f250_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2050)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth (2050 horizon)')
plt.show()


#%% Spatial indicators 2100 (2094-2099)
import datetime

days_2100 =  datetime.datetime(2099, 12, 31) - datetime.datetime(2094, 1, 1)
n_days_2100 = days_2100.days
matrix_wtd_2100 = np.ones((south,east,n_days_2100))*np.nan

start_2100 = datetime.datetime(2094, 1, 1) - datetime.datetime(2020, 1, 1)
idx_start_2100 = start_2100.days
idx_2100 = []
for t in range(n_days_2100):
    idx_2100.append(idx_start_2100+t)

i=0
for t in idx_2100:
    matrix_wtd_2100[:,:,i] = matrix_wtd[:,:,t]
    i += 1

rast_min_2100 = np.amin(matrix_wtd_2100,2)
rast_max_2100 = np.amax(matrix_wtd_2100,2)
rast_mean_2100 = np.mean(matrix_wtd_2100,2)

rast_f250_2100 = np.ones((south,east))*np.nan
rast_f50_2100 = np.ones((south,east))*np.nan
rast_f30_2100 = np.ones((south,east))*np.nan
rast_f3_2100 = np.ones((south,east))*np.nan

for i in range(south):
    for j in range(east):
        c250 = 0
        c50 = 0
        c30 = 0
        c3 = 0
        for t in range(n_days_2100):
            if matrix_wtd_2100[i,j,t] <= 0.03:
                c250 += 1
                c50 += 1
                c30 += 1
                c3 += 1
            elif matrix_wtd_2100[i,j,t] <= 0.3:
                c250 += 1
                c50 += 1
                c30 += 1
            elif matrix_wtd_2100[i,j,t] <= 0.5:
                c250 += 1
                c50 += 1
            elif matrix_wtd_2100[i,j,t] <= 2.5:
                c250 += 1
            
        rast_f250_2100[i,j] = c250/n_days_2100*100
        rast_f50_2100[i,j] = c50/n_days_2100*100
        rast_f30_2100[i,j] = c30/n_days_2100*100
        rast_f3_2100[i,j] = c3/n_days_2100*100


plt.figure(dpi=300)
mapp = plt.imshow(rast_f250_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2100)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth (2100 horizon)')
plt.show()


#%% Array to tiff

import rasterio as rio
import os

dem_path = out_path+'/'+watershed_name+'/'+'results_stable/geographic/watershed_dem.tif'
tif_dir_path = 'C:/Users/Martin Le Mesnil/Travail/Modélisation/' + sim_name + '/rasters/'
data_nodata_val = -9999

data_to_tif_list = [rast_f250_2030, rast_f50_2030, rast_f30_2030, rast_f3_2030,
                    rast_min_2030, rast_max_2030, rast_mean_2030,
                    rast_f250_2050, rast_f50_2050, rast_f30_2050, rast_f3_2050,
                    rast_min_2050, rast_max_2050, rast_mean_2050,
                    rast_f250_2100, rast_f50_2100, rast_f30_2100, rast_f3_2100,
                    rast_min_2100, rast_max_2100, rast_mean_2100]

data_to_tif_str_list = ['rast_f250_2030', 'rast_f50_2030', 'rast_f30_2030', 'rast_f3_2030',
                        'rast_min_2030', 'rast_max_2030', 'rast_mean_2030',
                        'rast_f250_2050', 'rast_f50_2050', 'rast_f30_2050', 'rast_f3_2050',
                        'rast_min_2050', 'rast_max_2050', 'rast_mean_2050',
                        'rast_f250_2100', 'rast_f50_2100', 'rast_f30_2100', 'rast_f3_2100',
                        'rast_min_2100', 'rast_max_2100', 'rast_mean_2100']

i=0
for data_to_tif in data_to_tif_list:
    with rio.open(dem_path) as src:
        ras_data = src.read()
        ras_nodata = src.nodatavals
        ras_dtype = src.dtypes
        ras_meta = src.profile
        
    # Type of data
    data_dtype = data_to_tif.dtype
    # Change base dem from data
    ras_meta['dtype'] = data_dtype
    ras_meta['nodata'] = data_nodata_val
    
    # Create new data raster with base dem size
    tif_name = data_to_tif_str_list[i]
    new_tif_path = tif_dir_path + tif_name + '.tiff'
    if not os.path.exists(tif_dir_path):
        os.makedirs(tif_dir_path)
    with rio.open(new_tif_path, 'w', **ras_meta) as dst:
        dst.write(data_to_tif, 1)
    i+=1

