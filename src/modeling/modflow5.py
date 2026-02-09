# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import pandas as pd
import numpy as np
import os
import sys
import imageio                           # Import raster to numpy matrix (not georeferenced but handy)
from os.path import dirname, abspath
import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import math

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Flopy
import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp

# Hydromodpy
from tools import toolbox, Process
from modeling import downslope

df = dirname(dirname(abspath(__file__)))
sys.path.append(df)


#%% CLASS

class Modflow5(Process):
    """
    TODO@TB: description
    Class Modflow.
    
    To build, run the hydrologic model and manage/format simulation outputs.
    """
    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'modflow5',
                 output_name: str = 'mf5'):

        """
        Initialize method. WIP

        Parameters
        ----------
        geographic : object
            Object geographic build by HydroModPy.
        model_folder : str, optional
            Path where the model will be store. The default is 'HydroModPy_outputs'.
        """
        
        # class initialization
        super().__init__(name,output_name)
        self._mod = {}
                
        # default path settings 
        self.set_iptpar(model_name   = 'default',
                        model_folder = None,        # must be updated by user
                        bin_path     = 'default')
        # default advanced parameters
        self._default_advanced_parameters()
        # default names for variables in shared environment, that will be used
        # to parameterize Modflow packages in pre-processing
        self._default_shared_parameters()
        
        # ==== TODO@TB: residuals of previous Modflow class initialization
        # default advanced parameters: plot options 
        self.set_advpar(plot_cross  = True,
                        cross_ylim = [])
    
        
    # %%% SETTER AND GETTER
    @property
    def get_module(self):
        return self._mod

    def add_module(self, mod):
        modname = mod.get_name
        self._mod.update({modname : mod})
        self.clear_csdpar()    
        
        
    # %%% PREPROCESSING
    # preprocessing and processing modules
    def processing_modules(self, shrenv):
        for modname in self.get_module:
            mod = self.get_module[modname]
            mod.preprocessing(shrenv)
            shrenv = mod.processing(shrenv)
        return shrenv
    
    def preprocessing(self,shrenv: dict={}):
        """
        Pre-processing to build the hydrologic model.

        Returns
        -------
        None.

        """
        # workflow paths consolidation
        self._workflow_paths()
        # # processing modules to get consolidated simulation parameters
        # shrenv = self._processing_modules(shrenv)
        # load consolidated parameters into Modflow packages and prepare
        # simulation
        self._load_modflow_packages(shrenv) 
        # check grid flow connectivity (optional)
        self._check_water_flow_connectivity()
        # plot cross-section figures (optional)
        # TODO@TB: move to its own postprocessing class
        self._plot_cross_section(shrenv)
        

    # %%% PROCESSING    
    def processing(self, shrenv: dict={}):
        """
        Run the hydrologic model.

        Parameters
        ----------
        write_model : bool, optional
            Flag to write input files or not. The default is True.
        run_model : bool, optional
            Flag to run model or not. The default is False.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation is done correctly.

        """        
        write_model = self.get_advpar['pc_write_model']
        verbose     = self.get_advpar['pc_verbose']
        run_model   = self.get_advpar['pc_run_model']
        
        # Create modflow files
        if write_model == True:
            # Write input files
            self.mf.write_input()
        
        # Run modflow files
        success_model = False
        if run_model == True:
            success_model, tempo = self.mf.run_model(silent=not verbose) 
        
        return shrenv, success_model
        
    # %%% POST-PROCESSING
    # TODO@TB: check & rework if necessary (looking at you, intermittency_x)
    def postprocessing(self, shrenv):

        """
        Create outputs files.

        Parameters
        ----------
        model_modflow : object
            MODFLOW Python object.
        watertable_elevation : bool, optional
            Write watertable elevation outputs. The default is True.
        watertable_depth : bool, optional
            Write watertable depth outputs. The default is True.
        seepage_areas : bool, optional
            Write seepage areas outputs. The default is True.
        outflow_drain : bool, optional
            Write outflow drain outputs. The default is True.
        groundwater_flux : bool, optional
            Write groundwater flux outputs. The default is True.
        groundwater_storage : bool, optional
            Write groundwater storage outputs. The default is True.
        accumulation_flux : bool, optional
            Write accumulation flux outputs. The default is True.
        persistency_index : bool, optional
            Write persistency index outputs. The default is False.
        intermittency_monthly : bool, optional
            Write intermittency monthly outputs. The default is False.
        intermittency_weekly : bool, optional
            Write intermittency weekly outputs. The default is False.
        intermittency_daily : bool, optional
            Write intermittency daily outputs. The default is False.
        export_all_tif : bool, optional
            Write all files .tif at each time step. The default is False.
        """

        watertable_elevation  = self.get_advpar['ppc_watertable_elevation']
        watertable_depth      = self.get_advpar['ppc_watertable_depth']
        seepage_areas         = self.get_advpar['ppc_seepage_areas']
        outflow_drain         = self.get_advpar['ppc_outflow_drain']
        groundwater_flux      = self.get_advpar['ppc_groundwater_flux']
        groundwater_storage   = self.get_advpar['ppc_groundwater_storage']
        accumulation_flux     = self.get_advpar['ppc_accumulation_flux']
        verbose               = self.get_advpar['ppc_verbose']
        persistency_index     = self.get_advpar['ppc_persistency_index']
        intermittency_yearly  = self.get_advpar['ppc_intermittency_yearly']
        intermittency_monthly = self.get_advpar['ppc_intermittency_monthly']
        intermittency_weekly  = self.get_advpar['ppc_intermittency_weekly']
        intermittency_daily   = self.get_advpar['ppc_intermittency_daily']
        export_all_tif        = self.get_advpar['ppc_export_all_tif']       
        
        sgridnam = self.get_shrpar['sgrid']
        sgrid    = self.get_envar(shrenv,sgridnam)
        dem      = sgrid.top
        dem[dem<=-9999] = -9999  #TODO@TB
        dem[dem>=9999] = -9999
        nlay     = sgrid.nlay
        botm     = sgrid.botm
        resolution = sgrid.delc[0]
        synam  = self.get_shrpar['sy']        
        sy     = self.get_envar(shrenv,synam)
        #TODO@TB: all variables set as properties below: for modpath
        self.sy = sy   
        ssnam  = self.get_shrpar['ss']
        ss     = self.get_envar(shrenv,ssnam)
        self.ss = ss 
        self.nrow=sgrid.nrow
        self.ncol=sgrid.ncol
        self.nlay=sgrid.nlay
        
        # Create folders 
        self.save_file = os.path.join(self.full_path, '_postprocess')
        toolbox.create_folder(self.save_file)        
        
        self.figure_file = os.path.join(self.full_path, '_postprocess', '_figures')
        toolbox.create_folder(self.figure_file)
        
        self.temporary_file = os.path.join(self.full_path, '_postprocess','_temporary')
        toolbox.create_folder(self.temporary_file)
        
        self.tifs_file = os.path.join(self.full_path, '_postprocess', '_rasters')
        toolbox.create_folder(self.tifs_file)
        
        self.save_fig = os.path.join(self.model_folder, '_figures')
        toolbox.create_folder(self.save_fig)

        # %%%% Load essential data
        
        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name)
        
        # Files have been output in the processing phase and are re-read here
        self.dem_mask = (dem<-9999)
        # heads
        self.head_fpu = fpu.HeadFile(self.path_file+'.hds') 
        # fluxes
        self.cbb = fpu.CellBudgetFile(self.path_file+'.cbc')
        
        # Import times
        self.times = self.head_fpu.get_times()
        self.kstpkpers = self.head_fpu.get_kstpkper()
        
        # Params model
        self.nper = self.dis.nper
        self.kper = np.arange(0,self.nper,1)
        if len(self.kper) > 1:
            self.kstp = self.nstp[self.kper] - 1
             
        # %%%% Export results over times
        
        # Fill dictionnaries .npy or .nc over times and create .tif
        
        # Create dictionnaries for each of the results to extract 
        # x[time]=matrix
        #   - x: type of output
        #   - time: time at which it is taken
        #   - matrix: 2D matrix of values
        self.dict_watertable_elevation = {}
        self.dict_watertable_depth = {}
        self.dict_seepage_areas = {}
        self.dict_outflow_drain = {}
        self.dict_groundwater_flux = {}
        self.dict_specific_discharge = {}
        self.dict_accumulation_flux = {}
        self.dict_groundwater_storage = {}
        self.dict_persistency_index = {}
        self.dict_intermittency_yearly = {}
        self.dict_intermittency_monthly = {}
        self.dict_intermittency_weekly = {}
        self.dict_intermittency_daily = {}
        
        # print('Post-processing MODFLOW', ':', self.model_name)
        
        # Loop over times: fills each of the previous structures and create raster
        for item, time in enumerate(self.times):
            if verbose == True:
                print(' Post-processing:  Stress period:   ', str(int(item+1)), ' / ', str(len(self.times)))
            
            if len(self.times) == 1:
                self.kstpkper = self.kstpkpers[0]
            
            if len(self.times) > 1:
                self.kstpkper = (self.kstp[item], self.kper[item])
            
            lead_numb = str(item)
            
            export_tif = True
            if export_all_tif == False:
                if item > 0:
                    export_tif = False
            
            # Search watertable data positive values
            self.head = self.head_fpu.get_data(totim=time)  # self.head_all = self.head_fpu.get_alldata(), self.head_all[item][0]
            if nlay == 1:
                self.head_data = self.head[0]
            else:
                ### Option 1
                drycellval = self.get_advpar['upw_hdry']
                self.head_data = pp.get_water_table(self.head, drycellval) # -9999                
                ### Option 2
                # head_final = np.zeros([self.nrow,self.ncol])
                # for i in range(0,self.nrow):
                #     for j in range (0,self.ncol):
                #         for k in range(0,self.nlay): 
                #             if self.head[k,i,j] > 0:
                #                 head_final[i,j] = self.head[k,i,j]
                #                 break   
                # self.head_data = head_final.copy()
            
            if watertable_elevation == True:   
                ### Watertable elevation
                self.wt_elev = self.head_data.copy()
                self.wt_elev[self.dem_mask] = -9999
                output_path = self.tifs_file+'/watertable_elevation_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_elev, output_path, -9999)                  
                self.dict_watertable_elevation[item] = self.wt_elev
            
            if watertable_depth == True:
                ### Watertable depth
                self.wt_depth = dem - self.wt_elev.copy()
                self.wt_depth[self.dem_mask] = -9999
                output_path = self.tifs_file+'/watertable_depth_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_depth, output_path, -9999)
                self.dict_watertable_depth[item] = self.wt_depth
            
            if seepage_areas == True:
                ### Seepage areas
                self.seep_area = dem - self.wt_elev.copy()
                self.seep_area[self.seep_area >= 0] = 0
                self.seep_area[self.seep_area < 0] = 1
                self.seep_area[self.dem_mask] = -9999
                output_path = self.tifs_file+'/seepage_areas_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.seep_area, output_path, -9999)
                self.dict_seepage_areas[item] = self.seep_area
            
            if outflow_drain == True:
                ### Outflow drain
                self.drain = self.cbb.get_data(text='DRAINS', kstpkper=self.kstpkper, totim=time)            
                self.out_all = np.zeros((1, self.dis.nrow, self.dis.ncol))
                sim = 0
                count = 0
                for i in range(0, self.dis.nrow):
                    for j in range(0, self.dis.ncol):
                     # if self.drain_array[i,j] == 1:  #TODO@TB: will return error if drains arent present everywhere on first layer (e.g. ocean)
                        self.out_all[sim, i, j] = np.abs(self.drain[0][count][1])
                        count = count + 1
                self.out_drn = self.out_all[0]
                self.out_drn[self.dem_mask] = -9999
                output_path = self.tifs_file+'/outflow_drain_t('+lead_numb+').tif' 
                if accumulation_flux==True:
                    toolbox.export_tif(self.dem_watershed_path, self.out_drn, output_path, -9999)
                else:
                    if export_tif==True:
                        toolbox.export_tif(self.dem_watershed_path, self.out_drn, output_path, -9999)
                self.dict_outflow_drain[item] = self.out_drn
            
            if groundwater_flux == True:
                ### Groundwater flux
                self.cbb_data = self.cbb.get_data(kstpkper=(0, 0))
                self.frf = self.cbb.get_data(text='FLOW RIGHT FACE', kstpkper=self.kstpkper, totim=time)[0]
                self.fff = self.cbb.get_data(text='FLOW FRONT FACE', kstpkper=self.kstpkper, totim=time)[0]
                if nlay == 1:
                    self.flux = np.sqrt(self.frf**2 + self.fff**2)        
                if nlay > 1:
                    self.flf = self.cbb.get_data(text='FLOW LOWER FACE', kstpkper=self.kstpkper, totim=time)[0] # > 1 lay
                    self.flux = np.sqrt(self.frf**2 + self.fff**2 + self.flf**2)
                self.flux_top = self.flux[0]
                self.flux_top[self.dem_mask] = -9999
                output_path = self.tifs_file+'/groundwater_flux_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.flux_top, output_path, -9999)
                self.dict_groundwater_flux[item] = self.flux_top
            
            if groundwater_storage == True:
                ### Groundwater storage
                self.wt_sto = self.wt_elev.copy()
                self.wt_sto[dem<0] = np.nan
                self.wt_sto = ( self.wt_sto - botm[-1] ) * (resolution**2) * np.nanmean(sy)
                output_path = self.tifs_file+'/groundwater_storage_t('+lead_numb+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.dem_watershed_path, self.wt_sto, output_path, -9999)
                self.dict_groundwater_storage[item] = self.wt_sto

            if accumulation_flux == True:
                ### Accumulation flux
                accumulated_flow = downslope.Downslope(self.geographic,
                                                              'outflow_drain_t('+lead_numb+').tif',
                                                              'tracept_t('+lead_numb+').shp',
                                                              'accumulation_flux_t('+lead_numb+').tif',
                                                              extraction_folder=self.save_file)
                # accumulated_flow = downslope.Downslope(self.geographic,
                #                                               'outflow_drain_t('+lead_numb+').tif',
                #                                               'tracept_t('+lead_numb+').shp',
                #                                               'accumulation_flux_t('+lead_numb+').tif',
                #                                               'seepage_areas_t('+lead_numb+').tif',
                #                                               'accum_cells_t('+lead_numb+').tif',
                #                                               'river_network_t('+lead_numb+').tif',
                #                                               'river_network_t('+lead_numb+').shp',
                #                                               'longprofile_t('+lead_numb+').html',
                #                                               extraction_folder=self.save_file)
                accumulated_flow.trace_cumulated()
                # accumulated_flow.trace_rivers(threshold=50)
                output_path = self.tifs_file+'/accumulation_flux_t('+lead_numb+').tif'
                try:
                    self.dict_accumulation_flux[item] = imageio.v2.imread(output_path)
                except:
                    self.dict_accumulation_flux[item] = imageio.imread(output_path)
                    pass
            
        ### Save dictionaries to npy
        if watertable_elevation == True:
            if verbose == True:
                print('  ','Export watertable elevation')
            np.save(self.save_file+'/watertable_elevation', self.dict_watertable_elevation)
        if watertable_depth == True:
            if verbose == True:
                print('  ','Export watertable depth')
            np.save(self.save_file+'/watertable_depth', self.dict_watertable_depth)
        if seepage_areas == True:
            if verbose == True:
                print('  ','Export seepage areas')
            np.save(self.save_file+'/seepage_areas', self.dict_seepage_areas)
        if outflow_drain == True:
            if verbose == True:
                print('  ','Export outflow drain')
            np.save(self.save_file+'/outflow_drain', self.dict_outflow_drain)
        if groundwater_flux == True:
            if verbose == True:
                print('  ','Export groundwater flux')
            np.save(self.save_file+'/groundwater_flux', self.dict_groundwater_flux)
        if groundwater_storage == True:
            if verbose == True:
                print('  ','Export groundwater storage')
            np.save(self.save_file+'/groundwater_storage', self.dict_groundwater_storage)
        if accumulation_flux == True:
            if verbose == True:
                print('  ','Export accumulation flux')
            np.save(self.save_file+'/accumulation_flux', self.dict_accumulation_flux)

        if persistency_index == True:
            ### Persistency index
            if verbose == True:
                print('  ','Export persistency index')
            acc_npy_raw = np.load(os.path.join(self.save_file,'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            for key in range(len(acc_npy)):
                mask = dem
                # mask = imageio.imread(self.geographic.watershed_box_buff_dem)
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
            pi_export = days_flux.copy()
            self.pi = np.ma.masked_where(days_flux <= 0, days_flux)
            self.dict_persistency_index[0] = self.pi
            pi_export[days_flux <= 0] = -9999
            pi_export[mask<=0] = -9999
            output_path = self.tifs_file+'/persistency_index_t('+'-'+').tif'
            toolbox.export_tif(self.dem_watershed_path, pi_export, output_path, -9999)
        
            np.save(self.save_file+'/persistency_index', self.dict_persistency_index)
            
        if intermittency_daily == True:
            ### Intermittency daily
            if verbose == True:
                print('  ','Export intermittency daily')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=365:
                inf = 0
                sup = 365
                step = int(round(len(acc_npy_raw)/365))
                compt=0            
                for i in range(step):
                    # print('t: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))                    
                    zero = acc_npy_raw[0] * 0                
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo                    
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))                
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<365] = 0
                        tempo[days_flux==365] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_daily_t('+str(compt)+').tif'
                        # if export_tif==True:
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1                    
                    inf+=365
                    sup+=365                    
            np.save(self.save_file+'/intermittency_daily', self.dict_intermittency_daily)
        
        if intermittency_weekly == True:
            if verbose == True:
                print('  ','Export intermittency weekly')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=52:
                inf = 0
                sup = 52
                step = int(round(len(acc_npy_raw)/52))
                compt=0            
                for i in range(step):
                    # print('t: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))                    
                    zero = acc_npy_raw[0] * 0                
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo                    
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))                
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<52] = 0
                        tempo[days_flux==52] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_daily[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_weekly_t('+str(compt)+').tif'
                        # if export_tif==True:
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1                    
                    inf+=52
                    sup+=52
            np.save(self.save_file+'/intermittency_weekly', self.dict_intermittency_weekly)
        
        if intermittency_monthly == True:
            ### Intermittency monthly
            if verbose == True:
                print('  ','Export intermittency monthly')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=12:
                inf = 0
                sup = 12
                step = int(round(len(acc_npy_raw)/12))
                compt=0            
                for i in range(step):
                    # print('t: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))                    
                    zero = acc_npy_raw[0] * 0                
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo                    
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))                
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<12] = 0
                        tempo[days_flux==12] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_monthly_t('+str(compt)+').tif'
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1                    
                    inf+=12
                    sup+=12                    
            np.save(self.save_file+'/intermittency_monthly', self.dict_intermittency_monthly)
            
        if intermittency_yearly == True:
            ### Intermittency monthly
            if verbose == True:
                print('  ','Export intermittency yearly')
            acc_npy_raw = np.load(os.path.join(self.save_file, 'accumulation_flux.npy'),
                              allow_pickle=True).item()
            acc_npy = list(acc_npy_raw.items())[:]
            if len(acc_npy_raw)>=1:
                inf = 0
                sup = 1
                step = int(round(len(acc_npy_raw)/1))
                compt=0            
                for i in range(step):
                    # print('t: '+str(i)+' / '+str((step)))
                    interv = list(acc_npy)[inf:sup]
                    for key in range(len(interv)):
                        mask = imageio.imread(self.geographic.watershed_dem)
                        interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))                    
                    zero = acc_npy_raw[0] * 0                
                    for j in range(len(interv)):
                        tempo = interv[j].copy()
                        tempo[tempo>0] = 1
                        zero = zero + tempo                    
                    days_flux = zero.copy()
                    days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
                    days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))                
                    for k in range(len(interv)):
                        tempo = np.ma.masked_where(interv[k]<=0, interv[k])
                        tempo[days_flux<1] = 0
                        tempo[days_flux==1] = 1
                        tempo_export = tempo.copy()
                        self.tempo = np.ma.masked_where(interv[k]<=0, tempo)
                        self.dict_intermittency_monthly[compt] = self.tempo
                        tempo_export[interv[k]<=0] = -9999
                        tempo_export[mask<=0] = -9999
                        output_path = self.tifs_file+'/intermittency_yearly_t('+str(compt)+').tif'
                        toolbox.export_tif(self.geographic.watershed_dem,
                                           tempo_export,
                                           output_path, -9999)
                        compt+=1                    
                    inf+=12
                    sup+=12                    
            np.save(self.save_file+'/intermittency_yearly', self.dict_intermittency_monthly)

    # %%% PRIVATE METHODS: DEFAULT PARAMETERS
    # default advanced parameters    
    def _default_advanced_parameters(self):
        # default advanced parameters: Modflow module
        self.set_advpar(mf_version  = 'mfnwt',
                        mf_listunit = 2,
                        mf_verbose  = False,)
        # default advanced parameters: Nwt module
        self.set_advpar(nwt_headtol    = 1e-4, 
                        nwt_fluxtol    = 500, 
                        nwt_maxiterout = 5000,
                        nwt_thickfact  = 1e-05,
                        nwt_linmeth    = 1,
                        nwt_iprnwt     = 1,
                        nwt_ibotav     = 1,
                        nwt_options    = 'COMPLEX',
                        nwt_Continue   = False,
                        nwt_backflag   = 0,
                        nwt_stoptol    = 1e-10)
        # default advanced parameters: Bas module
        self.set_advpar(bas_hnoflo = -9999)   #TODO@TB WARNING: has to be manually changed in ModPath class too
        # default advanced parameters: Upw module
        self.set_advpar(upw_laytyp = 1,
                        upw_laywet = 0, 
                        upw_iphdry = 1,
                        upw_hdry   = -10000,  #TODO@TB WARNING: has to be manually changed in ModPath class too
                        upw_layvka = 1)
        # default advanced parameters: Evt module
        self.set_advpar(evt_nevtop = 3, 
                        evt_exdp   = 10, 
                        evt_ievt   = 1, 
                        evt_ipakcb = 1)
        # default advanced parameters: Well module 
        self.set_advpar(wel_ipakcb = 1)
        # default advanced parameters: Oc module
        self.set_advpar(oc_extension  = ['oc','hds','cbc'],                                
                        oc_unitnumber = None,
                        oc_compact    = True,
                        oc_stress_period_save
                                      = 'end_each_stress_period',
                        oc_stress_period_data
                                      = ['save head', 'save budget'])
        # default advanced parameters: lmt module
        self.set_advpar(lmt_isused             = True,
                        lmt_output_file_name   = 'mt3d_link.ftl',
                        lmt_extension          = 'lmt8', 
                        lmt_output_file_format = 'unformatted', 
                        lmt_unitnumber         = None)
        # default advanced parameters: check grid flow connectivity option
        self.set_advpar(check_grid_flow_connectivity = True)
        # default advanced parameters: processing modflow simulation
        self.set_advpar(pc_write_model = True,
                        pc_verbose     = True,
                        pc_run_model   = True)
        # default advanced parameters: postprocessing modflow simulation
        self.set_advpar(ppc_watertable_elevation  = True,
                        ppc_watertable_depth      = True, 
                        ppc_seepage_areas         = True,
                        ppc_outflow_drain         = True,
                        ppc_groundwater_flux      = True,
                        ppc_groundwater_storage   = True,
                        ppc_accumulation_flux     = True,
                        ppc_verbose               = True,
                        ppc_persistency_index     = False,
                        ppc_intermittency_yearly  = False,
                        ppc_intermittency_monthly = False,
                        ppc_intermittency_weekly  = False,
                        ppc_intermittency_daily   = False,
                        ppc_export_all_tif        = False)


    # default names for variables in shared environment, that will be used
    # to parameterize Modflow packages in pre-processing
    def _default_shared_parameters(self):
        self.set_shrpar(sgrid  = 'sdis',
                        tgrid  = 'tdis',
                        ibound = 'ibound',
                        strt   = 'strt',
                        chd    = 'chd',
                        hk     = 'hk',
                        sy     = 'sy',
                        ss     = 'ss',
                        vka    = 'vka',
                        rch    = 'rch',
                        evt    = 'evt',
                        wel    = 'wel',
                        drn    = 'drn')
    
    # %%% PRIVATE METHODS: PREPROCESSING
    # workflow paths consolidation
    def _workflow_paths(self):
        # iptpar is relative path, property is absolute user-specific path
        self.model_folder = self.get_iptpar['model_folder']
        self.model_name   = self.get_iptpar['model_name']
        self.bin_path     = self.get_iptpar['bin_path']
        if self.bin_path == 'default':
            self.bin_path = os.path.join(toolbox.hydromodpy_root(),'bin')
        
        if not os.path.exists(self.model_folder):
            toolbox.create_folder(self.model_folder) 
            
        self.full_path = os.path.join(self.model_folder, self.model_name)
        if not os.path.exists(self.full_path):
            toolbox.create_folder(self.full_path)
        
        if (sys.platform == 'win32') or (sys.platform == 'win64'):
            self.exe = os.path.join(self.bin_path, 'win' ,'mfnwt.exe')
        if (sys.platform == 'linux'):
            self.exe = os.path.join(self.bin_path, 'linux' ,'mfnwt')
        if (sys.platform == 'darwin'):
            self.exe = os.path.join(self.bin_path, 'mac' ,'mfnwt')   
        self.full_path = os.path.join(self.model_folder, self.model_name)
    
    
    # # preprocessing and processing modules
    # def _processing_modules(self, shrenv):
    #     for modname in self.get_module:
    #         mod = self.get_module[modname]
    #         mod.preprocessing(shrenv)
    #         shrenv = mod.processing(shrenv)
    #     return shrenv
    
    
    # load consolidated parameters into Modflow packages
    def _load_modflow_packages(self, shrenv):  
        # %%%% Solvers   
        # Flopy initialization of Modflow model
        # ---- flopy.modflow.Modflow
        self.mf = flopy.modflow.Modflow(modelname = self.get_iptpar['model_name'], 
                                        exe_name  = self.exe,  
                                        version   = self.get_advpar['mf_version'],
                                        listunit  = self.get_advpar['mf_listunit'],
                                        verbose   = self.get_advpar['mf_verbose'],
                                        model_ws  = self.full_path)    
        
        # Uses Nwt for Modflow 2005, necessary for unconfined aquifers (improved interactions between surface and aquifer)
        # Sets up numerical parameters
        # ---- flopy.modflow.ModflowNwt
        self.nwt = flopy.modflow.ModflowNwt(model      = self.mf,
                                            headtol    = self.get_advpar['nwt_headtol'],
                                            fluxtol    = self.get_advpar['nwt_fluxtol'],
                                            maxiterout = self.get_advpar['nwt_maxiterout'],
                                            thickfact  = self.get_advpar['nwt_thickfact'],
                                            linmeth    = self.get_advpar['nwt_linmeth'],
                                            iprnwt     = self.get_advpar['nwt_iprnwt'],
                                            ibotav     = self.get_advpar['nwt_ibotav'],
                                            options    = self.get_advpar['nwt_options'],
                                            Continue   = self.get_advpar['nwt_Continue'],
                                            backflag   = self.get_advpar['nwt_backflag'],
                                            stoptol    = self.get_advpar['nwt_stoptol'])
        
        # %%%% Discretization
        # Master spatial & time discretization
        sgridnam = self.get_shrpar['sgrid']
        sgrid    = self.get_envar(shrenv,sgridnam)
        tgridnam = self.get_shrpar['tgrid']
        tgrid    = self.get_envar(shrenv,tgridnam)
        # ---- flopy.modflow.ModflowDis 
        self.dis = flopy.modflow.ModflowDis(model  = self.mf, 
                                            lenuni = sgrid.lenuni, 
                                            nlay   = sgrid.nlay, 
                                            nrow   = sgrid.nrow, 
                                            ncol   = sgrid.ncol, 
                                            delr   = sgrid.delr, 
                                            delc   = sgrid.delc,
                                            top    = sgrid.top, 
                                            botm   = sgrid.botm, 
                                            xul    = sgrid.xoffset, 
                                            yul    = sgrid.extent[3],
                                            itmuni = tgrid.time_units, 
                                            nper   = tgrid.nper, 
                                            perlen = tgrid.perlen, 
                                            nstp   = tgrid.nstp,
                                            steady = tgrid.steady_state, 
                                            start_datetime 
                                                   = tgrid.start_datetime)
        
        # %%%% Boundary conditions
        # Initial boundary conditions & initial hydraulic heads
        iboundnam = self.get_shrpar['ibound']
        ibound    = self.get_envar(shrenv,iboundnam)
        strtnam   = self.get_shrpar['strt']
        strt      = self.get_envar(shrenv,strtnam)
        # ---- flopy.modflow.ModflowBas
        self.bas = flopy.modflow.ModflowBas(model  = self.mf, 
                                            ibound = ibound, 
                                            strt   = strt, 
                                            hnoflo = self.get_advpar['bas_hnoflo'])
        
        # Time-Variant Specified Constant Heads (optional, e.g. sea level)
        # WARNING: once one cell is flagged as constant head during one time 
        # period it will remained flagged as constant head until the end of the 
        # simulation; only the value of the constant head can then be adjusted
        # (see ModflowChd documentation)
        chdnam = self.get_shrpar['chd']
        chddat = self.get_envar(shrenv,chdnam)
        # ---- flopy.modflow.ModflowChd (optional)
        if chddat != None:
            self.chd = flopy.modflow.ModflowChd(model              = self.mf, 
                                                stress_period_data = chddat)
        
    
        # %%%% Hydraulic parameters
        # Horizontal hydraulic conductivity, specific yield & specific storage,
        # and vertical anisotropy of hydraulic conductivity (ratio 
        # K_horizontal / K_vertical)
        hknam  = self.get_shrpar['hk']
        hk     = self.get_envar(shrenv,hknam)
        synam  = self.get_shrpar['sy']
        sy     = self.get_envar(shrenv,synam)
        ssnam  = self.get_shrpar['ss']
        ss     = self.get_envar(shrenv,ssnam)
        vkanam = self.get_shrpar['vka']
        vka    = self.get_envar(shrenv,vkanam)
        # ---- flopy.modflow.ModflowUpw
        self.upw = flopy.modflow.ModflowUpw(model  = self.mf, 
                                            hk     = hk,
                                            sy     = sy,
                                            ss     = ss,
                                            vka    = vka,
                                            laytyp = self.get_advpar['upw_laytyp'],
                                            laywet = self.get_advpar['upw_laywet'], 
                                            iphdry = self.get_advpar['upw_iphdry'],
                                            hdry   = self.get_advpar['upw_hdry'],
                                            layvka = self.get_advpar['upw_layvka'])
        
        
        # %%%% Source terms
        # Recharge of the aquifer (top of water table)
        rechnam = self.get_shrpar['rch']
        rech    = self.get_envar(shrenv,rechnam)
        # ---- flopy.modflow.ModflowRch
        self.rch = flopy.modflow.ModflowRch(model = self.mf, 
                                            rech  = rech)
        
        # Evapotranspiration (optional)
        evtrnam = self.get_shrpar['evt']
        evtdict = self.get_envar(shrenv,evtrnam)   
        # ---- flopy.modflow.ModflowEvt
        if evtdict != None:
            evtdata = evtdict['evtdata']
            evtsurf = evtdict['evtsurf'] 
            self.evt = flopy.modflow.ModflowEvt(model  = self.mf,
                                                evtr   = evtdata,
                                                surf   = evtsurf,
                                                nevtop = self.get_advpar['evt_nevtop'], 
                                                exdp   = self.get_advpar['evt_exdp'],
                                                ievt   = self.get_advpar['evt_ievt'],
                                                ipakcb = self.get_advpar['evt_ipakcb'])
       
    
        # %%%% Drain package
        drnnam = self.get_shrpar['drn']
        drndat = self.get_envar(shrenv,drnnam)
        
        # ---- flopy.modflow.ModflowDrn
        self.drn = flopy.modflow.ModflowDrn(model              = self.mf, 
                                            stress_period_data = drndat)
        
               
        # %%%% Well package (optional)
        welnam = self.get_shrpar['wel']
        weldat = self.get_envar(shrenv,welnam)
        
        # ---- flopy.modflow.ModflowWel
        if weldat != None:
            self.wel = flopy.modflow.ModflowWel(model  = self.mf,
                                                ipakcb = self.get_advpar['wel_ipakcb'],
                                                stress_period_data 
                                                       = weldat)
        
        # %%%% Output control
        
        # TODO@TB: should be parameterized by its own class? 
        oc_stress_period_save = self.get_advpar['oc_stress_period_save']
        if oc_stress_period_save == 'end_each_stress_period':
            oc_stress_period_data = self.get_advpar['oc_stress_period_data']           
            nper = tgrid.nper
            nstp = tgrid.nstp
            stress_period_data = {}
            for kper in range(nper):
                kstp = nstp[kper]
                # Default: Saves head (hds) and budget (cbc) for each of the stress periods
                stress_period_data[(kper, kstp-1)] = oc_stress_period_data
        # ---- flopy.modflow.ModflowOc
        self.oc = flopy.modflow.ModflowOc(model      = self.mf, 
                                          stress_period_data=stress_period_data, 
                                          extension  = self.get_advpar['oc_extension'],                                
                                          unitnumber = self.get_advpar['oc_unitnumber'],
                                          compact    = self.get_advpar['oc_compact'])
        self.oc.reset_budgetunit(fname = self.get_iptpar['model_name']+'.cbc')
        
        # %%%% Link with MT3DMS
        # ---- flopy.modflow.ModflowLmt
        lmt_isused = self.get_advpar['lmt_isused']
        if lmt_isused == True:
            self.lmt = flopy.modflow.ModflowLmt(model              = self.mf,
                                                output_file_name   = self.get_advpar['lmt_output_file_name'],
                                                extension          = self.get_advpar['lmt_extension'], 
                                                output_file_format = self.get_advpar['lmt_output_file_format'], 
                                                unitnumber         = self.get_advpar['lmt_unitnumber'])
   
    
    
    # check water flow connectivity
    def _check_water_flow_connectivity(self):
        
        check_grid = self.get_advpar['check_grid_flow_connectivity']
        if check_grid == False: return
        
        grid = self.mf.modelgrid.top_botm
        layers, rows, cols = grid.shape
        problematic_cells = []  # Store problematic cells

        for z in range(layers - 1):  # Focus on flow between layers
            # print(f"Checking layer {z}")
            for y in range(rows):
                for x in range(cols):
                    # Skip if the current cell is inactive (e.g., NaN or specific inactive value)
                    if np.isnan(grid[z, y, x]) or np.isnan(grid[z+1, y, x]):
                        continue

                    # Current cell's top and bottom elevations
                    current_top = grid[z, y, x]
                    current_bottom = grid[z+1, y, x]

                    neighbors = []

                    # Collect adjacent neighbors' top and bottom elevations
                    if y > 0 and not (np.isnan(grid[z, y-1, x]) or np.isnan(grid[z+1, y-1, x])):  # Left neighbor
                        neighbors.append((grid[z, y-1, x], grid[z+1, y-1, x]))
                    if y < rows - 1 and not (np.isnan(grid[z, y+1, x]) or np.isnan(grid[z+1, y+1, x])):  # Right neighbor
                        neighbors.append((grid[z, y+1, x], grid[z+1, y+1, x]))
                    if x > 0 and not (np.isnan(grid[z, y, x-1]) or np.isnan(grid[z+1, y, x-1])):  # Front neighbor
                        neighbors.append((grid[z, y, x-1], grid[z+1, y, x-1]))
                    if x < cols - 1 and not (np.isnan(grid[z, y, x+1]) or np.isnan(grid[z+1, y, x+1])):  # Back neighbor
                        neighbors.append((grid[z, y, x+1], grid[z+1, y, x+1]))

                    # If there are neighbors, check if water can flow
                    if neighbors:
                        can_flow = False
                        for neighbor_top, neighbor_bottom in neighbors:
                            # Check if current cell's range overlaps with neighbor's range
                            if (current_bottom <= neighbor_top and current_top >= neighbor_bottom):
                                can_flow = True
                                break
                        
                        if not can_flow:
                            problematic_cells.append((z, y, x))

        if not problematic_cells:
            print("Check model grid:", "all cells satisfy the water flow connectivity condition")
            self.prob_cells = 0
        else:
            print("Check model grid:", f"total number of problematic cells is {len(problematic_cells)}")
            self.prob_cells = len(problematic_cells)
     
    # cross-section visualisation 
    # TODO@TB: move to its own class      
    def _plot_cross_section(self,shrenv):
        
        plot_cross = self.get_advpar['plot_cross']
        if plot_cross == False: return
        
        hknam  = self.get_shrpar['hk']
        hk     = self.get_envar(shrenv,hknam)
        synam  = self.get_shrpar['sy']
        sy     = self.get_envar(shrenv,synam)
        ssnam  = self.get_shrpar['ss']
        ss     = self.get_envar(shrenv,ssnam)
        vkanam = self.get_shrpar['vka']
        vka    = self.get_envar(shrenv,vkanam)
        tgridnam = self.get_shrpar['tgrid']
        tgrid    = self.get_envar(shrenv,tgridnam)
        sgridnam = self.get_shrpar['sgrid']
        sgrid    = self.get_envar(shrenv,sgridnam)
        dem      = sgrid.top
        cross_ylim = self.get_advpar['cross_ylim']
        model_name = self.get_iptpar['model_name']
        grid_model = self.mf.modelgrid
        
        fig, axs = plt.subplots(1, 2, figsize=(14,4), dpi=300)
        axs = axs.ravel()
        
        modelxsect1 = flopy.plot.PlotCrossSection(model=self.mf, line={'Row': int((grid_model.shape[1])/2)})
        imhk = modelxsect1.plot_array(hk, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[0],
                                      # norm=mpl.colors.LogNorm(vmin=self.hk.min(), vmax=self.hk.max())
                                      norm=mpl.colors.LogNorm(vmin=1e-7, vmax=1e1)
                                      )
        # modelxsect1.plot_grid(ax=axs[0])
        lenuni = sgrid.lenuni 
        if lenuni == 2: lenuni = 'm'
        itmuni = tgrid.time_units
        axs[0].set_title('West-East (Row), K ['+lenuni+'/'+itmuni+']', fontsize=12)
        if cross_ylim == []:
            axs[0].set_ylim(np.nanmin(np.ma.masked_equal(dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(dem, -9999, copy=False)))
        else:
            axs[0].set_ylim(cross_ylim[0], cross_ylim[1])
        axs[0].set_xlabel('Distance ['+lenuni+']')
        axs[0].set_ylabel('Elevation ['+lenuni+']')
        # divider = make_axes_locatable(axs[0])
        # cax = divider.append_axes('right', size='5%', pad=0.05)
        # fig.colorbar(imhk, cax=cax, orientation='vertical')
        fig.colorbar(imhk)
        
        modelxsect2 = flopy.plot.PlotCrossSection(model=self.mf, line={'Column': int((grid_model.shape[2])/2)})
        imsy = modelxsect2.plot_array(sy*100, masked_values=[-9999], cmap='jet', alpha=0.5, lw=0.1, ax=axs[1],
                                      # norm=mpl.colors.LogNorm(vmin=self.sy.min(), vmax=self.sy.max())
                                      norm=mpl.colors.LogNorm(vmin=0.1, vmax=100)
                                      )
        # modelxsect2.plot_grid(ax=axs[1])
        axs[1].set_title('North-South (Column), Sy [%]', fontsize=12)
        if cross_ylim == []:
            axs[1].set_ylim(np.nanmin(np.ma.masked_equal(dem, -9999, copy=False)),
                            np.nanmax(np.ma.masked_equal(dem, -9999, copy=False)))
        else:
            axs[1].set_ylim(cross_ylim[0], cross_ylim[1])
        axs[1].set_xlabel('Distance ['+lenuni+']')
        axs[1].set_ylabel('Elevation ['+lenuni+']')
        # divider = make_axes_locatable(axs[1])
        # cax = divider.append_axes('right', size='5%', pad=0.05)
        # fig.colorbar(imsy, cax=cax, orientation='vertical')
        fig.colorbar(imsy)
        
        fig.suptitle(model_name.upper(), y=1.0, fontsize=10)
        fig.tight_layout()
        plt.show()
        
        # for i in list(range(len(hk[:,0,0]))):
        #     plt.imshow(np.log10(hk[i,:,:]), interpolation='none')
        #     plt.colorbar()
        #     plt.show()
        
#%% NOTES
