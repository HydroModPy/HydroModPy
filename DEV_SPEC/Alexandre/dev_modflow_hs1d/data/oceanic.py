import os
import numpy as np
import pandas as pd
import geopandas as gpd
from netCDF4 import Dataset
import data.display_oceanic as display_oceanic

class Oceanic:
	def __init__(self, out_path, geographic, oceanic_path):
		print('Extraction des données océaniques')
		self.figure_folder = out_path + 'figures/oceanic/'
		if not os.path.exists(self.figure_folder):
				os.makedirs(self.figure_folder)
		self.mean_sea_level(geographic,oceanic_path)
		self.rise_sea_level(geographic, oceanic_path)

	def mean_sea_level(self,geographic,oceanic_path):
		ram_path = oceanic_path+"/RAM_2020.shp"
		gdf = gpd.read_file(ram_path)
		ports = gdf.to_crs(epsg=2154)
		ports = ports.dropna(subset=['NM', 'ZH_Ref'])
		ports = ports.reset_index()
		dist = np.sqrt((geographic.centroid[0]-ports.geometry.x.values)**2+(geographic.centroid[1]-ports.geometry.y.values)**2)
		index = (np.abs(dist)).argmin()
		self.port = ports.SITE[index]
		self.MSL = ports.NM[index]/100+ports.ZH_Ref[index]

	def rise_sea_level(self, geographic, oceanic_path):
		xidx, yidx = self.idx_from_global_map(oceanic_path+'/rsl_ts_26.nc',geographic)
		scenarios = ['RCP2.6','RCP4.5','RCP8.5']
		rsl_name = {'RCP2.6':'rsl_ts_26.nc',
					'RCP4.5':'rsl_ts_45.nc',
					'RCP8.5':'rsl_ts_85.nc'}
		self.RSL = {}
		self.RMSL = {}
		for sce in scenarios:
			nc = Dataset(oceanic_path+'/'+rsl_name[sce], "r", format="NETCDF4")
			date = np.array(nc.variables['time'][:])
			df = pd.DataFrame(date, columns=["date"])
			df.index = pd.to_datetime(df['date'],format='%Y')
			df = df.drop(['date'], axis=1)
			v = []; vh = []; vl = []; vstdh = []; vstdl = []
			for i in range(0, len(nc.variables['time'][:])):
				med = nc.variables['slr_md'][i][yidx][xidx]
				v.append(med)
				high = nc.variables['slr_he'][i][yidx][xidx]
				vh.append(med+(1.645*high))
				vstdh.append(med+high)
				low = nc.variables['slr_le'][i][yidx][xidx]
				vstdl.append(med-low)
				vl.append(med-(1.645*low))

			df['median'] = v
			df['std high'] = vstdh
			df['std low'] = vstdl
			df['95th per'] = vh
			df['5th per'] = vl

			df1 = df.copy()
			df1 = df1 - df1['median'].loc['2020'].values[0] + self.MSL

			df = df.resample('D')
			df = df.interpolate(method='linear')
			df1 = df1.resample('D')
			df1 = df1.interpolate(method='linear')
			self.RSL[sce] = df
			self.RMSL[sce] = df1

	def idx_from_global_map(self, path, geographic):
		nc = Dataset(path, "r", format="NETCDF4")
		find_idx = np.zeros((np.shape(nc.variables['slr_md'][0])[0]*np.shape(nc.variables['slr_md'][0])[1],5))
		compt = 0
		for x in range(0,np.shape(nc.variables['slr_md'][0])[1]):
			for y in range(0,np.shape(nc.variables['slr_md'][0])[0]):
				find_idx[compt,:] = [x,y,nc.variables['x'][x].data.item(),nc.variables['y'][y].data.item(),nc.variables['slr_md'][0][y][x]]
				compt +=1
		find_idx = find_idx[~np.isnan(find_idx).any(axis=1)]
		distance = np.sqrt((find_idx[:,3]-geographic.centroid_long_lat_Greenwich[0])**2+(find_idx[:,2]-geographic.centroid_long_lat_Greenwich[1])**2)
		idx = distance.argmin()
		xidx = find_idx[idx][0]
		yidx = find_idx[idx][1]
		return int(xidx), int(yidx)

	def display_data(self, values):
		values_list = ['RMSL','RSL']
		if values not in values_list:
			print('You must specify the values you want to display')
		if values =='RMSL':
			display_oceanic.display_data(self.RMSL,self.figure_folder+'RMSL')
		if values =='RSL':
			display_oceanic.display_data(self.RSL,self.figure_folder+'RSL')

