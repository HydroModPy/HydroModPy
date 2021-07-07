# -*- coding: utf-8 -*-

import os
import sys
import numpy as np
import rasterio as rio
import rasterio.plot
import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff
import flopy.utils.postprocessing as pp
import topography
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class modflow:
    def __init__(self, dem_path, watershed='name', model_name='modflow_model', model_folder=os.path.dirname(os.getcwd())+'\\output\\',
                 param=True, watertable=True, seepage=True, gwflux=True, outflow=True, spedisch=True):
        
        self.watershed = watershed
        self.model_folder = model_folder
        self.model_name = model_name
        self.model_save = self.model_folder+self.watershed+'\\'+self.model_name+'\\'
        self.model_ws = self.model_save+'\\modraw\\'
        self.model_file = self.model_ws + self.model_name
        self.dem_path = dem_path
        self.dem = topography.dem(self.dem_path)
        with rio.open(self.dem_path) as src:
            self.ras_data = src.read()
            self.ras_meta = src.profile
        # Functions
        self.param()
        self.watertable()
        self.watertable_depth()
        self.seepage()
        self.gwflux()
        self.outflow()
        self.spedisch()


    def param(self):
        self.mf = flopy.modflow.Modflow.load(self.model_file+'.nam', verbose=False, check=False, load_only=["bas6", "dis"])
        self.bas = flopy.modflow.ModflowBas.load(self.model_file+'.bas', self.mf)
        self.dis = flopy.modflow.ModflowDis.load(self.model_file+'.dis', self.mf)
        self.rch = flopy.modflow.ModflowRch.load(self.model_file+'.rch', self.mf)
        self.upw = flopy.modflow.ModflowUpw.load(self.model_file+'.upw', self.mf)
        self.nlay = self.dis.nlay
    
    def watertable_depth(self):
        self.watertable_depth = self.dem.data - self.head_data[0]
        self.watertable_depth[self.head_data[0] == -9999] = -9999
        # Export
        self.ras_meta['dtype'] = self.head_data[0].dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'watertable_depth.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.watertable_depth, 1)

    def watertable(self):
        self.head_fpu = fpu.HeadFile(self.model_file+'.hds')
        self.head_all = self.head_fpu.get_alldata() # mflay=None
        self.head_data = self.head_fpu.get_data()
        self.head_data[0][self.dem.data==-99999] = -9999
        self.head_data[0][self.head_data[0]==-9999] = -9999
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()

        # Export
        self.ras_meta['dtype'] = self.head_data[0].dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'watertable.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.head_data[0], 1)
    
    def seepage(self):
        self.seep_diff = self.dem.data - self.head_data[0]
        self.seep_diff[self.seep_diff > 0] = 0
        self.seep_diff[self.seep_diff < 0] = 1
        self.seep_diff[self.dem.data==-99999] = -9999
        # Export
        self.ras_meta['dtype'] = self.seep_diff.dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'seepage.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.seep_diff, 1)
    
    def gwflux(self):
        self.cbb = fpu.CellBudgetFile(self.model_file+'.cbc')
        self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
        self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper[0])[0]
        self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper[0])[0]
        if self.nlay > 1:
            self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper[0])[0] # > 1 lay
            self.gw_flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
        if self.nlay ==1:
            self.gw_flux = np.sqrt(self.frf**2 + self.fff**2)
        self.gw_flux[0][self.dem.data==-99999] = -9999
        # Export
        self.ras_meta['dtype'] = self.gw_flux[0].dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'gwflux.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.gw_flux[0], 1)
            
    def outflow(self):
        self.out_drn = np.ones((1, self.dis.nrow, self.dis.ncol))
        self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper[0])
        sim = 0
        count = 0
        for i in range(0, self.dis.nrow):
            for j in range(0, self.dis.ncol):
                self.out_drn[sim, i, j] = np.abs(self.drain[0][count][1])
                count = count + 1
        self.out_drn[self.out_drn == 0] = 0 # quantity of drain m3/m
        self.out_drn[0][self.dem.data==-99999] = -9999
        # Export
        self.ras_meta['dtype'] = self.out_drn[0].dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'outflow.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.out_drn[0], 1)
        
    def spedisch(self):
        self.qx, self.qy, self.qz = pp.get_specific_discharge(self.mf, self.model_file+'.cbc')
        self.spe_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
        self.spe_disch[0][self.dem.data==-99999] = -9999
        # Export
        self.ras_meta['dtype'] = self.spe_disch[0].dtype
        self.ras_meta['nodata'] = -9999
        with rio.open(self.model_save + 'spedisch.tif', 'w', **self.ras_meta) as dst:
            dst.write(self.spe_disch[0], 1)
