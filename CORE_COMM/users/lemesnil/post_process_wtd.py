# -*- coding: utf-8 -*-
"""
Created on Tue Nov 15 10:56:21 2022

@author: Martin Le Mesnil
"""

#%% Paths

watershed_name = 'Saint-Germain-sur-Ay'
# Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
sim_name = '20202100_MPICCLRCP85_19012023173740'
# 20202100_MPICCLRCP85_08122022095605 20102014_REA_14122022115903
out_path = 'C:/Users/Martin Le Mesnil/Travail/HydroModPy/output2/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

col_map = 'jet'

site_dict = {'Saint-Germain-sur-Ay' : 'SGA',
             'Agon-Coutainville' : 'AGC',
             'Barneville-Carteret' : 'BNV',
             'Baie-du-Cotentin' : 'BDC',
             'Caen-la-Mer' : 'CLM'}

#%% Watertable depth processing
import os
import matplotlib.pyplot as plt
import numpy as np

path = os.path.join(simulations_folder, sim_name, '_watershed', 'watertable_depth.npy')
wt_depth = np.load(path, allow_pickle=True).item()

for t in range(len(wt_depth)):
    wt_depth[t][wt_depth[t]==-9999] = np.nan
    wt_depth[t][wt_depth[t]<0] = 0

plt.figure(dpi=300)
mapp = plt.imshow(wt_depth[2500], cmap = col_map)
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


#%% Spatial indicators function

def spatial_indic_surfex(yr_min, yr_max, start_yr, save_fig=False, save_rast=False):
    import datetime
    
    days_per =  datetime.datetime(yr_max, 12, 31) - datetime.datetime(yr_min, 1, 1)
    n_days_per = days_per.days
    matrix_wtd_per = np.ones((south,east,n_days_per))*np.nan
    
    start_per = datetime.datetime(yr_min, 1, 1) - datetime.datetime(start_yr, 1, 1)
    idx_start_per = start_per.days
    idx_per = []
    for t in range(n_days_per):
        idx_per.append(idx_start_per + t)
    
    i=0
    for t in idx_per:
        matrix_wtd_per[:,:,i] = matrix_wtd[:,:,t]
        i += 1
    
    rast_min = np.amin(matrix_wtd_per,2)
    rast_max = np.amax(matrix_wtd_per,2)
    rast_mean = np.mean(matrix_wtd_per,2)
    
    rast_f250 = np.ones((south,east))*np.nan
    rast_f50 = np.ones((south,east))*np.nan
    rast_f30 = np.ones((south,east))*np.nan
    rast_f3 = np.ones((south,east))*np.nan
    
    for i in range(south):
        for j in range(east):
            c250 = 0
            c50 = 0
            c30 = 0
            c3 = 0
            for t in range(n_days_per):
                if matrix_wtd_per[i,j,t] <= 0.03:
                    c250 += 1
                    c50 += 1
                    c30 += 1
                    c3 += 1
                elif matrix_wtd_per[i,j,t] <= 0.3:
                    c250 += 1
                    c50 += 1
                    c30 += 1
                elif matrix_wtd_per[i,j,t] <= 0.5:
                    c250 += 1
                    c50 += 1
                elif matrix_wtd_per[i,j,t] <= 2.5:
                    c250 += 1
                
            rast_f250[i,j] = c250/n_days_per*100
            rast_f50[i,j] = c50/n_days_per*100
            rast_f30[i,j] = c30/n_days_per*100
            rast_f3[i,j] = c3/n_days_per*100
    
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_f250, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Occurency (%)")
    plt.axis('off')
    plt.title('Watertable depth < 2.5 m (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_f50, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Occurency (%)")
    plt.axis('off')
    plt.title('Watertable depth < 50 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_f30, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Occurency (%)")
    plt.axis('off')
    plt.title('Watertable depth < 30 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_f3, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Occurency (%)")
    plt.axis('off')
    plt.title('Watertable depth < 3 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_min, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Watertable depth (m)")
    plt.axis('off')
    plt.title('Minimum watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_max, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Watertable depth (m)")
    plt.axis('off')
    plt.title('Maximum watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()
    
    plt.figure(dpi=300)
    mapp = plt.imshow(rast_mean, cmap = col_map)
    cbar = plt.colorbar(mapp)
    cbar.set_label("Watertable depth (m)")
    plt.axis('off')
    plt.title('Mean watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
    plt.show()

    if save_fig:
        print('fig enabled')
    
    if save_rast:
        import rasterio as rio
        import os

        watershed_name = 'Saint-Germain-sur-Ay'
        # Caen-la-Mer Baie-du-Cotentin Barneville-Carteret Agon-Coutainville Saint-Germain-sur-Ay
        sim_name = '20102014_REA_14122022115903'
        # 20202100_MPICCLRCP85_08122022095605 

        dem_path = out_path+'/'+watershed_name+'/'+'results_stable/geographic/watershed_dem.tif'
        tif_dir_path = 'C:/Users/Martin Le Mesnil/Travail/Modélisation/' + watershed_name + '/' + sim_name + '/rasters_img_2014/'
        data_nodata_val = -9999

        data_to_tif_list = [rast_f250, rast_f50, rast_f30, rast_f3,
                            rast_min, rast_max, rast_mean]

        data_to_tif_str_list = ['rast_f250', 'rast_f50', 'rast_f30', 'rast_f3',
                                'rast_min', 'rast_max', 'rast_mean']

        i=0
        for data_to_tif in data_to_tif_list:
            with rio.open(dem_path) as src:
                # ras_data = src.read()
                # ras_nodata = src.nodatavals
                # ras_dtype = src.dtypes
                ras_meta = src.profile
                
            # Type of data
            data_dtype = data_to_tif.dtype
            # Change base dem from data
            ras_meta['dtype'] = data_dtype
            ras_meta['nodata'] = data_nodata_val
            
            # Create new data raster with base dem size
            tif_name = data_to_tif_str_list[i] + '_' + site_dict[watershed_name] + '_' + str(yr_min) + '-' + str(yr_max)
            new_tif_path = tif_dir_path + tif_name + '.tiff'
            if not os.path.exists(tif_dir_path):
                os.makedirs(tif_dir_path)
            with rio.open(new_tif_path, 'w', **ras_meta) as dst:
                dst.write(data_to_tif, 1)
            i+=1

#%% Print indicators

spatial_indic_surfex(1965, 1975, 1965)
spatial_indic_surfex(2010, 2014, 1965, save_rast=True)


#%% Spatial indicators 1970 (1965-1975)
import datetime

days_1970 =  datetime.datetime(1975, 12, 31) - datetime.datetime(1965, 1, 1)
n_days_1970 = days_1970.days
matrix_wtd_1970 = np.ones((south,east,n_days_1970))*np.nan

start_1970 = datetime.datetime(1965, 1, 1) - datetime.datetime(1965, 1, 1)
idx_start_1970 = start_1970.days
idx_1970 = []
for t in range(n_days_1970):
    idx_1970.append(idx_start_1970+t)

i=0
for t in idx_1970:
    matrix_wtd_1970[:,:,i] = matrix_wtd[:,:,t]
    i += 1

rast_min_1970 = np.amin(matrix_wtd_1970,2)
rast_max_1970 = np.amax(matrix_wtd_1970,2)
rast_mean_1970 = np.mean(matrix_wtd_1970,2)

rast_f250_1970 = np.ones((south,east))*np.nan
rast_f50_1970 = np.ones((south,east))*np.nan
rast_f30_1970 = np.ones((south,east))*np.nan
rast_f3_1970 = np.ones((south,east))*np.nan

for i in range(south):
    for j in range(east):
        c250 = 0
        c50 = 0
        c30 = 0
        c3 = 0
        for t in range(n_days_1970):
            if matrix_wtd_1970[i,j,t] <= 0.03:
                c250 += 1
                c50 += 1
                c30 += 1
                c3 += 1
            elif matrix_wtd_1970[i,j,t] <= 0.3:
                c250 += 1
                c50 += 1
                c30 += 1
            elif matrix_wtd_1970[i,j,t] <= 0.5:
                c250 += 1
                c50 += 1
            elif matrix_wtd_1970[i,j,t] <= 2.5:
                c250 += 1
            
        rast_f250_1970[i,j] = c250/n_days_1970*100
        rast_f50_1970[i,j] = c50/n_days_1970*100
        rast_f30_1970[i,j] = c30/n_days_1970*100
        rast_f3_1970[i,j] = c3/n_days_1970*100


plt.figure(dpi=300)
mapp = plt.imshow(rast_f250_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (1970 era)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_1970, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth (1970 era)')
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
mapp = plt.imshow(rast_f250_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2030, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2030 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2030, cmap = col_map)
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
mapp = plt.imshow(rast_f250_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2050, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2050 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2050, cmap = col_map)
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
mapp = plt.imshow(rast_f250_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 2.5 m (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f50_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 50 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f30_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 30 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_f3_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Occurency (%)")
plt.axis('off')
plt.title('Watertable depth < 3 cm (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_min_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Minimum watertable depth (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_max_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Maximum watertable depth (2100 horizon)')
plt.show()

plt.figure(dpi=300)
mapp = plt.imshow(rast_mean_2100, cmap = col_map)
cbar = plt.colorbar(mapp)
cbar.set_label("Watertable depth (m)")
plt.axis('off')
plt.title('Mean watertable depth (2100 horizon)')
plt.show()


#%% Array to tiff

import rasterio as rio
import os

dem_path = out_path+'/'+watershed_name+'/'+'results_stable/geographic/watershed_dem.tif'
tif_dir_path = 'C:/Users/Martin Le Mesnil/Travail/Modélisation/' + watershed_name + '/' + sim_name + '/rasters/'
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
    tif_name = data_to_tif_str_list[i] + '_' + site_dict[watershed_name]
    new_tif_path = tif_dir_path + tif_name + '.tiff'
    if not os.path.exists(tif_dir_path):
        os.makedirs(tif_dir_path)
    with rio.open(new_tif_path, 'w', **ras_meta) as dst:
        dst.write(data_to_tif, 1)
    i+=1

#%% Array to tiff 1970

import rasterio as rio
import os

dem_path = out_path+'/'+watershed_name+'/'+'results_stable/geographic/watershed_dem.tif'
tif_dir_path = 'C:/Users/Martin Le Mesnil/Travail/Modélisation/' + watershed_name + '/' + sim_name + '/rasters_img_1970/'
data_nodata_val = -9999

data_to_tif_list = [rast_f250_1970, rast_f50_1970, rast_f30_1970, rast_f3_1970,
                    rast_min_1970, rast_max_1970, rast_mean_1970]

data_to_tif_str_list = ['rast_f250_1970', 'rast_f50_1970', 'rast_f30_1970', 'rast_f3_1970',
                        'rast_min_1970', 'rast_max_1970', 'rast_mean_1970']

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


#%% Temporal indicators on selected area

def temp_indic(i_min, i_max, j_min, j_max, depth, yr_min, yr_max, site_str, addsmooth):
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    from scipy.ndimage import uniform_filter1d
    
    date_list = pd.date_range(str(yr_min)+'-01-01',str(yr_max-1)+'-12-31',freq='1D')
    freq_30_yr = []
    diy_30_yr = []

    for year in range(yr_min,yr_max):
        print(year)
        sum_30 = np.zeros((i_max-i_min+1,j_max-j_min+1))
        diy = 0
        for x in range(len(date_list)):
            if date_list[x].year == year:
                diy += 1
                for i in range(i_min,i_max+1):
                    for j in range(j_min,j_max+1):
                        if wt_depth[x+((yr_min-2020)*365)][i,j] <= depth:
                            sum_30[i-i_min,j-j_min] += 1
                if date_list[x].day == 31 & date_list[x].month == 12:
                    freq_30 = sum_30 / diy
                    freq_30_yr.append(np.nanmean(freq_30)*100)
                    diy_30_yr.append(np.nanmean(sum_30))
            elif date_list[x].year > year:
                break
    
    # f30_df = pd.DataFrame(freq_30_yr, index=pd.date_range('2020-01-01','2099-12-31',freq='1Y').year)            
    diy30_df = pd.DataFrame(diy_30_yr, index=pd.date_range(str(yr_min)+'-01-01',str(yr_max-1)+'-12-31',freq='1Y').year)            
    if addsmooth:
        diy30_df_smooth = diy30_df.copy()
        diy30_df_smooth.iloc[:,0] = uniform_filter1d(diy_30_yr, size=8)
    
    plt.figure(dpi=300)
    plt.plot(diy30_df)
    plt.plot(diy30_df_smooth)
    plt.title('Dépassement de la profondeur de nappe 30 cm - ' + site_str)
    plt.ylabel('Jours par an')
    if addsmooth:
        plt.legend(['Annuel','Lissé 8 ans'])
    plt.show()


temp_indic(55, 80, 19, 36, 0.3, 2020, 2100, 'Marais maritimes', addsmooth=True)
# temp_indic(99, 111, 28, 32, 0.03, 2033, 2100, 'SGA Plage', addsmooth=True)
# temp_indic(18, 33, 52, 63, 0.3, 2020, 2100, 'BSA Amont', addsmooth=True)



# #localization of peninsula

# for i in range(rast_f30_2030.shape[0]):
#     for j in range(rast_f30_2030.shape[1]):
#         if rast_f30_2030[i,j] == 60.28951486697965:
#             print('North: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 73.78716744913928:
#             print('South: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 23.435054773082943:
#             print('West: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 32.316118935837245:
#             print('East: ('+ str(i) + ', ' + str(j) + ')')
  
# for i in range(rast_f30_2030.shape[0]):
#     for j in range(rast_f30_2030.shape[1]):
#         # if rast_f30_2030[i,j] == 31.0641627543036:
#         #     print('NorthWest: ('+ str(i) + ', ' + str(j) + ')')
#         # if rast_f30_2030[i,j] == 15.101721439749607:
#         #     print('SouthWest: ('+ str(i) + ', ' + str(j) + ')')
#         # if rast_f30_2030[i,j] == 16.51017214397496:
#         #     print('SouthEast: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 10.015649452269171:
#             print('NorthEast: ('+ str(i) + ', ' + str(j) + ')')

# for i in range(rast_f30_2030.shape[0]):
#     for j in range(rast_f30_2030.shape[1]):
#         # if rast_f30_2030[i,j] == 8.020344287949923:
#         #     print('NorthWest: ('+ str(i) + ', ' + str(j) + ')')
#         # if rast_f30_2030[i,j] == 6.533646322378717:
#         #     print('SouthWest: ('+ str(i) + ', ' + str(j) + ')')
#         # if rast_f30_2030[i,j] == 3.482003129890454:
#         #     print('SouthEast: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 1.251956181533646:
#             print('NorthEast: ('+ str(i) + ', ' + str(j) + ')')

# for i in range(rast_f30_2030.shape[0]):
#     for j in range(rast_f30_2030.shape[1]):
#         # if rast_f30_2030[i,j] == 5.790297339593114:
#         #     print('West: ('+ str(i) + ', ' + str(j) + ')')
#         if rast_f30_2030[i,j] == 9.780907668231611:
#             print('East: ('+ str(i) + ', ' + str(j) + ')')

# temp_indic(185, 190, 169, 192, "Presqu'ile Sud")
# temp_indic(65, 74, 231, 242, "StAubin d'Arquenay")
# temp_indic(174, 176, 201, 202, "Presqu'île Nord", addsmooth=True)
# temp_indic(40, 40, 312, 317, "Merville-Franceville", addsmooth=True)
        
# temp_indic(227, 238, 126, 137, 'Fleury s/ Orne', addsmooth=True)          
            

