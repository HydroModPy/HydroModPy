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

# %% LIBRAIRIES

import os
import pandas as pd
import numpy as np
import flopy
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
from shapely.geometry import Polygon, Point, LineString


# import requests
# from tools import toolbox

# import urllib
# import zipfile
# import geopandas as gpd
# from selenium import webdriver

# from flopy.utils.particletrackfile import ParticleTrackFile
# import time
# import glob
# import ssl
# import matplotlib.pyplot as plt

# from pyproj import Transformer


# %% CLASS


class Residencetimes:

    """ 
    WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers
    y_coord: list of float
        Lambert 93 Y coordinates of piezometers
    x_iloc: list of int
        list of x-index of model cells corresponding to piezometers
    y_iloc: list of int
        list of y-index of model cells corresponding to piezometers

    Methods
    -------

    """

    # %% INITIALIZATION
    # TB: not really a RTD class, more of a Particle Tracking class
    def __init__(self):
        """
        Initialize method. 

        Parameters
        ----------
        """

    # %% LOAD PARTICLE TRACKING DATA  
    # TB: should add an option to use simulation results directly from MP class,
    # without having to load saved files (for better performances)
    def load_modpath_results(self,
                             geographic: object, #used?
                             model_modflow: object, #necessary?
                             model_modpath: object,
                             filt_inout: bool=True
                             ):
        
        # path
        self.full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)     
        self.mp_res_path = os.path.join(self.full_path ,'_postprocess', '_particles')
        
        # model dimensions
        self.nrow=model_modflow.nrow
        self.ncol=model_modflow.ncol
        self.nlay=model_modflow.nlay
        
        # particle tracking direction: forward or backward
        self.track_dir = model_modpath.track_dir
        
        # model name
        self.model_name=model_modpath.model_name
        
        # models
        self.model_modpath = model_modpath
        
        # load and store particles position from .mppth file
        self.particles=self._load_mppth_file(filt_inout)
            
        # number of particles
        self.npart=self.particles['particleid'].max()
        

   
    # %% EXTRACT PARTICLES FOR ALL MODEL CELLS (WHERE PARTICLES ARE PRESENT)

    def get_particles_all_cells(self,
                                particle_pos: str='center',
                                zero_based: bool=False
                                ):
        """
        WIP       
        """
        
        # get particles data
        prt = self.get_particles(particle_pos=particle_pos,zero_based=zero_based)
        
        # get transit times distributions for each cell
        prt = prt.groupby(['k','i','j'])['time'].apply(list)
        prt = pd.DataFrame(prt).reset_index()
        prt = prt.rename(columns={'time' : 'all_times'})
        
        # get mean transit time and particle count for each cell
        prt['mean'] = list(map(np.mean, prt['all_times']))
        prt['std'] = list(map(np.std, prt['all_times']))
        prt['npart'] = list(map(len, prt['all_times']))
        
        # formate outputs
        prt = prt.iloc[:,[0,1,3,4,5,2]]

        return prt
    
    
    # %% EXTRACT 2D MAP OF MEAN RESIDENCE TIMES BETWEEN Z LAYERS

    def get_particles_from_zlayers(self,
                                   particle_pos: str='center',
                                   zmap_min: float=None,
                                   zmap_max: float=None
                                   ):
        """
        WIP 
        comprised between
        default : mean residence times over the full thickness of the model domain
        """
        
        # initialization
        prt_df = self.get_particles(particle_pos=particle_pos,zero_based=True)
        
        # remove particles with z <= zmin_map and z >= zmax_map   
        prt_df = prt_df[(prt_df['z']>=zmap_min[prt_df['i'],prt_df['j']])]
        prt_df = prt_df[(prt_df['z']<=zmap_max[prt_df['i'],prt_df['j']])]
        
        # get mean time for particle changing layer at the same ij pos
        prt_df = prt_df.groupby(['particleid','i','j'])['time'].mean()
        prt_df = pd.DataFrame(prt_df).reset_index()
        
        # get residence times distribution for each cell
        # prt_df = prt_df.groupby(['i','j'])['time'].apply(list)
        prt_df = prt_df.groupby(['i','j'])['time'].agg(list)
        prt_df = pd.DataFrame(prt_df).reset_index()
        prt_df = prt_df.rename(columns={'time' : 'all_times'})
        
        # get mean residence time and particle count for each cell
        prt_df['mean'] = list(map(np.mean, prt_df['all_times']))
        prt_df['std'] = list(map(np.std, prt_df['all_times']))
        prt_df['npart'] = list(map(len, prt_df['all_times']))
        
        # formate outputs
        prt_df = prt_df.iloc[:,[0,1,3,4,5,2]]       
        
        return prt_df
    
    # %% EXTRACT RESIDENCE TIMES FOR INTERCEPTION ZONE

    def get_rtd_from_cuboid(self,
                            particle_pos: str='center',
                            xmin: float=None,
                            xmax: float=None,
                            ymin: float=None,
                            ymax: float=None,
                            zmin: float=None,
                            zmax: float=None,
                            zero_based: bool=False):
                
        """
        WIP - not tested yet
        """
        
        # get particles data & initialization
        particles = self.get_particles(particle_pos=particle_pos,zero_based=zero_based)
        if xmin == None: xmin = np.min(particles['x'])
        if xmax == None: xmax = np.max(particles['x'])
        if ymin == None: ymin = np.min(particles['y'])
        if ymax == None: ymax = np.max(particles['y'])
        if zmin == None: zmin = np.min(particles['z'])
        if zmax == None: zmax = np.max(particles['z'])
        
        # select particles crossing the capture zone
        particles = particles(particles['x'] >= xmin)
        particles = particles(particles['x'] <= xmax)
        particles = particles(particles['y'] >= ymin)
        particles = particles(particles['y'] <= ymax)
        particles = particles(particles['z'] >= zmin)
        particles = particles(particles['z'] <= zmax)
        
        # removes duplicate particles (case of particles crossing cell 
        # boundaries inside the capture zone)
        particles = particles.groupby(['particleid'])['time'].mean()
        particles = pd.DataFrame(particles).reset_index()

        return particles
    
    # %% PARTICLE POSITIONS

    def get_particles(self,
                      particle_pos: str='center',
                      zero_based: bool=False
                      ):
        """
        Returns particle positions in space and time.
        # TB: should be moved to MP class or a new particle tracking class
        
        Parameters
        ----------
        particle_pos : str, default= 'center'
            types of particle positions:
                'in'      : particle positions when entering each cell
                'out'     : particle positions when exiting each cell
                'center'  : particle positions halfway between entry and exit points for each cell
                'starting': only initial particle positions (= injection positions)
                'ending'  : only final particle positions (= last registered positions)      
        zero_based: bool, default = False
            choose between zero-based (True) and one-based (False) particle indexing
        
        Returns
        -------
        particles : object of pandas.DataFrame class
            positions of particles in space and time
        """
        
        # get particles & initialization
        particles_in=self.particles.copy()
        if zero_based:
            particles_in = self._change_base(particles=particles_in,direction='one_to_zero')
        
        # add unique cell identifier
        cellid = [list(map(str,particles_in['k'])),list(map(str,particles_in['i'])),list(map(str,particles_in['j']))]
        cellid = list(map("-".join, zip(*cellid)))
        particles_in['cellid']=cellid
        
        # particle positions when entering each cell (default pmpath6 result)                  
        if particle_pos == 'in':
            return particles_in.reset_index(drop=True)
        
        # only initial particle positions (= injection positions)
        pid_in = particles_in.particleid[:-1]
        pid_in = pd.concat([pd.Series([0]),pid_in],ignore_index=True)
        pid_in = particles_in.particleid-pid_in
        if particle_pos == 'starting':
            particles_starting = particles_in[(pid_in != 0)]
            return particles_starting.reset_index(drop=True)
        
        # only final particle positions (= last registered positions)
        pid_out = particles_in.particleid[1:]
        pid_out = pd.concat([pid_out,pd.Series([0])],ignore_index=True)
        pid_out = particles_in.particleid-pid_out 
        if particle_pos == 'ending':
            particles_ending = particles_in[(pid_out != 0)]
            return particles_ending.reset_index(drop=True)

        # particle positions when exiting each cell
        colnames = ['time','x','y','z','xloc','yloc','zloc']
        particles_out = particles_in.copy()
        
        dftemp = particles_out[colnames][1:]
        dftemp=dftemp.reset_index(drop=True)
        particles_out.update(dftemp) 
        
        particles_out.xloc[(particles_out.xloc == 1)]=-1
        particles_out.xloc[(particles_out.xloc == 0)]=1
        particles_out.xloc[(particles_out.xloc == -1)]=0
        
        particles_out.yloc[(particles_out.yloc == 1)]=-1
        particles_out.yloc[(particles_out.yloc == 0)]=1
        particles_out.yloc[(particles_out.yloc == -1)]=0
        
        particles_out.zloc[(particles_out.zloc == 1)]=-1
        particles_out.zloc[(particles_out.zloc == 0)]=1
        particles_out.zloc[(particles_out.zloc == -1)]=0
        
        particles_out.update(particles_in[(pid_out != 0)])
        
        if particle_pos == 'out':
            return particles_out.reset_index(drop=True)
        
        # particle positions halfway between entry and exit points for each cell
        particles_center = particles_in.copy()
        particles_center[colnames] = (particles_in[colnames]+particles_out[colnames])/2
        if particle_pos == 'center':
            return particles_center.reset_index(drop=True)
        
    # %% EXPORT FILES
    
    def particles_to_csv(self,
                         folder_path: str='default',
                         particle_pos: str='all',
                         zero_based: bool=False,
                         ):
        """
        Save particle positions as .csv file(s).
        See  residencetimes.get_particles for details about the available types of particle positions
        [TB: Should be moved into Modpath class or to a new particle tracking class]

        Parameters
        ----------
        folder_path : str, default = 'default'
            path of the folder where results files will be saved.
            default is result folder for Modpath simulations
        particle_pos : str, default= 'all'
            types of particle positions to save: 'in','out','starting','ending','center'
            default is 'all', for which a file will be created for each possible type of position
        zero_based: bool, default = False
            choose between zero-based (True) and one-based (False) particle indexing
        
        Returns
        -------
        """
        
        if particle_pos == 'all': 
            particle_pos = ['in','out','starting','ending','center']
        else: 
            particle_pos = [particle_pos]   
        
        if folder_path == 'default':
            folder_path = self.mp_res_path
            
        for pos in particle_pos:
            df = self.get_particles(particle_pos=pos,zero_based=zero_based)
            file_path = os.path.join(folder_path, ''.join(['particles_', pos, '.csv']))
            df.to_csv(path_or_buf=file_path, index=False)
            
            
    def get_pathlines(self,
                      folder_path: str='default',
                      ):
        """
        Save particle positions as .shp file.
        [TB: Should be moved into Modpath class or to a new particle tracking class]

        Parameters
        ----------
            folder_path : str, default = 'default'
                path of the folder where results files will be saved.
                default is result folder for Modpath simulations
    
        Returns
        -------
        """
    
        if folder_path == 'default':
            folder_path = self.mp_res_path
        
        mg=self.model_modpath.mf.modelgrid
        
        # load and formate particle data
        prt_df = self.get_particles(particle_pos= 'in',zero_based= True)
            
        prt_df.x, prt_df.y = flopy.utils.geometry.transform(
            prt_df.x, prt_df.y, mg.xoffset, mg.yoffset, mg.angrot_radians)
        
        prt_df['xyz']=prt_df[['x','y','z']].values.tolist()        
        
        prt_df = prt_df.groupby(['particleid']).agg(
            timemax = pd.NamedAgg(column="time", aggfunc="max"),
            coordinates = pd.NamedAgg(column="xyz", aggfunc=LineString))
        
        return prt_df
    
    # particles = self.get_particles(particle_pos= 'in',zero_based= True)
    # particles =particles.to_records()
    
    # crs = self.model_modpath.geographic.crs_proj
    # if isinstance(crs, (int,float)) == True:
    #     epsg = crs
    # elif crs[:4].upper() == 'EPSG':
    #     epsg = int(crs.split(':')[-1])
    # else:
    #     epsg = None
    
    # ParticleTrackFile.write_shapefile(
    #     self,
    #     data=particles,
    #     one_per_particle=True,
    #     direction='ending',
    #     shpname=os.path.join(folder_path, 'pathlines.shp'),
    #     mg=self.model_modpath.mf.modelgrid,
    #     epsg=epsg,
    #     verbose=False,
    # )
            
        

    # %% PRIVATE METHODS
    
    def _load_mppth_file(self,
                         filt_inout: bool=True
                         ):
        """
        Load and formates particles positions from .mppth file.

        Parameters
        ----------
        filt_inout : bool, default = True
            option to filter particles that are injected into and removed from 
            the model in the same cell (= no infiltration)
        
        Returns
        -------
        particles : object of pandas.DataFrame class
            positions of particles in space and time
        """
        
        # load .mmpth particle file       
        path_mppth = os.path.join(self.full_path, self.model_name)
        pthobj = flopy.utils.PathlineFile(path_mppth+'.mppth')
        particles = pthobj.get_alldata()
        particles = pd.DataFrame(np.concatenate(particles))
        particles = particles.sort_values(by=["particleid","time"])
        
        # convert back to one-based (default Modflow base)
        particles = self._change_base(particles=particles,direction='zero_to_one')
        
        # filter duplicate values
        pid = particles.particleid[:-1]
        pid = pd.concat([pd.Series([1]),pid],ignore_index=True)
        pid = particles.particleid-pid
        
        ptime = particles.time[:-1]
        ptime = pd.concat([pd.Series([-1]),ptime],ignore_index=True)
        ptime = particles.time-ptime
        
        toremove = (pid == 0) & (ptime == 0)
        particles = particles[~toremove]
        
        # filter particles that are injected into and removed from the model
        # in the same cell (= no infiltration)
        if filt_inout:
            particles = particles[particles.duplicated(subset=['particleid'],keep=False)]
        
        return particles.reset_index(drop=True)
    
    def _change_base(self,
                     particles: object,
                     direction: str='one_to_zero'
                     ):
        """
        Change particle indexing from one-based to zero-based, or conversely.

        Parameters
        ----------
        particles : object of pandas.DataFrame class
            positions of particles in space and time in initial base
        direction : str, default = 'one_to_zero'
            direction of base conversion: 'one_to_zero' or 'zero_to_one'
        
        Returns
        -------
        particles : object of pandas.DataFrame class
            positions of particles in space and time in final base
        """
        
        if   direction == 'one_to_zero': a=-1
        elif direction == 'zero_to_one': a=1
        
        particles['particleid']       = particles['particleid']+a
        particles['particlegroup']    = particles['particlegroup']+a
        particles['k']                = particles['k']+a
        particles['i']                = particles['i']+a
        particles['j']                = particles['j']+a
        particles['linesegmentindex'] = particles['linesegmentindex']+a
        
        return particles
        

# %% NOTES
