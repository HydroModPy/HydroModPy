# -*- coding: utf-8 -*-
"""
Created on Mon Sep  6 10:32:10 2021

@author: ronan
"""

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
import imageio
import deepdish as dd
'''os.path.dirname(os.getcwd())'''
sys.path.append(os.getcwd())

class modflow:

    def __init__(self, dem_path,
                 watershed='name', 
                 model_name='modflow_model', 
                 model_folder=os.path.dirname(os.getcwd())+'\\output\\',
                 param=True, 
                 watertable=True, 
                 seepage=True, 
                 gwflux=True, 
                 outflow=True, 
                 spedisch=True,
                 out_folder=os.path.dirname(os.getcwd())+'\\output\\'):
    
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
        self.out_folder = out_folder
            
        # Functions
        self.param()
        self.opens()
        self.times()
        self.iterative()
    
    def param(self):
        self.mf = flopy.modflow.Modflow.load(self.model_file+'.nam', verbose=False, check=False, load_only=["bas6", "dis"])
        self.bas = flopy.modflow.ModflowBas.load(self.model_file+'.bas', self.mf)
        self.dis = flopy.modflow.ModflowDis.load(self.model_file+'.dis', self.mf)
        self.rch = flopy.modflow.ModflowRch.load(self.model_file+'.rch', self.mf)
        self.upw = flopy.modflow.ModflowUpw.load(self.model_file+'.upw', self.mf)
        self.nlay = self.dis.nlay
        self.nper = self.dis.nper
        self.nstp = self.dis.nstp
        self.kper = np.arange(0,self.nper,1) # ==> time
        self.kstp = self.nstp[self.kper] - 1
    
    def opens(self):
        self.dem = imageio.imread(self.dem_path)
        self.dem[self.dem<0] = np.nan
        self.maskdata = imageio.imread(self.dem_path)
        self.head_fpu = fpu.HeadFile(self.model_file+'.hds')
        self.head_all = self.head_fpu.get_alldata() # mflay=None
        self.head_data = self.head_fpu.get_data()
        self.head_data_mask = np.ma.masked_array(self.head_data, mask=(self.head_data==-9999))
        self.min_head = np.min(self.head_data_mask)
        self.max_head = np.max(self.head_data_mask)
        self.head_save = self.head_data.copy()
        self.head_save[0][self.maskdata==-99999] = np.nan
        self.head_save[0][self.head_save[0]==-99999] = np.nan
        self.dicoseep = {}
        self.dicodrn = {}
        self.dicoq = {}
        self.dicowt = {}

    def times(self):
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
    
    def iterative(self):
        for iplot, time in enumerate(self.times):
            print('Time : ', iplot)
            self.watertable(time=time)
            # self.depth()
            self.gwflux(iplot=iplot, time=time)
            self.spedisch()
            self.outflow(time=time)
            self.seepage()
            self.store(iplot=iplot)
        self.save()
            
        def watertable(self, time):
            self.head_tr = self.head_fpu.get_data(totim=time)
            self.head_tr = self.maskdata - self.head_tr
            self.head_tr[0][self.maskdata==-99999] = np.nan
    
        # def depth(self):
        #     self.depth = self.dem.data - self.head_data[0]
        #     self.depth[self.head_data[0] == -9999] = -9999
        #     self.ras_meta['dtype'] = self.head_data[0].dtype
        #     self.ras_meta['nodata'] = -9999
        #     with rio.open(self.model_save + 'depth.tif', 'w', **self.ras_meta) as dst:
        #         dst.write(self.depth, 1)
    
        def gwflux(self, iplot, time):    
            self.cbb = fpu.CellBudgetFile(self.model_file + '.cbc')
            self.kstpkper = (self.kstp[iplot], self.kper[iplot])
            self.fff = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
            self.frf = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
            if self.nlay > 1:
                self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0]
                self.Q = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
            if self.nlay ==1:
                self.Q = np.sqrt(self.frf**2 + self.fff**2)
                    
        def spedisch(self):    
            self.qx, self.qy, self.qz = pp.get_specific_discharge(self.mf, self.model_file + '.cbc')
            self.q = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
            self.q[0][self.maskdata==-99999] = np.nan
                
        def outflow(self, time):    
            self.drn_drain = np.ones((1, self.dis.nrow, self.dis.ncol))
            self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
            sim = 0
            count = 0
            for i in range(0, self.dis.nrow):
                for j in range(0, self.dis.ncol):
                    self.drn_drain[sim, i, j] = np.abs(self.drain[0][count][1])
                    count = count + 1
            self.drn_drain[self.drn_drain == 0] = 0 # quantity of drain m3/m
            self.drn_drain[0][self.maskdata==-99999] = np.nan
                
        def seepage(self):
            self.seep = self.maskdata-self.head_tr[0]
            self.seep[self.seep > 0] = 0
            self.seep[self.seep <= 0] = 1
            self.seep[self.maskdata==-99999] = np.nan
                
        def store(self, iplot):    
            self.dicodrn[iplot] = self.drn_drain[0]
            self.dicowt[iplot] = self.head_tr[0]
            self.dicoseep[iplot] = self.seep
            self.dicoq[iplot] = self.q[0]
        
        def save(self):
            foldout = self.out_folder + self.watershed + '/' +self.model_name +'/'
            if not os.path.exists(foldout):
                os.makedirs(foldout)
            dd.io.save(foldout+'drn.h5', self.dicodrn)
            dd.io.save(foldout+'wt.h5', self.dicowt)
            dd.io.save(foldout+'seep.h5', self.dicoseep)
            dd.io.save(foldout+'q.h5', self.dicoq)
    
#%% Test

import trans_extract as trans

path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/3_analysis/transient_calib/'

trans.modflow(path+'7_outputs/Canut/gis/watershed_dem.tif',
              watershed='Canut', 
              model_name='5k&5n_Canut_1_50_11.633_0.018_0.209_0.001', 
              model_folder=path+'7_outputs/',
              out_folder='D:/Users/abherve/LOCAL/')
