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

class modflow_model:
	"""
	dem_path: path of the DEM (.tif)
	watershed: a name referencing the area
	model_name: a name referencing the model (conditions, etc.)
	model_foler: where to place the simulation
	exe: path to the executable (mfnwt.exe on Windows)

	climatic: float or Dataframe Datatimeseries — Recharge
	lay_number: int (default 1) — Number of layers
	thick: float — Define the thickness of the aquifer below free surface
	bottom: optional float — Alternative way to define thickness, with fixed elevation of the bottom. Overrides 'thick' if present.
	thick_exp: float (default 1) — Factor by which depth of successive layers is multiplied.

	hyd_cond: float or numpy array (size of the dem) — Hydraulic conductivity
	cond_decay: float or numpy array (size of the dem) — Coefficient for conductivity exponential decay with depth. 0 = constant conductivity, 1e-2 = conductivity divided by e every 100m depth.
	porosity: float or numpy array (size of the dem)

	coastal_aquifer: boolean — whether points below sea level should be considered boundary conditions
	SLR: float — sea level rise
	autofix_layers: boolean — whether to automatically fix cells depth so that all cells of a given layer are connected
	min_overlap: float — if autofix_layers is enabled, horizontally adjacent cells will overlap vertically by at least this length.
	"""
	def __init__(self, dem_path, watershed='name', model_name='modflow_model',
				 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe'),
				 climatic=8e-4, lay_number=1, thick=100., bottom=None, thick_exp=1., hyd_cond=8.64e-2, cond_decay=0., porosity=0.01,
				 coastal_aquifer=False, SLR = 0., time_step='daily', autofix_layers=False, min_overlap=1.0):
        
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
		self.thick_exp = thick_exp
		self.bottom = bottom
		self.nlay = lay_number
		self.autofix_layers = autofix_layers
		self.min_overlap = min_overlap
		self.hyd_cond = hyd_cond
		self.cond_decay = cond_decay
		self.porosity = porosity
		self.dem = topography.dem(self.dem_path)
		self.exe = exe
        
		self.build_modflow_model()

	def build_modflow_model(self):
		self.mf = flopy.modflow.Modflow(self.model_name, 
										exe_name=self.exe, version='mfnwt',listunit=2, verbose=False,
										model_ws=self.full_path)
		self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=1000, thickfact=1e-05, linmeth=1,iprnwt=0,ibotav=0, options='COMPLEX')
		
		try:
			if len(self.hyd_cond)!=1:
				self.dem.data[self.hyd_cond<0]=-9999
		except:
			pass

		if isinstance(self.climatic, int) or isinstance(self.climatic, float):
			self.climatic = [self.climatic]

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

		# Determine bottom layer
		self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
		if self.bottom is None:
			bottom_layer = self.dem.data - self.thick
		else:
			bottom_layer = self.bottom

		if self.thick_exp != 1.:
			exp_scale = 1-self.thick_exp**self.nlay
		for i in range(1, self.nlay+1):
			# p is the ratio between top and bottom
			if self.thick_exp == 1.:
				p = i / self.nlay
			else:
				p = (1-self.thick_exp**i) / exp_scale
			self.zbot[i-1] = bottom_layer * p + self.dem.data * (1-p)

		if self.autofix_layers:
			self.fix_layers(min_overlap=self.min_overlap)

		self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, delr=self.dem.geodata[1], delc=abs(self.dem.geodata[5]), top=self.dem.data, botm=self.zbot, itmuni=4, lenuni=2,
		nper=self.nper, perlen=self.perlen, nstp=self.nstp, steady=self.steady, xul=self.dem.xmin,yul=self.dem.ymax)
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
		if self.cond_decay != 0.:
			depth = np.zeros(self.hk.shape)
			depth[1:,:,:] = self.dem.data - self.zbot[:-1,:,:]
			self.hk *= np.exp(-self.cond_decay*depth)
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

	def fix_layers(self, min_overlap=1.0):
		top = self.dem.data
		for bot in self.zbot:
			max_bot = top.copy()
			max_bot[:-1,:] = np.minimum(max_bot[:-1,:], top[1:,:])
			max_bot[1:,:] = np.minimum(max_bot[1:,:], top[:-1,:])
			max_bot[:,:-1] = np.minimum(max_bot[:,:-1], top[:,1:])
			max_bot[:,1:] = np.minimum(max_bot[:,1:], top[:,:-1])
			max_bot -= min_overlap
			too_high = bot > max_bot
			if np.any(too_high):
				bot[too_high] = max_bot[too_high]

			top = bot
