# -*- coding: utf-8 -*-
"""
Created on Thu Dec  2 14:38:37 2021

@author: Nicolas Cornette
"""

# Modules
import os
import numpy as np
import pandas as pd
import whitebox
import matplotlib as mpl
import matplotlib.pyplot as plt
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
from osgeo import gdal, osr

class Hillslope:
    """
    class Hillslopes used to generate hillslopes structure from watershed and stream network
    
    Attributes
    ----------
    
    Methods
    -------
    generate_hillslopes(geographic, out_path)
        generate hillslopes from singular points (outlet, head and confluences) extract from stream network
    compute_1Dprofile()
        generate the hillslope 1D profile, i.e. width profile, distance to the river and elevation profile
    """
    
    def __init__(self, geographic, 
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):
        
        print('Extraction des versants et du profil 1D')
        
        # Define gis inputs
        direc = geographic.direc
        stream = geographic.watershed_stream
        watershed = geographic.watershed_shp
        watershed_dem = geographic.watershed_fill
        cellsize = geographic.resolution
        gis_path = os.path.join(out_path, 'results_stable/geographic/')
        
        # Generate hillslopes
        self.extract_hillslopes(direc, stream, watershed, gis_path)
        
        # Compute 1D profile
        self.hs1D = self.profile1D(direc, stream, watershed_dem, cellsize, gis_path)
        
        # Equivalent hillslope
        self.equivalent_hillslope()
        
    def extract_hillslopes(self, direc, stream, watershed, gis_path):
        
        # Generate hillslopes from regional stream network and flux direction
        hillslopes = gis_path + 'region_hillslopes.tif'
        wbt.hillslopes(direc, stream, hillslopes)
        
        # Clip hillslopes to watershed extent
        self.watershed_hillslopes = gis_path + 'watershed_hillslopes.tif'
        wbt.clip_raster_to_polygon(hillslopes, watershed, self.watershed_hillslopes, 
                                   maintain_dimensions=True)
        
    def profile1D(self, direc, stream, watershed_dem, cellsize, gis_path):
        
        # Hillslopes indices
        hillslopes = gdal.Open(self.watershed_hillslopes)
        self.hillslopes = hillslopes.ReadAsArray()
        
        # Extract the mean distance to the closest river network points
        self.distance_to_river = self.__distance_to_river(direc, stream, 
                                                     watershed_dem, gis_path)
        
        # Elevation raster 
        elevation = gdal.Open(watershed_dem)
        self.elevation = elevation.ReadAsArray()
        
        # Get unique hillslope ID and remove NO DATA
        unique_hillslope_ID = np.unique(self.hillslopes)
        unique_hillslope_ID = np.delete(unique_hillslope_ID, [0,1])
        
        # Loop on individual hillslope
        hillslopes_1D = []
        
        for i in unique_hillslope_ID:
            
            # Select individual hillslopes meshes
            idx_r, idx_c = np.where(self.hillslopes == i)
            
            # Get distance to the river
            distance_values = self.distance_to_river[idx_r, idx_c]
            
            # Get elevation
            elevation_values = self.elevation[idx_r, idx_c] 
            
            # Initialize 1D dataframe
            df = pd.DataFrame(distance_values, columns = ['distance'])
            df['elevation'] = elevation_values
            
            # Set 1D x profile
            x = np.arange(np.round(np.min(distance_values)), np.round(np.max(distance_values)),
                          np.round(cellsize))
            
            # Number of cellsize between each distance to the river values
            distance_range = []
            n_cellsize = []
            elevation_range = []
            count = 0
            
            for d in x:
                distance_range.append(d)
                
                if count == 0:
                    df_subset = df[df.distance<=distance_range[count]]
                    n = df_subset.count()
                    n_cellsize.append(n[0])
                    elevation_range.append(np.mean(df_subset.elevation))
                
                if count != 0:
                    df_subset = df[(df.distance>distance_range[count-1]) & (df.distance<=distance_range[count])]
                    n = df_subset.count()
                    n_cellsize.append(n[0])
                    elevation_range.append(np.mean(df_subset.elevation))
                
                count += 1 
                
            # Compute the width profile
            width_values = self.__width_profile(n_cellsize, cellsize)
            
            # 1D individual hillslope profile
            df_hillslope = pd.DataFrame()
            df_hillslope['x'] = x
            df_hillslope['w'] = width_values
            df_hillslope['z'] = elevation_range
            
            hillslopes_1D.append(df_hillslope)
            
        return hillslopes_1D
    
    def equivalent_hillslope(self):
        
        # Concatenate all data frames
        all_df_hillslope = pd.concat(self.hs1D)
        
        # compute equivalent hillslope profile
        hsB_w = all_df_hillslope.groupby('x')['w'].sum()
        hsB_z = all_df_hillslope.groupby('x')['z'].mean()
        hsB = pd.DataFrame(hsB_w, columns = ['w'])
        hsB['z'] = hsB_z
        
        # Plot equivalent hillslope
        plt.plot(hsB.index, hsB['z'], color='k',linewidth=2)
        plt.ylabel('Elevation [m]')
        plt.xlabel('Distance to the river [m]')
        plt.title('Topographical profile')
        plt.show()
        
        plt.plot(hsB.index, hsB['w'], color='k',linewidth=2)
        plt.ylabel('Width [m²]')
        plt.xlabel('Distance to the river [m]')
        plt.title('Width profile')
        plt.show()
        
    def __distance_to_river(self, direc, stream, watershed_dem, gis_path):
        
        # Compute distance to the closest stream for each cell
        distance2stream = gis_path + 'distance2stream.tif'
        wbt.downslope_distance_to_stream(watershed_dem, stream, distance2stream)
        long_profile = gis_path + 'long_profile.tif'
        wbt.long_profile(direc, stream, watershed_dem, long_profile)
        
        # Load distance to the nearest stream network
        distance = gdal.Open(distance2stream)
        distance = distance.ReadAsArray()
        
        return distance
    
    def __width_profile(self, n_cellsize, cellsize):
        
        # Compute the width profile
        n_cellsize = np.array(n_cellsize)
        width = n_cellsize * cellsize
        
        return width
    