# coding:utf-8
import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
from os.path import dirname, abspath

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

class Modpath:
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
    def __init__(self,geographic, model_name='modflow_model', 
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mp6.exe'), 
                 porosity = 0.01 ,verbose=True):
        self.model_name = model_name
        self.geographic = geographic
        self.model_folder = model_folder
        self.porosity = porosity
        self.full_path = os.path.join(model_folder, model_name)
        if not os.path.isdir(self.full_path):
            raise FileNotFoundError('Directory not found: {}'.format(self.full_path))
        self.exe = exe

    def pre_processing(self, verbose=True):
        prefix = os.path.join(self.full_path, self.model_name)
        nam_file = '{}.nam'.format(prefix)
        dis_file = '{}.dis'.format(prefix)
        head_file = '{}.hds'.format(prefix)
        bud_file = '{}.cbc'.format(prefix)
        bas_file = '{}.bas'.format(prefix)
        lpf_file = '{}.upw'.format(prefix)

        self.mf = flopy.modflow.Modflow.load(nam_file,model_ws=self.full_path, verbose=False, check=False)
        bas = flopy.modflow.ModflowBas.load(bas_file, self.mf)
        lpf = flopy.modflow.ModflowUpw.load(lpf_file, self.mf, check=False)
        nlay = self.mf.nlay
        ncol = self.mf.ncol
        nrow = self.mf.nrow
        laytype = lpf.laytyp.array
        iboundData = bas.ibound.array
        
        self.mp = flopy.modpath.Modpath6(modelname=self.mf.name,model_ws=self.full_path, simfile_ext='mpsim', namefile_ext='mpnam', version='modpath',
                               exe_name=self.exe, modflowmodel=self.mf, head_file=head_file, dis_file=dis_file, dis_unit=87, budget_file=bud_file)
        self.mp.array_free_format = True
        cbb = fpu.CellBudgetFile(bud_file)
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

        self.mp.dis_file = dis_file
        self.mp.head_file = head_file
        self.mp.budget_file = bud_file


        #ptcol = 1
        #ptrow = 1
        #ifaces = [6]  # top face:6 ; bottom face:5 ; row face:3-4 ; column face:1-2

        # self.mp.write_input()

        flopy.modpath.Modpath6Sim(model=self.mp, option_flags=[2, 1, 1, 1, 1, 2, 2, 1, 1, 2, 1, 1],
                                   group_placement=[[1, 1, 1, 0, 1, 1]], stop_zone=1, zone=szone)
        stl = flopy.modpath.mp6sim.StartingLocationsFile(model=self.mp, inputstyle=1)
        prow = 1
        pcol = 1
        #stldata = flopy.modpath.mpsim.StartingLocationsFile.get_empty_starting_locations_data(npt=ncol*nrow*prow*pcol)
        stldata = stl.get_empty_starting_locations_data(npt=np.sum(self.geographic.dem_clip != -99999)*pcol*prow)

        hds_1c = fpu.HeadFile(head_file)
        # hds_1c = ff.FormattedHeadFile('model1.hds')
        head_1c = hds_1c.get_alldata(mflay=None)

        head = np.full((nrow, ncol), np.nan)
        for i in range(0, nrow):
            for j in range(0, ncol):
                for k in range(0, nlay):
                    if head_1c[0][k][i, j] > 0:
                        head[i, j] = head_1c[0][k][i, j]
                        break

        compt = 0
        for i in range(0, nrow):
            for j in range(0, ncol):
                if self.geographic.dem_clip[i,j] != -99999.:
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
                                stldata[compt]['zloc0'] = 1
                                stldata[compt]['xloc0'] = (ii+0.1)/(prow+0.2)
                                stldata[compt]['yloc0'] = (jj+0.1)/(pcol+0.2)
                                compt = compt + 1
        self.point_data = stldata
        stl.data = stldata
        
        # print(self.porosity)
        flopy.modpath.Modpath6Bas(self.mp, hnoflo=-9999.0, hdry=-100, def_face_ct=0, laytyp=laytype, ibound=iboundData,
										prsity=self.porosity, prsityCB=self.porosity, extension='mpbas', unitnumber=86)
        self.mp.write_input()
    
    def processing(self, verbose=True):
        succes, buff = self.mp.run_model(silent=not verbose)
    
