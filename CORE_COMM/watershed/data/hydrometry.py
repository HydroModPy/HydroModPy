# -*- coding: utf-8 -*-
"""
Created on Tue Jan  4 14:09:11 2022

@author: ronan
"""

#%%

import pandas as pd
import chardet
import numpy as np
import matplotlib.pyplot as plt

import time
from selenium import webdriver
import glob
import zipfile
import os

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

#%%

code_station = 'J7513010'

data_folder = 'D:/Users/abherve/TEST/Watershed/results_stable/hydrology/'

#%%

url = 'http://hydro.eaufrance.fr/'
chrome_options = webdriver.ChromeOptions()
prefs = {'download.default_directory' : data_folder.replace('/','\\')}
chrome_options.add_experimental_option('prefs', prefs)
driver = webdriver.Chrome(chrome_options=chrome_options)
driver.get(url)

timeout = 3
try:
    element_present = EC.presence_of_element_located((By.ID, 'main'))
    WebDriverWait(driver, timeout).until(element_present)
except TimeoutException:
    print("Timed out waiting for page to load")
finally:
    print("Page loaded")
    
# try:
elem0 = driver.find_element_by_name('btnValider')
elem0.click()

elem1 = driver.find_element_by_link_text("Téléchargement (nécessité de disposer d'un compte)")
elem1.click()

elem2 = driver.find_element_by_name("username")
elem2.send_keys("AUNIV084")

elem3 = driver.find_element_by_name("password")
elem3.send_keys("DRUNIV2022")

elem4 = driver.find_element_by_name("btnCnx")
elem4.click()

try:
    elem5 = driver.find_element_by_xpath("//a[@title='Tout supprimer']")
    elem5.click()
except:
    pass

try:
    elem6 = driver.find_element_by_link_text('Consultation (pas de compte nécessaire)')
    elem6.click()
except:
    pass

elem7 = driver.find_element_by_name("code_station")
elem7.send_keys(code_station)

elem8 = driver.find_element_by_name("station_hors_service")
elem8.click()

elem9 = driver.find_element_by_name("btnValider")
elem9.click()

elem10 = driver.find_element_by_name("station[]")
elem10.click()

elem11 = driver.find_element_by_xpath("//input[@value='Exporter']")
elem11.click()

elem12 = driver.find_element_by_xpath("//input[@value='QJM']")
elem12.click()

elem13 = driver.find_element_by_name('debut_an')
elem13.click()
opt13 = elem13.find_elements_by_tag_name('option')
opt13[len(opt13)-1].click()

elem14 = driver.find_element_by_name("btnValider")
elem14.click()

elem15 = driver.find_element_by_link_text("page d'accueil")
elem15.click()

elem16 = None
while elem16 is None:
    driver.refresh()
    try:
        elem16 = driver.find_element_by_xpath('//a[@href="'+'tmp/9745_1/qjm.zip'+'"]')
        elem16.click()
    except:
        time.sleep(5)
        pass

elem17 = driver.find_element_by_link_text('Exporter les données (Accès restreint)')
elem17.click()

elem18 = driver.find_element_by_xpath("//input[@value='FICHE-STATION']")
elem18.click()

elem19 = driver.find_element_by_link_text("page d'accueil")
elem19.click()

elem20 = None
while elem20 is None:
    driver.refresh()
    try:
        elem20 = driver.find_element_by_xpath('//a[@href="'+'tmp/9745_2/fiche-station.zip'+'"]')
        elem20.click()
    except:
        time.sleep(5)
        pass

files = glob.glob(data_folder+'/*.zip')
for file in files:
    with zipfile.ZipFile(file, 'r') as zip_ref:
        zip_ref.extractall(data_folder+'/'+code_station)
    os.remove(file)

driver.close()

#%%

fiche_path = glob.glob(data_folder+code_station+'/'+'*fiche-station.csv')[0]

with open(fiche_path) as f:
    lines = f.readlines()

data = pd.DataFrame()

name = lines[3].split(';')[1]
x = lines[41].split(';')[0]
y = lines[41].split(';')[1]
area = lines[4].split(';')[1]
alti = lines[17].split(';')[1]
first = lines[59].split(';')[1][0:4]
last =lines[59].split(';')[1][-4:]

#%%

qjm_path = glob.glob(data_folder+code_station+'/'+'qjm*')[0]

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
    débit = debit.set_index(debit.columns.tolist()[0], inplace=True)
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
name_out = 'Hydrometric_'+code_station+'_'+name+'_'+x+'-'+y+'_'+area+'_'+alti+'_'+first+'-'+last
df.to_csv(data_folder+code_station+'/'+name_out+'.csv', sep=';')

plt.plot(df)

#%%