# coding:utf-8
"""

"""

#%% LIBRAIRIES

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
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1.inset_locator import zoomed_inset_axes 
from mpl_toolkits.axes_grid1.inset_locator import mark_inset
from datetime import datetime
# Hydromodpy
from tools import toolbox

#%% CLASS

class Piezometry:
    """ 
        
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers
    y_coord: list of float
        Lambert 93 Y coordinates of piezometers
    x_iloc: list of int
        list of x-index of model cells corresponding to piezometers
    y_iloc: list of int
        list of y-index of model cells corresponding to piezometers

    Methods
    -------
    
    """
    
    #%% INIT
    
    def __init__(self, out_path, geographic):
        print('Extraction des données piézomètriques')
        data_folder = os.path.join(out_path,'results_stable','piezometric')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.figure_folder = os.path.join(out_path,'results_stable','_figures','piezometric')
        if not os.path.exists(self.figure_folder):
                os.makedirs(self.figure_folder)  
        self.download_init_data(data_folder, geographic)
        self.out_path = out_path
        self.geo_x_coord = geographic.x_coord
        self.geo_y_coord = geographic.y_coord
        self.x_coord = []
        self.y_coord = []
        self.x_iloc = []
        self.y_iloc = []
        self.codes_bss = []
        self.depth_well = []
        self.elevation_well = []
        try:
            self.extract_piezos_from_watershed(data_folder, geographic)
        except:
            pass
        self.piezos_shp = os.path.join(data_folder,'shapefile','piezos.shp')
        if os.path.exists(os.path.join(data_folder,'shapefile','piezos.shp')):
            self.extract_data_from_code_bss(data_folder)
        self.load_piezometric_data(data_folder)
    
    #%% DOWNLOAD PIEZOMETERS ID AT FRANCE SCALE
    
    def download_init_data(self,data_folder, geographic):
        #ADES continue data
        filename = os.path.join(data_folder, 'piezometers.zip')
        folder = os.path.join(data_folder, 'shapefile')
        url = 'https://www.data.gouv.fr/fr/datasets/r/f10f3f18-eac3-4cee-b178-4c577c4fd689'
        if not os.path.exists(folder):
            ssl._create_default_https_context = ssl._create_unverified_context
            urllib.request.urlretrieve(url, filename)
            with zipfile.ZipFile(filename, 'r') as zip_ref:
                zip_ref.extractall(folder)
            os.remove(filename)
            
        #BSS discrete data
        filename = data_folder + 'BSS.zip'
        folder = os.path.join(data_folder, 'shapefile')
        #if not os.path.exists(os.path.join(folder,"BSS.shp")):
        bss = 'bss_export_' + str(geographic.dep_code) + '.zip'
        bss_csv = 'bss_export_' + str(geographic.dep_code) + '.csv'
        url = 'http://infoterre.brgm.fr/telechargements/ExportsPublicsBSS/' + bss
        #url = 'http://data.cquest.org/brgm/banque_sous_sol/' + bss
        print('     '+'Piezometric page loaded')
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
            urllib.request.urlretrieve(url, filename)
            with zipfile.ZipFile(filename, 'r') as zip_ref:
                zip_ref.extractall(folder)
            os.remove(filename)
        except:
            pass
        combined_csv = pd.read_csv(os.path.join(folder, bss_csv),sep=";")
        combined_csv = combined_csv[combined_csv['date_eau_sol'].notna()]
        combined_csv = combined_csv[combined_csv['prof_eau_sol'].notna()]
        combined_csv = combined_csv[combined_csv['x_ref06'].notna()]
        combined_csv = combined_csv[combined_csv['y_ref06'].notna()]
        combined_csv = combined_csv[combined_csv['z_bdalti'].notna()]
        df = combined_csv[['ID_BSS','indice','date_eau_sol','z_bdalti','prof_eau_sol','x_ref06','y_ref06']]
        df = df[pd.to_numeric(df['prof_eau_sol'], errors='coerce').notnull()]
        for i in ['z_bdalti','prof_eau_sol','x_ref06','y_ref06']:
            df[i] = df[i].astype('float64')
        df['cote_eau'] = df['z_bdalti'] - df['prof_eau_sol']
        df.to_csv(os.path.join(folder,"BSS.csv"), index=False, encoding='utf-8-sig')
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x_ref06, df.y_ref06))
        gdf = gdf.set_crs(epsg=2154)
        gdf.to_file(os.path.join(folder,"BSS.shp"))
        os.remove(os.path.join(folder, bss_csv))
            
    #%% CLIP DATA AT THE CATCHMENT SCALE
    
    def extract_piezos_from_watershed(self,data_folder, geographic):
        # ADES continue data
        watershed = gpd.read_file(geographic.watershed_box_shp)
        piezos_shp = os.path.join(data_folder, 'shapefile','point_eau_piezo.shp')
        piezos_fr = gpd.read_file(piezos_shp)
        piezos_fr.to_crs(epsg=2154, inplace=True)
        piezos = gpd.clip(piezos_fr, watershed)
        if len(piezos)!=0:
            piezos.to_file(os.path.join(data_folder, 'shapefile','piezos.shp'))
            self.codes_bss = piezos['code_bss'].tolist()
            for i in range (0, len(self.codes_bss)):
                self.codes_bss[i] = self.codes_bss[i].replace('/','_')
            self.x_coord = piezos['geometry'].x.tolist()
            self.y_coord = piezos['geometry'].y.tolist()
            for i in range(0, len(self.x_coord)):
                idx = (np.abs(geographic.x_coord- self.x_coord[i])).argmin()
                # index is determined by lowest difference between piezometer coordinate and model cell coordinate
                idy = (np.abs(geographic.y_coord- self.y_coord[i])).argmin()
                self.x_iloc.append(idx)
                self.y_iloc.append(idy) 
        
        #BSS discrete data
        bss_shp = os.path.join(data_folder,'shapefile','BSS.shp')
        bss_fr = gpd.read_file(bss_shp)
        bss_fr.to_crs(epsg=2154, inplace=True)
        bss = gpd.clip(bss_fr, watershed)
        self.codes_bss_discrete = bss['indice'][bss['cote_eau'] != 0].tolist()
        self.date_discrete = bss['date_eau_s'][bss['cote_eau'] != 0].tolist()
        self.elevation_discrete = bss['cote_eau'][bss['cote_eau'] != 0].tolist()
        self.depth_discrete = bss['prof_eau_s'][bss['cote_eau'] != 0].tolist()
        self.x_coord_discrete = bss['x_ref06'][bss['cote_eau'] != 0].tolist()
        self.y_coord_discrete = bss['y_ref06'][bss['cote_eau'] != 0].tolist()
        self.x_iloc_discrete = []
        self.y_iloc_discrete = []
        for i in range(0, len(self.x_coord_discrete)):
            idx = (np.abs(geographic.x_coord - self.x_coord_discrete[i])).argmin()
            idy = (np.abs(geographic.y_coord- self.y_coord_discrete[i])).argmin()
            self.x_iloc_discrete.append(idx)
            self.y_iloc_discrete.append(idy)
        bss.to_file(os.path.join(data_folder,'shapefile','piezos_discrete.shp'))
        
        return piezos
    
    #%% DOWNLOAD PIEZOMETRY ON THE WEB 
    
    def extract_data_from_code_bss(self,data_folder):
        for code in self.codes_bss:
            code_ = code.replace('_','/')
            print('          '+code)
            if not os.path.exists(data_folder+'/'+code):
                url = 'https://ades.eaufrance.fr/Fiche/PtEau?Code=' + code_
                chrome_options = webdriver.ChromeOptions()
                prefs = {'download.default_directory' : data_folder.replace('/','\\')}
                chrome_options.add_experimental_option('prefs', prefs)
                driver = webdriver.Chrome(options=chrome_options)
                driver.get(url)
                try:
                    elem = driver.find_element_by_link_text('Tout télécharger')
                    elem.click()
                    compt = 0
                    while (compt==0):
                        if len(glob.glob(os.path.join(data_folder,'*.zip'))) == 1:
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
            desc_file = os.path.join(data_folder,code,'ades_export','Descriptif','descriptif.txt')
            df1 = pd.read_csv(desc_file, delimiter = '|',header=0, engine='python', encoding='latin1')
            self.depth_well.append(df1['Profondeur investigation maximale'][0])
            self.elevation_well.append(df1['Altitude'][0])
            file = os.path.join(data_folder, code, 'ades_export','Quantite','chroniques.txt')
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

    #%% ADD OWN MANUAL DATA

    def add_data(self):
        files = glob.glob(os.path.join(self.out_path, 'results_stable/add_data/piezometry_*.csv'))
        if len(files)>0:
            for file in files:
                file1 = file.split('piezometry')[-1].split('.csv')[0].split('_')
                self.codes_bss.append(file1[1])
                self.x_coord.append(float(file1[2]))
                self.y_coord.append(float(file1[3]))
                self.elevation_well.append(float(file1[4]))
                self.depth_well.append(float(file1[5]))
                idx = (np.abs(self.geo_x_coord- int(file1[2]))).argmin()
                idy = (np.abs(self.geo_y_coord- int(file1[3]))).argmin()
                self.x_iloc.append(idx)
                self.y_iloc.append(idy)
                df = pd.read_csv(file, delimiter = ';',header=0, engine='python', encoding='latin1')
                df.columns = ['Date', file1[1]]
                df.index = pd.to_datetime(df['Date'],format='%d/%m/%Y %H:%M')
                df = df.drop(['Date'], axis=1)
                self.elevation = pd.concat([self.elevation, df], axis=1).sort_index()
            df = pd.DataFrame({'code_bss': self.codes_bss, 'X': self.x_coord, 'Y': self.y_coord})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.X, df.Y))
            gdf.to_file(self.piezos_shp)
        
    #%% DISPLAY PLOT
    
    def display_data(self,value='elevation',start=None,end=None):
        fontprop = toolbox.plot_params(15,15,18,20)
        values_list = ['elevation','depth']
        if value not in values_list:
            print('You must specify the value you want to display: elevation or depth')
        fig, ax = plt.subplots(figsize=(7,7))
        colors = plt.cm.rainbow(np.linspace(0, 1, len(self.codes_bss)))
        if len(self.codes_bss) == 6:
            colors = ['r','m','y','g','k','b']
        if value =='elevation':
            interp_elev = self.elevation[start:end].interpolate() #linear interpolation of NaN values (in case several piezometers are logging non synchronized)
            interp_elev.plot(ax=ax,color=colors,lw=2)
            #df = pd.DataFrame({'Date': [datetime.strptime(date, '%d/%m/%Y')for date in self.date_discrete], 'elevation_discrete': self.elevation_discrete})
            #df = df.set_index('Date')
            #df.plot(ax=ax,style='ok')
            plt.ylabel('Elevation [m asl]')
        plt.legend(loc='best')
        plt.xlabel('Date')
    
        plt.tight_layout()
        name_out = os.path.join(self.figure_folder,'plot')
        fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')

#%% NOTES

