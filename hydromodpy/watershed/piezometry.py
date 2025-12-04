# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
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
import matplotlib.pyplot as plt
import whitebox
from pyproj import Transformer
from shapely.geometry import Polygon, Point
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
import requests

logger = get_logger(__name__)

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
    
    def __init__(self, out_path: str, geographic: object):
        """
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs.
        geographic : object
            Variable object of the model domain (watershed).
        """
        logger.info('Extracting piezometry dataset for watershed')
        
        data_folder = os.path.join(out_path,'results_stable','piezometry')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.figure_folder = os.path.join(out_path,'results_stable','_figures','piezometry')
        if not os.path.exists(self.figure_folder):
            os.makedirs(self.figure_folder)  
        # if not os.path.exists(os.path.join(data_folder,'shapefile','BSS.shp')):
        #    self.download_init_data(data_folder, geographic)
        self.out_path = out_path
        self.geo_x_coord = geographic.x_coord
        self.geo_y_coord = geographic.y_coord
        self.crs_proj = geographic.crs_proj
        self.x_coord = []
        self.y_coord = []
        self.x_coord_wgs84 = []
        self.y_coord_wgs84 = []
        self.x_iloc = []
        self.y_iloc = []
        self.codes_bss = []
        self.depth_well = []
        self.start_date = []
        self.end_date = []
        self.elevation_well = []
        self.extract_piezos_from_watershed(data_folder, geographic)
        self.piezos_shp = os.path.join(data_folder,'shapefile','piezos.shp')
        #if os.path.exists(os.path.join(data_folder,'shapefile','piezos.shp')):
        #    self.extract_data_from_code_bss(data_folder)
        self.load_piezometric_data(data_folder)
    
    #%% DOWNLOAD PIEZOMETERS ID AT FRANCE SCALE
    
    def download_init_data(self, data_folder, geographic):
        """
        Download France piezometric data with API.

        Parameters
        ----------
        data_folder : str
            Path of stable results for piezometry.
        """
        #ADES continue data
        filename = os.path.join(data_folder, 'piezometers.zip')
        folder = os.path.join(data_folder, 'shapefile')
        url = 'https://www.data.gouv.fr/fr/datasets/r/f10f3f18-eac3-4cee-b178-4c577c4fd689'
        if not os.path.exists(folder):
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
                urllib.request.urlretrieve(url, filename)
                with zipfile.ZipFile(filename, 'r') as zip_ref:
                    zip_ref.extractall(folder)
                os.remove(filename)
            except:
                pass
            
        #BSS discrete data
        filename = data_folder + 'BSS.zip'
        folder = os.path.join(data_folder, 'shapefile')
        #if not os.path.exists(os.path.join(folder,"BSS.shp")):
        bss = 'bss_export_' + str(geographic.dep_code) + '.zip'
        bss_csv = 'bss_export_' + str(geographic.dep_code) + '.csv'
        url = 'http://infoterre.brgm.fr/telechargements/ExportsPublicsBSS/' + bss
        #url = 'http://data.cquest.org/brgm/banque_sous_sol/' + bss
        logger.debug('BSS piezometric archive page loaded')
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
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x_ref06, df.y_ref06), crs="EPSG:2154")
        gdf.to_file(os.path.join(folder,"BSS.shp"))
        os.remove(os.path.join(folder, bss_csv))
            
    #%% CLIP DATA AT THE CATCHMENT SCALE
    
    def extract_piezos_from_watershed(self, data_folder, geographic):
        """
        Clip piezoemeters at the model domain (watershed) scale.
        
        Returns
        -------
        piezos : shapefile
            Piezometer clipping points.
        """
        folder = os.path.join(data_folder, 'shapefile')
        if not os.path.exists(folder):
            os.mkdir(folder)
        
        wgs_coord = str(geographic.ll_long_lat[1])+','+str(geographic.ll_long_lat[0])+',' + str(geographic.ur_long_lat[1])+',' + str(geographic.ur_long_lat[0])
        url = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations?bbox="+wgs_coord
        reponse = requests.get(url)
        self.piezos = reponse.json()
        
        crs_proj = "epsg:4326"
        try:
            if self.piezos['count'] > 0: 
                for i in range(0, self.piezos['count']):
                    self.codes_bss.append(self.piezos['data'][i]['code_bss'])
                    self.x_coord_wgs84.append(self.piezos['data'][i]['geometry']['coordinates'][0])
                    self.y_coord_wgs84.append(self.piezos['data'][i]['geometry']['coordinates'][1])
                    self.depth_well.append(self.piezos['data'][i]['profondeur_investigation'])
                    self.elevation_well.append(self.piezos['data'][i]['altitude_station'])
                
                    transformer = Transformer.from_crs(crs_proj,geographic.crs_proj)
                    self.xy_coord= transformer.transform(self.y_coord_wgs84[i], self.x_coord_wgs84[i])
                    self.x_coord.append(self.xy_coord[0])
                    self.y_coord.append(self.xy_coord[1])
                    self.start_date.append(self.piezos['data'][i]['date_debut_mesure'])
                    self.end_date.append(self.piezos['data'][i]['date_fin_mesure'])
            
                for i in range(0, len(self.x_coord)):
                    idx = (np.abs(geographic.x_coord- self.x_coord[i])).argmin()
                    # index is determined by lowest difference between piezometer coordinate and model cell coordinate
                    idy = (np.abs(geographic.y_coord- self.y_coord[i])).argmin()
                    self.x_iloc.append(idx)
                    self.y_iloc.append(idy) 
            
            
            piezos = []
            for i in range(0, self.piezos['count']):
                piezos.append([self.codes_bss[i], Point([self.x_coord[i],self.y_coord[i]])])
            shp_piezo = gpd.GeoDataFrame(
                data=piezos,
                columns=['code_bss', 'geometry'],
                crs=self.crs_proj,
            )
            shp_piezo.to_file(os.path.join(data_folder, 'shapefile','piezos.shp'))
        except:
            pass
        
        """
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
        """
        
        #return piezos
    
    #%% DOWNLOAD PIEZOMETRY ON THE WEB 
    
    def extract_data_from_code_bss(self, data_folder):
        """
        Function to download data on BRGM site.
        """
        for code in self.codes_bss:
            code_ = code.replace('_','/')
            logger.debug('Downloading piezometer %s', code)
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

    def load_piezometric_data(self, data_folder):
        """
        Function to transform data from downloaded data.
        """
        self.depth = pd.DataFrame()
        self.elevation = pd.DataFrame()
        
        url = 'https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques?code_bss='
        for i in range(0,len(self.codes_bss)):
            code = self.codes_bss[i]
            time = []
            elev = []
            prof = []
            
            start = int(self.start_date[i].split('-')[0])
            end = int(self.end_date[i].split('-')[0])
            years = np.linspace(start,end, end-start+1)
            for y in years :
                url1 = url + code + '&date_debut_mesure=' + str(int(y)) + '-01-01&date_fin_mesure=' + str(int(y+1))+'-01-01'
                reponse = requests.get(url1)
                self.piezos = reponse.json()
                for d in range(0,len(self.piezos['data'])):
                    time.append(self.piezos['data'][d]['timestamp_mesure'])
                    elev.append(self.piezos['data'][d]['niveau_nappe_eau'])
                    prof.append(self.piezos['data'][d]['profondeur_nappe'])
            
            depth = pd.DataFrame({'Date':time,'Mesure':prof})
            depth.index = pd.to_datetime(depth['Date'], unit='ms')
            depth = depth.drop(['Date'], axis=1)
            depth.columns = [code]
            self.depth = pd.concat([self.depth, depth], axis=1).sort_index()
            elevation = pd.DataFrame({'Date':time,'Mesure':elev})
            elevation.index = pd.to_datetime(elevation['Date'], unit='ms')
            elevation = elevation.drop(['Date'], axis=1)
            elevation.columns = [code]
            self.elevation = pd.concat([self.elevation, elevation], axis=1).sort_index()
        
        """
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
        """
    #%% ADD OWN MANUAL DATA

    def add_data(self):
        """
        Function to add manual data from a .csv file.
        This file should contain list of coordinate points.
        """
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
                try:
                    df.index = pd.to_datetime(df['Date'],format='%d/%m/%Y %H:%M')
                except:
                    df.index = pd.to_datetime(df['Date'],format='%d/%m/%Y %H:%M:%S')
                df = df.drop(['Date'], axis=1)
                self.elevation = pd.merge(self.elevation, df, left_index=True, right_index=True, how='outer') #pd.concat([self.elevation, df], axis=1).sort_index()
            df = pd.DataFrame({'code_bss': self.codes_bss, 'X': self.x_coord, 'Y': self.y_coord})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.X, df.Y), crs=self.crs_proj)
            gdf.to_file(self.piezos_shp)
        
    #%% DISPLAY PLOT
    
    def display_data(self, value='elevation', start=None, end=None):
        """
        Parameters
        ----------
        values : str, optional
            Type of plot required : 'elevation' or 'depth'. The default is 'elevation'.
        start : float, optional
            Start elevation value for interpolation. The default is None.
        end : float, optional
            End elevation value for interpolation. The default is None.
        """
        fontprop = toolbox.plot_params(15,15,18,20)
        values_list = ['elevation','depth']
        if value not in values_list:
            logger.error('Unsupported piezometry display value: %s', value)
        fig, ax = plt.subplots(figsize=(7,4))
        colors = plt.cm.rainbow(np.linspace(0, 1, len(self.codes_bss)))
        if len(self.codes_bss) == 6:
            colors = ['r','m','y','g','k','b']
        if value =='elevation':
            interp_elev = self.elevation[start:end].interpolate() #linear interpolation of NaN values (in case several piezometers are logging non synchronized)
            interp_elev.plot(ax=ax,color=colors,lw=2)
            #df = pd.DataFrame({'Date': [datetime.strptime(date, '%d/%m/%Y')for date in self.date_discrete], 'elevation_discrete': self.elevation_discrete})
            #df = df.set_index('Date')
            #df.plot(ax=ax,style='ok')
            plt.ylabel('Elevation [m.a.s.l]')
        plt.legend(loc='best')
        plt.xlabel('Date')
    
        plt.tight_layout()
        name_out = os.path.join(self.figure_folder,'plot')
        # fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')

#%% NOTES
