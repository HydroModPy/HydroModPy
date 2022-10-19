# -*- coding: utf-8 -*-
"""
Created on Fri Jul  8 10:37:20 2022

@author: Lucas
"""
    #%% packages already called in main code
    import geopandas as gpd
    import rasterio
    import numpy
    import xarray as xr
    from shapely.geometry import mapping
    xr.set_options(keep_attrs = True)
    from affine import Affine
    
    #%% Paths and names
    # inpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    # inpt_nc_file="Aug_1980-2010.nc"
    
    # watershed_path="C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan/South3"
    
    # outpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    # outpt_nc_file="Aug_1980-2010_S1.nc"
    
    # inpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    # inpt_nc_file="MON_1980-2010.nc"
    
    # watershed_path="C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan/Morakot1"
    
    # outpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    # outpt_nc_file="MON_1980-2010_clipped_1.nc"
    
    
    
    inpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    inpt_nc_file="20090801-20090815_var.nc"
    
    watershed_path="C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan/South3"
    
    outpt_nc_path="C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/"
    outpt_nc_file="20090801-20090815_clipped_4.nc"
    #%% load netcdf & create its georef
    with xr.open_dataset( inpt_nc_path + inpt_nc_file , decode_coords = 'all') as ds:
        ds.load() #load as dataset
    ds.rio.write_crs('epsg:4326',inplace = True) # coordinates ref system of the input file (lat/lon)
    
    #%% create a georef for the zone to reproject the netcdf to
    
    x_res = 30 # resolution of the otput file
    x_min = 260000# 280000# 260000 # 274000 # 280000 # x-coordinate of the top left corner (coordinates of the output file)
    y_res = 30 # resolution of the otput file
    y_max = 2510000# 2583000# 2516000 # 2574000 # 2583000 # y-coordinate of the top left corner
    height_ = 1000 # number of y cells (from y_max to y_min)
    width_ = 1000 # number of x cells (from x_min to x_max)
    
    transform_ = Affine(x_res, 0.0 , x_min,
                  0.0, -y_res, y_max) # transform matrix


    #%% reproject netcdf
    ds_reproj = ds.rio.reproject(dst_crs = 'epsg:32651',
        transform = transform_,
        resampling = rasterio.enums.Resampling(5),# interpolation method (5="average")
        shape = (height_, width_)  )
    
    # ds_reproj.to_netcdf(outpt_nc_path_nc_path + "20090801-20090815_reproj_4.nc") # save to netcdf
    # ds_reproj.to_netcdf(outpt_nc_path + "MON_1980-2010_reproj_1.nc") # save to netcdf

    #%% crop netcdf to shapefile
    mask_df = gpd.read_file(watershed_path + "/results_stable/geographic/watershed.shp") #load as geodataframe
    clipped_ds = ds_reproj.rio.clip(mask_df.geometry.apply(mapping), mask_df.crs, all_touched = True)
    
    # clipped_ds.to_netcdf(outpt_nc_path + outpt_nc_file) # save to netcdf

    #%% create csv file of recharge and runoff + drainage
    mean_rech=clipped_ds.QCHARGE.mean(dim=['x','y'])
    mean_rech[mean_rech<0] = 0 # no negative rechage
    
    numpy.savetxt(watershed_path + "/results_stable/hydrology/mean_recharge_watershed.csv" , mean_rech, delimiter=" ")
    
    
    # sum_drai=clipped_ds.QDRAI.sum(dim=['x','y'])
    # numpy.savetxt("C:/Users/Lucas/Desktop/sum_qdrai_watershed1.csv" , sum_drai, delimiter=" ")
    
    # sum_runoff=clipped_ds.QOVER.sum(dim=['x','y'])
    # numpy.savetxt("C:/Users/Lucas/Desktop/sum_qover_watershed1.csv" , sum_runoff, delimiter=" ")

    
    
    
    
    