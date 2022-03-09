# -*- coding: utf-8 -*-
"""
Created on Mon Jan 25 17:51:53 2021

@author: Alexandre Gauvain
"""

# Modules
import flopy
import numpy as np
import os
import pandas as pd
import sys
import imageio
from os.path import dirname, abspath
from osgeo import gdal
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import geopandas as gpd
import glob

import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

# HydroModPy modules
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
from tools import toolbox

from surface_flow import routing_accflux

# VARIABLES GLOBALES

class Modflow():
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
    def __init__(self, geographic, sink_fill = False, box=True,
                 climatic=8e-4, lay_number=1, thick=50,
                 bottom=None, thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, 
                 sea_level=None, cond_decay=0., model_name='modflow_model',
                 model_folder=os.path.join(os.path.dirname(os.getcwd()), 'output'), 
                 exe=os.path.join(os.path.dirname(os.getcwd()), 'bin', 'mfnwt.exe')):
        
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name) #'modraw'
        self.climatic = climatic.copy()
        self.sea_level = sea_level 
        self.thick = thick
        self.thick_exp = thick_exp
        self.geographic = geographic
        self.resolution = geographic.resolution
        self.sink_fill = sink_fill
        try : 
            self.sink = geographic.depressions_data
        except:
            pass
        self.bottom = bottom
        self.nlay = lay_number
        self.hyd_cond = hyd_cond
        self.porosity = porosity
        self.cond_decay = cond_decay
        self.xul = geographic.xmin
        self.yul = geographic.ymax
        # if sea_level == None:
        if box == True:
            self.dem = geographic.dem_box_data  
            self.dem_path = geographic.watershed_box_buff_dem
        else:
            self.dem = geographic.dem_data
            self.dem_path = geographic.watershed_buff_dem
        self.exe = exe

    def pre_processing(self, verbose=False):
        if verbose == True:
            print('Build model')
        self.mf = flopy.modflow.Modflow(self.model_name, 
                                        exe_name=self.exe, version='mfnwt', listunit=2, verbose=False,
                                        model_ws=self.full_path) # external_path=self.full_path
        self.nwt = flopy.modflow.ModflowNwt(self.mf, headtol=0.001, fluxtol=500, maxiterout=5000,
                                            thickfact=1e-05, linmeth=1, iprnwt=1, ibotav=1, options='COMPLEX',
                                            Continue=False, backflag=0) # ibotav=0

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
            if pd.infer_freq(self.climatic.index) != 'D':
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
            delr=self.resolution, delc=self.resolution, top=self.dem.data, 
            botm=self.zbot, itmuni=4, lenuni=2, nper=self.nper, perlen=self.perlen, 
            nstp=self.nstp, steady=self.steady, xul=self.xul, yul=self.yul,
            start_datetime=self.start_datetime) # itmuni = 0 ==> undefined
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
        
        if (self.climatic < 0).any().any() == True:
            #evt package
            self.evt = self.climatic.copy()
            self.evt[self.evt>=0] = 0
            self.evt = abs(self.evt)
            self.evtData = {}
            for kper in range(0, self.nper):
                if isinstance(self.evt,(int,float)):
                    self.evtData[kper] = self.evt
                else:
                    if kper == 0:
                        # self.evtData[kper] = np.nanmean(self.evt)
                        self.evtData[kper] = 0
                    else:
                        self.evtData[kper] = self.evt[kper]
            if verbose == True:
                print('ETR')
                print(self.evt)
            self.evt = flopy.modflow.ModflowEvt(self. mf, nevtop=3,
                                                evtr=self.evtData, 
                                                surf=0, exdp=self.thick)
            if not isinstance(self.climatic,(int,float)):
                self.climatic[self.climatic<0] = 0
                
        # rch package
        if not isinstance(self.climatic,(int,float)):
            self.climatic[self.climatic<0] = 0
        self.rchData = {}
        for kper in range(0, self.nper):
            if isinstance(self.climatic,(int,float)):
                self.rchData[kper] = self.climatic
            else:
                if kper == 0:
                    self.rchData[kper] = np.nanmean(self.climatic)
                    # self.rchData[kper] = self.climatic.iloc[0]
                    
                else:
                    self.rchData[kper] = self.climatic[kper]
        if verbose == True:
            print('REC')
            print(self.climatic)
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
                if self.sink_fill == False:
                    self.drnData[compt, 4] =self.hk[0, i, j]* self.thick*self.resolution**2  #cond()
                else:
                    if self.sink[i,j]>0:
                        self.drnData[compt, 4] = 0
                    else:
                        self.drnData[compt, 4] =self.hk[0, i, j]* self.thick*self.resolution**2  
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

    def processing(self, verbose=False):
        if verbose == True:
            print('Simulation d\'un modèle')
        # write input files
        self.mf.write_input()
        # run model
        succes, buff = self.mf.run_model(silent=not verbose)# True without msg
        return succes
        
    def post_processing(self, first_only = False,
                              watertable_elevation = True, watertable_depth=True, 
                              seepage_areas = True, outflow_drain = True,
                              groundwater_flux = True, specific_discharge = False,
                              accumulation_flux = True, perenn_intermit = False,
                              groundwater_storage = False,
                              verbose = True, export_tif = True):
        # self.wt_elev = []
        # self.wt_depth = []
        # self.seep_area = []
        # self.out_drn  = []
        # self.gw_flux = []
        # self.spe_disch = []
        # self.flux_top = []
        
        if verbose == True:
            print('Extract results of the simulation')
        
        # Create folders        
        self.save_file = os.path.join(self.full_path, '_watershed')
        toolbox.create_folder(self.save_file)        
        
        self.figure_file = os.path.join(self.full_path, '_figures')
        toolbox.create_folder(self.figure_file)
        
        self.surfaceflow_file = os.path.join(self.full_path, '_watershed','_surfaceflow')
        toolbox.create_folder(self.surfaceflow_file)
        
        self.tifs_file = os.path.join(self.full_path, '_watershed', '_tifs')
        toolbox.create_folder(self.tifs_file)
        
        # Model parameters
        self.path_file = os.path.join(self.full_path, self.model_name)
        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1) # ==> time
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1
        self.rechval = self.rch.rech[0][0,0]
        col = ['nrow','ncol','res','nlay','nper','rech','hk','sy']
        var = [self.nrow,self.ncol,self.resolution,self.nlay,self.nper,
               np.mean(self.rechval),np.mean(self.hyd_cond),np.mean(self.porosity)]
        params = pd.DataFrame(var).T
        params.columns = col
        params = params.round(3)
        self.params = params
        self.params.to_csv(self.full_path+'/_model_parameters.txt', sep=';', index=False)

        # Import essential data
        self.dem_mask = (self.dem<-4000)
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds')
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')
        
        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkper = self.head_fpu.get_kstpkper()
        if len(self.times) == 1:
            self.kstpkper = self.kstpkper[0]
                
        # Create dictionnaries
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_groundwater_flux = {}
        self.dict_specific_discharge = {}
        self.dict_accumulation_flux = {}
        self.dict_groundwater_storage = {}
        self.list_traces = []
        
        # self.dict_watertable_elevation = (self.save_file+'/watertable_elevation'+'.h5')
        # self.dict_watertable_depth = (self.save_file+'/watertable_depth'+'.h5')
        # self.dict_seepage_areas = (self.save_file+'/seepage_areas'+'.h5')
        # self.dict_outflow_drain = (self.save_file+'/outflow_drain'+'.h5')
        # self.dict_groundwater_flux = (self.save_file+'/groundwater_flux'+'.h5')
        # self.dict_specific_discharge = (self.save_file+'/specific_discharge'+'.h5')
        # self.dict_accumulation_flux = (self.save_file+'/accumulation_flux'+'.h5')
        
        if verbose == True:
            print('Post-processing in progress')
        
        # Loop from time
        for item, time in enumerate(self.times):
            if verbose == True:
                print('Post-processing time : ', item)
                     
            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])
            
            # lead_numb = "%03d" % (item,)
            lead_numb = str(item)
            
            if first_only==True:
                if item>0:
                    export_tif=False
            
            # Watertable data
            if self.nlay > 1:
                self.head_all = self.head_fpu.get_alldata() # mflay=None
                self.head_data = self.head_all[item][0]
            else:
                self.head_data = self.head_fpu.get_data(totim=time)
                self.head_data = self.head_data[0]
                
            if watertable_elevation == True:   
                ### Watertable elevation
                self.wt_elev = self.head_data.copy()
                self.wt_elev[self.dem_mask] = -9999
                # self.wt_elev.to_hdf(self.dict_watertable_elevation, lead_numb)
                output_path = self.tifs_file+'/watertable_elevation_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.wt_elev, -9999, output_path)
                self.dict_watertable_elevation[item] = self.wt_elev
            
            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = self.dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                # self.wt_depth.to_hdf(self.dict_watertable_depth, lead_numb)
                output_path = self.tifs_file+'/watertable_depth_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.wt_depth, -9999, output_path)
                self.dict_watertable_depth[item] = self.wt_depth
            
            if seepage_areas == True:
                ### Seepage areas
                self.seep_area = self.dem - self.wt_elev.copy()
                self.seep_area[self.seep_area >= 0] = 0
                self.seep_area[self.seep_area < 0] = 1
                self.seep_area[self.dem_mask] = -9999
                # self.seep_area.to_hdf(self.dict_seepage_areas, lead_numb)
                output_path = self.tifs_file+'/seepage_areas_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.seep_area, -9999, output_path)
                self.dict_seepage_areas[item] = self.seep_area
            
            if outflow_drain == True:
                # Outflow data
                self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)
            
                ### Outflow drain
                self.out_all = np.ones((1, self.dis.nrow, self.dis.ncol))
                sim = 0
                count = 0
                for i in range(0, self.dis.nrow):
                    for j in range(0, self.dis.ncol):
                        self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                        count = count + 1
                self.out_drn = self.out_all[0]
                self.out_drn[self.dem_mask] = -9999
                # self.out_drn.to_hdf(self.dict_outflow_drain, lead_numb)
                output_path = self.tifs_file+'/outflow_drain_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.out_drn, -9999, output_path)
                self.dict_outflow_drain[item] = self.out_drn
            
            if groundwater_flux == True:
                # Groundwater data
                self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
                self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
                self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
                if self.nlay == 1:
                    self.flux = np.sqrt(self.frf**2 + self.fff**2)        
                if self.nlay > 1:
                    self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
                    self.flux = np.sqrt(self.frf**2 + self.fff**2, self.flf**2)
            
                ### Groundwater flux
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                # self.gw_flux.to_hdf(self.dict_groundwater_flux, lead_numb)
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.flux_top, -9999, output_path)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                # Groundwater data
                # print(self.kstpkper)
                # if time == 0:
                #     self.sto = np.ones((1, self.dis.nrow, self.dis.ncol)) * np.nan
                # else:
                #     self.sto = self.cbb.get_data(text='STORAGE', kstpkper=self.kstpkper, totim=time)[0]
                # self.gw_storage = self.sto.copy()
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[self.dem<0] = np.nan
                self.wt_sto = ( self.wt_sto - (self.dem-30) ) * (self.resolution**2) * self.porosity
                self.dict_groundwater_storage[item] = self.wt_sto
                # np.count_nonzero(~np.isnan(dem))
                # self.gw_sto = np.nansum(self.wt_sto)
            
            if specific_discharge == True:                
                ### Specific discharge
                # Import data
                if self.nlay == 1:
                    self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, None), self.mf, self.wt_elev.copy())
                if self.nlay > 1:
                    self.qx, self.qy, self.qz = pp.get_specific_discharge((self.frf, self.fff, self.flf), self.mf, self.wt_elev.copy())            
                self.specif_disch = np.sqrt(self.qx**2 + self.qy**2 + self.qz**2)
                self.specif_disch_top = self.specif_disch[0]
                self.specif_disch_top[self.dem_mask] = -9999
                # self.specif_disch.to_hdf(self.dict_specific_discharge, lead_numb)
                output_path = self.tifs_file+'/specific_discharge_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_path, self.specif_disch_top, -9999, output_path)
                self.dict_specific_discharge[item] = self.specif_disch_top
            
            if accumulation_flux == True:
                ### Accumulation flux
                routing_accflux.RoutingAccflux(self.geographic,
                                           'outflow_drain_t('+lead_numb+').tif',
                                           'tracept_t('+lead_numb+').shp',
                                           'accumulation_flux_t('+lead_numb+').tif',
                                           extraction_folder=self.save_file)
                output_path = self.tifs_file+'/accumulation_flux_t('+lead_numb+').tif'
                self.dict_accumulation_flux[item] = imageio.imread(output_path)
        
        # Save dictionaries to npy
        try:
            if watertable_elevation == True:
                np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
            if watertable_depth == True:
                np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
            if seepage_areas == True:
                np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
            if outflow_drain == True:
                np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
            if groundwater_flux == True:
                np.save(self.save_file+'/groundwater_flux', self.dict_groundwater_flux)
            if specific_discharge == True:   
                np.save(self.save_file+'/specific_discharge', self.dict_specific_discharge)
            if accumulation_flux == True:
                np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)
            if groundwater_storage == True:
                np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        except:
            pass
        
        if perenn_intermit == True:
            self.list_traces = sorted(glob.glob(self.surfaceflow_file+'/'+'tracept_t*.shp'), key=os.path.getmtime)
            # print(self.list_traces)
            cpt = 1
            inf = 0
            sup = 12
            step = int(round(len(self.list_traces)/12))
            for i in range(step):
                interv = self.list_traces[inf:sup]
                coord = []
                print('Check intermittency : '+str(cpt)+'/'+str(step))
                for file in interv:
                    outflow = gpd.read_file(file)
                    x_list = outflow.geometry.x
                    y_list = outflow.geometry.y
                    mix = list(zip(x_list, y_list))
                    coord.extend(mix)
                dfc = pd.DataFrame(coord, columns=['x','y'])
                dfc['z'] = dfc['x'].astype(str) + dfc['y'].astype(str)
                values = dfc['z'].value_counts()
                values = values[values>=12]
                for bis in interv:
                    outflow = gpd.read_file(bis)
                    outflow['x'] = outflow.geometry.x
                    outflow['y'] = outflow.geometry.y
                    outflow['z'] = outflow['x'].astype(str) + outflow['y'].astype(str)
                    val = 0
                    outflow['Persistanc'] = val
                    for xy in values.index:
                        val = 1
                        outflow.loc[outflow['z']==xy,'Persistanc'] = val
                    outflow.to_file(bis)
                inf+=12
                sup+=12
                cpt+=1

#%% notes

# # Export
# if self.calib == True:
#     if item == 0:
#         tif_adds.export_tif(self.dem_path, self.wt_depth, -9999,
#                             self.save_file+'/watertable_depth_t('+lead_numb+').tif')
# else:
#     tif_adds.export_tif(self.dem_path, self.wt_depth, -9999,
#                         self.save_file+'/watertable_depth_t('+lead_numb+').tif')
# # print('export watertable_depth')
        
   