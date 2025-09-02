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
import os
import whitebox
import imageio
import numpy as np

import pandas as pd
import matplotlib.pyplot as plt

wbt = whitebox.WhiteboxTools()
import tempfile
wbt.verbose = False

# HydroModPy
from tools import toolbox

#%% CLASS

class Streams:
    """
    TB: WIP
    """
    
    #%% INITIALIZATION      
    def __init__(self):
        """
        """
        
    #%% STREAM NETWORK FROM GROUNDWATER DISCHARGE        
    def from_gw_discharge(self, 
                          geographic: object,
                          discharge_rast_path: str,
                          extraction_method: str='from_upstream_cells_count',
                          threshold: float=5,
                          nodata_val: float=-99999,
                          clip_watershed_option=False
                          ):
        """
        Extract stream network from groundwater outflow
        
        Parameters
        ----------
        WIP
        geographic : object
            Variable object of the model domain (watershed).

        """
        
        self.geographic = geographic # @TB: Only store DEM? should also ensure that it is the filled DEM
        self.discharge_rast_path = discharge_rast_path 
        
        with tempfile.TemporaryDirectory() as temp_dir: 
            # Temporary whiteboxtools files
            stream_rast_path = os.path.join(temp_dir, '_streams.tif')
            cmass_path = os.path.join(temp_dir, '_cmass.tif')
            d8pt_rast_path = os.path.join(temp_dir, '_d8pt.tif')
            
            # Rivers will be defined as all cells with cumulated gw discharge
            # larger than threshold value
            if extraction_method == 'from_cumulated_discharge':
                drain_raster_path = discharge_rast_path
                
            # Rivers will be defined as all cells with cumulated number of
            # upstream cells larger than threshold number
            elif extraction_method == 'from_upstream_cells_count':
                # Boolean raster flagging gw discharge point as 1
                drain_raster_path = os.path.join(temp_dir, '_bdrain.tif')
                im = imageio.imread(discharge_rast_path)
                im[im<0] = 0
                im[im>0] = 1
                toolbox.export_tif(geographic.watershed_buff_fill, 
                                   im, 
                                   drain_raster_path, 
                                   0)
                        
            # Cumulated discharge
            self.cumulated_discharge(geographic,
                                     drain_raster_path,
                                     cmass_path,
                                     nodata_val,
                                     clip_watershed_option)
                
            # Extract stream network
            wbt.extract_streams(cmass_path, 
                                stream_rast_path, 
                                threshold,
                                zero_background=True)
                
            # Get flow pointer grid from D8 algorithm for future use
            # @TB: currently already calculated and stored as 
            # geographic.watershed_direc, done here again for the sake of
            # consistency of routing methods inside the Streams class
            self.d8_pointer(geographic,
                            d8pt_rast_path,
                            nodata_val,
                            clip_watershed_option)
            
            # Storage
            self.stream_rast     = imageio.imread(stream_rast_path)
            self.watershed_direc = imageio.imread(d8pt_rast_path)


    #%% CUMULATED GROUNDWATER OUTFLOW        
    def cumulated_discharge(self,
                            geographic: object,
                            discharge_rast_path: str,
                            out_rast_path: str=None,
                            nodata_val: float=-99999,
                            clip_watershed_option=False
                            ):
        """
        Cumulated mass flux of gw discharge outflows, according to the DEM.
        
        @TB: copied from downslope.cumulated_discharge to ensure the coherence
        of routing algorithms used to compute flow accumulation (here D8
        algorithm, cf WhiteBoxTools user manual)
        
        """
        # Create flux, efficiency and adsorption rasters requiered by wbt
        # as temporary files
        with tempfile.TemporaryDirectory() as temp_dir: 
            restemp_rast_path = os.path.join(temp_dir, '_restemp.tif')
            
            ### Loading ###
            load_rast_path = os.path.join(temp_dir, '_load_t(xxx).tif')
            im = imageio.imread(discharge_rast_path)
            im = np.array(im)
            im = im.astype(float)
            im[im<0] = 0
            # # Remove data outside watershed option (reduces computational load)
            # if clip_watershed_option == True:
            #     dem_clip = geographic.dem_clip
            #     im[dem_clip <= 0] = -99999
            toolbox.export_tif(geographic.watershed_buff_fill, 
                               im, 
                               load_rast_path, 
                               -99999)
            ### Efficiency ###
            eff_rast_path = os.path.join(temp_dir, '_eff_t(xxx).tif')#
            im = imageio.imread(geographic.watershed_buff_fill)
            im[im>=0] = 1
            toolbox.export_tif(geographic.watershed_buff_fill, 
                               im, 
                               eff_rast_path, 
                               -99999)        
            ### Adsorption ###
            abs_rast_path = os.path.join(temp_dir, '_abs_t(xxx).tif')
            im = imageio.imread(geographic.watershed_buff_fill)
            im[im>=0] = 0
            toolbox.export_tif(geographic.watershed_buff_fill, 
                               im, 
                               abs_rast_path, 
                               -99999)
            
            # Flow accumulation with d8massflux
            wbt.d8_mass_flux(geographic.watershed_buff_fill,
                             load_rast_path, 
                             eff_rast_path,
                             abs_rast_path, 
                             restemp_rast_path)
            
            # Cleans up nodata_val in result file
            res = imageio.imread(restemp_rast_path)
            res = np.array(res)
            res = res.astype(float)
            res[res<0] = nodata_val
            
            # Remove data outside watershed option (reduces computational load)
            if clip_watershed_option == True:
                dem_clip = geographic.dem_clip
                res[dem_clip <= 0] = -99999
            
            # Export to file (optional)
            if out_rast_path!= None:
                toolbox.export_tif(geographic.watershed_buff_fill, 
                                   res, 
                                   out_rast_path, 
                                   nodata_val)
            
            return res
        
        #%% CUMULATED GROUNDWATER OUTFLOW        
    def cumulated_discharge_no_geog(self,
                                    dem_raster_path: str,
                                    discharge_rast_path: str,
                                    out_rast_path: str=None,
                                    nodata_val: float=-99999
                                    # clip_watershed_option=False
                                    ):
            """
            Cumulated mass flux of gw discharge outflows, according to the DEM.
            
            @TB: copied from downslope.cumulated_discharge to ensure the coherence
            of routing algorithms used to compute flow accumulation (here D8
            algorithm, cf WhiteBoxTools user manual)
            
            """
            # Create flux, efficiency and adsorption rasters requiered by wbt
            # as temporary files
            with tempfile.TemporaryDirectory() as temp_dir: 
                restemp_rast_path = os.path.join(temp_dir, '_restemp.tif')
                
                ### Loading ###
                load_rast_path = os.path.join(temp_dir, '_load_t(xxx).tif')
                im = imageio.imread(discharge_rast_path)
                im = np.array(im)
                im = im.astype(float)
                im[im<0] = 0
                # # Remove data outside watershed option (reduces computational load)
                # if clip_watershed_option == True:
                #     dem_clip = geographic.dem_clip
                #     im[dem_clip <= 0] = -99999
                toolbox.export_tif(dem_raster_path, 
                                   im, 
                                   load_rast_path, 
                                   -99999)
                ### Efficiency ###
                eff_rast_path = os.path.join(temp_dir, '_eff_t(xxx).tif')#
                im = imageio.imread(dem_raster_path)
                im[im>=0] = 1
                toolbox.export_tif(dem_raster_path, 
                                   im, 
                                   eff_rast_path, 
                                   -99999)        
                ### Adsorption ###
                abs_rast_path = os.path.join(temp_dir, '_abs_t(xxx).tif')
                im = imageio.imread(dem_raster_path)
                im[im>=0] = 0
                toolbox.export_tif(dem_raster_path, 
                                   im, 
                                   abs_rast_path, 
                                   -99999)
                
                # Flow accumulation with d8massflux
                wbt.d8_mass_flux(dem_raster_path,
                                 load_rast_path, 
                                 eff_rast_path,
                                 abs_rast_path, 
                                 restemp_rast_path)
                
                # Cleans up nodata_val in result file
                res = imageio.imread(restemp_rast_path)
                res = np.array(res)
                res = res.astype(float)
                res[res<0] = nodata_val
                
                # # Remove data outside watershed option (reduces computational load)
                # if clip_watershed_option == True:
                #     dem_clip = self.geographic.dem_clip
                #     res[dem_clip <= 0] = -99999
                
                # Export to file (optional)
                if out_rast_path!= None:
                    toolbox.export_tif(dem_raster_path, 
                                       res, 
                                       out_rast_path, 
                                       nodata_val)
                
                return res
            
    #%% D8 POINTER RASTER FOR FLOW DIRECTION        
    def d8_pointer(self,
                   geographic: object,
                   out_rast_path: str=None,
                   nodata_val: float=-99999,
                   clip_watershed_option=False
                   ):
        """
        Get flow pointer grid from D8 algorithm
        See WBT user manual
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Temporary file for storing results
            restemp_rast_path = os.path.join(temp_dir, '_restemp.tif')
            
            # Remove data outside watershed option (reduces computational load)
            if clip_watershed_option == False:
                dem_path = geographic.watershed_buff_fill
            else:
                dem_path = os.path.join(temp_dir, '_dem.tif')
                im = imageio.imread(geographic.watershed_buff_fill)
                dem_clip = geographic.dem_clip
                im[dem_clip <= 0] = nodata_val
                toolbox.export_tif(geographic.watershed_buff_fill, 
                                   im, 
                                   dem_path, 
                                   nodata_val)
                
            # Flow pointer grid using the D8 algorithm    
            wbt.d8_pointer(dem_path, restemp_rast_path)
            
            # nodata values
            watershed_direc = imageio.imread(restemp_rast_path)
            watershed_direc = np.array(watershed_direc)
            watershed_direc = watershed_direc.astype(float)
            watershed_direc[watershed_direc < 0] = nodata_val
            
            # Export to file (optional)
            if out_rast_path!= None:
                toolbox.export_tif(geographic.watershed_buff_fill, 
                                   watershed_direc, 
                                   out_rast_path, 
                                   nodata_val)
            
            return watershed_direc

    #%% SPLIT NETWORK AS INIVIDUAL STREAMS        
    def split_network(self, 
                      out_folder_path: str=None,
                      clip_watershed_option=False
                      ):
        
        with tempfile.TemporaryDirectory() as temp_dir: 
            
            if out_folder_path == None:
                out_folder_path = temp_dir
            
            # Temporary whiteboxtools file : stream network & flow direction 
            stream_rast_path = os.path.join(temp_dir, '_streams.tif')
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               self.stream_rast, 
                               stream_rast_path)
            
            # Temporary whiteboxtools file : flow direction raster
            d8pt_rast_path = os.path.join(temp_dir, '_d8pt.tif')
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               self.watershed_direc, 
                               d8pt_rast_path)
            
            # Distance to stream outlet
            dist_file_path = os.path.join(out_folder_path, 'distanceToOutlet.tif')
            wbt.distance_to_outlet(d8pt_rast_path, 
                                   stream_rast_path, 
                                   dist_file_path, 
                                   zero_background=True)
            self.distance_to_outlet = imageio.imread(dist_file_path)
            
            # Tributaries
            trib_file_path = os.path.join(out_folder_path, 'tributaries.tif')
            wbt.tributary_identifier(d8pt_rast_path, 
                                     stream_rast_path, 
                                     trib_file_path, 
                                     zero_background=True)
            self.tributaries = imageio.imread(trib_file_path)
            
            # Stream link class
            # attributes a number to each stream cell:
            #   - 1 : exterior link
            #   - 2 : interior link
            #   - 3 : source node (head water)
            #   - 4 : link node
            #   - 5 : sink node
            slc_file_path = os.path.join(out_folder_path, 'streamLinkClass.tif')
            wbt.stream_link_class(d8pt_rast_path, 
                                  stream_rast_path, 
                                  slc_file_path, 
                                  zero_background=True)
            self.stream_link_class = imageio.imread(slc_file_path)
            
            ##### WIP
            stream_raster = imageio.imread(stream_rast_path)
            stream_raster[stream_raster<=0] = -99999
            # stream_raster[stream_raster<=0] = np.nan
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                                stream_raster, 
                                stream_rast_path)
            
            demtemp_rast_path = os.path.join(out_folder_path, 'demTemp.tif') 
            demtemp_rast = imageio.imread(self.geographic.watershed_buff_fill)
            # demtemp_rast[stream_raster<=0] = -99999
            demtemp_rast[stream_raster<=0] = np.nan
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                                demtemp_rast, 
                                demtemp_rast_path)
            
            # fig, ax = plt.subplots(1,1, figsize=(7,5))
            # demtemp_rast = np.ma.masked_where(demtemp_rast < 0, demtemp_rast)
            # plt.imshow(demtemp_rast)
            # plt.show
            ##### WIP
            
            # wbt.d8_pointer(stream_rast_path, d8pt_rast_path)
            
            # Split stream network between as many streams that connect each
            # source node to their sink node
            source_rast = np.array(self.stream_link_class).astype(float)
            source_rast[source_rast < 3] = 0
            source_rast[source_rast > 3] = 0
            # Indices of source nodes
            source_ind = np.transpose(np.nonzero(source_rast))
            nsources = source_ind.shape[0]
            # Extraction of each stream
            all_streams = {}
            
            for i in list(range(0,nsources)):
                
                # currpos = source_ind[i,:]
                # currdist = self.distance_to_outlet[currpos[0],currpos[1]]
                # cstream = self.distance_to_outlet*0
                
                # while currdist !=0:
                #     cstream[currpos[0],currpos[1]]=1
                    
                    
                
                stream_file_path = os.path.join(out_folder_path, 'stream_'+str(i)+'.tif')
                
                c_source_file_path = os.path.join(temp_dir, 'csource.tif')
                c_source_rast = source_rast*0
                c_source_rast[source_ind[i,0],source_ind[i,1]] = 1
                # c_source_rast[stream_raster<=0] = -99999
                toolbox.export_tif(self.geographic.watershed_buff_fill, 
                                   c_source_rast, 
                                   c_source_file_path)
                
                self.cumulated_discharge_no_geog(demtemp_rast_path,
                                                 c_source_file_path,
                                                 stream_file_path)
                
                # self.cumulated_discharge(self.geographic,
                #                          c_source_file_path,
                #                          stream_file_path,
                #                          clip_watershed_option=clip_watershed_option)
                
                all_streams[i] = imageio.imread(stream_file_path)
            
            # for i in list(range(0,nsources)):
            #     stream_file_path = os.path.join(out_folder_path, 'stream_'+str(i)+'.tif')
                
            #     c_source_file_path = os.path.join(temp_dir, 'csource.tif')
            #     c_source_rast = source_rast*0
            #     c_source_rast[source_ind[i,0],source_ind[i,1]] = 1
            #     toolbox.export_tif(self.geographic.watershed_buff_fill, 
            #                        c_source_rast, 
            #                        c_source_file_path)
                
            #     self.cumulated_discharge(self.geographic,
            #                              c_source_file_path,
            #                              stream_file_path,
            #                              clip_watershed_option=clip_watershed_option)
            #     all_streams[i] = imageio.imread(stream_file_path)
                
            self.all_streams_rast = all_streams
    
    #%% LONG PROFILES FROM STREAMS        
    def long_profiles(self, 
                      data
                      # out_folder_path: str=None
                      ):
        
        # Data can be either a matrix or a file
        if isinstance(data,str):
            data = np.array(imageio.imread(data))
        
        # Distances fromstream outlet
        dist = np.array(self.distance_to_outlet)
        dist = dist.reshape(-1)
        
        # Profiles will be obtained for each individual stream
        all_long_profiles = {}
        for i in list(range(len(self.all_streams_rast))):
            cstream = np.array(self.all_streams_rast[i])
            
            cdata = np.copy(data)
            cdata[cstream != 1] = 0
            cdata = cdata.reshape(-1)
            
            res = np.column_stack((dist,cdata))
            res = res[res[:,1]>0,:]
            res = res[res[:, 0].argsort()]
            all_long_profiles[i]=res
        
        return all_long_profiles
        
    #%% EXPORT STREAM NETWORK AS FILES
    
    def export_as_raster(self,
                         out_file_path: str
                         ):
        """
        Export river network as raster file (.tif).
        """
        toolbox.export_tif(self.geographic.watershed_buff_fill, 
                           self.stream_rast, 
                           out_file_path)

    def export_as_vector(self,
                         out_file_path: str
                         ):
        """
        Export river network as vector file (.shp).
        """
        with tempfile.TemporaryDirectory() as temp_dir: 
            # Temporary whiteboxtools files
            stream_rast_path = os.path.join(temp_dir, '_streams.tif')
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               self.stream_rast, 
                               stream_rast_path)
            
            d8pt_rast_path = os.path.join(temp_dir, '_d8pt.tif')
            toolbox.export_tif(self.geographic.watershed_buff_fill, 
                               self.watershed_direc, 
                               d8pt_rast_path)
            
            wbt.raster_streams_to_vector(stream_rast_path, 
                                         d8pt_rast_path, 
                                         out_file_path)
        
#%% NOTES
