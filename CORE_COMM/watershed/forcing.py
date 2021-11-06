# coding:utf-8

import pandas as pd
import os 
import sys
from os.path import dirname, abspath

class Forcing:
    
    def __init__(self, out_path, time_step='D'):

        self.variables = ['REC','RUN', 'ETP', 'PPT', 'TAS']
        self.scenarios = ['historic','RCP2.6','RCP4.5','RCP6.0','RCP8.5']
        self.simulations = ['REA','ACC1','BCC1','BNU1','CAN1','CNR1','CSI1','IPS1','MIR1','NOR1']

        self.data_folder = os.path.join(out_path, 'results_stable/climatic/')
        
        self.time_step = time_step
        
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
            print(var)
            df = self.base.copy()
            for sim in self.simulations:
                for sce in self.scenarios:
                    try:
                        hdf = pd.read_hdf(self.data_folder+sim+'.h5',var+'/'+sce) # mm/day or °C
                        df[sim+'_'+sce] = hdf.MEAN                                         
                    except:
                        continue
            
            if (self.time_step == 'M'):
                mask = df.resample("M").count() >= 27
                if (var == 'TAS'):
                    df = df.resample("M").mean()[mask]
                else:
                    # df = df.resample('M').sum(min_count=27) # mm/month
                    df = df.resample("M").sum()[mask]
                    
            if (self.time_step == 'Y'):
                mask = df.resample("Y").count() >= 364
                if (var == 'TAS'):
                    df = df.resample("Y").mean()[mask]
                else:
                    # df = df.resample('Y').sum(min_count=364) # mm/year
                    df = df.resample("Y").sum()[mask]
            
            df.to_csv(self.data_folder+'_'+var+'_'+self.time_step+'.csv', sep=';')

