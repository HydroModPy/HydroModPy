# coding:utf-8
import os
import urllib
import zipfile
import geopandas as gpd
from selenium import webdriver
import pandas as pd
import numpy as np
import time
import glob
import ssl

class Piezometry:
    def __init__(self, out_path, geographic):
        print('Extraction des données piézomètriques')
        data_folder = os.path.join(out_path,'results_stable','piezometric/')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)    
        self.download_init_data(data_folder)
        self.out_path = out_path
        self.geo_x_coord = geographic.x_coord
        self.geo_y_coord = geographic.y_coord
        self.x_coord = []
        self.y_coord = []
        self.x_iloc = []
        self.y_iloc = []
        self.depth_well = []
        self.elevation_well = []
        self.exctract_piezos_from_watershed(data_folder, geographic)
        self.piezos_shp = os.path.join(data_folder,'shapefile','piezos.shp')
        if os.path.exists(os.path.join(data_folder,'shapefile','piezos.shp')):
            self.extract_data_from_code_bss(data_folder)
            self.load_piezometric_data(data_folder)

    def download_init_data(self,data_folder):
        filename = data_folder + 'piezometers.zip'
        folder = data_folder + '/' + 'shapefile'
        url = 'https://www.data.gouv.fr/fr/datasets/r/f10f3f18-eac3-4cee-b178-4c577c4fd689'
        if not os.path.exists(folder):
            ssl._create_default_https_context = ssl._create_unverified_context
            urllib.request.urlretrieve(url, filename)
            with zipfile.ZipFile(filename, 'r') as zip_ref:
                zip_ref.extractall(data_folder + '/' + 'shapefile')
            os.remove(filename)
        return self

    def exctract_piezos_from_watershed(self,data_folder, geographic):
        watershed = gpd.read_file(geographic.watershed_box_shp)
        piezos_shp = data_folder + 'shapefile/point_eau_piezo.shp'
        piezos_fr = gpd.read_file(piezos_shp)
        piezos_fr.to_crs(epsg=2154, inplace=True)
        piezos = gpd.clip(piezos_fr, watershed)
        if len(piezos)!=0:
            piezos.to_file(data_folder + 'shapefile/piezos.shp')
            self.codes_bss = piezos['code_bss'].tolist()
            for i in range (0, len(self.codes_bss)):
                self.codes_bss[i] = self.codes_bss[i].replace('/','_')
            self.x_coord = piezos['geometry'].x.tolist()
            self.y_coord = piezos['geometry'].y.tolist()
            for i in range(0, len(self.x_coord)):
                idx = (np.abs(geographic.x_coord- self.x_coord)).argmin()
                idy = (np.abs(geographic.y_coord- self.y_coord)).argmin()
                self.x_iloc.append(idx)
                self.y_iloc.append(idy)
        return self, piezos

    def extract_data_from_code_bss(self,data_folder):
        for code in self.codes_bss:
            code_ = code.replace('_','/')
            if not os.path.exists(data_folder+'/'+code):
                url = 'https://ades.eaufrance.fr/Fiche/PtEau?Code=' + code_
                chrome_options = webdriver.ChromeOptions()
                prefs = {'download.default_directory' : data_folder.replace('/','\\')}
                chrome_options.add_experimental_option('prefs', prefs)
                driver = webdriver.Chrome(chrome_options=chrome_options)
                driver.get(url)
                try:
                    elem = driver.find_element_by_link_text('Tout télécharger')
                    elem.click()
                    compt = 0
                    while (compt==0):
                        if len(glob.glob(data_folder + '*.zip')) == 1:
                            compt +=1
                            time.sleep(1)
                        time.sleep(1)
                    driver.close()
                    file = glob.glob(data_folder+'/*.zip')[0]
                    with zipfile.ZipFile(file, 'r') as zip_ref:
                        zip_ref.extractall(data_folder+'/'+code)
                    os.remove(file)
                except:
                    self.codes_bss.remove(code)

    def load_piezometric_data(self,data_folder):
        self.depth = pd.DataFrame()
        self.elevation = pd.DataFrame()
        for code in self.codes_bss:
            desc_file = os.path.join(data_folder,'ades_export','Descriptif','descriptif.txt')
            df1 = pd.read_csv(desc_file, delimiter = '|',header=0, engine='python', encoding='latin1')
            self.depth_well.append(df1['Profondeur investigation maximale'][0])
            self.elevation_well.append(df1['Altitude'][0])
            file = data_folder + code + '/ades_export/Quantite/chroniques.txt'
            df = pd.read_csv(file, delimiter = '|',header=0, engine='python', encoding='latin1')
            depth = df[['Date de la mesure','Profondeur relative/repère de mesure']]
            depth.columns = ['Date', 'Mesure']
            depth.index = pd.to_datetime(depth['Date'],format='%d/%m/%Y %H:%M:%S')
            depth = depth.drop(['Date'], axis=1)
            depth.columns = [code]
            self.depth = pd.concat([self.depth, depth], axis=1).sort_index()
            elevation = df[['Date de la mesure','Côte NGF']]
            elevation.columns = ['Date', 'Mesure']
            elevation.index = pd.to_datetime(elevation['Date'],format='%d/%m/%Y %H:%M:%S')
            elevation = elevation.drop(['Date'], axis=1)
            elevation.columns = [code]
            self.elevation = pd.concat([self.elevation, elevation], axis=1).sort_index()

    def add_data(self):
        files = glob.glob(os.path.join(self.out_path, 'results_stable/add_data/piezometry_*.csv'))
        if len(files)>0:
            for file in files:
                self.codes_bss.append(file.split('_')[-5])
                self.x_coord.append(float(file.split('_')[-4]))
                self.y_coord.append(float(file.split('_')[-3]))
                self.elevation_well.append(float(file.split('_')[-2]))
                self.depth_well.append(float(file.split('_')[-1].split('.')[0]))
                idx = (np.abs(self.geo_x_coord- int(file.split('_')[-2]))).argmin()
                idy = (np.abs(self.geo_y_coord- int(file.split('_')[-1].split('.')[0]))).argmin()
                self.x_iloc.append(idx)
                self.y_iloc.append(idy)
                df = pd.read_csv(file, delimiter = ';',header=0, engine='python', encoding='latin1')
                df.columns = ['Date', file.split('_')[-3]]
                df.index = pd.to_datetime(df['Date'],format='%d/%m/%Y %H:%M')
                df = df.drop(['Date'], axis=1)
                self.elevation = pd.concat([self.elevation, df], axis=1).sort_index()
            df = pd.DataFrame({'code_bss': self.codes_bss, 'X': self.x_coord, 'Y': self.y_coord})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.X, df.Y))
            gdf.to_file(self.piezos_shp)








        
