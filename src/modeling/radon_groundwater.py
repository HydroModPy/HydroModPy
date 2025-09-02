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
import time
import flopy
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
# from shapely.geometry import Polygon, Point, LineString
# from collections import Counter


# %% CLASS


class Radon_groundwater:

    """ 
    WIP
    Attributes
    ----------

    Methods
    -------

    """

    # %% INITIALIZATION
    def __init__(self):
        """
        Initialize method. 

        Parameters
        ----------
        """
        # Degradation constant
        # @TB Degradation constant in days; should be checked for homogeneity
        # with ModPath results
        self.half_life = 3.82

    # %% PREPROCESSING GROUNDWATER REACTIVE TRANSPORT MODULE 
   
    def preprocessing(self,
                      rtd: object,
                      ceq: float=57000,
                      c0:  float=0
                      ):
        
        self.nrow = rtd.nrow
        self.ncol = rtd.ncol
        self.nlay = rtd.nlay
        
        # Parameter spatialization
        ##### @TB: placeholder while waiting for general spatialization of 
        ##### of parameters in HMP
        base_dict = self.create_base_spatialization(rtd.nrow,rtd.ncol,rtd.nlay,zero_based=False)       
        base_df = pd.DataFrame(base_dict)
        
        ceq_df = base_df.copy()
        ceq_df['ceq']=base_df['j']*0+ceq
        # ceq_df.loc[ceq_df['j'] <= 36, 'ceq'] = 108000
        
        c0_df = base_df.copy()
        c0_df['c0']=base_df['j']*0+c0
        
        rate = np.log(2) / self.half_life
        rate_df = base_df.copy()
        rate_df['rate']=base_df['j']*0+rate
        #####
        
        # Particles positions in and out of cells
        prt_in  = rtd.get_particles(particle_pos='in',zero_based=False)
        prt_out = rtd.get_particles(particle_pos='out',zero_based=False)
        
        # Initialization of main data storage dataframe
        prt = prt_in.copy()
        prt = prt.rename(columns={'time':'time_in'})
        prt['time_out'] = prt_out['time']
        
        prt = pd.merge(prt,c0_df[['cellid','c0']],on='cellid',how='left')
        prt = pd.merge(prt,ceq_df[['cellid','ceq']],on='cellid',how='left')
        prt = pd.merge(prt,rate_df[['cellid','rate']],on='cellid',how='left')
        
        prt['cin']  = prt['c0']*0 - 1
        prt['cout'] = prt['c0']*0 - 1
        
        self.conc = prt
    
    # %% PROCESSING GROUNDWATER REACTIVE TRANSPORT MODULE  
    def processing(self):
        
        print('Starting Radon Reactive Transport Simulation for Groundwater... ')
        start_time = time.time()
        
        # Particle data
        prt = self.conc.copy()
        
        # Starting position of all particles
        pid_in = prt.particleid[:-1]
        pid_in = pd.concat([pd.Series(np.zeros(1)),pid_in],ignore_index=True)
        pid_in = prt.particleid-pid_in
        partic_in = prt.particleid[pid_in==1].to_numpy()
        
        # Initialization: at t=0, concentration entering injection cells cin is 
        # equal to injection concentration c0 at this cell
        prt.cin[pid_in==1] = prt.c0[pid_in==1]
        
        # Loop on time steps
        pid_c = pid_in
        for ntstep in range(1,len(prt.particleid)+1): 
        
            # c_out = c_in + (c_eq-c_in) * (1-exp(-rate*(t_out-t_in)))            
            conc = prt.time_out[pid_c==1] - prt.time_in[pid_c==1]
            conc = np.multiply(prt.rate[pid_c==1],conc)
            conc = 1 - np.exp(-conc)
            conc = np.multiply(prt.ceq[pid_c==1] - prt.cin[pid_c==1],conc)
            conc = prt.cin[pid_c==1] + conc
            prt.cout[pid_c==1] = conc
            
            # Index of cells for next time step
            pid_c = pid_in[:-ntstep]
            pid_c = pd.concat([pd.Series(np.zeros(ntstep)),pid_c],ignore_index=True)
            
            # removes cases when next particles are different from first 
            # iteration particles
            partic_c = partic_in*0
            temp     = prt.particleid[pid_c==1].to_numpy()
            partic_c[0:len(temp)] = temp
            temp2 = partic_c==partic_in
            temp2 = temp2[0:len(temp)]
            pid_c[pid_c==1] = temp2

            if len(pid_c[pid_c==1]) == 0:
                break
            
            # update cin values for next iteration
            pid_old = pid_c[1:]
            pid_old = pd.concat([pid_old,pd.Series([0])],ignore_index=True)
            prt.cin[pid_c==1]=prt.cout[pid_old==1].to_numpy()
  
        # Storage
        self.conc = prt
        
        print('Normal termination of simulation. Ellapsed run time: '+str(round(time.time() - start_time,1))+'s')
        
    # %% EXTRACT 2D MAP OF MEAN CONCENTRATIONS BETWEEN Z LAYERS

    def get_concentrations_from_zlayers(self,
                                        conc_pos: str='in',
                                        zmap_min: float=None,
                                        zmap_max: float=None,
                                        zero_based: bool=True
                                        ):
        """
        WIP 
        comprised between
        default : mean residence times over the full thickness of the model domain
        """
        
        # initialization
        prt_df = self.get_concentrations(conc_pos,zero_based=True)
        
        # remove concentrations with z <= zmin_map and z >= zmax_map   
        prt_df = prt_df[(prt_df['z']>=zmap_min[prt_df['i'],prt_df['j']])]
        prt_df = prt_df[(prt_df['z']<=zmap_max[prt_df['i'],prt_df['j']])]
        
        # get mean concentrations for particle changing layer at the same ij pos
        prt_df = prt_df.groupby(['particleid','i','j'])['c_radon'].mean()
        prt_df = pd.DataFrame(prt_df).reset_index()
        
        # get concentrations distribution for each cell
        # prt_df = prt_df.groupby(['i','j'])['time'].apply(list)
        prt_df = prt_df.groupby(['i','j'])['c_radon'].agg(list)
        prt_df = pd.DataFrame(prt_df).reset_index()
        prt_df = prt_df.rename(columns={'c_radon' : 'all_c_radon'})
        
        # get mean concentration and particle count for each cell
        prt_df['mean'] = list(map(np.mean, prt_df['all_c_radon']))
        prt_df['std'] = list(map(np.std, prt_df['all_c_radon']))
        prt_df['npart'] = list(map(len, prt_df['all_c_radon']))
        
        # formate outputs
        prt_df = prt_df.iloc[:,[0,1,3,4,5,2]]       
        
        return prt_df
    

    # %% CONCENTRATION POSITIONS FOR GW

    def get_concentrations(self,
                           particle_pos: str='in',
                           zero_based: bool=False
                           ):
        """
        WIP
        Returns particle positions in space and time.
        # TB: should be moved to MP class or a new particle tracking class
        # TB: copied & adapted from watershed.residencetimes
        Parameters
        ----------
        particle_pos : str, default= 'out'
            types of particle positions:
                'in'      : particle positions when entering each cell
                'out'     : particle positions when exiting each cell
                'center'  : NOT IMPLEMENTED particle positions halfway between entry and exit points for each cell
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
        particles_in=self.conc.copy()
        if zero_based:
            particles_in = self._change_base(particles=particles_in,direction='one_to_zero')
        
        # drops and rename
        particles_in = particles_in.rename(columns={'cin':'c_radon','time_in':'time'})
        particles_in = particles_in.drop(columns=['cout','time_out'])
        
        # particle positions when entering or exiting each cell (default)                  
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
        colnames = ['time','x','y','z','xloc','yloc','zloc','c_radon']
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
        
        # Cocentration at cell center is not arithmetic mean of cocentrations
        # in and out of cells; so this option is not working
        # # particle positions halfway between entry and exit points for each cell
        # particles_center = particles_in.copy()
        # particles_center[colnames] = (particles_in[colnames]+particles_out[colnames])/2
        # if particle_pos == 'center':
        #     return particles_center.reset_index(drop=True)

        
        
    # %% CREATE BASE DICTIONNARY WITH CELL INDEXES FOR SPATIALIZATION
    # @TB: should be elsewhere, in geographic or Modflow classes
    def create_base_spatialization(self,
                                   nrow,
                                   ncol,
                                   nlay,
                                   zero_based : bool=False):
        
        # Indexing starts at 0 or 1
        valini = 1
        if zero_based == True:
            valini = 0
        
        # Layer index
        k = list(range(valini,nlay+valini))
        k = np.repeat(k,nrow*ncol)
        
        # Column index
        j = list(range(valini,ncol+valini))
        j = np.repeat(j,nrow)
        j = np.tile(j,(nlay,1))
        j = j.reshape(j.shape[0]*j.shape[1])
        
        # Line index
        i = list(range(valini,nrow+valini))
        i = np.tile(i,(ncol*nlay,1))
        i = i.reshape(i.shape[0]*i.shape[1])
        
        # Unique cell id for each cell
        cellid = [list(map(str,k)),list(map(str,i)),list(map(str,j))]
        cellid = list(map("-".join, zip(*cellid)))
        
        # Export as dictionary
        return {'cellid':cellid,'k':k,'i':i,'j':j}

    
    # %% PRIVATE METHODS
    def _change_base(self,
                     particles: object,
                     direction: str='one_to_zero'
                     ):
        """
        Change particle indexing from one-based to zero-based, or conversely.
        Copy-pasted from watershed.residencetimes
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
        
        
        k = particles['k']
        i = particles['i']
        j = particles['j']
        cellid = [list(map(str,k)),list(map(str,i)),list(map(str,j))]
        cellid = list(map("-".join, zip(*cellid)))
        
        particles['cellid'] = cellid
        
        return particles
    
    

# %% NOTES
