# -*- coding: utf-8 -*-
"""
Created on Mon Nov 23 11:05:15 2020

@author: Ronan
"""

#%% TOOLS

import shapefile as shp
import os
from osgeo import gdal
from osgeo.gdalconst import GA_ReadOnly
from osgeo import ogr
import geopandas as gpd
from glob import glob
import pandas as pd
import imageio
import rasterio as rio
import whitebox
wbt = whitebox.WhiteboxTools()
# from WBT.whitebox_tools import WhiteboxTools
# wbt = WhiteboxTools()
# wbt.set_whitebox_dir(os.getcwd())

#%% INCLUDE

def my(value):
    if not "%" in value:
        # print(value)
        return None

def rasterize(data, vectorSrc, field, outFile):
    dataSrc = gdal.Open(data)
    shp = ogr.Open(vectorSrc)
    lyr = shp.GetLayer()
    driver = gdal.GetDriverByName('GTiff')
    dst_ds = driver.Create(
        outFile,
        dataSrc.RasterXSize,
        dataSrc.RasterYSize,
        1,
        gdal.GDT_Float32)
    dst_ds.SetGeoTransform(dataSrc.GetGeoTransform())
    dst_ds.SetProjection(dataSrc.GetProjection())
    band = dst_ds.GetRasterBand(1)
    if field is None:
        gdal.RasterizeLayer(dst_ds, [1], lyr, None)
    else:
        OPTIONS = ['ATTRIBUTE=' + field]
        gdal.RasterizeLayer(dst_ds, [1], lyr, None, options=OPTIONS)    
    data, dst_ds, band, shp, lyr = None, None, None, None, None
    return outFile

#%% STEPS

def generate_dem(cwd, demname, outlets, snapdist, buffdist):
    ##### Dem #####
    dem = cwd + 'gis/' + demname # dem start
    ##### Fill #####
    fill = cwd + 'gis/' + 'frame_fill.tif'
    wbt.fill_depressions(dem, fill, callback=my)
    ##### Direction #####
    direc = cwd + 'gis/' + 'frame_direc.tif'
    wbt.d8_pointer(fill, direc, esri_pntr=False, callback=my)
    ##### Accumulation #####
    acc = cwd + 'gis/' + 'frame_acc.tif'
    wbt.d8_flow_accumulation(fill, acc, log=True, callback=my)
    ##### Outlets #####
    coord = pd.read_csv(cwd + 'data/' + outlets, sep='\t+', header = None, engine='python')
    ##### Shapefiles #####
    outlet = cwd + 'gis/' + 'outlet_coord_site.shp'
    w = shp.Writer(outlet)
    w.field('name', 'C')
    for i in range(0,len(coord)):
        point = [coord.loc[i,0],coord.loc[i,1]]
        w.point(point[0],point[1]) 
        w.record('point'+str(i))
    w.close()
    ##### Snap #####
    snap = cwd + 'gis/' + 'outlet_coord_site_snap.shp'
    wbt.snap_pour_points(outlet, acc, snap, snapdist, callback=my) # 150 m max to change location
    ##### Area #####
    watshd = cwd + 'gis/' + 'site_area.tif'
    wbt.watershed(direc, snap, watshd, esri_pntr=False, callback=my)
    ##### Polygon #####
    polyg = cwd + 'gis/' + 'site_polygon.shp'
    wbt.raster_to_vector_polygons(watshd, polyg, callback=my)
    ##### Dissolve #####
    wbt.multi_part_to_single_part(polyg, polyg, exclude_holes=True, callback=my)
    wbt.clean_vector(polyg, polyg, callback=my)
    wbt.dissolve(polyg, polyg, field=None, callback=my)
    ##### Polyline #####
    polyl = cwd + 'gis/' + 'site_polyline.shp'
    wbt.polygons_to_lines(polyg, polyl, callback=my)
    ##### Buffer #####
    site_polyg = gpd.read_file(polyg)
    bufferDist = buffdist
    site_polyg['geometry'] = site_polyg.geometry.buffer(bufferDist)
    buff = site_polyg.to_file(cwd + 'gis/' + 'buff.shp')
    buff = cwd + 'gis/' + 'buff.shp'
    ##### Model dem #####
    buff_dem = cwd + 'gis/' + 'buff_dem.tif'
    r = gdal.Warp(buff_dem, dem, cutlineDSName=buff, cropToCutline=True)
    
def topo_analysis(cwd, buff, polyg, framefill, framedirec, frameacc):
    buffpath = cwd + 'gis/' + buff
    polygpath = cwd + 'gis/' + polyg
    ##### Model fill #####
    buff_fill = cwd + 'gis/' + 'buff_fill.tif'
    r = gdal.Warp(buff_fill, cwd + 'gis/' + framefill, cutlineDSName=buffpath, cropToCutline=True)
    ##### Model direc #####
    buff_direc = cwd + 'gis/' + 'buff_direc.tif'
    r = gdal.Warp(buff_direc, cwd + 'gis/' + framedirec, cutlineDSName=buffpath, cropToCutline=True)
    ##### Model acc #####
    buff_acc = cwd + 'gis/' + 'buff_acc.tif'
    r = gdal.Warp(buff_acc, cwd + 'gis/' + frameacc, cutlineDSName=buffpath, cropToCutline=True)
    # # ##### Site dem #####
    site_fill = cwd + 'gis/' + 'site_fill.tif'
    wbt.clip_raster_to_polygon(buff_fill, polygpath, site_fill, maintain_dimensions=True, callback=my)
    # ##### Extent #####
    maskDs = gdal.Open(buff_fill, GA_ReadOnly) # your mask raster
    projection=maskDs.GetProjectionRef()
    geoTransform = maskDs.GetGeoTransform()
    minx = geoTransform[0]
    maxy = geoTransform[3]
    maxx = minx + geoTransform[1] * maskDs.RasterXSize
    miny = maxy + geoTransform[5] * maskDs.RasterYSize
    toclip = gdal.Open(buff_fill, GA_ReadOnly) # your data the one you want to clip
    modext = cwd + 'gis/' + 'buff_ext.tif' # output file
    gdal.Translate(modext, toclip, format='GTiff', projWin=[minx,maxy,maxx,miny], 
                              noData=-99999, outputSRS=projection)

def obs_streams(cwd, allstreams, buffill, field):
    demfill = cwd + 'gis/' + buffill
    
    ##### All streams
    inpshp = cwd + 'obs/' + allstreams
    clipshp = cwd + 'gis/' + 'buff.shp'
    outshp = cwd + 'obs/' + 'buff_streams.shp'
    
    # wbt.clip(inpshp, clipshp, outshp)
    
    import warnings; warnings.filterwarnings('ignore', 'GeoSeries.notna', UserWarning)
    s = gpd.read_file(inpshp)
    c = gpd.read_file(clipshp)
    o = gpd.clip(s, c)
    o.to_file(outshp)

    ##### Permanent streams
    shp_str = gpd.read_file(outshp)
    shp_str = shp_str[shp_str[field] == '4']
    outshperm = cwd+'obs/'+'buff_streams_perman.shp'
    shp_str.to_file(outshperm)
    
    outifperm = cwd + 'obs/' + 'buff_streams_perman.tif'
    rasterize(demfill, outshperm, field, outifperm)
    
    points = cwd + 'obs/' + 'buff_pt_streams_perman.shp'
    wbt.raster_to_vector_points(outifperm, points, callback=my)
    
def obs_flow(cwd, buffill):
    demfill = cwd + 'gis/' + buffill
        
    ##### Downslope sim. ==> obs.
    streams_perman = cwd + 'obs/' + 'buff_streams_perman.tif'
    distances_perman = cwd + 'obs/' + 'buff_dist_simtostr.tif'
    wbt.downslope_distance_to_stream(demfill, streams_perman, distances_perman, callback=my)
        
def create_mask(cwd, buffill, buffdirec, buffacc, coordexut):
    
    ##### Outlets #####
    coord = pd.read_csv(cwd + 'data/' + coordexut, sep='\t+', header = None, engine='python')
    ##### Shapefiles #####
    outlet = cwd + 'gis/' + 'outlet_coord_sbv.shp'
    w = shp.Writer(outlet)
    w.field('name', 'C')
    for i in range(0,len(coord)):
        point = [coord.loc[i,0],coord.loc[i,1]]
        w.point(point[0],point[1]) 
        w.record('point'+str(i))
    w.close()
    
    ##### Accumul #####
    demfill = cwd + 'gis/' + buffill
    demdirec = cwd + 'gis/' + buffdirec
    demacc = cwd + 'gis/' + buffacc
    ##### Subasins #####
    pts = cwd + 'gis/' + 'outlet_coord_sbv.shp' # Before : multipoints to points
    snap =  cwd + 'gis/' + 'outlet_coord_sbv_snap.shp'
    wbt.snap_pour_points(pts, demacc, snap, 500, callback=my)
    subasin =  cwd + 'mask/' + 'subasin.tif'
    wbt.watershed(demdirec, snap, subasin, esri_pntr=False, callback=my)
    
    subun = cwd + 'mask/' + 'subasin_unnest.tif'
    wbt.unnest_basins(demdirec, snap, subun, esri_pntr=False, callback=my)
    unnest = glob(cwd + 'mask/' + 'subasin_unnest'+'*')

    # Import exut sbv coord
    stah = pd.read_csv(cwd + 'data/' + coordexut,
                              names=['X','Y'],
                                      sep='\t+', header = None,
                                      parse_dates=True,
                                      decimal=".", engine='python')
    stah = stah.reset_index()
    for idx in stah.index:
        id_sta = stah.loc[idx,'index']
        sub = imageio.imread(unnest[0])
        sub[sub!=id_sta] = -9999
        subdtype = sub.dtype
        out = cwd + 'mask/' + str(id_sta) + '.tif'
        dem = imageio.imread(demfill)
        demdtype = dem.dtype
        with rio.open(demfill) as src:
            ras_data = src.read()
            maskdtype = ras_data.dtype
            ras_meta = src.profile
        if subdtype == 'int16':
            ras_meta['dtype'] = "int16"
        if subdtype == 'int32':
            ras_meta['dtype'] = "int32"
        if subdtype == 'float32':
            ras_meta['dtype'] = "float32"
        if subdtype == 'float64':
            ras_meta['dtype'] = "float64"
        ras_meta['nodata'] = -9999
        with rio.open(out, 'w', **ras_meta) as dst:
            dst.write(sub, 1)




# 
