# -*- coding: utf-8 -*-
"""
@author: Ronan Abhervé
"""

#%% LIBRAIRIES

# First : pip install dbfread

import os
import sys
import UtilsDBF
import UtilsNCDF
import UtilsBIN
import pandas as pd
import geopandas as gpd  
from glob import glob
import matplotlib.pyplot as plt
import numpy as np
import deepdish as dd

#%% CLASS

class extract_surfex:

	"""
   This class allows to convert binary file data form ftp aquifr to a summary file .h5 (netcdf)
   Name the output file 'REA.h5' in order to use the class in safransurfex.py and
   Use BV.add_safransurfex(folder_path_with_the_REA.h5_inside):
       clipping automatically with BV box buff area
       output automatically in 'climatic' results_stable

	Extract Safran-Surfex data from TEXT or BINARY files (ftp aquifr)
     shapefile: str path of the shapefile for clipping
     cells_number: define the cells to extract
     variables saved:
        		- REC: Recharge
             - RUN: Runoff
             - ETP: Evaportanspiration
             - PPT: Precipitation
             - TAS: Temperature
             - SNOW: Snow
	save_data: save data of not
	ouput_path: str of the output directory
	"""
    
	def __init__(self, path=os.getcwd(), shapefile=None, cells_number=None, save_data=True, output_path=os.getcwd()+'/'+'OUTPUT.h5'):		
		# self.path = os.getcwd()
		self.path = path
		self.fold_data = self.path # ROOT FOLDER
     ##############################################
     ### RESPECT THIS FORMAT/STRUCTURE FOR INPUT DATA FROM FTP AQUIFR OR CHANGE THE PATH FUNCTION 
		self.fold_mesh = self.path + '/MESH/' # MESH FOLDER
		self.fold_safran = self.fold_data + '/SAFRAN_DCSC_ORIG/' # SAFRAN FOLDER
		self.fold_surfex = self.fold_data + '/SURFEX_SAFRAN/' # ISBA FOLDER
		self.fmesh = self.fold_mesh + '/maille_meteo_fr_pr93.dbf' # France scale mesh
		self.mesh_tot = self.fold_mesh + '/maille_meteo_fr_pr93.shp' # France scale mesh
		self.mesh_clip = self.fold_mesh + '/CLIP/' + 'maille_meteo_fr_pr93_clip.shp'   
     ##############################################
		self.output_path = output_path
		self.extract_surfex_mesh()
		if shapefile == None and cells_number == None:
			print("Need to specify shapefile or cells_numbers parameters")
		if shapefile != None:
			self.extract_cells_from_shapefile(shapefile)
		else:
			self.cells_list = cells_number
		self.extract_cols
		try:
			self.extract_safran()
		except:
			pass
		self.extract_isba()
		self.var_list = ['SNOW','PPT','ETP','TAS','RUN','REC']
		if save_data == True:
 			self.save_storage_data()
		
	def extract_surfex_mesh(self):
		self.surfex_mesh = UtilsDBF.load_dbf(self.fmesh) #Extract surfex mesh
		self.surfex_ids = UtilsDBF.build_ids_list(self.surfex_mesh) #Create surfex cells ids
		self.meshgrid = UtilsDBF.build_grid(self.surfex_mesh) #Create surfex grid
		return self

	def extract_cells_from_shapefile(self, shpnam):
		""" CRS : 2154 (RGF 93) """
		mask = gpd.read_file(shpnam , encoding="utf-8") # shapefile mask
		mesh = gpd.read_file(self.mesh_tot, encoding="utf-8") # shapefile to mask
		intersect = gpd.clip(mesh, mask)
		intersect.to_file(self.mesh_clip) # shapefile out
		self.cells_list = intersect.num_id.to_list() # wanted Surfex cells list
		self.x_cells, self.y_cells = UtilsDBF.identify_cell(self.meshgrid, self.cells_list, self.surfex_ids)
		return self

	def extract_cols(self, VAR, cells_list):
		var=[]
		for i in cells_list:
		    var.append(VAR.iloc[:, i-1])     
		var = np.array(var)
		var[var>1e+10] = np.nan
		var = pd.DataFrame(var.T, columns=cells_list).apply(pd.to_numeric)
		return var

	def extract_safran(self):
		self.safran_list = ['SNOW','PPT','ETP','TAS']
		self.storage_data = {}
		self.list_safran = glob(self.fold_safran + 'RR*')
# 		self.list_safran = self.list_safran[0:5]
		for i in self.list_safran:
# 			if i == self.list_safran[0]:
				print(i)
				data = pd.read_csv(i, sep=';', header=None)
				start = i.split('\\')[-1].split('.')[0].split('_')[-2]
				start = start[:4] + '-' + start[4:6] + '-' + start[6:]
				end = i.split('\\')[-1].split('.')[0].split('_')[-1]
				end = end[:4] + '-' + end[4:6] + '-' + end[6:]
				times = pd.date_range(start=start, end=end)
				self.SNOW,self.PPT,self.ETP,self.TAS = tuple(np.transpose(data.iloc[:,2:].values.reshape((-1,9892,4)),[2,0,1]))
				self.array_list = [self.SNOW,self.PPT,self.ETP,self.TAS]
				   
				for array, var in zip(self.array_list,self.safran_list):
					print(var)
					VAR = pd.DataFrame(np.array(array).byteswap().newbyteorder()).apply(pd.to_numeric)
					VAR_cells = self.extract_cols(VAR, self.cells_list)
					VAR_cells['englobe'] = np.nanmean(VAR_cells, axis=1) # mean to study site zone
					VAR_cells['date'] = pd.Series(times)
					VAR_cells = VAR_cells.set_index('date')
					if i == self.list_safran[0]:
						self.storage_data[str(var)] = VAR_cells
					else:
						self.storage_data[str(var)] = self.storage_data[str(var)].append(VAR_cells, ignore_index=False)   		    
		return self

	def extract_isba(self):
		self.isba_list = ['RUN','REC']
		for it in self.isba_list:
			print(it)
			if it == 'RUN':
				self.list_isba = glob(self.fold_surfex + 'RUNOFF*')
# 				self.list_isba = self.list_isba[0:5]
			if it == 'REC':
				self.list_isba = glob(self.fold_surfex + 'DRAIN*')
# 				self.list_isba = self.list_isba[0:5]
			for i in self.list_isba:
# 				if i == self.list_isba[0]:
					print(i)
					var = np.fromfile(i,'>f4').reshape((-1,9892))
					start = i.split('\\')[-1].split('_')[-2]
					start = start + '-08' + '-01'
					end = i.split('\\')[-1].split('_')[-1]
					end = end + '-08' + '-01'
					times = pd.date_range(start=start, end=end, freq="1h")
					var = pd.DataFrame(np.array(var).byteswap().newbyteorder()).apply(pd.to_numeric)
					var_cells = self.extract_cols(var, self.cells_list)
					var_cells['englobe'] = np.nanmean(var_cells, axis=1) # mean to study site zone
					var_cells['date'] = pd.Series(times[:-1])
					var_cells = var_cells.set_index('date')
					var_cells = var_cells.diff()
					var_cells = var_cells.resample('D').sum() # mm/hour to mm/day
					if i == self.list_isba[0]:
						self.storage_data[str(it)] = var_cells
					else:
						self.storage_data[str(it)] = self.storage_data[str(it)].append(var_cells, ignore_index=False)   
		return self
    
	def save_storage_data(self):
		try:
 			os.remove(self.output_path)
		except:
 			pass
		h5file = (self.output_path)
		for var in self.var_list:
			try:
				self.storage_data[var].to_hdf(h5file, var+'/historic')
			except:
				pass
		return

#%% LAUNCH

extract_surfex(path='H:/SURFEX_CLIMATE_DATA/FTP_ISBA/', # ROOT FOLDER WITH FTP DATA
               # shapefile='C:/Users/Ronan/GitHub/HydroModPy-dev/users/ftp_aquifr_isba/polyg_meteo_fr_pr93.shp', # SHAPEFILE FOR CLIPPING
               shapefile=None,
               cells_number=list(np.arange(0,9892,1)), # SELECT THE CELLS TO KEEP : 9892 is all the cells
               # cells_number=None,
               save_data=True,
               output_path='C:/Users/Ronan/Downloads/REA.h5' # FOLDER TO STORE OUTPUT
               )

#%% CONTROL

"""
h5 = dd.io.load('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_h5_safransurfex/lasset/REA.h5')

fig, ax = plt.subplots(figsize=(10,5))
couleurs = ['navy','dodgerblue']
for i, j in enumerate(['RUN','REC']):
    xv = h5[j]['historic']
    ax.plot(xv['englobe'], c=couleurs[i], label=j)
    ax.set_ylim(0,30)
    ax.legend(loc='lower left')
    # ax.set_yscale('log')
"""
