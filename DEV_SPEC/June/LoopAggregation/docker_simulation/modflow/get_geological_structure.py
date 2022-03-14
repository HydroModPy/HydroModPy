# coding:utf-8

import flopy
import os, sys
import numpy as np
import pandas as pd
from osgeo import gdal, gdalconst
from osgeo import osr, ogr
from scipy.interpolate import griddata
import matplotlib.pyplot as plt
from scipy import interpolate
import subprocess

r_dem = os.path.dirname(os.path.abspath(__file__)) + "/data/MNT_TOPO_BATH_75m.tif"
r_k = os.path.dirname(os.path.abspath(__file__)) + "/data/GLHYMPS.tif"
r_gum = os.path.dirname(os.path.abspath(__file__)) + "/data/GUM.tif"
r_bedrock_depth = os.path.dirname(os.path.abspath(__file__)) + "/data/bedrock_depth.tif"
r_sea_earth = os.path.dirname(os.path.abspath(__file__)) + "/data/sea_earth.tif"
r_river = os.path.dirname(os.path.abspath(__file__)) + "/data/river_75m.tif"

def get_all_clip(coord):
    clip_dem = get_clip_dem(coord)
    clip_K = get_clip_K(coord)
    clip_gum = get_clip_gum(coord)
    clip_bd = clip_bedrock_depth(coord)
    lay_topo = clip_dem
    lay_wt = clip_bd
    lay_ft = np.ones((clip_dem.shape[0], clip_dem.shape[1])) * 50  # lay_wt/0.4
    b = np.max(lay_ft)
    lay_kb = np.ones((clip_dem.shape[0], clip_dem.shape[1])) * np.nanmin(clip_K)
    lay_kf = lay_kb * 1000
    lay_kw = clip_K
    for i in range(0, lay_kw.shape[0]):
        for j in range(0, lay_kw.shape[1]):
            if clip_gum[i, j] == 1:
                lay_kw[i, j] = 2 * lay_kf[i, j]
    return dem_geot, clip_dem_x, clip_dem_y, lay_topo, lay_wt, lay_ft, lay_kb, lay_kf, lay_kw, clip_sea_earth, clip_river

def get_clip_dem(coord):
    #r_dem = "H:/Users/gauvain/DEM/data/MNT_TOPO_BATH_75m.tif"
    r_dem = os.path.dirname(os.path.abspath(__file__)) + "/data/MNT_TOPO_BATH_75m.tif"
    print(r_dem)
    ulY, lrY, ulX, lrX, clip_dem_x, clip_dem_y = get_model_size(coord)
    dem = gdal.Open(r_dem)
    dem_geot = dem.GetGeoTransform()
    dem_data = dem.GetRasterBand(1).ReadAsArray()
    clip_dem = dem_data[ulY:lrY, ulX:lrX]
    return dem_geot, clip_dem_x, clip_dem_y, clip_dem

def save_clip_lidar(site_number):
    forestcover = os.path.dirname(os.path.abspath(__file__)) + "/data/Lidar1m.tif"
    sites = pd.read_table(os.path.dirname(os.path.abspath(__file__)) + "/data/study_sites.txt", sep='\s+', header=0, index_col=0)
    coord = sites._get_values[site_number, 1:5]
    save_clip_dem(site_number)
    site_name = sites.axes[0][site_number]
    clip = site_name+ '/' + site_name + '_MNT.tif'
    # output files
    cutline = site_name + '/cutline.shp'
    result = site_name+'/'+ site_name+ '_lidar1m.tif'
    # create the cutline polygon
    cutline_cmd = ["gdaltindex", cutline, clip]
    subprocess.check_call(cutline_cmd)
    # crop forestcover to cutline
    # Note: leave out the -crop_to_cutline option to clip by a regular bounding box
    warp_cmd = ["gdalwarp", "-of", "GTiff", "-cutline", cutline,"-crop_to_cutline", forestcover, result]
    subprocess.check_call(warp_cmd)

def save_clip_mnt5m(site_number):
    forestcover = os.path.dirname(os.path.abspath(__file__)) + "/data/MNT5m.tif"
    sites = pd.read_table(os.path.dirname(os.path.abspath(__file__)) + "/data/study_sites.txt", sep='\s+', header=0, index_col=0)
    coord = sites._get_values[site_number, 1:5]
    save_clip_dem(site_number)
    site_name = sites.axes[0][site_number]
    clip = site_name+'/'+site_name+'_MNT.tif'
    # output files
    cutline = site_name+'/cutline.shp'
    result = site_name+'/'+site_name+'_mnt5m.tif'
    # create the cutline polygon
    cutline_cmd = ["gdaltindex", cutline, clip]
    subprocess.check_call(cutline_cmd)
    # crop forestcover to cutline
    # Note: leave out the -crop_to_cutline option to clip by a regular bounding box
    warp_cmd = ["gdalwarp", "-of", "GTiff", "-cutline", cutline,"-crop_to_cutline", forestcover, result]
    subprocess.check_call(warp_cmd)

def save_clip_dem(site_number):
    sites = pd.read_csv(os.path.dirname(os.path.abspath(__file__)) + "/data/study_sites.txt", sep=',', header=0, index_col=0)
    coord = sites._get_values[site_number, 1:5]
    print(coord)
    geot, geotx, geoty, demData = get_clip_dem(coord)
    #print("geo", geot, geotx, geoty, demData)
    drv = gdal.GetDriverByName("GTiff")
    #os.makedirs(os.path.dirname(os.path.abspath(__file__)) + "/data/Masks/")
    ds = drv.Create(os.path.dirname(os.path.abspath(__file__)) + "/data/MNTs/"  + str(site_number) + '_MNT.tif',
                    demData.shape[1], demData.shape[0], 1, gdal.GDT_Float32) #+ sites.index._data[site_number] + '/'
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2154)
    ds.SetProjection(srs.ExportToWkt())
    gt = [geotx[0], geot[1], 0, geoty[1], 0, geot[5]]
    ds.SetGeoTransform(gt)
    ds.GetRasterBand(1).WriteArray(demData)

def get_clip_sea_earth(coord):
    sea_earth = gdal.Open(r_sea_earth)
    ulY, lrY, ulX, lrX, clip_dem_x, clip_dem_y = get_model_size(coord)
    sea_earth_data = sea_earth.GetRasterBand(1).ReadAsArray()
    clip_sea_earth = sea_earth_data[ulY:lrY, ulX:lrX]
    return clip_sea_earth

def get_clip_K(coord):
    r_k = os.path.dirname(os.path.abspath(__file__)) + "/data/GLHYMPS.tif"
    ulY, lrY, ulX, lrX = get_model_size(coord)
    k = gdal.Open(r_k)
    k_data = k.GetRasterBand(1).ReadAsArray()
    clip_K = k_data[ulY:lrY, ulX:lrX]
    clip_K[clip_K == 0] = -999998
    clip_K[clip_K == -999998] = np.max(clip_K)
    clip_K = 10 ** (clip_K / 100) * 1e+7
    return clip_K

def get_clip_gum(coord):
    r_gum = os.path.dirname(os.path.abspath(__file__)) + "/data/GUM.tif"
    ulY, lrY, ulX, lrX = get_model_size(coord)
    gum = gdal.Open(r_gum)
    gum_data = gum.GetRasterBand(1).ReadAsArray()
    clip_gum = gum_data[ulY:lrY, ulX:lrX]
    clip_gum[clip_dem == -99999.0] = 3
    clip_gum[clip_gum == 0] = 2
    return clip_gum

def get_clip_bedrock_depth(coord):
    r_bedrock_depth = os.path.dirname(os.path.abspath(__file__)) + "/data/bedrock_depth.tif"
    ulY, lrY, ulX, lrX = get_model_size(coord)
    bd = gdal.Open(r_bedrock_depth)
    bd_data = bd.GetRasterBand(1).ReadAsArray()
    clip_bd = bd_data[ulY:lrY, ulX:lrX]/100
    return clip_bd


def get_model_size(coord):
    r_dem = os.path.dirname(os.path.abspath(__file__)) + "/data/MNT_TOPO_BATH_75m.tif"
    xmin = coord[0]
    xmax = coord[1]
    ymin = coord[2]
    ymax = coord[3]
    dem = gdal.Open(r_dem)
    dem_geot = dem.GetGeoTransform()
    dem_Xpos = np.ones((dem.RasterXSize))
    dem_Ypos = np.ones((dem.RasterYSize))
    for i in range(0, dem.RasterYSize):
        yp = dem_geot[3] + (dem_geot[5] * i)
        dem_Ypos[i] = yp
    for j in range(0, dem.RasterXSize):
        xp = dem_geot[0] + (dem_geot[1] * j)
        dem_Xpos[j] = xp
    ulX = (np.abs(dem_Xpos - xmin)).argmin()
    lrX = (np.abs(dem_Xpos - xmax)).argmin()
    ulY = (np.abs(dem_Ypos - ymax)).argmin()
    lrY = (np.abs(dem_Ypos - ymin)).argmin()
    clip_dem_x = dem_Xpos[ulX:lrX]
    clip_dem_y = dem_Ypos[ulY:lrY]
    return ulY, lrY, ulX, lrX, clip_dem_x, clip_dem_y

def get_geological_structure(coord):
    """
    TO DO if r_dem does not exist ! 
    """
    global clip_dem; global clip_bd; global clip_K; global clip_gum; global dem_geot; global clip_dem_x; global clip_dem_y; global clip_sea_earth; global clip_river
    r_dem = os.path.dirname(os.path.abspath(__file__)) + "/data/MNT_TOPO_BATH_75m.tif"
    r_k = os.path.dirname(os.path.abspath(__file__)) + "/data/GLHYMPS.tif"
    r_gum = os.path.dirname(os.path.abspath(__file__)) + "/data/GUM.tif"
    r_bedrock_depth = os.path.dirname(os.path.abspath(__file__)) + "/data/bedrock_depth.tif"
    r_sea_earth = os.path.dirname(os.path.abspath(__file__)) + "/data/sea_earth.tif"
    r_river = os.path.dirname(os.path.abspath(__file__)) + "/data/river_75m.tif"

    try:
        if not os.path.exists(r_dem):
            raise FileNotFoundError("Error : " +  r_dem + " was not found...") #'/'.join(os.path.realpath(__file__).split('/')[:-1])  + '/' +
    except FileNotFoundError as pe:
        print(pe)
        sys.exit(1)


    # Bréville
    xmin = coord[0]
    xmax = coord[1]
    ymin = coord[2]
    ymax = coord[3]

    # Import DEM - Permeability map - Weathered thickness map
    if os.path.exists(r_dem):
        sea_earth = gdal.Open(r_sea_earth)
        dem = gdal.Open(r_dem)
        river = gdal.Open(r_river)
        dem_geot = dem.GetGeoTransform()
        sea_earth_data = sea_earth.GetRasterBand(1).ReadAsArray()
        river_data = river.GetRasterBand(1).ReadAsArray()
        dem_data = dem.GetRasterBand(1).ReadAsArray()
        dem_Xpos = np.ones((dem.RasterXSize))
        dem_Ypos = np.ones((dem.RasterYSize))
        for i in range(0, dem.RasterYSize):
            yp = dem_geot[3] + (dem_geot[5] * i)
            dem_Ypos[i] = yp
        for j in range(0, dem.RasterXSize):
            xp = dem_geot[0] + (dem_geot[1] * j)
            dem_Xpos[j] = xp
        ulX = (np.abs(dem_Xpos - xmin)).argmin()
        lrX = (np.abs(dem_Xpos - xmax)).argmin()
        ulY = (np.abs(dem_Ypos - ymax)).argmin()
        lrY = (np.abs(dem_Ypos - ymin)).argmin()
        clip_sea_earth = sea_earth_data[ulY:lrY, ulX:lrX]
        clip_sea_earth[clip_sea_earth != 1] = 0
        clip_river = river_data[ulY:lrY, ulX:lrX]
        clip_dem = dem_data[ulY:lrY, ulX:lrX]
        clip_dem_x = dem_Xpos[ulX:lrX]
        clip_dem_y = dem_Ypos[ulY:lrY]
        clip_dem[clip_dem == 0] = np.nan
        x = np.arange(0, clip_dem.shape[1])
        y = np.arange(0, clip_dem.shape[0])
        # mask invalid values
        array = np.ma.masked_invalid(clip_dem)
        xx, yy = np.meshgrid(x, y)
        # get only the valid values
        x1 = xx[~array.mask]
        y1 = yy[~array.mask]
        newarr = array[~array.mask]
        clip_dem = interpolate.griddata((x1, y1), newarr.ravel(), (xx, yy), method='cubic')
        clip_dem =np.around(clip_dem, 2)


    if os.path.exists(r_k):
        k = gdal.Open(r_k)
        k_data = k.GetRasterBand(1).ReadAsArray()
        k_Nd = k.GetRasterBand(1).GetNoDataValue()
        # dem_data[dem_data == dem_Nd] =
        clip_K = k_data[ulY:lrY, ulX:lrX]
        clip_K[clip_K == 0] = -999998
        clip_K[clip_K == -999998] = np.max(clip_K)
        clip_K = 10**(clip_K/100)*1e+7

    if os.path.exists(r_gum):
        gum = gdal.Open(r_gum)
        gum_data = gum.GetRasterBand(1).ReadAsArray()
        gum_Nd = gum.GetRasterBand(1).GetNoDataValue()
        # dem_data[dem_data == dem_Nd] =
        clip_gum = gum_data[ulY:lrY, ulX:lrX]
        clip_gum[clip_dem == -99999.0] = 3
        clip_gum[clip_gum == 0] = 2

    if os.path.exists(r_bedrock_depth):
        bd = gdal.Open(r_bedrock_depth)
        bd_geot = bd.GetGeoTransform()
        bd_data = bd.GetRasterBand(1).ReadAsArray()
        bd_Nd = dem.GetRasterBand(1).GetNoDataValue()
        # dem_data[dem_data == dem_Nd] = 0
        delr = bd_geot[1]
        delc = abs(bd_geot[5])
        bd_Xpos = np.ones((dem.RasterXSize))
        bd_Ypos = np.ones((dem.RasterYSize))
        for i in range(0, dem.RasterYSize):
            yp = bd_geot[3] + (bd_geot[5] * i)
            bd_Ypos[i] = yp
        for j in range(0, dem.RasterXSize):
            xp = bd_geot[0] + (bd_geot[1] * j)
            bd_Xpos[j] = xp
        ulX = (np.abs(bd_Xpos - xmin)).argmin()
        lrX = (np.abs(bd_Xpos - xmax)).argmin()
        ulY = (np.abs(bd_Ypos - ymax)).argmin()
        lrY = (np.abs(bd_Ypos - ymin)).argmin()
        clip_bd = bd_data[ulY:lrY, ulX:lrX]
        clip_bd_x = bd_Xpos[ulX:lrX]
        clip_bd_y = bd_Ypos[ulY:lrY]


        bd = np.ones((clip_dem.shape[0], clip_dem.shape[1]))
        for i in range(0, bd.shape[0]):
            for j in range(0, bd.shape[1]):
                    X = (np.abs(clip_bd_x - clip_dem_x[j])).argmin()
                    Y = (np.abs(clip_bd_y - clip_dem_y[i])).argmin()
                    bd[i, j] = clip_bd[Y, X]
        clip_bd = bd

        clip_bd[clip_dem == -99999] = 0
        clip_bd[clip_bd == -99999] = 0

    lay_topo = clip_dem
    lay_wt = clip_bd/100
    lay_ft = np.ones((clip_dem.shape[0],clip_dem.shape[1]))*50 #lay_wt/0.4
    b = np.max(lay_ft)
    lay_kb = np.ones((clip_dem.shape[0],clip_dem.shape[1]))*np.nanmin(clip_K)
    lay_kf = lay_kb*1000
    lay_kw = clip_K
    for i in range (0,lay_kw.shape[0]):
        for j in range (0, lay_kw.shape[1]):
            if clip_gum[i,j] == 1:
                lay_kw[i,j] = 2*lay_kf[i,j]

    #clip_dem[clip_dem == -99999] = 0

    return dem_geot, clip_dem_x,clip_dem_y,lay_topo, lay_wt, lay_ft, lay_kb, lay_kf, lay_kw, clip_sea_earth, clip_river



#ibndDs = gdal.GetDriverByName('GTiff').Create('ibound.tif',demDs.RasterXSize, demDs.RasterYSize, 1, gdal.GDT_Int32)
#ibndDs.SetProjection(demDs.GetProjection())
#ibndDs.SetGeoTransform(geot)






