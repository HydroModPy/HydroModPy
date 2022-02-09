# -*- coding: utf-8 -*-
"""
Created on Tue Jan  4 14:09:11 2022

@author: ronan
"""

import pandas as pd
import chardet
import numpy as np
import matplotlib.pyplot as plt

import time
from selenium import webdriver
import glob
import zipfile
import os
import datetime
import geopandas as gpd
import shutil

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

class Hydrometry:
    def __init__(self, initlocal_path, clipshp_path, outshp_path, outdata_path, outfig_path):
        
        print('Extraction des données hydrométriques')

        self.extract_hydrometry_from_watershed(initlocal_path, clipshp_path, outshp_path)
        # self.download_data_from_code_bh(outdata_path)
        # self.load_hydrometric_data(outdata_path, outfig_path)
    
    def extract_hydrometry_from_watershed(self, initlocal_path, clipshp_path, outshp_path):
        hydrometric_data = initlocal_path
        self.hydrometric_clip = outshp_path
        wbt.clip(hydrometric_data, clipshp_path, self.hydrometric_clip)
        hydromet_bv = gpd.read_file(self.hydrometric_clip)
        # p="D:/Users/abherve/HYDROMETRY/shp/clipped_hydrometric.shp"
        # hydromet_bv = gpd.read_file(p)
        hydromet_bv = hydromet_bv[~hydromet_bv['CdStatio_1'].isnull()]
        hydromet_bv = hydromet_bv[hydromet_bv['InfluLocal']==1]
        self.label = hydromet_bv['LbStationH'].to_list()
        self.influ = hydromet_bv['InfluLocal'].to_list()
        self.x_coord = hydromet_bv['CoordXStat'].tolist()
        self.y_coord = hydromet_bv['CoordYStat'].to_list()
        for i in range(len(hydromet_bv)):
            hydromet_bv['CdStationH'].iloc[i] = hydromet_bv.iloc[i]['CdStationH'][0:8]
            if hydromet_bv['timePositi'].iloc[i] == None:
                hydromet_bv['timePositi'].iloc[i] = datetime.datetime.today().strftime('%Y-%m-%d')
            if hydromet_bv['DtFermetur'].iloc[i] == None:
                hydromet_bv['DtFermetur'].iloc[i] = datetime.datetime.today().strftime('%Y-%m-%d')
            else:
                hydromet_bv['DtFermetur'].iloc[i] = hydromet_bv.iloc[i]['DtFermetur'][0:10]
        # self.date_inst = pd.to_datetime(hydromet_bv['timePositi'][0:10], format='%Y-%m-%d').to_list()
        # self.date_ferm = pd.to_datetime(hydromet_bv['DtFermetur'][0:10], format='%Y-%m-%d').to_list()            
        self.code_bh = hydromet_bv['CdStationH'].to_list()
        self.date_inst = hydromet_bv['timePositi'].to_list()
        self.date_ferm = hydromet_bv['DtFermetur'].to_list()
        
    def download_data_from_code_bh(self, outdata_path):
        
        url = 'http://hydro.eaufrance.fr/'
        chrome_options = webdriver.ChromeOptions()
        prefs = {'download.default_directory' : outdata_path.replace('/','\\')}
        chrome_options.add_experimental_option('prefs', prefs)
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        timeout = 10
        try:
            element_present = EC.presence_of_element_located((By.ID, 'main'))
            WebDriverWait(driver, timeout).until(element_present)
        except TimeoutException:
            print("     Timed out waiting for page to load")
        finally:
            print("     Hydrometric page loaded")
    
        # try:
        driver.find_element_by_name('btnValider').click()
        try:
            driver.find_element_by_link_text("Téléchargement (nécessité de disposer d'un compte)").click()
        except:
            driver.find_element_by_link_text("TÃ©lÃ©chargement (nÃ©cessitÃ© de disposer d'un compte)").click()
        driver.find_element_by_name("username").send_keys("AUNIV084")
        driver.find_element_by_name("password").send_keys("DRUNIV2022")
        driver.find_element_by_name("btnCnx").click()
                            
        for code, name in zip(self.code_bh, self.label):
        # label = ['Test']
        # code_bh = ['J0407610']
        # for code, name in zip(code_bh, label):
                        
            print('          '+code)
            error = False
            
            if not os.path.exists(outdata_path+'/'+code+'_'+name):
            
            # if os.path.exists(outdata_path+'/'+code+'_'+name+'/'):                
            #     shutil.rmtree(outdata_path+'/'+code+'_'+name+'/')
                
                try:
                    driver.find_element_by_xpath("//a[@title='Tout supprimer']").click()
                except:
                    pass
                try:
                    driver.find_element_by_link_text('Consultation (pas de compte nécessaire)').click()
                except:
                    pass
                try:
                    driver.find_element_by_link_text('Consultation (pas de compte nÃ©cessaire)').click()
                except:
                    pass
                try:
                    driver.find_element_by_name("code_station").clear()
                except:
                    pass
                
                driver.find_element_by_name("code_station").send_keys(code)       
                driver.find_element_by_name("station_hors_service").click()
                
                try:
                    driver.find_element_by_xpath("//input[@value='Nouvelle Recherche']").click()
                    driver.find_element_by_name("station[]").click()
                except:
                    driver.find_element_by_name("station_hors_service").click()
                    driver.find_element_by_xpath("//input[@value='Nouvelle Recherche']").click()
                    try:
                        driver.find_element_by_name("station[]").click()
                    except:
                        error = True
                        print('               No found')
                        pass
                    
                if error == True:
                    continue
                
                else:
                    driver.find_element_by_xpath("//input[@value='Exporter']").click()                
                    driver.find_element_by_xpath("//input[@value='QJM']").click()
                    
                    try:
                        elem = driver.find_element_by_name('debut_an')
                        elem.click()
                    except:
                        print('               No data')
                        error = True
                        element_present = driver.find_element_by_id('header_gauche')
                        element_present.click()
                        driver.find_element_by_name('btnValider').click()
                        pass
                    
                    if error == True:
                        continue
                    
                    opt = elem.find_elements_by_tag_name('option')
                    opt[len(opt)-1].click()
                    driver.find_element_by_name("btnValider").click()
                    
                    driver.find_element_by_link_text("page d'accueil").click()
                    
                    down = None
                    while down is None:
                        driver.refresh()
                        try:
                            down = driver.find_element_by_xpath('//a[@href="'+'tmp/9745_1/qjm.zip'+'"]')
                            down.click()
                        except:
                            time.sleep(5)
                            pass
                        
                    try:
                        driver.find_element_by_link_text('Exporter les données (Accès restreint)').click()
                    except:
                        driver.find_element_by_link_text('Exporter les donnÃ©es (AccÃ¨s restreint)').click()
                        pass
                    driver.find_element_by_xpath("//input[@value='FICHE-STATION']").click()
                    driver.find_element_by_link_text("page d'accueil").click()
                    
                    fich = None
                    while fich is None:
                        driver.refresh()
                        try:
                            fich = driver.find_element_by_xpath('//a[@href="'+'tmp/9745_2/fiche-station.zip'+'"]')
                            fich.click()
                        except:
                            time.sleep(5)
                            pass
                        
                    files = glob.glob(outdata_path+'/*.zip')
                    while len(files) != 2:
                        files = glob.glob(outdata_path+'/*.zip')
                        time.sleep(1)
                        
                    for file in files:
                        with zipfile.ZipFile(file, 'r') as zip_ref:
                            zip_ref.extractall(outdata_path+'/'+code+'_'+name)
                        os.remove(file)
            
        driver.close()
           
    def load_hydrometric_data(self, outdata_path, outfig_path):
        
        discharge = pd.DataFrame()
        # for code, label in zip(self.code_bh, self.label):
        # labels = ['L\'Auray [Le Loch] ï¿½ Brech - Er Loch']
        # code_bh = ['J6213010']
        # for code, label in zip(code_bh, labels):
        labels = os.listdir(outdata_path)
        # label = '102_J6213010'
        # labels = labels[102:103]
        # print(raw_path)
        for label in labels:
            # print(path)
            # path = "D:/Users/abherve/HYDROMETRY/data/BZH\J6213010_L'Auray [Le Loch] ï¿½ Brech - Er Loch"
            code = label.split('_')[1]
            try:
                file_path = glob.glob(outdata_path+'/'+label+'/'+'Hydrometric*.csv')
                if file_path != []:
                    if os.path.exists(file_path[0]):
                        os.remove(file_path[0])
                # print(path)
                fiche_path = glob.glob(outdata_path+'/'+label+'/'+"*fiche-station.csv")[0]
                # print(fiche_path)
                with open(fiche_path) as f:
                    lines = f.readlines()        
                name = lines[3].split(';')[1]
                nlines=0
                for line in lines:
                    nlines += 1
                    if (line.find('X (m)') >= 0):
                        x = lines[nlines].split(';')[0]
                        y = lines[nlines].split(';')[1]
                nlines=0
                for line in lines:
                    nlines += 1
                    if (line.find('Données disponibles') >= 0):
                        # print(lines[nlines-1])
                        first = lines[nlines-1].split(';')[1][0:4]
                        last = lines[nlines-1].split(';')[1][7:12]
                        # print(first, last)
                if (last == None) | (last==''):
                    last = datetime.datetime.today().strftime('%Y')
                area = lines[4].split(';')[1]
                alti = lines[17].split(';')[1]
                
                qjm_path = glob.glob(outdata_path+'/'+label+'/'+'qjm*')[0]  
                with open(qjm_path) as f:
                    lines = f.readlines()            
                compt = 0
                df = pd.DataFrame()
                for step in range(int(len(lines)/73)):
                    bloc = lines[compt:73+compt]
                    date = bloc[0][-5:-1]
                    debit = pd.DataFrame([sub.split(";") for sub in bloc[41:]])
                    debit.columns = debit.iloc[0]
                    debit = debit[1:]
                    debit = debit.filter(regex='Débit')
                    debit.columns = ['1','2','3','4','5','6','7','8','9','10','11','12']
                    debit = debit.stack().to_frame()
                    debit['day'] = debit.index.get_level_values(0)
                    debit['month'] = debit.index.get_level_values(1)
                    debit['year'] = date
                    debit['date'] = pd.to_datetime(debit[['year','month','day']], errors='coerce')
                    debit = debit.set_index('date', drop=True)
                    debit = debit.sort_index()
                    debit = debit.loc[debit.index.dropna()]
                    debit = debit.replace(to_replace='', value=np.nan)
                    debit = debit[debit.columns.tolist()[0]]
                    debit = pd.to_numeric(debit)
                    df = pd.concat([df,debit])
                    compt += 73
                df.columns = ['Q']
                name_out = 'Hydrometric_'+code+'_'+name+'_'+x+'-'+y+'_'+area+'_'+alti+'_'+first+'-'+last
                sortie = outdata_path+'/'+label+'/'
                df.to_csv(sortie+name_out+'.csv', sep=';')
                print('Success : '+code)
                append = df.copy()
                append.columns = [code]
                fig, ax = plt.subplots(1,1, figsize=(8,3))
                ax.plot(append, lw=2)
                ax.set_yscale('log')
                ax.set_xlabel('Date')
                ax.set_ylabel('Discharge [m$^3$/day]')
                ax.set_title(code+'\n'+name)
                fig.savefig(outfig_path+'/'+code+'_'+name+'.png', dpi=300, 
                            bbox_inches='tight', transparent=False)
                # discharge = pd.concat([discharge, append], axis=1).sort_index()
                plt.close()
            except:
                print('Error : '+code)
                pass
        # discharge.to_csv(outdata_path+'/'+'CONCAT_DATA'+'.csv', sep=';')
        
x = Hydrometry('C:/Users/ronan/OneDrive/_HydroDataPy/HYDROLOGY/France/Discharge/hydrometric.shp',
               'D:/Users/abherve/HYDROMETRY/shp/bzh.shp',
               'D:/Users/abherve/HYDROMETRY/shp/clipped_hydrometric.shp',
               'D:/Users/abherve/HYDROMETRY/data/BZH',
               'D:/Users/abherve/HYDROMETRY/fig/BZH')

#%% Notes

code_bh = ['J7373110','J7393010','J7313010']
outdata_path = 'D:/Users/abherve/HYDROMETRY/data/BZH'

x.extract_hydrometry_from_watershed('C:/Users/ronan/OneDrive/_HydroDataPy/HYDROLOGY/France/Discharge/hydrometric.shp',
                                    'D:/Users/abherve/HYDROMETRY/shp/bzh.shp',
                                    'D:/Users/abherve/HYDROMETRY/shp/clipped_hydrometric.shp')
x.download_data_from_code_bh('D:/Users/abherve/HYDROMETRY/data')
x.load_hydrometric_data('D:/Users/abherve/HYDROMETRY/data',
                        'D:/Users/abherve/HYDROMETRY/fig')

#%%

wbt.split_with_lines(
    'C:/Users/ronan/Downloads/LimiteMassifArmoricain/RegionOuest.shp', 
    'C:/Users/ronan/Downloads/LimiteMassifArmoricain/MA_manuel.shp', 
    'C:/Users/ronan/Downloads/LimiteMassifArmoricain/LimiteMassifArmoricainPolyg.shp')

#%%

import geopandas as gpd
x = gpd.read_file('D:/Users/abherve/HYDROMETRY/shp/clipped_hydrometric.shp')
x = x[x['InfluLocal']==1]

#%%

import os
outdata_path = 'D:/Users/abherve/HYDROMETRY/data/EBR/'
labels = os.listdir(outdata_path)
compt=0
for label in labels:
    lab = label.split('_')[0]
    print(lab)
    os.rename(outdata_path+label, outdata_path+str(compt)+'_'+lab)
    compt+=1

