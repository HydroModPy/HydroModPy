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
    def __init__(self, out_path, hydrometry_path, geographic):
        print('Extraction des données hydrométriques')
        data_folder = os.path.join(out_path,'results_stable','hydrometry')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.fig_hydromet = os.path.join(out_path,'results_stable','_figures','hydrometry')
        if not os.path.exists(self.fig_hydromet):
                os.makedirs(self.fig_hydromet)
        self.code_bh = []
        self.label = []
        self.x_coord = []
        self.y_coord = []
        self.date_inst = []
        self.date_ferm = []
        try:
            self.extract_hydrometry_from_watershed(data_folder, hydrometry_path, geographic)
            self.download_data_from_code_bh(data_folder)
            self.load_hydrometric_data(data_folder)
        except:
            pass
    
    def extract_hydrometry_from_watershed(self, data_folder, hydrometry_path, geographic):
        hydrometric_data = os.path.join(hydrometry_path, 'hydrometric.shp')
        self.hydrometric_clip = os.path.join(data_folder,'hydrometric.shp')
        wbt.clip(hydrometric_data, geographic.watershed_shp, self.hydrometric_clip)
        # try:
        hydromet_bv = gpd.read_file(self.hydrometric_clip)        
        self.label = hydromet_bv['LbStationH'].to_list()
        self.x_coord = hydromet_bv['CoordXStat'].tolist()
        self.y_coord = hydromet_bv['CoordYStat'].to_list()
        for i in range(len(hydromet_bv)):
            hydromet_bv['CdStationH'].iloc[i] = hydromet_bv.iloc[i]['CdStationH'][0:8]
            hydromet_bv['timePositi'].iloc[i] = hydromet_bv.iloc[i]['timePositi'][0:10]
            if hydromet_bv['DtFermetur'].iloc[i] == None:
                hydromet_bv['DtFermetur'].iloc[i] = datetime.datetime.today().strftime('%Y-%m-%d')
            else:
                hydromet_bv['DtFermetur'].iloc[i] = hydromet_bv.iloc[i]['DtFermetur'][0:10]
        # self.date_inst = pd.to_datetime(hydromet_bv['timePositi'][0:10], format='%Y-%m-%d').to_list()
        # self.date_ferm = pd.to_datetime(hydromet_bv['DtFermetur'][0:10], format='%Y-%m-%d').to_list()            
        self.code_bh = hydromet_bv['CdStationH'].to_list()
        self.date_inst = hydromet_bv['timePositi'].to_list()
        self.date_ferm = hydromet_bv['DtFermetur'].to_list()
        
    def download_data_from_code_bh(self, data_folder):
        
        url = 'http://hydro.eaufrance.fr/'
        chrome_options = webdriver.ChromeOptions()
        prefs = {'download.default_directory' : data_folder.replace('/','\\')}
        chrome_options.add_experimental_option('prefs', prefs)
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        timeout = 3
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
                            
        for code in self.code_bh:
            
            print('          '+code)
            error = False
            
            # if not os.path.exists(data_folder+'/'+code):
            
            if os.path.exists(data_folder+'/'+code+'/'):                
                shutil.rmtree(data_folder+'/'+code+'/')
                
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
                elem = driver.find_element_by_name('debut_an')
                elem.click()
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
                    
                files = glob.glob(data_folder+'/*.zip')
                while len(files) != 2:
                    files = glob.glob(data_folder+'/*.zip')
                    time.sleep(1)
                    
                for file in files:
                    with zipfile.ZipFile(file, 'r') as zip_ref:
                        zip_ref.extractall(data_folder+'/'+code)
                    os.remove(file)
            
        driver.close()
            
    def load_hydrometric_data(self, data_folder):
        
        self.discharge = pd.DataFrame()
        
        for code in self.code_bh:
            try:
                fiche_path = glob.glob(data_folder+'/'+code+'/'+'*fiche-station.csv')[0]        
                with open(fiche_path) as f:
                    lines = f.readlines()            
                name = lines[3].split(';')[1]            
                nlines=0
                for line in lines:
                    nlines += 1
                    if (line.find('X') >= 0):
                        x = lines[nlines].split(';')[0]
                        y = lines[nlines].split(';')[1]       
                        first = lines[nlines].split(';')[4][6:-6]
                        last = lines[nlines].split(';')[5][6:-6]
                if last == None:
                    last = datetime.datetime.today().strftime('%Y')
                area = lines[4].split(';')[1]
                alti = lines[17].split(';')[1]
                
                qjm_path = glob.glob(data_folder+'/'+code+'/'+'qjm*')[0]            
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
                df.to_csv(data_folder+'/'+code+'/'+name_out+'.csv', sep=';')
                append = df.copy()
                append.columns = [code]
                fig, ax = plt.subplots(1,1, figsize=(8,3))
                ax.plot(append, lw=2)
                ax.set_yscale('log')
                ax.set_xlabel('Date')
                ax.set_ylabel('Discharge [m$^3$/day]')
                ax.set_title(code+'\n'+name)
                fig.savefig(self.fig_hydromet+'/'+code+'_'+' - '+name+'.png', dpi=300, 
                            bbox_inches='tight', transparent=False)
                self.discharge = pd.concat([self.discharge, append], axis=1).sort_index()
            except:
                pass
                