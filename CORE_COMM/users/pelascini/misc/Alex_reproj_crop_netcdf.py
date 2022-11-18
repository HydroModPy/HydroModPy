# -*- coding: utf-8 -*-
"""
Created on Fri Jul  8 10:37:20 2022

@author: Lucas
"""
    #%% Alex Coche helps
    #%% packages already called in main code
    import geopandas as gpd
    import rasterio
    import numpy
    
    
    #%% calling packages
    import xarray as xr
    from shapely.geometry import mapping
    xr.set_options(keep_attrs = True)
    from affine import Affine
        
    #%% load netcdf & create its georef
    with xr.open_dataset(r"C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\20090801-20090815_var.nc", decode_coords = 'all') as ds:
        ds.load() #load as dataset
    ds.rio.write_crs('epsg:4326',inplace = True) # coordinates ref system of the input file (lat/lon)
    
    #%% create a georef for the zone to reproject the netcdf to
    
    x_res = 30 # resolution of the otput file
    x_min = 260000 # 274000 # 280000 # x-coordinate of the top left corner (coordinates of the output file)
    y_res = 30 # resolution of the otput file
    y_max = 2516000 # 2574000 # 2583000 # y-coordinate of the top left corner
    height_ = 1000 # number of y cells (from y_max to y_min)
    width_ = 1000 # number of x cells (from x_min to x_max)
    
    transform_ = Affine(x_res, 0.0 , x_min,
                  0.0, -y_res, y_max) # transform matrix


    #%% reproject netcdf
    ds_reproj = ds.rio.reproject(dst_crs = 'epsg:32651',
        transform = transform_,
        resampling = rasterio.enums.Resampling(5),# interpolation method (5="average")
        shape = (height_, width_)  )
    
    ds_reproj.to_netcdf(r'C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\20090801-20090815_reproj_4.nc') # save to netcdf
    
    #%% crop netcdf to shapefile
    mask_df = gpd.read_file(r"C:\Users\Lucas\Desktop\HYDROMODPY\Taiwan\Morakot3\results_stable\geographic\watershed.shp") #load as geodataframe
    clipped_ds = ds_reproj.rio.clip(mask_df.geometry.apply(mapping), mask_df.crs, all_touched = True)
    clipped_ds.to_netcdf(r'C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\20090801-20090815_clipped_4.nc')

    #%% create csv file of recharge and runoff + drainage
    mean_rech=clipped_ds.QCHARGE.mean(dim=['x','y'])
    mean_rech[mean_rech<0] = 0 # no negative rechage
    
    numpy.savetxt(r"C:\Users\Lucas\Desktop\blablabla_4.csv", mean_rech, delimiter=" ")
    
    
    
    sum_drai=clipped_ds.QDRAI.sum(dim=['x','y'])
    sum_runoff=clipped_ds.QOVER.sum(dim=['x','y'])
    
    
    
    
    
    