# coding:utf-8

import os
import sys
import flopy
import numpy as np
import topography
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class modflow_model:
	"""
	model_name
	model_path
	dem : path of dem file (.tif)
	climatic : float or Dataframe Datatimeseries
	lay_number: int - number of layer - default is 1
	thickness_aquifer: float
	cond_hyd :
		- homogeneous : float
		- heterogeneous : numpy array (same size as the dem)
	porosity: :
		- homogeneous : float
		- heterogeneous : numpy array (same size as the dem)
	"""
	def __init__(self, dem_path, watershed='name', climatic=8e-4, lay_number=1, thick=100, hyd_cond=8.64e-2, porosity=0.01, coastal_aquifer=False,
				 model_name='modflow_model', model_folder=os.path.dirname(os.getcwd())+'\\output\\', exe=os.path.dirname(os.getcwd()) + '\\bin\\'+'mfnwt.exe'):
		self.watershed = watershed
		self.model_name = model_name
		self.model_folder = model_folder
		self.dem_path = dem_path
		self.climatic = climatic
		self.thick = thick
		self.nlay = lay_number
		self.hyd_cond = hyd_cond
		self.porosity = porosity
		self.dem = topography.dem(self.dem_path)
		self.exe = exe
		self.build_modflow_model()

	def build_modflow_model(self):
		self.mf = flopy.modflow.Modflow(self.model_name, 
										exe_name=self.exe, version='mfnwt',listunit=2, verbose=False,
										model_ws=self.model_folder+self.watershed+'\\'+self.model_name+'\\modraw\\')
		self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=1000, thickfact=1e-05, linmeth=1,iprnwt=0,ibotav=0, options='COMPLEX')
		
		if len(self.climatic)==1:
			self.nper = 1
			self.perlen = 1
			self.nstp = [1]
			self.steady = True
		else:
			self.steady = np.zeros(len(self.climatic),dtype=bool)
			self.steady[0] = True
			self.nstp = np.ones(len(self.climatic))
			self.nper = len(self.climatic)
			self.perlen = np.ones(len(self.climatic))
			for i in range(1,len(self.climatic)):
				dif = self.climatic.index[i]-self.climatic.index[i-1]
				self.perlen[i] = dif.days

		self.nrow = self.dem.data.shape[0]
		self.ncol = self.dem.data.shape[1]
		thick_lay = self.thick / self.nlay
		self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
		for i in range (1,self.nlay+1):
			self.zbot[i-1] = self.dem.data - (thick_lay*i)

		self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, delr=self.dem.geodata[1], delc=abs(self.dem.geodata[5]), top=self.dem.data, botm=self.zbot, itmuni=4, lenuni=2,
		nper=self.nper, perlen=self.perlen, nstp=self.nstp, steady=self.steady, xul=self.dem.xmin,yul=self.dem.ymax)
		#proj4_str=self.dem.crs)
    
		self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
		for i in range (self.nlay):
			self.iboundData[i][self.dem.data < -1000] = 0
        
        #iboundData[i][self.structure.dem <= self.structure.mean_sea_level] = -1
        #iboundData[0][sea_earth == 1] = 1
		self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem.data
        #strtData[iboundData == -1] = self.structure.mean_sea_level

		self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)

        # lpf package
		self.laywet = np.zeros(self.nlay)
		self.laytype = np.ones(self.nlay)
        
		self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hyd_cond
		'''
        for i in range(0,len(self.number_structure)):
            for j in range(0,nlay):
                self.hk[j][self.structure.geology==self.number_structure[i]]= logParamValue[i]*3600*24
		'''
		self.upw = flopy.modflow.ModflowUpw(self.mf, iphdry=1, hdry=-100, laytyp=self.laytype, laywet=self.laywet, hk=self.hk,
                                       vka=1, sy=self.porosity, noparcheck=False, extension='upw', unitnumber=31)

		self.rchData = {}
		for kper in range(0, self.nper):
			self.rchData[kper] = self.climatic[kper] #à Modifer avec surfex
		self.rch = flopy.modflow.ModflowRch(self. mf, rech=self.rchData)

        # Drain package (DRN)
		self.drnData = np.zeros((self.nrow*self.ncol, 5))
		compt = 0
		self.drnData[:, 0] = 0 # layer
		for i in range (0,self.nrow):
			for j in range (0, self.ncol):
				self.drnData[compt, 1] = i #row
				self.drnData[compt, 2] = j #col
				self.drnData[compt, 3]= self.dem.data[i, j]#elev
				self.drnData[compt, 4] =self.hk[0, i, j]*self.dem.geodata[1] * abs(self.dem.geodata[5])  #cond() 
				compt += 1
		lrcec= {0:self.drnData}
		self.drn = flopy.modflow.ModflowDrn(self.mf, stress_period_data=lrcec)
        
        # oc package
		stress_period_data = {}
		for kper in range(self.nper):
			kstp = self.nstp[kper]
			stress_period_data[(kper, kstp-1)] = ['save head','save budget',]
		self.oc = flopy.modflow.ModflowOc(self.mf, stress_period_data=stress_period_data, extension=['oc','hds','cbc'],
                                unitnumber=[14, 51, 52, 53, 0], compact=True)
		self.oc.reset_budgetunit(fname= self.model_name+'.cbc')

        # write input files
		self.mf.write_input()
        # run model
		succes, buff = self.mf.run_model(silent=True)
