# coding:utf-8
import geopandas as gpd
import pandas as pd
import os 


class extract:
	def __init__(self,out_path, surfex_path, watershed_shp):
		data_folder = out_path + 'data/climatic/'
		if not os.path.exists(data_folder):
				os.makedirs(data_folder)

		self.extract_cells_from_shapefile(surfex_path, watershed_shp)
		self.extract_values_from_h5file(data_folder, surfex_path)

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
		simulations = ['REA','ACC1','BCC1','BNU1','CAN3','CAN4','CAN5','CNR1','CSI1','IPS1','MIR1','MIR2','MIR3','NOR1']
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
						values = values.iloc[:,self.cells_list]
						values['MEAN'] = values.mean(numeric_only=True, axis=1)
						values.to_hdf(h5file, var+'/'+sce)
						self.values[sim][var][sce] = values
					except:
						pass

class surfex:
	def __init__(self, h5_path, sim='ACC1', var='REC', sce='historic', resample='D', start_date=None, end_date=None):
		self.h5_path = h5_path
		self.sim = sim
		self.var = var
		self.sce = sce
		self.key = sim + '/' + var + '/' + sce
		self.resample = resample
		self.load_h5file()
		if start_date != None:
			self.start_date = start_date
		else:
			self.start_date = self.data.index[0]
		if end_date != None:
			self.end_date = end_date
		else:
			self.end_date = self.data.index[-1]
		self.extract_period()
		if self.resample != 'D':
			self.resample_data()

	def load_h5file(self):
		self.data = pd.read_hdf(self.h5_path,self.key)

	def extract_period(self):
		self.period_data = self.data[self.start_date:self.end_date].englobe

	def resample_data(self):
		self.period_data = self.data.resample(self.resample).mean().englobe

