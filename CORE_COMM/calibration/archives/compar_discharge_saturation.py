# -*- coding: utf-8 -*-
"""
Created on Fri Jan 21 15:13:17 2022

@author: ronan
"""

#%% Compare obs
"""
    def compar_discharge_chronic(self):
                
        ### OBSERVED DISCHARGE
        
        chronic_path = os.path.join(self.hydrology_path, 'chronics')        
        obs_files = os.listdir(chronic_path)
        
        if (self.outlet_type=='hydrometric'):
            # Waterhed
            basin_area = tif_features.basin_area(self.dem_clip, self.dem_clip, '==', -99999, self.resolution)
            obs_file = [x for x in obs_files if x.split('_')[3] == self.watershed_name]
            obs_file = obs_file[0]
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';')
        
        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'hydrometric']
            for mask_name in mask_list:
                x=2
                subasin_folder = os.path.join(self.subbasins_folder, mask_name)
                sub = gdal.Open(os.path.join(subasin_folder,'subbasin.tif'))
                dem_mask = sub.GetRasterBand(1).ReadAsArray()
                basin_area = tif_features.basin_area(dem_mask, dem_mask, '!=', 1, self.resolution)
                station_name = mask_name.split('_')[3]
                for x in obs_files:
                    try:
                        cond_split = x.split('_')[2]
                    except:
                        continue
                    if cond_split == station_name:
                        obs_file = x
                # obs_file = obs_file[0]
        
        print(obs_file)
        obs_path = os.path.join(chronic_path, obs_file)
        obs_data = pd.read_csv(obs_path, names = ['year','month','day','disch'], 
                               sep='\s+', header = None, parse_dates=True) # sep='\s+'
        time = pd.to_datetime(obs_data[['year','month','day']]) # create datetime
        time = time.sort_values()
        obs = pd.Series(obs_data['disch']) # create series discharge
        obs = obs*24*60*60 #m3/j
        obs_data = pd.DataFrame({'date':time, 'disch':obs}) # dataframe
        obs_data['disch_norm'] = obs_data['disch'] / (60 * 1000000) # m/j ==> area to add
        obs_data = obs_data.set_index('date')
        
        if self.time_step=='monthly':
            obs_data = obs_data.resample('M').sum()
        
        obs = np.array(obs_data['disch_norm'].values)
        
        ### SIMULATED DISCHARGE  
        
        if (self.outlet_type=='hydrometric'):
            # Waterhed
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
            sim_data = sim_data.set_index('date')
            sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
            
            sim = np.array(sim_data['outflow_drain'].values)
            
            df_stats = pd.DataFrame(columns=['RMSE', 'nRMSE', 'NSE', 'NSElog', 'BAL', 'MARE', 'KGE'])
            try:
                list_stats = serie_transf.efficiency_criteria(sim, obs)
            except:
                print('list_stats = None')            
            df_stats = df.append(list_stats)
            df_stats.to_csv(os.path.join(self.save_file, '_efficiency_criteria.csv'), sep=';')
            
        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'hydrometric']
            for mask_name in mask_list:
                masked_file = os.path.join(self.masked_folder, mask_name)
                sim_path = os.path.join(masked_file, '_simulated_chronics.csv')
                sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
                sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
                sim_data = sim_data.set_index('date')
                
                sim = np.array(sim_data['outflow_drain'].values)
                
                df_stats = pd.DataFrame(columns=['RMSE', 'nRMSE', 'NSE', 'NSElog', 'BAL', 'MARE', 'KGE'])
                try:
                    list_stats = serie_transf.efficiency_criteria(sim, obs)
                except:
                    print('list_stats = None')
                    list_stats = None
                df_stats.loc[len(df_stats)] = list_stats
                df_stats.to_csv(os.path.join(masked_file, '_efficiency_criteria.csv'), sep=';')

                return obs_data, sim_data, df_stats, mask_name
                
    def compar_saturation_chronic(self):
        
        obs_data = np.nan
        df_stats = np.nan
        
        ### SIMULATED SATURATION
        
        if (self.outlet_type=='onde'):
            # Waterhed
            sim_path = os.path.join(self.save_file, '_simulated_chronics.csv')
            sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
            sim_data = sim_data.set_index('date')
            sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
            
            sim = np.array(sim_data['seepage_areas'].values)

        if self.mask==True:
            mask_list = os.listdir(self.subbasins_folder)
            mask_list = [x for x in mask_list if x.split('_')[1] == 'onde']
            for mask_name in mask_list:
                masked_file = os.path.join(self.masked_folder, mask_name)
                sim_path = os.path.join(masked_file, '_simulated_chronics.csv')
                sim_data = pd.read_csv(sim_path, sep=';', parse_dates=True)
                sim_data['date'] = pd.to_datetime(sim_data['date'] , format='%Y-%m-%d %H:%M:%S')
                sim_data = sim_data.set_index('date')
                
                sim = np.array(sim_data['seepage_areas'].values)
                
                fig, ax = plt.subplots(1,1, figsize=(5,3))
                ax.plot(sim_data['seepage_areas'], color='red')
                ax.axhline(y=3, color='k', ls='--')
                ax.axhline(y=8, color='grey', ls='--')
                ax.set_ylim(-0.5, 25)
                ax.set_xlabel('Date')
                ax.set_ylabel('Saturation [%]')
                # ax.set_title(mask_name+'\n'+self.model_name)
                ax.set_title(mask_name.split('_')[3])
                ax.grid(True)
                yearsFmt = DateFormatter('%Y')
                ax.xaxis.set_major_formatter(yearsFmt)
                
            return obs_data, sim_data, df_stats, mask_name
"""