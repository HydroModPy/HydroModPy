# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import geopandas as gpd
import numpy as np
import os
from osgeo import gdal, osr
import pandas as pd
from pyproj import Proj
from pyproj import Transformer
from osgeo import gdal, osr
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False
from geopy.geocoders import Nominatim
import shutil
import imageio

# HydroModPy modules
from tools import toolbox

#%% CLASS 1

class Geographic:
    """
    
    class Geographic used to clip the watershed from regional DEM

    Attributes
    ----------
    watershed_shp: str
        path of watershed shapefile
    watershed_box_shp: str
        path of watershed shapefile (boundaries box)
    watershed_fill: str
        path of watershed filled
    watershed_dir: str
        path of watershed flow direction
    
    Methods
    -------
    processing(dem_path, x, y, snap_dist, buff_dist, out_path)
        creates files to extract watershed from regional DEM
    post_processing_dem(dem_path)
        loads files to 
        
    """
    
    #%% INIT
    
    def __init__(self, dem_path, x, y, snap_dist=150, buff_percent=10,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\',
                 from_shp = None, from_dem = False, from_xy = [], cell_size=100,
                 regio_path = None):
        print('Extraction des données géographiques')
        
        self.snap_dist = snap_dist
        self.from_shp = from_shp
        self.from_xy = from_xy
        self.regio_path = regio_path
        
        if self.from_xy != []:
            x = self.from_xy[0]
            y = self.from_xy[1]
            self.snap_dist = self.from_xy[2]
            buff_percent = self.from_xy[3]
        
        if from_dem == False:
            self.processing(dem_path, x, y, self.snap_dist, buff_percent, out_path)
        else:    
            self.model_from_dem(dem_path, out_path, cell_size)

        # if self.from_shp == None: # ADD FOR CLIMATE !!!
        self.post_processing_dem()
    
    #%% GENERATE FILES
    
    def processing(self, dem_path, x, y, snap_dist, buff_percent, out_path):
        
        # Generate folder where processing files are stored
        self.gis_path = os.path.join(out_path, 'results_stable/geographic/')
        toolbox.create_folder(self.gis_path)
        
        if self.regio_path == None:
            self.reg_path = os.path.join(out_path, 'results_stable/geographic/regional/')
        else:
            self.reg_path = self.regio_path
        toolbox.create_folder(self.reg_path)
        
        """
        Raw regional DEM
        """
        # Correction
        fill =  os.path.join(self.reg_path, 'region_fill.tif')
        if not os.path.exists(fill):
            wbt.fill_depressions(dem_path, fill) # or # wbt.breach_depressions(dem_path, fill, 2, 75*8)
        # Flow direction
        direc =  os.path.join(self.reg_path, 'region_direc.tif')
        if not os.path.exists(direc):
            wbt.d8_pointer(fill, direc, esri_pntr=False)
        # Flow accumulation
        acc =  os.path.join(self.reg_path, 'region_acc.tif')
        if not os.path.exists(acc):
            wbt.d8_flow_accumulation(fill, acc, log=True)
        
        # Correct no data
        wbt.modify_no_data_value(dem_path, new_value='-99999.0')
        
        # Open correct DEM
        dem = gdal.Open(dem_path)
        geodata = dem.GetGeoTransform()
    
        """
        Extract watershed from an outlet
        """
        if self.from_shp == None :
            # Extract the coordinate system
            proj = osr.SpatialReference(wkt=dem.GetProjection())
            self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
            #self.crs = 'EPSG:3035'
            # Create outlet shapefile from x and y coordinates
            df = pd.DataFrame({'x': [x], 'y': [y]})
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=self.crs)
            outlet_shp = self.gis_path + 'outlet.shp'
            gdf.to_file(outlet_shp)
            # Snap the outlet shapefile from the flow accumulation
            outlet_snap_shp = self.gis_path + 'outlet_snap.shp'
            wbt.snap_pour_points(outlet_shp, acc, outlet_snap_shp, snap_dist)
            # Generate raster watershed
            self.watershed = self.gis_path + 'watershed.tif'
            wbt.watershed(direc, outlet_snap_shp, self.watershed, esri_pntr=False)
            # tif = gdal.Open(watershed)
            # geotransf = tif.GetGeoTransform()
            # pixel_area = abs(geotransf[1] * geotransf[5])
            # band_size = (tif.GetRasterBand(1).XSize, tif.GetRasterBand(1).YSize)
            # area = band_size[0] * band_size[1] * pixel_area
            # Create shapefile polygon of the watershed
            self.watershed_shp = self.gis_path + 'watershed.shp'
            wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
        else:
            self.watershed_shp = self.gis_path + 'watershed.shp'
            shp_file = gpd.read_file(self.from_shp)
            shp_file.to_file(self.watershed_shp)
        wbt.polygon_area(self.watershed_shp)
        area = gpd.read_file(self.watershed_shp).AREA[0]/1000000
        self.area = np.abs(area)
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = self.gis_path + 'watershed_contour.shp'
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
        
        # if self.from_shp == None: # ADD FOR CLIMATE !!!
    
        """
        Buffer distance operations
        """
        # Normalize initial buffer distance value
        buff_raw = (np.sqrt(float(self.area))) * (float(buff_percent)/100) * 1000
        buff_raw = int(round(buff_raw))
        dist = np.linspace(0,buff_raw,buff_raw+1)*np.abs(geodata[1])
        buff_dist = dist[np.abs(dist-buff_raw).argmin()]
        # buff_dist = buff_raw
        # Buffer the watershed shapefile polygon
        site_polyg = gpd.read_file(self.watershed_shp)
        site_polyg.to_file(self.watershed_shp)
        site_polyg['geometry'] = site_polyg.geometry.buffer(buff_dist)
        buffer = self.gis_path + 'buff.shp'
        site_polyg.to_file(buffer)

        """
        Box extent operations
        """
        # Create box extent of the watershed
        self.watershed_box_shp = self.gis_path + 'watershed_box.shp'
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        # Buffer the box extent watershed shapefile polygon
        site_bound = gpd.read_file(self.watershed_box_shp)
        site_bound.to_file(self.watershed_box_shp)
        site_bound['geometry'] = site_bound.geometry.buffer(buff_dist)
        box_buffer = self.gis_path + 'box_buff.shp'
        site_bound.to_file(box_buffer)
        wbt.minimum_bounding_envelope(box_buffer, box_buffer, features=False)
        site_bound = gpd.read_file(box_buffer)
        site_bound.to_file(box_buffer)
        
        """
        Clip to reach buffer size
        """
        # Clip raw regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_dem = self.gis_path + 'watershed_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, buffer, self.watershed_buff_dem)
        # Clip corrected regional DEM from buffer watershed shapefile polygon
        self.watershed_buff_fill = self.gis_path + 'watershed_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, buffer, self.watershed_buff_fill)
        # Clip flow direction regional DEM from buffer watershed shapefile polygon
        watershed_buff_direc = self.gis_path + 'watershed_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, buffer, watershed_buff_direc)
        
        """
        Clip to reach watershed size
        """
        # Clip buffer watershed DEM from watershed shapefile polygon
        self.watershed_dem = self.gis_path + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(self.watershed_buff_dem, self.watershed_shp, self.watershed_dem, maintain_dimensions=True)
        # Clip corrected regional DEM from watershed shapefile polygon
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        wbt.clip_raster_to_polygon(fill, self.watershed_shp, self.watershed_fill)
        # Clip flow direction regional DEM from watershed shapefile polygon
        self.watershed_direc = self.gis_path + 'watershed_direc.tif'
        wbt.clip_raster_to_polygon(direc, self.watershed_shp, self.watershed_direc)
        wbt.slope(self.watershed_dem,
                  self.gis_path + 'watershed_slope.tif',
                  units="percent")
        slope = imageio.imread(self.gis_path + 'watershed_slope.tif')
        self.slope = np.nanmean(slope[slope>=0])
        
        """
        Clip to reach box extent size
        """
        # Clip raw regional DEM from buffer box extent watershed shapefile polygon
        self.watershed_box_buff_dem = self.gis_path + 'watershed_box_buff_dem.tif'
        wbt.clip_raster_to_polygon(dem_path, box_buffer, self.watershed_box_buff_dem)
        # Clip corrected regional DEM from buffer box extent watershed shapefile polygon
        watershed_box_buff_fill = self.gis_path + 'watershed_box_buff_fill.tif'
        wbt.clip_raster_to_polygon(fill, box_buffer, watershed_box_buff_fill)
        # Clip flow direction regional DEM from buffer box extent watershed shapefile polygon
        watershed_box_buff_direc = self.gis_path + 'watershed_box_buff_direc.tif'
        wbt.clip_raster_to_polygon(direc, box_buffer, watershed_box_buff_direc)
        
        """
        Create depressions raster
        """
        try:
            self.depressions = self.gis_path + 'depressions.tif'
            wbt.sink(self.watershed_box_buff_dem, self.depressions)
        except:
            pass
    
    #%% DEM FEATURES
    
    def post_processing_dem(self):

        # Open DEM used for modeling
        dem = gdal.Open(self.watershed_buff_dem)
        self.dem_data = dem.GetRasterBand(1).ReadAsArray()
        self.geodata = dem.GetGeoTransform()
        dem_box = gdal.Open(self.watershed_box_buff_dem)
        self.dem_box_data = dem_box.GetRasterBand(1).ReadAsArray()
        bv = gdal.Open(self.watershed_dem)
        self.dem_clip = bv.GetRasterBand(1).ReadAsArray()
        # Open DEM depressions
        try:
            dem_dep = gdal.Open(self.depressions)
            self.depressions_data = dem_dep.GetRasterBand(1).ReadAsArray()
        except:
            pass
        # Extract the coordinate system
        proj = osr.SpatialReference(wkt=dem.GetProjection())
        crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
        # Extract size characteristics
        self.x_pixel = self.dem_data.shape[1] # columns
        self.y_pixel = self.dem_data.shape[0] # rows
        # Extract resolution
        self.resolution_x = self.geodata[1] # pixelWidth: positive
        self.resolution_y = self.geodata[5] # pixelHeight: negative
        self.resolution = self.resolution_x
        # Extract bounds size
        self.xmin = self.geodata[0] # originX
        self.ymax = self.geodata[3] # originY
        self.xmax = self.xmin + self.x_pixel * self.resolution_x
        self.ymin = self.ymax + self.y_pixel * self.resolution_y
        # Generate coordinates
        self.x_coord = np.linspace(1,self.x_pixel, self.x_pixel)*(self.resolution_x) + self.xmin
        self.y_coord = self.ymax - np.linspace(1,self.y_pixel, self.y_pixel)*(self.resolution_x)
        # Calculate centroids
        self.centroid = [self.xmin+((self.xmax-self.xmin)/2),self.ymin+((self.ymax-self.ymin)/2)]
        # Transform centroids to World Geodetic System 1984
        try:
            transformer = Transformer.from_crs("epsg:2154", "epsg:4326")
            self.centroid_long_lat = transformer.transform(self.centroid[0], self.centroid[1])
            self.ur_long_lat = transformer.transform(self.xmax,self.ymax)
            self.ul_long_lat = transformer.transform(self.xmin,self.ymax) 
            self.ll_long_lat = transformer.transform(self.xmax,self.ymin)
            self.lr_long_lat = transformer.transform(self.xmin,self.ymin)
            # Transform to longitude/latitude London Greenwich
            self.centroid_long_lat_Greenwich = [self.centroid_long_lat[0], self.centroid_long_lat[1]]
            if self.centroid_long_lat_Greenwich[1]<0:
                self.centroid_long_lat_Greenwich[1] = self.centroid_long_lat_Greenwich[1] + 360
        except:
            pass
        try:
            locator = Nominatim(user_agent='google')
            location = locator.reverse(str(self.centroid_long_lat_Greenwich[0]) +','+str(self.centroid_long_lat_Greenwich[1]), timeout=120)
            self.dep_code = int(location.address.split(',')[-2][0:3])
        except:
            pass
        
    #%% XYZ FILE TO DEM
    
    # In the case of .txt files with x, y, z coordinates 
    
    def model_from_dem(self, dem_path, out_path, cell_size):
        # Paths
        self.gis_path = os.path.join(out_path, 'results_stable/geographic/')
        toolbox.create_folder(self.gis_path)
        # Generate tif from xyz file
        if (dem_path[-3:]=='txt'):
            x = pd.read_csv(dem_path, sep='\s+', header=None)
            x.to_csv(self.gis_path+'transform_xyz'+'.csv', sep=';', index=False)
            wbt.csv_points_to_vector(self.gis_path+'transform_xyz'+'.csv', 
                                     self.gis_path+'transform_xyz'+'.shp', 
                                     xfield=0, yfield=1, epsg=2154)
            self.watershed_raw = self.gis_path + 'watershed_raw.tif'
            wbt.vector_points_to_raster(self.gis_path+'transform_xyz'+'.shp', 
                                        self.watershed_raw, 
                                        field=2, 
                                        assign="last", 
                                        nodata=True, 
                                        cell_size=cell_size, 
                                        base=None)        
            # Create the watershed dem
            self.watershed_dem = self.gis_path + 'watershed_dem.tif'
            shutil.copyfile(self.watershed_raw, self.watershed_dem)
        else:
            # Find crs
            dem = gdal.Open(dem_path)
            proj = osr.SpatialReference(wkt=dem.GetProjection())
            self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
            print(self.crs)
            # Copy tif
            self.watershed_raw = self.gis_path + 'watershed_raw.tif'
            shutil.copyfile(dem_path, self.watershed_raw)
            # Proj layer
            self.watershed_dem = self.gis_path + 'watershed_dem.tif'
            ### gdal.Warp(self.watershed_dem, self.watershed_raw , dstSRS='EPSG:2154')
        # No data
        wbt.modify_no_data_value(self.watershed_dem, new_value='-99999.0')  
        # Buff dem
        self.watershed_buff_dem = self.gis_path + 'watershed_buff_dem.tif'
        shutil.copyfile(self.watershed_dem, self.watershed_buff_dem)
        # Buff box dem
        self.watershed_box_buff_dem = self.gis_path + 'watershed_box_buff_dem.tif'
        shutil.copyfile(self.watershed_dem, self.watershed_box_buff_dem)
        # Correction
        self.watershed_fill = self.gis_path + 'watershed_fill.tif'
        wbt.fill_depressions(self.watershed_dem, self.watershed_fill)
        # Flow direction
        self.watershed_direc = self.gis_path + 'watershed_direc.tif'
        wbt.d8_pointer(self.watershed_fill, self.watershed_direc, esri_pntr=False)
        # Flow accumulation
        self.watershed_acc = self.gis_path + 'watershed_acc.tif'
        wbt.d8_flow_accumulation(self.watershed_fill, self.watershed_acc, log=True)
        
        """
        # Create shapefile
        self.watershed_shp = self.gis_path + 'watershed.shp'
        wbt.raster_to_vector_polygons(self.watershed_dem, self.watershed_shp)
        """
        
        """
        # Area of shape
        wbt.polygon_area(self.watershed_shp)
        area = gpd.read_file(self.watershed_shp).AREA[0]/1000000
        self.area = np.abs(area)
        # Create shapefile polyline of the watershed
        self.watershed_contour_shp = self.gis_path + 'watershed_contour.shp'
        wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
        # Buff fill dem
        self.watershed_buff_fill = self.gis_path + 'watershed_buff_fill.tif'
        shutil.copyfile(self.watershed_fill, self.watershed_buff_fill)        
        # Buff box fill dem
        self.watershed_box_buff_fill = self.gis_path + 'watershed_box_buff_fill.tif'
        shutil.copyfile(self.watershed_fill, self.watershed_box_buff_fill)
        # Create box extent of the watershed
        self.watershed_box_shp = self.gis_path + 'watershed_box.shp'
        wbt.minimum_bounding_envelope(self.watershed_shp, self.watershed_box_shp, features=False)
        """
        
#%% CLASS 2

class Subbasin:
    
    #%% INIT
    
    def __init__(self, geographic, hydrometry, intermittency,
                 out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\'):        
        print('Extraction des données sous-bassins')
        
        self.subbasin_path = os.path.join(out_path, 'results_stable/subbasin/')
        if not os.path.exists(self.subbasin_path):
            toolbox.create_folder(self.subbasin_path)
        
        self.adddata_path = os.path.join(out_path, 'results_stable/add_data/')
        if not os.path.exists(self.adddata_path):
            toolbox.create_folder(self.adddata_path)
        
        try:
            code_bh = hydrometry.code_bh
            x_coord = hydrometry.x_coord
            y_coord = hydrometry.y_coord
            for i in range(len(code_bh)):
                sub_path = os.path.join(self.subbasin_path, 'hydrometry_'+code_bh[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
        
        try:
            code_onde = intermittency.code_onde
            x_coord = intermittency.x_coord
            y_coord = intermittency.y_coord
            for i in range(len(code_onde)):
                sub_path = os.path.join(self.subbasin_path, 'intermittency_'+code_onde[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
        
        try:
            code_sub, x_coord, y_coord = self.add_coord_manual()
            for i in range(len(code_sub)):
                sub_path = os.path.join(self.subbasin_path, 'subbasin_'+code_sub[i])
                self.extract_interest_zones(geographic, x_coord[i], y_coord[i], sub_path)
        except:
            pass
    
    #%% SUB-CATCHMENT FROM STATIONS
    
    # Extract sub-catchment from existing stations : hydrometry or intermittency
    
    def extract_interest_zones(self, geographic, X, Y, outpath):
        # Path of subbasin
        if os.path.exists(outpath):
            shutil.rmtree(outpath)
        toolbox.create_folder(outpath)        
        # Coordinates
        outpath = outpath + '/'
        df = pd.DataFrame({'x': [X], 'y': [Y]})
        gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=geographic.crs)
        outlet_shp = outpath + 'outlet.shp'
        gdf.to_file(outlet_shp)
        # Snap the outlet shapefile from the flow accumulation
        outlet_snap_shp = outpath + 'outlet_snap.shp'
        # wbt.snap_pour_points(outlet_shp, geographic.reg_path + 'region_acc.tif', 
        #                      outlet_snap_shp, geographic.snap_dist)
        wbt.snap_pour_points(outlet_shp, geographic.reg_path + 'region_acc.tif', 
                             outlet_snap_shp, 150) # add self.snap_dist
        # Generate raster watershed
        watershed = outpath + 'watershed.tif'
        wbt.watershed(geographic.reg_path + 'region_direc.tif', outlet_snap_shp, watershed, esri_pntr=False)
        # Create shapefile polygon of the watershed
        watershed_shp = outpath + 'watershed.shp'
        wbt.raster_to_vector_polygons(watershed, watershed_shp)
        shp = gpd.read_file(watershed_shp)
        shp.set_crs(geographic.crs, inplace=True, allow_override=True)
        shp.to_file(watershed_shp)
        wbt.polygon_area(watershed_shp)
        area = gpd.read_file(watershed_shp).AREA[0]/1000000
        area = np.abs(area)
        # Create shapefile polyline of the watershed
        watershed_contour_shp = outpath + 'watershed_contour.shp'
        wbt.polygons_to_lines(watershed_shp, watershed_contour_shp)
        # Clip buffer watershed DEM from watershed shapefile polygon
        watershed_dem = outpath + 'watershed_dem.tif'
        wbt.clip_raster_to_polygon(geographic.watershed_buff_dem, watershed_shp, watershed_dem, maintain_dimensions=True)        
    
    #%% SUB-CATCHMENT FROM XY POINT
    
    # .csv file with x, y coordinates representing the outlet desired sub-catchments
    
    def add_coord_manual(self):
        sub_list = pd.read_csv(os.path.join(self.adddata_path, 'add_coord_manual.txt'), sep=';')
        code_sub = sub_list['code_sub'].to_list()
        x_coord = sub_list['x_outlet'].to_list()
        y_coord = sub_list['y_outlet'].to_list()
        return code_sub, x_coord, y_coord
        
# x = Subbasins(BV.geographic, BV.hydrometry, BV.intermittency, BV.watershed_folder)

#%% NOTES

### ADD IF NECESSARY FOR MODEL FROM A CONCEPTUAL DEM ###
    # Correction
# self.watershed_fill = self.gis_path + 'watershed_fill.tif'
# wbt.fill_depressions(self.watershed_dem, self.watershed_fill) # or # wbt.breach_depressions(dem_path, fill, 2, 75*8)
    # Flow direction
# self.watershed_direc = self.gis_path + 'watershed_direc.tif'
# wbt.d8_pointer(self.watershed_fill, self.watershed_direc, esri_pntr=False)
    # Flow accumulation
# self.watershed_acc = self.gis_path + 'watershed_acc.tif'
# wbt.d8_flow_accumulation(self.watershed_fill, self.watershed_acc, log=True)
    # Create shapefile
# self.watershed_shp = self.gis_path + 'watershed.shp'
# wbt.raster_to_vector_polygons(self.watershed_dem, self.watershed_shp)
    # Area of shape
# wbt.polygon_area(self.watershed_shp)
# area = gpd.read_file(self.watershed_shp).AREA[0]/1000000
# area = np.abs(area)
    # Create shapefile polyline of the watershed
# self.watershed_contour_shp = self.gis_path + 'watershed_contour.shp'
# wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
    # Buff fill dem
# self.watershed_buff_fill = self.gis_path + 'watershed_buff_fill.tif'
# shutil.copyfile(self.watershed_fill, self.watershed_buff_fill)        
    # Buff box fill dem
# self.watershed_box_buff_fill = self.gis_path + 'watershed_box_buff_fill.tif'
# shutil.copyfile(self.watershed_fill, self.watershed_box_buff_fill)
    # Translate
# ds = gdal.Open(dem_path)
# self.watershed_raw = self.gis_path + 'watershed_raw.tif'
# ds = gdal.Translate(self.watershed_raw, ds)
# ds = None
    # Resampling
# self.watershed_dem = self.gis_path + 'watershed_dem.tif'        
# wbt.resample(self.watershed_reproj, self.watershed_dem, cell_size=cell_size, base=None, method="nn")
    # No data
# wbt.modify_no_data_value(self.watershed_dem, new_value='-99999.0')    

"""
for i in range(len(clip_hydrometric_shp)):
    df.loc[i,'type'] = 'hydrometric'
    df.loc[i,'code'] = clip_hydrometric_shp['CdStatio_1'].values[0]
    df.loc[i,'label'] = clip_hydrometric_shp['LbStationH'].values[0]
    df.loc[i,'x'] = clip_hydrometric_shp['CoordXStat'].values[0]
    df.loc[i,'y'] = clip_hydrometric_shp['CoordYStat'].values[0]
    df.loc[i,'start'] = pd.to_datetime(clip_hydrometric_shp['timePositi'].values[0][0:10], format='%Y-%m-%d')
    df.loc[i,'end'] = pd.to_datetime(clip_hydrometric_shp['DtFermetur'].values[0][0:10],format='%Y-%m-%d')
"""

