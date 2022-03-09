# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 14:22:05 2022

@author: ronan
"""

def calib_dichotomy(self, ident='modflow', type_river='streams', calib=True, climatic=8e-4, 
                    lay_number=1, thick=50, bottom=None, thick_exp=1., 
                    first=1, last=10000, gap=1, porosity=0.01, sea_level=None, cond_decay=0.):
    """
    AG: Destiné à disparaitre
    
    :meta private:
    """
    self.diff = last - first
    half = (first + last) / 2
    self.gap = gap
    
    self.df = pd.DataFrame()
    
    compt = 0
    while (self.diff > ((gap/100) * half)):
        half = (first + last) / 2
        hyd_cond = half * climatic
        
        ident = str('dic')+'-'+str(type_river)+'-'+str(round(half,3))+'-'+str(round(climatic,3))+'-'+str(round(thick,3))
        
        model = modflow.Modflow(self.geographic, calib=calib, time_step='monthly',
                                lay_number=lay_number, thick=thick, thick_exp=thick_exp, bottom=bottom,
                                hyd_cond=hyd_cond, cond_decay=cond_decay, porosity=porosity,
                                climatic=climatic, sea_level=sea_level, 
                                model_name=ident, model_folder=self.simulations_folder, 
                                exe=self.modflow_path +'/bin/mfnwt.exe')
        model.pre_processing()
        model.processing()
        model.post_processing()
        
        dicot = calib_dichotomy.Dichotomy(self.geographic, 
                                          type_river=type_river,
                                          hydrology_stable=os.path.join(self.stable_folder, 'hydrology'), 
                                          simulations_folder=os.path.join(self.simulations_folder, ident))
        mean_obs_to_sim, mean_sim_to_obs, condition = dicot.mean_distances()
        
        if condition > 1:
            first = half
        else:
            last = half
            
        self.diff = last - first
        
        print('==> Simulation : '+str(compt))            
        print('    Ecart = '+str(round(self.diff,2)))
        print('    K/R = '+str(round(half, 2)))
        print('    Condition = '+str(condition))
        print('    Gap = '+str(round((gap/100) * half, 2)))
        
        self.df.loc[compt,'KR'] = round(half, 4)
        self.df.loc[compt,'K'] = round(hyd_cond, 4)
        self.df.loc[compt,'Sflow'] = round(mean_sim_to_obs, 4)
        self.df.loc[compt,'Oflow'] = round(mean_obs_to_sim, 4)
        self.df.loc[compt,'Cond'] = round(condition, 4)    
        
        compt += 1
    
    self.df.to_csv(os.path.join(self.simulations_folder, '_dichotomy_'+type_river+'.csv'), sep=';', index=True)