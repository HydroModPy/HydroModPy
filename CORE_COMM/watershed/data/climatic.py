# coding:utf-8


import geopandas as gpd
import pandas as pd
import os 
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

from data import climatic_display

class Climatic:
    
    def __init__(self, out_path, surfex_path, watershed_shp):
        """

        Parameters
        ----------
        out_path : TYPE
            DESCRIPTION.
        surfex_path : TYPE
            DESCRIPTION.
        watershed_shp : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        """
        

        data_folder = os.path.join(out_path, 'results_stable/climatic/')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.figure_folder = os.path.join(out_path, 'results_stable/_figures/climatic/')

        if not os.path.exists(self.figure_folder):
                os.makedirs(self.figure_folder)
        print('Extraction des données climatiques')
        self.extract_cells_from_shapefile(surfex_path, watershed_shp)
        self.extract_values_from_h5file(data_folder, surfex_path)

    def extract_cells_from_shapefile(self, surfex_path, watershed_shp):
        """
        extract cells

        Parameters
        ----------
        surfex_path : TYPE
            DESCRIPTION.
        watershed_shp : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        """
        mesh_path = surfex_path + '/shapefile/maille_meteo_fr_pr93.shp'
        mask = gpd.read_file(watershed_shp , encoding="utf-8")
        mesh = gpd.read_file(mesh_path, encoding="utf-8") 
        intersect = gpd.clip(mesh, mask)
        self.cells_list = intersect.num_id.to_list() # wanted Surfex cells list

    def extract_values_from_h5file(self,data_folder, surfex_path):
        variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
        scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
        simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
        self.values = {}
        for sim in simulations:
            try:
                os.remove(data_folder+sim+'.h5')
            except:
                pass
            self.values[sim] = {}
            h5file = (data_folder+sim+'.h5')
            for var in variables:
                self.values[sim][var] = {}
                for sce in scenarios:
                    try:
                        values = pd.read_hdf(surfex_path+'/'+sim+'.h5',var+'/'+sce)
                        if sim == 'REA':
                            values.index.freq = values.index.inferred_freq
                        values = values.loc[:,self.cells_list]
                        values['MEAN'] = values.mean(numeric_only=True, axis=1)
                        values.to_hdf(h5file, var+'/'+sce)
                        self.values[sim][var][sce] = values
                    except:
                        pass

    def display_all_variables(self, model=None, start='1960', end='2010'):
        mod_list = ['all','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']
        if model == None or (model not in mod_list):
            print('You must specify the model you want to display')
        else:
            if model == 'all':
                for i in mod_list:
                    climatic_display.display_all_variables(self.values,self.figure_folder, i, start, end)

            climatic_display.display_all_variables(self.values, self.figure_folder, model, start, end)

    def display_intermensual_scenarios(self, var=None):
        var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
        if var == None or (var not in var_list):
            print('You must specify the variable you want to display')
        else:
            if var == 'all':
                for i in var_list:
                    climatic_display.display_intermensual_scenarios(self.values,self.figure_folder, i)

            climatic_display.display_intermensual_scenarios(self.values,self.figure_folder, var)

    def display_annual_scenarios(self, var=None):
        var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
        if var == None or (var not in var_list):
            print('You must specify the variable you want to display')
        else:
            if var == 'all':
                for i in var_list:
                    climatic_display.display_annual_scenarios(self.values,self.figure_folder, i)
            else:
                climatic_display.display_annual_scenarios(self.values,self.figure_folder,var)

    def display_anomaly(self, mod=None ,var=None, per_hist=[1950,2005], per_fut=  [[2006,2020],[2021,2035],[2036,2050],[2051,2100]]):
        var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
        mod_list = ['all','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']
        if var == None or mod==None or (var not in var_list) or (mod not in mod_list):
            print('You must specify the variable/model you want to display')
        else:
            climatic_display.display_anomaly(self.values,self.figure_folder, mod ,var, per_hist=per_hist, per_fut= per_fut)

class Merge:
    
    def __init__(self, out_path):

        self.variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
        self.scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
        self.simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']

        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
                
        columns = []
        for sim in self.simulations:
                for sce in self.scenarios:
                    if (sim == 'REA') & (sce == 'historic'):
                        columns.append(sim+'_'+sce)
                    if sim != 'REA':
                        columns.append(sim+'_'+sce)
                        
        date = pd.date_range(start='01/01/1960', end='31/12/2099', freq='D')
        self.base = pd.DataFrame(index=date, columns=columns)
        
        self.df_climate_bv()
        
    def df_climate_bv(self):
        for var in self.variables:
            df = self.base.copy()
            for sim in self.simulations:
                for sce in self.scenarios:
                    try:
                        hdf = pd.read_hdf(self.data_folder+sim+'.h5',var+'/'+sce) # mm/day or °C
                        df[sim+'_'+sce] = hdf.MEAN                                         
                    except:
                        continue
            
            # if (self.time_step == 'M'):
            dfm = df.copy() 
            mask = dfm.resample("M").count() >= 27
            if (var == 'TAS'):
                dfm = dfm.resample("M").mean()[mask]
            else:
                # df = df.resample('M').sum(min_count=27) # mm/month
                dfm = dfm.resample("M").sum()[mask]
                    
            # if (self.time_step == 'Y'):
            dfy = df.copy()
            mask = dfy.resample("Y").count() >= 364
            if (var == 'TAS'):
                dfy = dfy.resample("Y").mean()[mask]
            else:
                # df = df.resample('Y').sum(min_count=364) # mm/year
                dfy = dfy.resample("Y").sum()[mask]
            
            df.to_csv(self.data_folder+'_'+var+'_'+'D'+'.csv', sep=';')
            dfm.to_csv(self.data_folder+'_'+var+'_'+'M'+'.csv', sep=';')
            dfy.to_csv(self.data_folder+'_'+var+'_'+'Y'+'.csv', sep=';')