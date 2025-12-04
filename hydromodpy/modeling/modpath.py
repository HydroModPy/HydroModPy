# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
from os.path import dirname, abspath
import random
import warnings
import pickle
import geopandas as gpd
import rasterio
import flopy.utils.postprocessing as pp
import whitebox
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
logger = get_logger(__name__)

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Modpath:
    """
    Class Modpath.
    
    To build, run particle traccking from modflow simulation.
    """
    
    def __init__(self,
                 geographic: object,
                 model_modflow: object,
                 # Worflow settings
                 model_folder: str='HydroModPy_outputs',
                 model_name: str='Default_modpath',
                 bin_path: str=os.path.join(os.getcwd(),'bin'),
                 # Specific settings
                 zone_partic: str='domain',
                 track_dir: str='forward',
                 bore_depth: list=None,
                 cell_div: int=1,
                 zloc_div: bool=False,
                 sel_random: int=None,
                 sel_slice: int=None):
        """
        Initialize method.

        Parameters
        ----------
        geographic : object
            Geographic object build by HydroModPy.
        model_modflow : object
            Python object of the MODFLOW model.
        model_folder : str, optional
            Name of the folder. The default is 'HydroModPy_outputs'.
        model_name : str, optional
            Name of the model. The default is 'Default'.
        bin_path : str, optional
            Location folder of the modflow executables. The default is 'bin'.
        zone_partic : str, optional
            Path of the raster used to inject particles: where value > 0.
            The default is 'domain', so the particles are injected where the model domain area > 0m. 
        track_dir: str
            Choice 'forward' or 'backward' particle tracking method.
            The default is 'forward'.
        bore_depth: list
            [Not stable, currently in development]
            If not None, inject a particle in the z direction (vertical), at the center position of each lays.
        cell_div: int
            Fix the number of particles injected uniformly distributed for each cell.
            If 3 is set, 9 particles will be inejcted (3x*3y)
            The dault is 1.
        zloc_div: bool
            If True, 'cell_div' is also applied vetically for the cells.
            If cell_div is 3 and zloc_div is True, 18 particles will be injected (3x*3y*3z).
            The default is False.
        sel_random: int
            Select randomly where inject a total number of particles.
        sel_random: int
            Select with slicing value where particles.
        """
        
        #%% Initialisation
        
        self.geographic = geographic
        
        self.model_modflow = model_modflow
        self.model_name = model_name
        self.model_folder = model_folder
        self.full_path = os.path.join(model_folder, model_name)
        
        if not os.path.isdir(self.full_path):
            raise FileNotFoundError('Directory not found: {}'.format(self.full_path))
        if (sys.platform == 'win32') or (sys.platform == 'win64'):
            self.exe = os.path.join(bin_path, 'win' ,'mp6.exe')
        if (sys.platform == 'linux'):
            self.exe = os.path.join(bin_path, 'linux' ,'mp6')
        if (sys.platform == 'darwin'):
            self.exe = os.path.join(bin_path, 'mac' ,'mp6')
        
        # Parameters for particles
        if zone_partic == 'domain':
            self.zone_partic = geographic.watershed_box_buff_dem
        else:
            self.zone_partic = zone_partic
        self.track_dir = track_dir
        self.bore_depth = bore_depth
        self.cell_div = cell_div
        self.zloc_div = zloc_div
        self.sel_random = sel_random
        self.sel_slice = sel_slice

    #%% PRE-PROCESSING
    
    def pre_processing(self):
        """
        Pre-processing to build the partickle tracking.

        Returns
        -------
        None.

        """
        
        #%% Load and import
        
        prefix = os.path.join(self.full_path, self.model_name)
        nam_file = '{}.nam'.format(prefix)
        dis_file = '{}.dis'.format(prefix)
        head_file = '{}.hds'.format(prefix)
        bud_file = '{}.cbc'.format(prefix)
        bas_file = '{}.bas'.format(prefix)
        lpf_file = '{}.upw'.format(prefix)
        
        # ---- flopy.modflow.Modflow.load
        self.mf = flopy.modflow.Modflow.load(
            nam_file,
            model_ws=self.full_path,
            verbose=False,
            check=False,
            exe_name=getattr(self.model_modflow, "exe", None) or "mfnwt",
        )
        
        # Avoid re-loading packages already attached to the model (prevents flopy duplicate warnings)
        bas = self.mf.get_package('BAS6')
        if bas is None:
            bas = flopy.modflow.ModflowBas.load(bas_file, self.mf)
        lpf = self.mf.get_package('UPW')
        if lpf is None:
            lpf = flopy.modflow.ModflowUpw.load(lpf_file, self.mf, check=False)
        nlay = self.mf.nlay
        ncol = self.mf.ncol
        nrow = self.mf.nrow
        laytype = lpf.laytyp.array
        iboundData = bas.ibound.array
        
        # ---- flopy.modpath.Modpath6
        self.mp = flopy.modpath.Modpath6(modelname=self.mf.name,
                                         model_ws=self.full_path,
                                         simfile_ext='mpsim',
                                         namefile_ext='mpnam',
                                         version='modpath',
                                         exe_name=self.exe,
                                         modflowmodel=self.mf,
                                         head_file=head_file,
                                         dis_file=dis_file,
                                         dis_unit=87,
                                         budget_file=bud_file)
        
        self.mp.array_free_format = True
        cbb = fpu.CellBudgetFile(bud_file)
        # cbb.list_records()
        rec_drn = cbb.get_data(kstpkper=(0, 0), text='DRAINS')
        rec_rch = cbb.get_data(kstpkper=(0, 0), text='RECHARGE')
        
        self.mp.dis_file = dis_file
        self.mp.head_file = head_file
        self.mp.budget_file = bud_file
                
        #%% Specific parametrization
        
        if self.track_dir=='forward':
            track = 1
            zone_opt = 1
            zone_inj = 1
            
        if self.bore_depth==None:
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
            zone_opt = 2
            zone_inj = szone.copy()

        if self.track_dir=='backward':
            track = 2
            zone_opt = 1
            zone_inj = 1

        flags = option_flags=[2, # SimulationType : 1 = Endpoint simulation; 2 = Pathline simulation; 3 = Timeseries simulation
                              track, # TrackingDirection : 1 = Forward tracking; 2 = Backward tracking
                              1, # WeakSinkOption : 1 = Allow particles to pass through cells that contain weak sinks; 2 = Stop particles when they enter cells that contain weak sinks.
                              1, # WeakSourceOption : 1 = Allow particles to pass through cells that contain weak sources; 2 = Stop particles when they enter cells that contain weak sources.
                              1, # ReferenceTimeOption : 1 = Specify a value for reference time; 2 = Specify a stress period, time step, and relative time position within the time step to use to compute the reference time.
                              2, # StopOption : 1 = For forward tracking simulations, stop at the end of the MODFLOW simulation. For backward tracking simulations, stop at the beginning of the MODFLOW simulation. 2 = Extend the initial or final steady-state MODFLOW time step as far as necessary to track all particles through to their termination points. For forward tracking simulations, this option would have an effect whenever the final MODFLOW stress period is steady-state. For backward tracking simulations, this option would have an effect whenever the first MODFLOW stress period is steady-state. If all MODFLOW stress periods are transient, option 2 produces the same result as option 1. 3 = Specify a value of tracking time at which to stop the particle-tracking computation.
                              2, # ParticleGenerationOption : 1 = Specify information to automatically generate particles for a collection of cells. 2 = Read particle locations from a starting locations file.
                              1, # TimePointOption : 1 = Time points are not specified. 2 = A specified number of time points are calculated for a fixed time increment. 3 = An array of time point values is specified.
                              1, # BudgetOutputOption : 1 = No budget checking 2 = A summary of cell-by-cell budgets is printed in the Listing File 3 = A list of cells is specified for which detailed budget information is summarized in the Listing File 4 = Trace mode is in effect
                              zone_opt, # ZoneArrayOption : 1 = No zone data are read. 2 = Zone data are read.
                              1, # RetardationOption : 1 = Retardataion factors are not read or used in the velocity calculations. 2 = An array of retardation factors is read and used in the velocity calculations.
                              1] # AdvectiveObservationsOption : 1 = Advective observations are not computed or saved. 2 = Advective observations are computed and saved for all time points. 3 = Advective observations are computed and saved only for the final time point.        
        logger.debug('Modpath settings - track: %s, zone_opt: %s, zone_inj: %s', track, zone_opt, type(zone_inj))
        
        # ---- flopy.modpath.Modpath6
        flopy.modpath.Modpath6Sim(model=self.mp, option_flags=flags,
                                  group_placement=[[1, 1, 1, 0, 1, 1]], stop_zone=1, zone=zone_inj) # szone

        with rasterio.open(self.zone_partic) as src:
            mask_dem = src.read(1)

        # ---- flopy.modpath.mp6sim.StartingLocationsFile
        stl = flopy.modpath.mp6sim.StartingLocationsFile(model=self.mp, inputstyle=1)
        
        prow = self.cell_div
        pcol = self.cell_div
        # if self.zloc_div == True:
        #     play = self.cell_div
        # else:
        #     play = 1
        if self.bore_depth != None:
            # play = len(self.bore_depth)
            play = nlay
        else:
            play = 1
            
        stldata = stl.get_empty_starting_locations_data(npt=np.sum(mask_dem>0)*prow*pcol*play)
              
        hds_1c = fpu.HeadFile(head_file)
        # head_1c = hds_1c.get_alldata(mflay=None)
        head_1c = hds_1c.get_data(totim=1)        
        wt = pp.get_water_table(head_1c, -100) # -9999
        # wt = np.ones((nrow, ncol)) * wt
                
        if self.track_dir == 'forward':
            compt = 0
            for i in range(0, nrow):
                for j in range(0, ncol):
                    if mask_dem[i,j] > 0: # active or note
                        for r in range(prow):
                            for c in range(pcol):
                                for l in range(play):
                                    stldata[compt]['label'] = 'p' + str(compt+1) + '-' + str(r) + '-' + str(c)
                                    for k in range(0, nlay):
                                        if (wt[i, j] > self.mf.dis.botm.array[k, i, j]):
                                            stldata[compt]['k0'] = k
                                            break
                                    # Calculate the starting location for each sub-cell
                                    stldata[compt]['j0'] = j
                                    stldata[compt]['i0'] = i
                                    # stldata[compt]['xloc0'] = (r +1) * 1/(prow +1)
                                    # stldata[compt]['yloc0'] = (c +1) * 1/(pcol +1)
                                    # stldata[compt]['xloc0'] = (r+0.1)/(prow+0.2) # old method
                                    # stldata[compt]['yloc0'] = (c+0.1)/(pcol+0.2) # old method
                                    stldata[compt]['xloc0'] = (r+0.5)/(prow) # new method
                                    stldata[compt]['yloc0'] = (c+0.5)/(pcol) # new method
                                    if k == 0:
                                        ztop = self.mf.dis.top.array[i,j]
                                    else:
                                        ztop = self.mf.dis.botm.array[k-1, i, j]
                                    zbot = self.mf.dis.botm.array[k, i, j]
                                    thickness = ztop - zbot
                                    if thickness <= 0:
                                        aux_stl = 0.0
                                    else:
                                        # Normalize the water level between 0 and 1 using the local cell thickness
                                        aux_stl = min(max((wt[i, j] - zbot) / thickness, 0.0), 1.0)
                                    # ==> min((wt[i, j] - zbot)/(ztop - zbot), 1.)
                                    val_z_wt = np.abs(aux_stl)
                                    # if l == 0:
                                    stldata[compt]['zloc0'] = val_z_wt
                                    # else:
                                    #     stldata[compt]['zloc0'] = 0
                                    compt = compt + 1
                
        if self.track_dir == 'backward':
            compt = 0
            for i in range(0, nrow):
                for j in range(0, ncol):
                    if mask_dem[i,j] > 0: # active or note
                        for r in range(prow):
                            for c in range(pcol):
                                for l in range(play):
                                    stldata[compt]['label'] = 'p' + str(compt+1) + '-' + str(r) + '-' + str(c)
                                    # for k in range(0, nlay):
                                    #     if (wt[i, j] > self.mf.dis.botm.array[k, i, j]):
                                    #         stldata[compt]['k0'] = k
                                    #         break
                                    # Calculate the starting location for each sub-cell
                                    stldata[compt]['j0'] = j
                                    stldata[compt]['i0'] = i
                                    # stldata[compt]['xloc0'] = (r +1) * 1/(prow +1)
                                    # stldata[compt]['yloc0'] = (c +1) * 1/(pcol +1)
                                    # stldata[compt]['xloc0'] = (r+0.1)/(prow+0.2) # old method
                                    # stldata[compt]['yloc0'] = (c+0.1)/(pcol+0.2) # old method
                                    stldata[compt]['xloc0'] = (r+0.5)/(prow) # new method
                                    stldata[compt]['yloc0'] = (c+0.5)/(pcol) # new method
                                    # stldata[compt]['xloc0'] = 0.5
                                    # stldata[compt]['yloc0'] = 0.5
                                    stldata[compt]['zloc0'] = 0.5
                                    if self.bore_depth == True:
                                        # z0 not exist at this step: need to find the good k (layer) to inject at different depth (create a loop)
                                        # For example: stldata[compt]['z0'] = self.mf.dis.top.array[i,j] - self.bore_depth[l]
                                        stldata[compt]['k0'] = l
                                    else:
                                        stldata[compt]['k0'] = 0
                                    compt = compt + 1
        
        #%% Select random particles to inject
        
        # Random
        if self.sel_random != None:
            if self.sel_random >= len(stldata):
                val_random = len(stldata) - 1
            else:
                val_random = self.sel_random
            self.point_data = np.random.choice(stldata, val_random)
            self.point_data = self.point_data.view(np.recarray)
            self.point_data = self.point_data[np.argsort(self.point_data['particleid'])] # do not work for pathlines, bug sometimes
        else:
            self.point_data = stldata
        
        # Slicing
        if self.sel_slice != None:
            self.point_data = stldata[::self.sel_slice]
        
        #%% Finalize settings
        
        stl.data = self.point_data
        
        self.poro_modpath = self.model_modflow.sy
        self.ss_modpath = self.model_modflow.ss
        
        # ---- flflopy.modpath.Modpath6Basopy.modpath.mp6sim.StartingLocationsFile
        flopy.modpath.Modpath6Bas(self.mp,
                                  hnoflo=-9999,
                                  hdry=-100,
                                  # def_iface=[6, 6],
                                  def_face_ct=0,    # ifaces = [6]  # top face:6 ; bottom face:5 ; row face:3-4 ; column face:1-2
                                  laytyp=laytype,
                                  ibound=iboundData,
                                  prsity=self.poro_modpath,
                                  prsityCB=self.ss_modpath,
                                  extension='mpbas',
                                  unitnumber=86)
        
        # 1	gauche	face Ouest (x– direction)
        # 2	droite	face Est (x+ direction)
        # 3	avant	face Sud (y– direction)
        # 4	arrière	face Nord (y+ direction)
        # 5	bas   	face inférieure (z– direction)
        # 6	haut	face supérieure (z+ direction)
                        
    #%% PROCESSING
    
    def processing(self,
                   write_model:bool=True,
                   run_model:bool=False):
        """
        Run the partickle tracking.

        Parameters
        ----------
        write_model : bool, optional
            Flag to write input files or not. The default is True.
        run_model : bool, optional
            Flag to run model or not. The default is False.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation finished correctly.

        """
        # Create modflow files
        if write_model == True:
            self.mp.write_input()
       
        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mp.run_model(silent=not verbose) # True without msg
        
        return success_model

    #%% POST-PROCESSING
    
    def post_processing(self, 
                        model_modpath:object,
                        starting_point:bool = True,
                        ending_point:bool = True,
                        pathlines_shp:bool = True,
                        particles_shp:bool = True,
                        random_id = None):
        """
        Create outputs files.

        Parameters
        ----------
        model_modpath : object
            MODPATH python object.
        ending_point : bool, optional
            Write ending point files. The default is True.
        starting_point : bool, optional
            Write starting point files. The default is True.
        pathlines_shp : bool, optional
            Write pathlines shapefiles. The default is True.
        particles_shp : bool, optional
            Write particles shapefiles. The default is True.
        random_id : int, optional
            Export random pathlines. The default is None.
        """
        
        # The outputs to create
        self.starting_point = starting_point
        self.ending_point = ending_point
        self.pathlines_shp = pathlines_shp
        self.particles_shp = particles_shp
        
        # Path and load
        self.full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)
        
        self.particles_file = os.path.join(self.full_path, '_postprocess', '_particles')
        toolbox.create_folder(self.particles_file)
                
        grid_model = model_modpath.mf.modelgrid
        
        crs = model_modpath.geographic.crs_proj
        if isinstance(crs, (int, float)):
            epsg = crs
        elif isinstance(crs, str) and crs[:4].upper() == 'EPSG':
            epsg = int(crs.split(':')[-1])
        else:
            epsg = None
        crs_for_write = crs if crs is not None else (f"EPSG:{epsg}" if epsg is not None else None)

        def ensure_crs(gdf):
            """Attach CRS when missing to avoid warnings and mismatches."""
            if gdf.crs is None and crs_for_write is not None:
                return gdf.set_crs(crs_for_write, allow_override=True)
            return gdf
            
        # Import mpend file
        path_mpend = os.path.join(model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name)
        # ---- flopy.utils.EndpointFile
        endobj = flopy.utils.EndpointFile(path_mpend+'.mpend')
        e = endobj.get_alldata()
        
        # Create ending point file
        if ending_point == True:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                endobj.write_shapefile(endpoint_data=e,
                                       shpname=os.path.join(self.particles_file, 'ending.shp'),
                                       direction='ending',
                                       mg=grid_model,
                                       crs=crs_for_write)
        
        # Create starting point file
        if starting_point == True:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                endobj.write_shapefile(endpoint_data=e,
                                       shpname=os.path.join(self.particles_file, 'starting.shp'),
                                       direction='starting',
                                       mg=grid_model,
                                       crs=crs_for_write)
        
        # Import mppth file
        if (pathlines_shp == True) or (particles_shp == True):
        
            path_mppth = os.path.join(model_modpath.model_folder, model_modpath.model_name, model_modpath.model_name)
            # ---- flopy.utils.PathlineFile
            pthobj = flopy.utils.PathlineFile(path_mppth+'.mppth')
            pth_data = pthobj.get_alldata()
                
            if random_id != None:
                shp_endpoint = gpd.read_file(os.path.join(self.particles_file, 'ending.shp'))
                keep_id = shp_endpoint.particleid
                keep_id = keep_id.tolist()
     
                # if not os.path.exists(self.particles_file+'/_random_id.data'):
                id_random_particles = random.sample(keep_id[:-1], random_id)
                with open(self.particles_file+'/_random_id.data', 'wb') as f:
                    pickle.dump(id_random_particles, f)
                        
                pth_data_save = []
                for o, i in enumerate(id_random_particles):
                    logger.debug('Processing random particle %d/%d (id: %s)', o, len(id_random_particles), i)
                    for j in pth_data:
                        if i == j.particleid[0]:
                            pth_data_save.append(j)
            else:
                pth_data_save = pth_data
            
            # Create pathlines file
            if pathlines_shp == True:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                    pthobj.write_shapefile(pathline_data=pth_data_save,
                                            shpname=os.path.join(self.particles_file, 'pathlines.shp'),
                                            one_per_particle=True, 
                                            direction='ending',
                                            mg=grid_model,
                                            crs=crs_for_write,
                                            verbose=False)
            
            # Create particles file
            if particles_shp == True:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Truncating shapefile fieldname.*")
                    pthobj.write_shapefile(pathline_data=pth_data_save,
                                            shpname=os.path.join(self.particles_file, 'particles.shp'),
                                            one_per_particle=False, 
                                            direction='ending',
                                            mg=grid_model,
                                            crs=crs_for_write,
                                            verbose=False)
    
    def filt_processing(self,
                        model_modpath:object,
                        norm_flux: bool=False, # weight time by fluxes (recharge)
                        filt_time: bool=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                        filt_seep: bool=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                        filt_inout: bool=True, # delete particles in and out in the same cell (first layer)
                        calc_rtd: bool=True, # compute residence time distribution
                        random_id: int=None # select randomly to keep
                        ):
    
        # Convert days in years
        def update_time(df, filt_time):
            if filt_time == True:
                df['time_y'] = df['time'] / 365 # convert in years
                try:
                    df['time_win_y'] = df['time_win'] / 365 # convert in years
                except:
                    pass
                df = df[df['time']>0]
            return df
        
        # Keep particles ending in seepage and not in/out in the same cell
        def update_locout(df, filt_seep, filt_inout):
            if filt_seep == True:
                if self.track_dir == 'forward':
                    df = df[df['k']<=1] # out in first layer
                    df = df[df['zone']==1] # out in seepage zone
            if filt_inout == True:
                df = df[df.i0.astype(str)+'-'+df.j0.astype(str)!=
                        df.i.astype(str)+'-'+df.j.astype(str)] # NOT IN AND OUT FOR SAME CELL
            keep_particles = df['particleid']
            return df, keep_particles
        
        # Paths
        self.full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)
        self.particles_file = os.path.join(self.full_path, '_postprocess', '_particles')

        crs = model_modpath.geographic.crs_proj
        if isinstance(crs, (int, float)):
            epsg = crs
        elif isinstance(crs, str) and crs[:4].upper() == 'EPSG':
            epsg = int(crs.split(':')[-1])
        else:
            epsg = None
        crs_for_write = crs if crs is not None else (f"EPSG:{epsg}" if epsg is not None else None)

        def ensure_crs(gdf):
            """Attach CRS when missing to avoid warnings and mismatches."""
            if gdf.crs is None and crs_for_write is not None:
                return gdf.set_crs(crs_for_write, allow_override=True)
            return gdf
        
        # Create a new shapefile named '_weighted'
        if norm_flux == True:
            modeldir = self.full_path+'/'
            namepath = model_modpath.model_name
            model_name = model_modpath.model_name
            mymodel       = model_modpath.mf
            aux_rech      = mymodel.get_package('RCH')
            mybas         = mymodel.get_package('BAS6')
            mydis         = mymodel.get_package('DIS')
            ncol          = np.unique(mydis.ncol)[0]
            nrow          = np.unique(mydis.nrow)[0]
            nlay          = np.unique(mydis.nlay)[0]
            dcol          = np.unique(mydis.delc)[0]
            drow          = np.unique(mydis.delr)[0]    
            period        = 0
            step          = 0
            Qx, Qy, Qz_rech  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, 
                                                      kstpkper=(step, period), totim=None,boundary_ifaces={'RECHARGE': 6}, hdsfile=modeldir+namepath+'.hds', 
                                                      model=mymodel)
            Qx_2, Qy_2, Qz_drain  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, 
                                                           kstpkper=(step, period), totim=None,boundary_ifaces={'DRAINS': 6}, hdsfile=modeldir+namepath+'.hds', 
                                                           model=mymodel)
            recharge_raw      = aux_rech.rech.array[0,0]
            recharge_list     = recharge_raw.flatten()
            recharge_matrix   = recharge_raw * dcol * drow
            drain_matrix      = Qz_drain[0,:,:]
            sflux = recharge_matrix - drain_matrix
            sflows = sflux/drow/dcol
            
            toolbox.export_tif(self.geographic.watershed_box_buff_dem,
                               sflows,
                               self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'sflows_weighted.tif',
                               -9999)
            wbt.extract_raster_values_at_points(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'sflows_weighted.tif', 
                                                self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting.shp',
                                                out_text=False)
            wbt.extract_raster_values_at_points(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'sflows_weighted.tif', 
                                                self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending.shp',
                                                out_text=False)
            
            start = gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting.shp')
            start = ensure_crs(start)
            start_weighted = start.copy()
            start_weighted.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting_weighted.shp')
            
            end = gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending.shp')
            end = ensure_crs(end)
            end_weighted = end.copy()
            end_weighted.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending_weighted.shp')
            
            recharge_list = np.ones(len(end))*recharge_raw.mean()
            
            start_process = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting_weighted.shp'))
            end_process = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending_weighted.shp'))

            if self.track_dir == 'forward':
                end_process['VALUE1_in'] = start_weighted['VALUE1']
                end_process['rchPerc'] = end_process['VALUE1_in'] / recharge_list
                end_process.loc[end_process['rchPerc']<0, 'rchPerc'] = 0
                time_win = (end_process['time'])*end_process['rchPerc']
            if self.track_dir == 'backward':
                start_process['VALUE1_in'] = end_weighted['VALUE1']
                start_process['rchPerc'] = start_process['VALUE1_in'] / recharge_list
                start_process.loc[start_process['rchPerc']<0, 'rchPerc'] = 0
                time_win = (start_process['time'])*start_process['rchPerc']     
        
            start_process['time_win'] = time_win
            end_process['time_win'] = time_win
            
            end_up = update_time(end_process, filt_time)
            end_up, keep_particles = update_locout(end_up, filt_seep, filt_inout)
            end_up = ensure_crs(end_up)
            end_up.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending_weighted.shp')

            start_up = update_time(start_process, filt_time)
            start_up, keep_particles = update_locout(start_up, filt_seep, filt_inout)
            start_up = ensure_crs(start_up)
            start_up.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting_weighted.shp')
            
            if self.pathlines_shp == True:
                pathlines_process = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'pathlines.shp'))
                if self.track_dir == 'forward':
                    pathlines_process['time_win'] = (end_process['time'])*end_process['rchPerc']
                if self.track_dir == 'backward':
                    pathlines_process['time_win'] = (start_process['time'])*start_process['rchPerc']
                pathlines_up = update_time(pathlines_process, filt_time)
                pathlines_up = pathlines_up[pathlines_up['particleid'].isin(keep_particles)]
                if random_id != None:
                    if not os.path.exists(self.model_folder+'/'+'_id_particles_random.data'):
                        id_particles_random = random.sample(pathlines_up[:-1], random_id)
                        with open(self.model_folder+'/'+'_id_particles_random.data', 'wb') as f:
                            pickle.dump(id_particles_random, f)
                    else:
                        with open(self.model_folder+'/'+'_id_particles_random.data', 'rb') as f:
                            id_particles_random = pickle.load(f)
                    pathlines_up = pathlines_up[pathlines_up['particleid'].isin(id_particles_random)]                    
                pathlines_up = ensure_crs(pathlines_up)
                pathlines_up.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'pathlines_weighted.shp')
            
            if self.particles_shp == True:
                particles_process = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'particles.shp'))
                particles_up = update_time(particles_process, filt_time)
                if random_id != None:
                    if not os.path.exists(self.model_folder+'/'+'_id_particles_random.data'):
                        id_particles_random = random.sample(particles_up[:-1], random_id)
                        with open(self.model_folder+'/'+'_id_particles_random.data', 'wb') as f:
                            pickle.dump(id_particles_random, f)
                    else:
                        with open(self.model_folder+'/'+'_id_particles_random.data', 'rb') as f:
                            id_particles_random = pickle.load(f)
                    particles_up = particles_up[particles_up['particleid'].isin(id_particles_random)]                    
                particles_up = ensure_crs(particles_up)
                particles_up.to_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'particles_weighted.shp')
        
        #%% PLOT
        
        if calc_rtd == True:
            if self.track_dir == 'forward': 
                end = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'ending_weighted.shp'))
            if self.track_dir == 'backward': 
                end = ensure_crs(gpd.read_file(self.model_folder+'/'+model_name+'/'+'_postprocess/_particles/'+'starting_weighted.shp'))
            try:
                shp = gpd.read_file(self.geographic.watershed_shp)
                end = end.clip(shp)
            except:
                pass
            end.loc[end['time_win']==0, :] = np.nan
            end = end.dropna()
            try:
                tau = np.average(end['time_win'], weights=end['rchPerc'])
                def pdf_function(M, nbin, Weight):    
                    bin_min = np.quantile(M, 0.01)
                    bin_max = np.quantile(M, 0.99)
                    bins = np.logspace(np.log10(bin_min),np.log10(bin_max), nbin)
                    pdf, binEdges = np.histogram(M, bins=bins,density=True, weights=Weight)
                    dx = np.diff(binEdges)  
                    xh =  (binEdges[1:] + binEdges[:-1])/2
                    xh = np.array(xh)
                    return (xh, pdf)
                nbin = int(2*len(end['time_win'])**(2/5))          #Scott's Rules
                [xh, yh] = pdf_function(end['time_win']/tau, nbin, end.rchPerc)
                idzeros = np.where(yh != 0)
                xfil = xh[idzeros]
                yfil = yh[idzeros]
                x_log = np.log10(xfil)
                y_log = np.log10(yfil)
                # x_log = (xfil)
                # y_log = (yfil)
            except:
                pass
            def func(x, a, b, c, d, e):
                return a * x**4 + b * x**3 + c * x**2 + d * x + e
            try:
                params, covariance = curve_fit(func, x_log, y_log)
                a, b, c, d, e = params
                x_fit = np.linspace(min(x_log), max(x_log), 100)
                y_fit = func(x_fit, a, b, c, d, e)
                
                fig = plt.figure(figsize=(6,4))
                ax = fig.add_subplot(111)
                ax.plot(xfil, yfil, '-', lw=2, c='red', label='Binning on particles')
                ax.plot(xh, yh, marker='o', markeredgecolor='none', lw=0, c='red')
                ax.plot(10**x_fit, 10**y_fit, '-', lw=2, c='k', label='Fitting curve')
                ax.set_ylabel("PDF")
                ax.set_xlabel("t / "+r'$\tau$')
                ax.set_xscale('log')
                ax.set_title('Residence times distribution')
                ax.legend(loc='upper right')
                # ax.set_xlim(tmin, tmax)
                # ax.set_ylim(-0.1, 13)
            except:
                pass

#%% NOTES

# logger.debug('Point data: %s', self.point_data)

# if sorted(self.point_data['particleid']) == list(self.point_data['particleid']):
#     logger.debug("list1 is sorted")
# else:
#     logger.debug("list is not sorted")
