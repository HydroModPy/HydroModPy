# -*- coding: utf-8 -*-
"""
Created on Wed Jan 19 13:44:15 2022

@author: ronan
"""

import os
import geopandas as gpd
import whitebox
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

class Intermittency:
    def __init__(self, out_path, intermittency_path, geographic):
        print('Extraction des données d\'intermittence')
        data_folder = os.path.join(out_path,'results_stable','intermittency')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.fig_intermit = os.path.join(out_path,'results_stable','_figures','intermittency')
        if not os.path.exists(self.fig_intermit):
                os.makedirs(self.fig_intermit)
        self.code_onde = []
        self.label = []
        self.x_coord = []
        self.y_coord = []
        self.date_first = []
        self.date_last = []
        try:
            self.extract_intermittency_from_watershed(data_folder, intermittency_path, geographic)
            self.load_intermittency_data(data_folder)
        except:
            pass
        
    def extract_intermittency_from_watershed(self, data_folder, intermittency_path, geographic):
        onde_data = os.path.join(intermittency_path, 'onde.shp')
        self.onde_clip = os.path.join(data_folder,'onde.shp')
        wbt.clip(onde_data, geographic.watershed_shp, self.onde_clip)
        intermit_bv = gpd.read_file(self.onde_clip)
        stations = intermit_bv['<LbSiteHyd'].unique()
        for i in stations:
            mask = (intermit_bv['<LbSiteHyd'] == i)
            raw = intermit_bv[mask]
            self.code_onde.append(raw.iloc[0]['<CdSiteHyd'])
            self.label.append(raw.iloc[0]['<LbSiteHyd'])
            self.x_coord.append(raw.iloc[0]['<CoordXSit'])
            self.y_coord.append(raw.iloc[0]['<CoordYSit'])
            # self.date_first.append(pd.to_datetime(raw.iloc[0]['<DtRealObs'], format='%Y-%m-%d'))
            # self.date_last.append(pd.to_datetime(raw.iloc[-1]['<DtRealObs'],format='%Y-%m-%d'))
            self.date_first.append(raw.iloc[0]['<DtRealObs'])
            self.date_last.append(raw.iloc[-1]['<DtRealObs'])
            
    def load_intermittency_data(self, data_folder):
        self.flowing = pd.DataFrame()
        shp = gpd.read_file(self.onde_clip)
        # shp =gpd.read_file("D:/Users/abherve/HYDROMODPY/Rejet/results_stable/intermittency/onde.shp")
        # shp = gpd.read_file(BV.intermittency.onde_clip)
        shp['date'] =  pd.to_datetime(shp['<DtRealObs'], format = '%Y-%m-%d')
        shp['code_flow'] = np.nan
        dicecoul = {'Assec':1,
                    'Ecoulement non visible':2,
                    'Ecoulement visible faible':3,
                    'Ecoulement visible acceptable':4,
                    'Ecoulement visible':5}
        for i in range(len(shp)):
            shp.loc[i,'code_flow'] = dicecoul[shp.loc[i,'<LbRsObser']]
        for code in self.code_onde:
            # code = "J7380001"
            mask = (shp['<CdSiteHyd'] == code)
            raw = shp.copy()
            raw = raw[mask]
            append = raw[['date','code_flow']]
            append = append.set_index('date')
            append.columns = [code]
            self.flowing = pd.concat([self.flowing, append], axis=1).sort_index()
            fig, ax = plt.subplots(1,1, figsize=(5,2))
            ax.scatter(append.index, append[code], c=append[code], cmap='jet_r',
                       vmin=1, vmax=5,
                       marker='|', s=50, lw=1.5)
            # try:
            #     lab = raw['<LbSiteHyd'][0]
            # except:
            lab = raw.iloc[0]['<LbSiteHyd']
                # pass
            ax.set_title(code+' - '+lab)
            # ax.set_yticks([-1, 0, 1, 2, 3])
            # try:
            ax.set_yticklabels(['-','Assec','Invisible','Faible','Acceptable','Visible'])
            # except:
            #     ax.set_yticks([1, 2, 3, 4, 5])
            #     pass
            # ax.set_xticks(zip([-1, 0, 1, 2, 3],
            #                   ['-','Assec','Invisible','Faible','Acceptable','Visible']))
            # ax.yaxis.set_ticks(['-','Assec','Invisible','Faible','Acceptable','Visible'])
            ax.set_ylim(0.5,5.5)
            ax.set_xlim(([pd.to_datetime('2012'), pd.to_datetime('2022')]))                  
            years = mdates.YearLocator(2)   # every year
            ax.xaxis.set_major_locator(years)
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_formatter(years_fmt)
            yearsmin = mdates.YearLocator(1)
            ax.xaxis.set_minor_locator(yearsmin)
            # months = mdates.MonthLocator(6)  # every month
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ? 
            # ax.xaxis.set_minor_locator(months)
            ax.grid(True, axis='x', which='major')   
            plt.tight_layout()
            fig.savefig(self.fig_intermit+'/'+code+'_'+lab+'.png', dpi=300, 
                        bbox_inches='tight', transparent=False)
            print(code)
            # plt.close()
            
        