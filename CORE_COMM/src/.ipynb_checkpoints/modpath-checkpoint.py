# coding:utf-8
import os
import sys
import flopy
import numpy as np
import extract as e

'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class modpath_model:
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
	def __init__(self, watershed='naming', model_name = 'modflow_model', model_folder = os.path.dirname(os.getcwd()) + '\\output\\'):
		self. = os.getcwd()
		self.

	def build_modpath_model(self):
		mf1 = flopy.modflow.Modflow.load(modelname+'.nam',model_ws=modelfolder, verbose=False, check=False)
		dis = flopy.modflow.ModflowDis.load(modelfolder+modelname+'.dis', mf1)
		bas = flopy.modflow.ModflowBas.load(modelfolder+modelname+'.bas', mf1)
		lpf = flopy.modflow.ModflowUpw.load(modelfolder + modelname + '.upw', mf1, check=False)
		nlay = mf1.nlay
		ncol = mf1.ncol
		nrow = mf1.nrow
		zbot = dis.botm.array
		laytype = lpf.laytyp.array
		iboundData = bas.ibound.array

		dis_file = '{}.dis'.format(modelfolder+mf1.name)
		head_file = '{}.hds'.format(modelfolder+mf1.name)
		bud_file = '{}.cbc'.format(modelfolder+mf1.name)
		
		mp = flopy.modpath.Modpath(modelname=mf1.name,model_ws=modelfolder, simfile_ext='mpsim', namefile_ext='mpnam', version='modpath',
                               exe_name=filename+'mp6.exe', modflowmodel=mf1, head_file=head_file, dis_file=dis_file, dis_unit=87, budget_file=bud_file)
		mp.array_free_format = True
		cbb = fpu.CellBudgetFile('{}.cbc'.format(modelfolder+mf1.name))
		# cbb.list_records()
		rec_drn = cbb.get_data(kstpkper=(0, 0), text='DRAINS')
		rec_rch = cbb.get_data(kstpkper=(0, 0), text='RECHARGE')

		drn = np.ones((nrow, ncol))
		compti = 0
		comptj = 0
		for ii in range(0, rec_drn[0].shape[0]):
			drn[compti, comptj] = -1 * rec_drn[0][ii][1]
			comptj += 1
		if comptj == ncol:
			compti += 1
			comptj = 0
		rch = rec_rch[0][1]
		b = drn / rch
		b[np.isnan(b)]=0
		szone = []
		for i in range(0, nlay):
			a = np.zeros((nrow, ncol), dtype=int)
		if i == 0:
			a[b >= 1] = 1
		a[iboundData[i] == -1] = 1
		szone.append(a)

		mp.dis_file = dis_file
		mp.head_file = head_file
		mp.budget_file = bud_file


		ptcol = 1
		ptrow = 1
		ifaces = [6]  # top face:6 ; bottom face:5 ; row face:3-4 ; column face:1-2

		# mp.write_input()

		sim = flopy.modpath.ModpathSim(model=mp, option_flags=[2, 1, 1, 1, 1, 2, 2, 1, 1, 2, 1, 1],
                                   group_placement=[[1, 1, 1, 0, 1, 1]], stop_zone=1, zone=szone)
	    stl = flopy.modpath.mpsim.StartingLocationsFile(model=mp, inputstyle=1)
		prow = 1
		pcol = 1
		stldata = flopy.modpath.mpsim.StartingLocationsFile.get_empty_starting_locations_data(npt=ncol*nrow*prow*pcol)

		hds_1c = fpu.HeadFile(modelfolder+modelname+'.hds')
		# hds_1c = ff.FormattedHeadFile('model1.hds')
		head_1c = hds_1c.get_alldata(mflay=None)

		head = np.ones((nrow, ncol)) * np.nan
		for i in range(0, nrow):
			for j in range(0, ncol):
				for k in range(0, nlay):
					if head_1c[0][k][i, j] > 0:
						head[i, j] = head_1c[0][k][i, j]
		break

		compt = 0
		for i in range(0, nrow):
			for j in range(0, ncol):
				if head_1c[0][0][i][j] != 0.48:
					for ii in range (0, prow):
						for jj in range (0, pcol):
							stldata[compt]['label'] = 'p' + str(compt + 1) + '-'+str(ii)+ '-'+str(jj)
							for k in range(0, nlay):
								if head_1c[0][k, i, j] > 0:
									stldata[compt]['k0'] = k
									break
							stldata[compt]['j0'] = j
							stldata[compt]['i0'] = i
							stldata[compt]['zloc0'] = 0.9
							stldata[compt]['xloc0'] = (ii+0.1)/(prow+0.2)
							stldata[compt]['yloc0'] = (jj+0.1)/(pcol+0.2)
							compt = compt + 1
    stl.data = stldata

    mpbas = flopy.modpath.ModpathBas(mp, hnoflo=-9999.0, hdry=-100, def_face_ct=0, laytyp=laytype, ibound=iboundData,
                                     prsity=0.01, prsityCB=0.01, extension='mpbas', unitnumber=86)

    mp.write_input()
    cwd = os.path.join(os.getcwd(), modelname)
    mpsf = '{}.mpsim'.format(modelfolder+mf1.name)
    mp_exe_name = 'mp6.exe'
    xstr = '{} {}'.format(mp_exe_name, mpsf)
    succes, buff = mp.run_model()
