# coding:utf-8

# Modules
import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff
import flopy.utils.postprocessing as pp
import numpy as np
import rasterio as rio
from IPython.core.debugger import set_trace as st
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

# HydroModPy modules
from tools import tif_adds
from watershed import topography

class run_model:
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
	def __init__(self,geographic, watershed='name', climatic=8e-4, lay_number=1, thick=50, 
                 bottom=None, thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, sea_level = None, cond_decay=0.,
                 time_step='daily', model_name='modflow_model', 
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):

		self.model_name = model_name
		self.model_folder = model_folder # watershed folder ?
		self.full_path = os.path.join(model_folder, model_name) #'modraw'
		self.climatic = climatic
		self.sea_level = sea_level 
		self.time_step = time_step
		self.thick = thick
		self.thick_exp = thick_exp
		self.bottom = bottom
		self.nlay = lay_number
		self.hyd_cond = hyd_cond
		self.cond_decay = cond_decay
		if sea_level == None:
			self.dem = geographic.dem_data
		else:
			self.dem = geographic.dem_box_data
		self.porosity = porosity
		self.exe = exe
        
		self.build_modflow_model(geographic)

	def build_modflow_model(self, geographic):
		self.mf = flopy.modflow.Modflow(self.model_name, 
										exe_name=self.exe, version='mfnwt',listunit=2, verbose=False,
										model_ws=self.full_path, external_path=self.full_path)
		self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=1000, thickfact=1e-05, linmeth=1,iprnwt=0,ibotav=0, options='COMPLEX')
		
		try:
			if len(self.hyd_cond)!=1:
				self.dem[self.hyd_cond<0]=-9999
		except:
			pass
		
		if isinstance(self.climatic,(int,float))==True:
			self.nper = 1
			self.perlen = 1
			self.nstp = [1]
			self.steady = True
			self.start_datetime = None
		else:
			self.start_datetime = self.climatic.index[0]
			self.steady = np.zeros(len(self.climatic),dtype=bool)
			self.steady[0] = True
			self.nstp = np.ones(len(self.climatic))
			self.nper = len(self.climatic)
			self.perlen = np.ones(len(self.climatic))
			if self.time_step=='daily':
				for i in range(1,len(self.climatic)):
					dif = self.climatic.index[i]-self.climatic.index[i-1]
					self.perlen[i] = dif.days

		self.nrow = self.dem.shape[0]
		self.ncol = self.dem.shape[1]

		self.zbot = np.ones((self.nlay, self.nrow, self.ncol))
		if self.bottom is None:
			bottom_layer = self.dem - self.thick
		else:
			bottom_layer = self.bottom

		if self.thick_exp != 1.:
			exp_scale = 1-self.thick_exp**self.nlay

		for i in range(1, self.nlay+1):
			if self.thick_exp == 1.:
				p = i / self.nlay
			else:
				p = (1-self.thick_exp**i) / exp_scale
			self.zbot[i-1] = bottom_layer * p + self.dem * (1-p)

		self.dis = flopy.modflow.ModflowDis(self.mf, self.nlay, self.nrow, self.ncol, 
			delr=geographic.resolution, delc=geographic.resolution, top=self.dem.data, 
			botm=self.zbot, itmuni=4, lenuni=2, nper=self.nper, perlen=self.perlen, 
			nstp=self.nstp, steady=self.steady, xul=geographic.xmin,yul=geographic.ymax, start_datetime=self.start_datetime)
		#proj4_str=self.dem.crs)
    
		self.iboundData = np.ones((self.nlay, self.nrow, self.ncol))
		self.strtData = np.ones((self.nlay, self.nrow, self.ncol))* self.dem

		for i in range (self.nlay):
			if isinstance(self.sea_level,(int,float)) == True:
				self.iboundData[i][self.dem <= self.sea_level] = -1
				self.strtData[self.iboundData == -1] = self.sea_level
			self.iboundData[i][self.dem < -1000] = 0

		self.bas = flopy.modflow.ModflowBas(self.mf, ibound=self.iboundData, strt=self.strtData, hnoflo=-9999)

		# Constant Head package
		if self.sea_level != None:
			package = np.zeros((self.nper,self.nrow, self.ncol))
			if isinstance(self.sea_level,(int,float)) == False:
				self.chdData = {}
				for kper in range(0, self.nper):
					chdKper = []
					for i in range (0,self.nrow):
						for j in range (0, self.ncol):
							if self.dem[i,j] < self.sea_level[kper]:
								package[kper,i,j] = 1
								chdKper.append([0,i,j,self.sea_level[kper],self.sea_level[kper]])
					self.rchData[kper] = chdKper

        # lpf package
		self.laywet = np.zeros(self.nlay)
		self.laytype = np.ones(self.nlay)
        
		self.hk = np.ones((self.nlay, self.nrow, self.ncol))*self.hyd_cond
		if self.cond_decay != 0.:
			depth = np.zeros(self.hk.shape)
			depth[1:,:,:] = self.dem - self.zbot[:-1,:,:]
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
			if isinstance(self.climatic,(int,float)):
				self.rchData[kper] = self.climatic
			else:
				if kper == 0:
					self.rchData[kper] = np.nanmean(self.climatic)
				else:
					self.rchData[kper] = self.climatic[kper]
		self.rch = flopy.modflow.ModflowRch(self. mf, rech=self.rchData)

        # Drain package (DRN)
		self.drnData = np.zeros((self.nrow*self.ncol, 5))
		compt = 0
		self.drnData[:, 0] = 0 # layer
		for i in range (0,self.nrow):
			for j in range (0, self.ncol):
				self.drnData[compt, 1] = i #row
				self.drnData[compt, 2] = j #col
				self.drnData[compt, 3]= self.dem[i, j]#elev
				self.drnData[compt, 4] =self.hk[0, i, j]* self.thick *geographic.resolution**2  #cond() 
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

