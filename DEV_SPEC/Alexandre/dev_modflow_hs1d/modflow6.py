# coding:utf-8

import os
import sys
import flopy
import numpy as np
import topography
import sea
from IPython.core.debugger import set_trace as st
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class modflow6_model:
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
	def __init__(self, dem_path, watershed='name', climatic=8e-4, lay_number=1, thick=100, bottom=None, hyd_cond=8.64e-2, porosity=0.01, coastal_aquifer=False,
                 time_step='daily', model_name='modflow_model', model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):
        
		self.watershed = watershed
		self.model_name = model_name
		self.model_folder = model_folder
		self.full_path = os.path.join(model_folder, watershed, model_name, 'modraw')
		self.dem_path = dem_path
		self.climatic = climatic
		self.coastal_aquifer = coastal_aquifer
		self.SLR = SLR
		self.time_step = time_step
		self.thick = thick
		self.bottom = bottom
		self.nlay = lay_number
		self.hyd_cond = hyd_cond
		self.porosity = porosity
		self.dem = topography.dem(self.dem_path)
		self.exe = exe
        
		self.build_modflow_model()

	def build_modflow6_model(self):
		sim = flopy.mf6.MFSimulation(sim_name=simName, version='mf6', exe_name='bin/mf6.exe', sim_ws=self.full_path)
		model = flopy.mf6.MFModel(sim,modelname=self.model_name,model_nam_file=self.model_name+'.nam')
		imsPackage = flopy.mf6.ModflowIms(sim, print_option='ALL',
                                   complexity='SIMPLE', outer_hclose=0.00001,
                                   outer_maximum=50, under_relaxation='NONE',
                                   inner_maximum=30, inner_hclose=0.00001,
                                   linear_acceleration='CG',
                                   preconditioner_levels=7,
                                   preconditioner_drop_tolerance=0.01,
                                   number_orthogonalizations=2)


		sim.register_ims_package(imsPackage,[self.model_name])
		
		try:
			if len(self.hyd_cond)!=1:
				self.dem.data[self.hyd_cond<0]=-9999
		except:
			pass
		
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
			if self.time_step=='daily':
				for i in range(1,len(self.climatic)):
					dif = self.climatic.index[i]-self.climatic.index[i-1]
					self.perlen[i] = dif.days

		self.nrow = self.dem.data.shape[0]
		self.ncol = self.dem.data.shape[1]

		self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
		if self.bottom is None:
			thick_lay = self.thick / self.nlay
			for i in range (1,self.nlay+1):
				self.zbot[i-1] = self.dem.data - (thick_lay*i)
		else:
			for i in range (1,self.nlay+1):
				self.zbot[i-1] = self.bottom*(i/self.nlay) + self.dem.data*(1-i/self.nlay)

		period_data = []
		for i in range (0, self.nper):
			period_data.append((1.0,1,1.0))
		tdis = flopy.mf6.ModflowTdis(sim, time_units='days', nper=self.nper, perioddata=period_data)
		disPackage = flopy.mf6.ModflowGwfdis(model, length_units='METERS', nlay=self.nlay, nrow=self.nrow, ncol=self.ncol, delr=self.dem.geodata[1], delc=abs(self.dem.geodata[5]), top = self.dem.data, botm=self.zbot)

		'''self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, delr=self.dem.geodata[1], delc=abs(self.dem.geodata[5]), top=self.dem.data, botm=self.zbot, itmuni=4, lenuni=2,
								nper=self.nper, perlen=self.perlen, nstp=self.nstp, steady=self.steady, xul=self.dem.xmin,yul=self.dem.ymax)'''
		#proj4_str=self.dem.crs)
    
		self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
		self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem.data

		for i in range (self.nlay):
			if self.coastal_aquifer==True:
				self.sea = sea.mean_sea_level(self.dem.centroid)     
				self.iboundData[i][self.dem.data <= (self.sea.mean_sea_level+self.SLR)] = -1
				self.strtData[self.iboundData == -1] = self.sea.mean_sea_level + self.SLR
			self.iboundData[i][self.dem.data < -1000] = 0

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
				self.drnData[compt, 4] =self.hk[0, i, j]*self.dem.geodata[1] #* abs(self.dem.geodata[5])  #cond() 
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
