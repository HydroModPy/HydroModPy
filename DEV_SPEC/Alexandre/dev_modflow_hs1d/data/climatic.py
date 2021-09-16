# coding:utf-8

import geopandas as gpd
import pandas as pd
import data.display_climatic as display_climatic 
import os 

class Climatic:
	def __init__(self,out_path, surfex_path, watershed_shp):
		data_folder = out_path + '/data/climatic/'
		if not os.path.exists(data_folder):
				os.makedirs(data_folder)
		self.figure_folder = out_path + '/figures/climatic/'
		if not os.path.exists(self.figure_folder):
				os.makedirs(self.figure_folder)
		print('Extraction des données climatiques')
		self.extract_cells_from_shapefile(surfex_path, watershed_shp)
		self.extract_values_from_h5file(data_folder, surfex_path)
        
		self.display_all_variables(model='REA', start='1960', end='2010')

	def extract_cells_from_shapefile(self, surfex_path, watershed_shp):
		mesh_path = surfex_path + '/shapefile/maille_meteo_fr_pr93.shp'
		mask = gpd.read_file(watershed_shp , encoding="utf-8")
		mesh = gpd.read_file(mesh_path, encoding="utf-8") 
		intersect = gpd.clip(mesh, mask)
		self.cells_list = intersect.num_id.to_list() # wanted Surfex cells list
		return self

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
					display_climatic.display_all_variables(self.values,self.figure_folder, i, start, end)

			display_climatic.display_all_variables(self.values,self.figure_folder, model, start, end)

	def display_intermensual_scenarios(self, var=None):
		mod_list = ['all','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']		
		var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
		if var == None or (var not in var_list):
			print('You must specify the variable you want to display')
		else:
			if var == 'all':
				for i in mod_list:
					display_climatic.display_intermensual_scenarios(self.values,self.figure_folder, i)

			display_climatic.display_intermensual_scenarios(self.values,self.figure_folder, var)

	def display_annual_scenarios(self, var=None):
		mod_list = ['all','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']
		var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
		if var == None or (var not in var_list):
			print('You must specify the variable you want to display')
		else:
			if var == 'all':
				for i in mod_list:
					display_climatic.display_annual_scenarios(self.values,self.figure_folder, i)
			else:
				display_climatic.display_annual_scenarios(self.values,self.figure_folder,var)

	def display_anomaly(self, mod=None ,var=None, per_hist=[1950,2005], per_fut=  [[2006,2020],[2021,2035],[2036,2050],[2051,2100]]):
		var_list = ['all','TAS','PPT','ETP','RUN','REC','SNOW']
		mod_list = ['all','ACC1','BCC1','BNU1','CAN1','CAN2','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1','REA']
		if var == None or mod==None or (var not in var_list) or (mod not in mod_list):
			print('You must specify the variable/model you want to display')
		else:
			display_climatic.display_anomaly(self.values,self.figure_folder, mod ,var, per_hist=per_hist, per_fut= per_fut)
