# -*- coding: utf-8 -*-
"""
Created on Mon Jan 23 18:33:37 2023

@author: Martin Le Mesnil
"""

#%% Spatial indicators function

def wtd_spat_indic(BV, sim_name, yr_min, yr_max, depth_list, figures = False, save_rast = False):
    import os
    import datetime
    import numpy as np
    import matplotlib.pyplot as plt
    from os.path import dirname

    wtd_in_path = os.path.join(BV.simulations_folder, sim_name, '_watershed/watertable_depth.npy')
    wt_depth = np.load(wtd_in_path, allow_pickle=True).item()

    for t in range(len(wt_depth)):
        wt_depth[t][wt_depth[t]==-9999] = np.nan
        wt_depth[t][wt_depth[t]<0] = 0
    
    south = len(wt_depth[0]) #75m
    east = len(wt_depth[0][0]) #75m   
    duration = len(wt_depth) #1d

    matrix_wtd = np.ones((south,east,duration), dtype='uint8')*np.nan
    for t in range(duration):
        matrix_wtd[:,:,t] = wt_depth[t]

    days_per =  datetime.datetime(yr_max, 12, 31) - datetime.datetime(yr_min, 1, 1)
    n_days_per = days_per.days
    matrix_wtd_per = np.ones((south,east,n_days_per), dtype='uint8')*np.nan
    
    start_yr = int(sim_name[0:4])
    start_per = datetime.datetime(yr_min, 1, 1) - datetime.datetime(start_yr, 1, 1)
    idx_start_per = start_per.days
    idx_per = []
    for t in range(n_days_per):
        idx_per.append(idx_start_per + t)
    
    i=0
    for t in idx_per:
        matrix_wtd_per[:,:,i] = matrix_wtd[:,:,t]
        i += 1
    
    rast_f_list = []
    depth_list_pos = []
    for d in depth_list:
        if d == -1:
            rast_min = np.amin(matrix_wtd_per,2)
            rast_max = np.amax(matrix_wtd_per,2)
            rast_mean = np.mean(matrix_wtd_per,2)
        else:
            rast_f = np.ones((south,east))*np.nan
            for i in range(south):
                for j in range(east):
                    c = 0
                    for t in range(n_days_per):
                        if matrix_wtd_per[i,j,t] <= d:
                            c += 1
                    rast_f[i,j] = c/n_days_per*100
            rast_f_list.append(rast_f)
            depth_list_pos.append(d)

    # rast_f250 = np.ones((south,east))*np.nan
    # rast_f50 = np.ones((south,east))*np.nan
    # rast_f30 = np.ones((south,east))*np.nan
    # rast_f3 = np.ones((south,east))*np.nan
    
    # for i in range(south):
    #     for j in range(east):
    #         c250 = 0
    #         c50 = 0
    #         c30 = 0
    #         c3 = 0
    #         for t in range(n_days_per):
    #             if matrix_wtd_per[i,j,t] <= 0.03:
    #                 c250 += 1
    #                 c50 += 1
    #                 c30 += 1
    #                 c3 += 1
    #             elif matrix_wtd_per[i,j,t] <= 0.3:
    #                 c250 += 1
    #                 c50 += 1
    #                 c30 += 1
    #             elif matrix_wtd_per[i,j,t] <= 0.5:
    #                 c250 += 1
    #                 c50 += 1
    #             elif matrix_wtd_per[i,j,t] <= 2.5:
    #                 c250 += 1
                
    #         rast_f250[i,j] = c250/n_days_per*100
    #         rast_f50[i,j] = c50/n_days_per*100
    #         rast_f30[i,j] = c30/n_days_per*100
    #         rast_f3[i,j] = c3/n_days_per*100
    
    if figures != False:
        col_map = 'jet'
        fig_dir = os.path.join(dirname(BV.simulations_folder), 'figures', sim_name)
        os.makedirs(fig_dir, exist_ok=True)
        
        if -1 in depth_list:
            
            plt.figure(dpi=300)
            mapp = plt.imshow(rast_min, cmap = col_map)
            cbar = plt.colorbar(mapp)
            cbar.set_label("Watertable depth (m)")
            plt.axis('off')
            plt.title('Minimum watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
            plt.text(0.1,0.9,sim_name.split(sep='_')[1])
            if figures == 'save':
                plt.savefig(os.path.join(fig_dir, 'min_' + str(yr_min) + '_' + str(yr_max)))
            plt.show()
            
            plt.figure(dpi=300)
            mapp = plt.imshow(rast_max, cmap = col_map)
            cbar = plt.colorbar(mapp)
            cbar.set_label("Watertable depth (m)")
            plt.axis('off')
            plt.title('Maximum watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
            plt.text(0.1,0.9,sim_name.split(sep='_')[1])
            if figures == 'save':
                plt.savefig(os.path.join(fig_dir, 'max_' + str(yr_min) + '_' + str(yr_max)))
            plt.show()
            
            plt.figure(dpi=300)
            mapp = plt.imshow(rast_mean, cmap = col_map)
            cbar = plt.colorbar(mapp)
            cbar.set_label("Watertable depth (m)")
            plt.axis('off')
            plt.title('Mean watertable depth (' + str(yr_min) + '-' + str(yr_max) + ')')
            plt.text(0.1,0.9,sim_name.split(sep='_')[1])
            if figures == 'save':
                plt.savefig(os.path.join(fig_dir, 'mean_' + str(yr_min) + '_' + str(yr_max)))
            plt.show()

        r = -1
        for rast in rast_f_list:
            r += 1
            plt.figure(dpi=300)
            mapp = plt.imshow(rast, cmap = col_map)
            cbar = plt.colorbar(mapp)
            cbar.set_label("Occurency (%)")
            plt.axis('off')
            depth_str = str(depth_list_pos[r])
            plt.title('Watertable depth < ' + depth_str + ' m (' + str(yr_min) + '-' + str(yr_max) + ')')
            plt.text(0.1,0.9,sim_name.split(sep='_')[1])
            if figures == 'save':
                depth_str_cm = str(int(depth_list_pos[r]*100))
                plt.savefig(os.path.join(fig_dir, 'f' + depth_str_cm + '_' + str(yr_min) + '_' + str(yr_max)))
            plt.show()


        
    #     plt.figure(dpi=300)
    #     mapp = plt.imshow(rast_f250, cmap = col_map)
    #     cbar = plt.colorbar(mapp)
    #     cbar.set_label("Occurency (%)")
    #     plt.axis('off')
    #     plt.title('Watertable depth < 2.5 m (' + str(yr_min) + '-' + str(yr_max) + ')')
    #     plt.text(0.1,0.9,sim_name.split(sep='_')[1])
    #     if figures == 'save':
    #         plt.savefig(os.path.join(fig_dir, 'f250_' + str(yr_min) + '_' + str(yr_max)))
    #     plt.show()

    #     plt.figure(dpi=300)
    #     mapp = plt.imshow(rast_f50, cmap = col_map)
    #     cbar = plt.colorbar(mapp)
    #     cbar.set_label("Occurency (%)")
    #     plt.axis('off')
    #     plt.title('Watertable depth < 50 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    #     plt.text(0.1,0.9,sim_name.split(sep='_')[1])
    #     if figures == 'save':
    #         plt.savefig(os.path.join(fig_dir, 'f50_' + str(yr_min) + '_' + str(yr_max)))
    #     plt.show()
        
    #     plt.figure(dpi=300)
    #     mapp = plt.imshow(rast_f30, cmap = col_map)
    #     cbar = plt.colorbar(mapp)
    #     cbar.set_label("Occurency (%)")
    #     plt.axis('off')
    #     plt.title('Watertable depth < 30 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    #     plt.text(0.1,0.9,sim_name.split(sep='_')[1])
    #     if figures == 'save':
    #         plt.savefig(os.path.join(fig_dir, 'f30_' + str(yr_min) + '_' + str(yr_max)))
    #     plt.show()
        
    #     plt.figure(dpi=300)
    #     mapp = plt.imshow(rast_f3, cmap = col_map)
    #     cbar = plt.colorbar(mapp)
    #     cbar.set_label("Occurency (%)")
    #     plt.axis('off')
    #     plt.title('Watertable depth < 3 cm (' + str(yr_min) + '-' + str(yr_max) + ')')
    #     plt.text(0.1,0.9,sim_name.split(sep='_')[1])
    #     if figures == 'save':
    #         plt.savefig(os.path.join(fig_dir, 'f3_' + str(yr_min) + '_' + str(yr_max)))
    #     plt.show()
        
    
    # if figures == 'save':
    #     pass
    
    if save_rast != False:
        import rasterio as rio
        import os

        tif_dir_path = save_rast
        data_nodata_val = -9999
        
        data_to_tif_list = rast_f_list
        data_to_tif_str_list = []
        for d in depth_list:
            if d != -1:
                depth_str_cm = str(int(d*100))
                rast_name = 'rast_f' + depth_str_cm
                data_to_tif_str_list.append(rast_name)
            elif d == -1:
                data_to_tif_list.append(rast_min)
                data_to_tif_list.append(rast_max)
                data_to_tif_list.append(rast_mean)
        if -1 in depth_list:
            data_to_tif_str_list.append('rast_min')
            data_to_tif_str_list.append('rast_max')
            data_to_tif_str_list.append('rast_mean')

                
        # data_to_tif_list = [rast_f250, rast_f50, rast_f30, rast_f3,
        #                     rast_min, rast_max, rast_mean]
        # data_to_tif_str_list = ['rast_f250', 'rast_f50', 'rast_f30', 'rast_f3',
        #                         'rast_min', 'rast_max', 'rast_mean']
        
        dem_path = os.path.join(BV.watershed_folder, 'results_stable/geographic/watershed_dem.tif')
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
            site_dict = {'Saint-Germain-sur-Ay' : 'SGA',
                         'Agon-Coutainville' : 'AGC',
                         'Barneville-Carteret' : 'BNV',
                         'Baie-du-Cotentin' : 'BDC',
                         'Caen-la-Mer' : 'CLM'}
            tif_name = data_to_tif_str_list[i] + '_' + site_dict[BV.watershed_name] + '_' + str(yr_min) + '-' + str(yr_max)
            new_tif_path = os.path.join(tif_dir_path, tif_name + '.tiff')
            if not os.path.exists(tif_dir_path):
                os.makedirs(tif_dir_path)
            with rio.open(new_tif_path, 'w', **ras_meta) as dst:
                dst.write(data_to_tif, 1)
            i+=1
