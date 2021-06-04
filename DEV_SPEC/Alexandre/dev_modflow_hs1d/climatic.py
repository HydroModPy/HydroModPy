# coding:utf-8

import pandas as pd

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


	


