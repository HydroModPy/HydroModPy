# coding:utf-8
import os
import urllib
import zipfile
import geopandas as gpd
from selenium import webdriver
import pandas as pd
import time
import glob

class extract:
	def __init__(self, out_path, geographic):
		data_folder = out_path + 'data/piezometric/'
		if not os.path.exists(data_folder):
				os.makedirs(data_folder)	
		self.download_init_data(data_folder)
		self.exctract_piezos_from_watershed(data_folder, geographic)
		self.extract_data_from_code_bss(data_folder)
		self.load_piezometric_data(data_folder)

	def download_init_data(self,data_folder):
		filename = data_folder + 'piezometers.zip'
		folder = data_folder + '/' + 'shapefile'
		url = 'https://www.data.gouv.fr/fr/datasets/r/509bbb07-e375-45a2-81ac-c17820f57546'
		if not os.path.exists(folder):
			urllib.request.urlretrieve(url, filename)
			with zipfile.ZipFile(filename, 'r') as zip_ref:
				zip_ref.extractall(data_folder + '/' + 'shapefile')
			os.remove(filename)
		return

	def exctract_piezos_from_watershed(self,data_folder, geographic):
		watershed = gpd.read_file(geographic.watershed_box_shp)
		piezos_shp = data_folder + 'shapefile/point_eau_piezo.shp'
		piezos_fr = gpd.read_file(piezos_shp)
		piezos_fr.to_crs(epsg=2154, inplace=True)
		piezos = gpd.clip(piezos_fr, watershed)
		piezos.to_file(data_folder + 'shapefile/piezos.shp')
		self.codes_bss = piezos['code_bss'].tolist()
		for i in range (0, len(self.codes_bss)):
			self.codes_bss[i] = self.codes_bss[i].replace('/','_')
		self.x_coord = piezos['geometry'].x.tolist()
		self.y_coord = piezos['geometry'].y.tolist()

	def extract_data_from_code_bss(self,data_folder):
		for code in self.codes_bss:
			code_ = code.replace('_','/')
			url = 'https://ades.eaufrance.fr/Fiche/PtEau?Code=' + code_
			chrome_options = webdriver.ChromeOptions()
			prefs = {'download.default_directory' : data_folder.replace('/','\\')}
			chrome_options.add_experimental_option('prefs', prefs)
			driver = webdriver.Chrome(chrome_options=chrome_options)
			driver.get(url)
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

	def load_piezometric_data(self,data_folder):
		self.depth = pd.DataFrame()
		self.elevation = pd.DataFrame()
		for code in self.codes_bss:
			file = data_folder + code + '/ades_export/Quantite/chroniques.txt'
			df = pd.read_csv(file, delimiter = '|',header=0, engine='python')
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

			











		
