# coding:utf-8

import os
import sys
import pandas as pd


class Params:
	"""
	A class used to create hydraulic parameters of the watershed

	Attributes
	----------
	geology_code: list of int
		geological codes from geology python object (geology.geology_code)
		
	Returns
	----------
	names : list of str
		the name of each parameter
	geo_codes : list of str
		the geological code of each parameter
	types : list of str
		the type of each parameter
	units : list of str
		the unit of each parameter

	Methods
	-------
	CreateParams(geology_code, folder)
		Create and save parameters
	
	"""
	
	def __init__(self, geology_code, folder):
		"""
		Constructor
		
		Parameters
		----------
		geology_code : list of int
			geological codes from geology python object
		folder : str
			the path where we save the params file
		"""
		
		self.names = []
		self.geo_codes = []
		self.types = []
		self.units = []
		
		self.CreateParams(geology_code, folder)
		
	def CreateParams(self, geology_code, folder):
		"""
		Load hydraulic parameters
		Parameters
		----------
		geology_code : list of int
			geological codes from geology python object
		folder : str
			the path where we save the params file
		"""
		list_params = ['K','Phi'] # add E : thickness ?
		for i in list_params:
			for j in range(1, len(geology_code)+1):
				self.names.append(i+str(j))
				self.geo_codes.append(geology_code[j-1])
				if i == 'K':
					self.types.append('Hydraulic Conductivity')
					self.units.append('m/s')
				elif i == 'Phi':
					self.types.append('Porosity')
					self.units.append('-')
				elif i == 'E':
					self.types.append('Thickness')
					self.units.append('m')
		
		self.store = pd.DataFrame({'names': self.names,'geo_codes': self.geo_codes,'types': self.types, 'units': self.units})
		self.store.to_csv(folder + 'params.csv',header=False, index=False)
		
	
	def LoadParams(self):
		"""
		Load hydraulic parameters

		Parameters
		----------
		sound : str, optional
			The sound the animal makes (default is None)

		Returns
		------
		NotImplementedError
			If no sound is set for the animal or passed in as a
			parameter.
		"""
		
		