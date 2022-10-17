# -*- coding: utf-8 -*-
"""
Created on Wed Sep 15 2021

@author: Ronan Abhervé
"""

# Modules
import os
import sys
import numpy as np
import rasterio as rio
import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.formattedfile as ff
import flopy.utils.postprocessing as pp

# HydroModPy modules
import topography
from tools import tif_adds

# Temporary
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class extract_steady:
    def __init__(self,
                 watershed_name,
                 dem_path,
                 model_name,
                 model_folder,
                 model_parameters=True, 
                 watertable_elevation=True, 
                 watertable_depth=True, 
                 seepage_areas=True,
                 gw_flux=True, 
                 outflow_drn=True, 
                 specific_discharge=True):
        
        self.watershed = watershed_name
        self.model_folder = model_folder
        self.model_name = model_name
        self.model_save = self.model_folder+self.watershed+'\\'+self.model_name+'\\'
        self.model_ws = self.model_save+'\\modraw\\'
        self.model_file = self.model_ws + self.model_name
        self.dem_path = dem_path
        self.dem = topography.dem(self.dem_path)
            
        # Functions
        self.param()
        self.watertable()
        self.watertable_depth()
        self.seepage()
        self.gwflux()
        self.outflow()
        self.spedisch()

    def model_parameters(self):
        self.mf = flopy.modflow.Modflow.load(self.model_file+'.nam', verbose=False, check=False, load_only=["bas6", "dis"])
        self.bas = flopy.modflow.ModflowBas.load(self.model_file+'.bas', self.mf)
        self.dis = flopy.modflow.ModflowDis.load(self.model_file+'.dis', self.mf)
        self.rch = flopy.modflow.ModflowRch.load(self.model_file+'.rch', self.mf)
        self.upw = flopy.modflow.ModflowUpw.load(self.model_file+'.upw', self.mf)
        self.nlay = self.dis.nlay
        
    def watertable_elevation(self):
        self.head_fpu = fpu.HeadFile(self.model_file+'.hds')
        self.head_all = self.head_fpu.get_alldata() # mflay=None
        self.head_data = self.head_fpu.get_data()
        self.head_data[0][self.dem.data==-99999] = -9999
        self.head_data[0][self.head_data[0]==-9999] = -9999
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        tif_adds(self.dem_path, self.head_data[0], -9999,
                 self.model_save+'watertable_elevation.tif')
                
    def watertable_depth(self):
        self.watertable_depth = self.dem.data - self.head_data[0]
        self.watertable_depth[self.head_data[0] == -9999] = -9999
        tif_adds(self.dem_path, self.watertable_depth, -9999,
                 self.model_save+'watertable_depth.tif')

    def seepage_areas(self):
        self.seep_diff = self.dem.data - self.head_data[0]
        self.seep_diff[self.seep_diff > 0] = 0
        self.seep_diff[self.seep_diff < 0] = 1
        self.seep_diff[self.dem.data==-99999] = -9999
        # Export
        self.ras_meta['dtype'] = self.seep_diff.dtype
        self.ras_meta['nodata'] = -9999
        tif_adds(self.dem_path, self.seep_diff, -9999,
                 self.model_save+'seepage_areas.tif')
            
    def gw_flux(self):
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
        tif_adds(self.dem_path, self.gw_flux, -9999,
                 self.model_save+'gw_flux.tif')

    def outflow_drn(self):
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
        tif_adds(self.dem_path, self.out_drn[0], -9999,
                 self.model_save+'outflow_drn.tif')
            
    def specific_discharge(self):
        self.qx, self.qy, self.qz = pp.get_specific_discharge(self.mf, self.model_file+'.cbc')
        self.spe_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
        self.spe_disch[0][self.dem.data==-99999] = -9999
        tif_adds(self.dem_path, self.spe_disch, -9999,
                 self.model_save+'specific_discharge.tif')
  

        
