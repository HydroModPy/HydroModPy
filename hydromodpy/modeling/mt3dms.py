# -*- coding: utf-8 -*-
"""
Created on Thu Apr  3 13:06:53 2025

@author: rabherve
"""

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
import numpy as np
from os.path import dirname, abspath
import rasterio
import flopy.utils.binaryfile as bf
import whitebox
import shutil

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
from hydromodpy.modeling import masstransfer
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Mt3dms:
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
                 suffix_name: str='_mt',
                 bin_path: str=os.path.join(os.getcwd(),'bin'),
                 # Specific settings
                 spc_name: str='NO3',
                 sconc_init: float=0,
                 sconc_input = 0,
                 disp_long: float=0,
                 disp_transh: float=0,
                 disp_transv: float=0,
                 diffu_coeff: float=0,
                 react_order: int=None, # for MT3DM: 0, 1, 100
                 rate_decay: float=0,
                 plot_conc: bool=True,
                 ):
        """
        Initialize method.

        Parameters
        ----------
        geographic : object
            Geographic object build by HydroModPy.
        """

        #%% Initialisation

        self.geographic = geographic

        self.model_folder = model_folder
        self.model_name = model_name
        self.full_path = os.path.join(model_folder, model_name)
        self.model_modflow = model_modflow
        self.suffix_name = suffix_name
        self.model_name_mt = model_name + self.suffix_name

        if not os.path.isdir(self.full_path):
            raise FileNotFoundError('Directory not found: {}'.format(self.full_path))
        if (sys.platform == 'win32') or (sys.platform == 'win64'):
            self.exe = os.path.join(bin_path, 'win' ,'mt3d-usgs_1.1.0_64.exe')
        if (sys.platform == 'linux'):
            self.exe = os.path.join(bin_path, 'linux' ,'mt3dusgs')
        if (sys.platform == 'darwin'):
            self.exe = os.path.join(bin_path, 'mac' ,'mt3dusgs')

        self.spc_name = spc_name
        self.sconc_init = sconc_init
        self.sconc_input = sconc_input

        self.disp_long = disp_long
        self.disp_transh = disp_transh
        self.disp_transv = disp_transv
        self.diffu_coeff = diffu_coeff

        self.react_order = react_order
        self.rate_decay = rate_decay

        self.plot_conc = plot_conc

        self.mf = model_modflow.mf

        self.new_stepsize = 1

    #%% PRE-PROCESSING

    def pre_processing(self):
        """
        Pre-processing to build the trasnport model.

        Returns
        -------
        None.

        """

        self.mt = flopy.mt3d.Mt3dms(modflowmodel=self.mf, modelname=self.model_name_mt, version='mt3d-usgs',
                                   model_ws=self.full_path,
                                   exe_name=self.exe,
                                   ftlfilename='mt3d_link.ftl',
                                   namefile_ext='mtnam', verbose=False, ftlfree=False)

        gcg = flopy.mt3d.Mt3dGcg(self.mt, mxiter=10,
                                 # cclose=1e-7,
                                 # iter1=1000
                                 )

        #%% Specific parametrization

        self.ssflag = ['True'] # This one is for the transport simulation (STEADY FOR THE FIRST PERIOD)
        for i in range((self.mf.nper-1)*self.new_stepsize):
            self.ssflag.append(' ')

        self.btn = flopy.mt3d.Mt3dBtn(self.mt,
                                      nlay=self.mf.nlay,
                                      nrow=self.mf.nrow,
                                      ncol=self.mf.ncol,
                                      delr=self.model_modflow.resolution,
                                      delc=self.model_modflow.resolution,
                                      nper=self.mf.nper,                        # mf.nper*new_stepsize+1
                                      nprs=self.mf.nper,                        # mf.nper*new_stepsize+1
                                      nstp=self.model_modflow.nstp,
                                      perlen=self.model_modflow.perlen,
                                      prsity=self.model_modflow.sy,
                                      sconc=self.sconc_init,
                                      laycon=1,
                                      ncomp=1,
                                      mcomp=1,
                                      tsmult=1,
                                      nprmas=0,
                                      thkmin=0.01,                              # 0.0001/(delv/nlay))
                                      icbund=1,
                                      timprs=[self.mf.nper],
                                      ssflag=self.ssflag,
                                      species_names=self.spc_name,
                                      cinact=1e30,
                                      Legacy99Stor=True,
                                      NoWetDryPrint=True,
                                      MFStyleArr=True,
                                      obs=None,
                                      savucn=True,
                                      DRYCell=True,
                                      chkmas=True,
                                      unitnumber=None,
                                      tunit='D', lunit='M', munit='KG',
                                      )

        #%% Advection package

        adv = flopy.mt3d.Mt3dAdv(self.mt,
                                 mixelm=-1,
                                 # percel=0.75
                                 )
        # Solution method (mixelm)
        # • Finite Difference Method (FDM)
        # • MOC : Method of Characteristics (MOC)
        # • MMOC : Modified Method of Characteristics (MMOC)
        # • HMOC : Hybrid Method of Characteristics (HMOC)
        # • TVD (MIXELM = -1 - try to use this one)

        #%% Dispersion package

        self.disp = flopy.mt3d.mtdsp.Mt3dDsp(self.mt,
                           al=self.disp_long, # unit L
                           trpt=self.disp_transh, # ratio of the horizontal transverse dispersivity to the longitudinal dispersivity, 10x moins
                           trpv=self.disp_transv, # ratio of the vertical transverse dispersivity to the longitudinal dispersivity, 100x moins
                           dmcoef=self.diffu_coeff, #L2T-1
                           extension='dsp') # Not used for the moment

        #%% Reactivity package

        if self.react_order == None:
            ireact = 0
        if self.react_order == 1:
            ireact = 1
        if self.react_order == 0:
            ireact = 100
        self.rct = flopy.mt3d.mtrct.Mt3dRct(self.mt,
                                            isothm=0, # no sorption is simulated
                                            ireact=ireact, # 0: no-reaction, 1: first-order, 100: zero-order
                                            igetsc=0, # 0 : the initial concentration for the sorbed or immobile phase is not read
                                            rhob=None,
                                            rc1=self.rate_decay, # (unit, T-1)
                                            )

        #%% Concentration package

        self.ssm = flopy.mt3d.Mt3dSsm(self.mt,
                                 crch=self.sconc_input,
                                 mxss=None,                                     # mxss=mf.nrow*mf.ncol*(nper*new_stepsize+1)+10,
                                 stress_period_data=None)

    #%% PROCESSING

    def processing(self,
                   write_model:bool=True,
                   run_model:bool=False,
                   verbose: bool=True):
        """
        Run the trasnport model.

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
            self.mt.write_input()

        # Run modflow files
        success_model = True

        if run_model == True:
            if verbose is False:
                logger.info("Running MT3DMS transport simulation")
            success_model, tempo = self.mt.run_model(silent=not verbose, pause=False,
                                                     # report=True,
                                                     normal_msg='normal termination') # True without msg

        shutil.copy(self.full_path+'/'+'MT3D001.UCN', self.full_path+'/'+self.model_name_mt+'.UCN')

        return success_model

    #%% POST-PROCESSING

    def post_processing(self,
                        model_mt3dms:object,
                        concentration_seepage:bool=True,
                        mass_seepage:bool=True,
                        mass_accumulated:bool=False,
                        export_all_tif:bool=False):
        """
        Create outputs files.

        Parameters
        ----------
        model_mt3dms : object
            MT3DMS python object.
        """

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

        #%% Load essential data

        # Modflow specific files (written in the processing phase)
        self.path_file = os.path.join(self.full_path, self.model_name_mt+'.UCN')

        # Files have been output in the processing phase and are re-read here
        self.dem_mask = (self.model_modflow.dem<-9999)

        # Fluxes
        self.outflow_drain = np.load(os.path.join(self.save_file, 'outflow_drain'+'.npy'), allow_pickle=True).item()

        self.ucnobj  = bf.UcnFile(self.path_file)
        self.concobj_1c = self.ucnobj.get_alldata(mflay=None) # 4D:[time, lay, row, col]

        concobj_1c_fil = self.concobj_1c.copy()
        concobj_1c_fil[concobj_1c_fil>=1e30] = np.nan
        concobj_1c_fil = concobj_1c_fil[:]

        the_mins = []
        the_maxs = []

        self.dict_concentration_seepage = {}
        self.dict_mass_seepage = {}
        self.dict_mass_accumulated = {}

        # Boucle sur chaque pas de temps
        # for i in range(len(concobj_1c_fil)):
        for i in range(model_mt3dms.model_modflow.nper):
            the_time = str(i+1)
            logger.info("Processing MT3DMS timestep %d/%d", i+1, model_mt3dms.model_modflow.nper)

            export_tif = True
            if export_all_tif == False:
                if i > 0:
                    export_tif = False

            seep = self.outflow_drain[i]

            if concentration_seepage==True:

                concobj_1c_fil_surf = concobj_1c_fil[i+1][0]
                # concobj_1c_fil_surf = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf)
                concobj_1c_fil_surf[seep <= 0] = -9999
                concobj_1c_fil_surf[self.dem_mask] = -9999

                output_path = self.tifs_file+'/concentration_seepage_t('+the_time+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.model_modflow.dem_watershed_path, concobj_1c_fil_surf, output_path, -9999)
                self.dict_concentration_seepage[i] = concobj_1c_fil_surf

                the_mins.append(np.nanmin(concobj_1c_fil_surf))
                the_maxs.append(np.nanmax(concobj_1c_fil_surf))

            if mass_seepage==True:

                massobj_1c_fil_surf = concobj_1c_fil[i+1][0]
                # massobj_1c_fil_surf = np.ma.masked_where(seep <= 0, massobj_1c_fil_surf)
                massobj_1c_fil_surf[seep <= 0] = np.nan
                massobj_1c_fil_surf = massobj_1c_fil_surf * seep # mg/l to kg/m3 ==> kg/m3 * m3/d ==> kg/d
                massobj_1c_fil_surf[self.dem_mask] = -9999
                massobj_1c_fil_surf = np.where(np.isnan(massobj_1c_fil_surf), -9999, massobj_1c_fil_surf)

                output_path = self.tifs_file+'/mass_seepage_t('+the_time+').tif'
                if export_tif==True:
                    toolbox.export_tif(self.model_modflow.dem_watershed_path, massobj_1c_fil_surf, output_path, -9999)
                self.dict_mass_seepage[i] = massobj_1c_fil_surf

            if mass_accumulated==True:

                accumulated_mass = masstransfer.Masstransfer(self.geographic,
                                                              'mass_seepage_t('+the_time+').tif',
                                                              'tracept_conc_t('+the_time+').shp',
                                                              'mass_accumulated_t('+the_time+').tif',
                                                              extraction_folder=self.save_file)
                accumulated_mass.trace_cumulated()
                output_path = self.tifs_file+'/mass_accumulated_t('+the_time+').tif'
                with rasterio.open(output_path) as src:
                    self.dict_mass_accumulated[i] = src.read(1)

        the_min = np.nanmin(the_mins)
        the_max = np.nanmax(the_maxs)

        # concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        if concentration_seepage == True:
            logger.info("Exporting concentration seepage timeseries")
            np.save(self.save_file+'/concentration_seepage', self.dict_concentration_seepage)

        if mass_seepage == True:
            logger.info("Exporting mass seepage timeseries")
            np.save(self.save_file+'/mass_seepage', self.dict_mass_seepage)

        if mass_accumulated == True:
            logger.info("Exporting accumulated mass timeseries")
            np.save(self.save_file+'/mass_accumulated', self.dict_mass_accumulated)


#%% ---- NOTES
logger = get_logger(__name__)
