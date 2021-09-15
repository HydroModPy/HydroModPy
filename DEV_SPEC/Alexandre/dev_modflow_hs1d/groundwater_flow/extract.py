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
import deepdish as dd

# HydroModPy modules
import topography
from tools import tif_adds

# Temporary
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class extract_model:
    def __init__(self,
                 watershed,
                 dem_path,
                 model_name,
                 model_folder):
        
        # Attributes
        self.watershed = watershed
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name) # model_folder == watershed_folder
        self.dem_path = dem_path
        self.dem = topography.load_dem(self.dem_path)
        self.dem_mask = (self.dem.data==-99999)
    
        # Functions
        self.model_parameters()
        self.open_essential()
        self.iterate_times()

    def model_parameters(self):
        self.mf = flopy.modflow.Modflow.load(self.full_path+'.nam', verbose=False, check=False, load_only=["bas6", "dis"])
        self.bas = flopy.modflow.ModflowBas.load(self.full_path+'.bas', self.mf)
        self.dis = flopy.modflow.ModflowDis.load(self.full_path+'.dis', self.mf)
        self.rch = flopy.modflow.ModflowRch.load(self.full_path+'.rch', self.mf)
        self.upw = flopy.modflow.ModflowUpw.load(self.full_path+'.upw', self.mf)
        self.nlay = self.dis.nlay
        self.nper = self.dis.nper
        self.nstp = self.dis.nstp
        self.kper = np.arange(0,self.nper,1) # ==> time
        self.kstp = self.nstp[self.kper] - 1
    
    def open_simulation(self):
        self.head_fpu = fpu.HeadFile(self.full_path+'.hds')        
        self.cbb = fpu.CellBudgetFile(self.full_path+'.cbc')
        
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_gw_flux = {}
        self.dict_specific_discharge = {}
        
    def iterate_times(self):
        for item, time in enumerate(self.times):
            print('Time : ', item)
            
            self.watertable_outputs(time=time)
            self.gw_flux(time=time)
            self.outflow_drain(time=time)
            
            self.store_indict(item=item)
        
        self.save_dict()
            
    def watertable_outputs(self, item, time):
        # Import data
        self.head_all = self.head_fpu.get_alldata() # mflay=None
        self.head_data = self.head_fpu.get_data(totim=time)
        
        ### Watertable elevation
        # Top layer
        self.wt_elev = self.head_data[0]
        # Mask
        self.wt_elev[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.wt_elev, -9999,
                     self.model_folder+'/watertable_elevation_t(0).tif')
        
        ### Watertable depth
        self.wt_depth = self.dem.data - self.wt_elev
        # Mask
        self.wt_depth[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.wt_depth, -9999,
                     self.model_folder+'/watertable_depth_t(0).tif')
        
        ### Watertable intercept
        self.seep_area = self.dem.data - self.wt_elev
        # Mask
        self.seep_area[self.seep_area > 0] = 0
        self.seep_area[self.seep_area <= 0] = 1
        self.seep_area[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.seep_area, -9999,
                     self.model_folder+'/seepage_areas_t(0).tif')
        
    def outflow_drain(self, item, time):
        # Import data
        self.out_all = np.ones((1, self.dis.nrow, self.dis.ncol))
        self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
        # Loop storage
        sim = 0
        count = 0
        for i in range(0, self.dis.nrow):
            for j in range(0, self.dis.ncol):
                self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                count = count + 1
        # Top layer
        self.out_drn = self.out_all[0]
        # Mask
        self.out_drn[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.out_drn, -9999,
                     self.model_folder+'outflow_drain_t(0).tif')
            
    def gw_flux(self, item, time):
        ### Groundwater flux
        # Import data
        self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
        self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
        self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
        # Depend nlayers
        if self.nlay ==1:
            self.flux = np.sqrt(self.frf**2 + self.fff**2)        
            self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, None), 
                                                                   self.mf, self.full_path+'.cbc')
        if self.nlay > 1:
            self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
            self.flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
            self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, self.flf),                                                                    
                                                                   self.mf, self.full_path+'.cbc')
        # Top layer
        self.flux_top = self.flux[0]
        # Mask
        self.flux_top[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.flux_top, -9999,
                     self.model_folder+'/gw_flux_t(0).tif')
        
        ### Specific discharge
        # Import data
        self.specif_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
        # Top layer
        self.sepcif_disch_top = self.specif_disch[0]
        # Mask
        self.sepcif_disch_top[self.dem_mask] = -9999
        # Export
        if item == 0:
            tif_adds(self.dem_path, self.specif_disch, -9999,
                     self.model_folder+'specific_discharge_t(0).tif')
        
    def store_indict(self, item):    
        self.dict_watertable_elevation[item] = self.wt_elev
        self.dict_watertable_depth[item] = self.wt_depth
        self.dict_seepage_areas[item] = self.seep_area
        self.dict_outflow_drain[item] = self.out_drn
        self.dict_gw_flux[item] = self.flux_top
        self.dict_specific_discharge[item] = self.specif_disch
        
    def save_dict(self):    
        dd.io.save(self.model_folder+'watertable_elevation.h5', self.dict_watertable_elevation)
        dd.io.save(self.model_folder+'watertable_depth.h5', self.dict_watertable_elevation)
        dd.io.save(self.model_folder+'seepage_areas.h5', self.dict_watertable_elevation)
        dd.io.save(self.model_folder+'outflow_drain.h5', self.dict_watertable_elevation)
        dd.io.save(self.model_folder+'gw_flux.h5', self.dict_watertable_elevation)
        dd.io.save(self.model_folder+'specific_discharge.h5', self.dict_watertable_elevation)
    
#%%

# np.ma.masked_array(self.head_data, mask=(self.head_data==-9999))