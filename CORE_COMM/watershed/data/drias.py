# coding:utf-8
"""

"""

#%% LIBRAIRIES

import geopandas as gpd
import pandas as pd
import os 
import sys
from os.path import dirname, abspath
import glob
import xarray as xr
from shapely.geometry import mapping
import numpy as np
xr.set_options(keep_attrs = True)
try:
    import rioxarray as rio
except:
    pass
import rasterio
import matplotlib.pyplot as plt
import gc

# df = dirname(dirname(abspath(__file__)))
# sys.path.append(df)

#%% CLASS

class Drias:
    
    #%% INIT
    
    def __init__(self, out_path, drias_path, watershed_shp, list_models='all', list_vars = 'all'):
        """

        Parameters
        ----------
        out_path : TYPE
            DESCRIPTION.
        explore2_path : TYPE
            DESCRIPTION.
        watershed_shp : TYPE
            DESCRIPTION.
        
        list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
                       'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
        
        list_vars = ['DRAINC','RUNOFF','EVAPC','tasAdjust','prtotAdjust']
        
        Returns
        -------
        None.

        """
        
        data_folder = os.path.join(out_path, 'results_stable/drias')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
                
        print('Extraction des données explore2')
        
        df = pd.DataFrame()
        df.index = pd.date_range(start="1951-01-01",end="2099-12-31")
        

        if list_models == 'all':
            list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
                           'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
        
        if list_vars == 'all':
            list_vars = ['DRAINC','RUNOFF','EVAPC','tasAdjust','prtotAdjust']
            
        print(list_models)
        print(list_vars)
        
        for model in list_models:
            models_path = glob.glob(os.path.join(drias_path, model +'*'))
            
            for model in models_path:
                print('     '+model)
                                
                for var in list_vars: # ['DRAINC','RUNOFF','EVAPC']
                    files_path = glob.glob(model + '/' + var + '*' + '.nc') # 'QGIS.nc'
                    for en, file_path in enumerate(files_path):
                        if not os.path.exists(os.path.join(data_folder, file_path.split('\\')[-1])):
                            self.clip_netcdf(data_folder, file_path, watershed_shp, var)
    
        self.extract_values(data_folder, df)
    
    #%% TIME FUNCTION
    
    def select_period(df, first, last):
        df = df[(df.index.year>=first) & (df.index.year<=last)]
        return df
    
    #%% CLIP DATA
    
    def clip_netcdf(self, data_folder, path_qgis, shp_path, var):
        
        with xr.open_dataset(path_qgis, decode_coords = 'all') as ds:
            ds.load()
        # ds.sel(x = 76000, y = 2273000)
   
        geodf = gpd.read_file(shp_path)
        geom = geodf.geometry.apply(mapping)
        try :
            clipped_ds = ds.rio.clip(geom, geodf.crs, all_touched = True, drop = True)
        except :
            pass
        clipped_ds = ds.clip(geom, geodf.crs, all_touched = True, drop = True)
        # ds.rio.write_crs("epsg:2154", inplace = True)
        
        del ds
                
        outfile_path = os.path.join(data_folder, path_qgis.split('\\')[-1])
        
        if (var == 'tasAdjust') | (var == 'prtotAdjust') :
            clipped_ds.lat.attrs['missing_value'] = np.nan
            clipped_ds.lon.attrs['missing_value'] = np.nan
            # del clipped_ds.lat.attrs['_FillValue']
            clipped_ds['lat'] = clipped_ds['lat'].where(pd.notnull(clipped_ds['lat']), -9999).astype('int32')
            clipped_ds['lon'] = clipped_ds['lon'].where(pd.notnull(clipped_ds['lon']), -9999).astype('int32')
            # del clipped_ds.lon.attrs['_FillValue']
        
        clipped_ds.to_netcdf(outfile_path)
        
        del clipped_ds
        
        gc.collect()
    
    #%% CSV DATA
    
    def extract_values(self, data_folder, df):
        
        paths_netcdf = glob.glob(os.path.join(data_folder, '*.nc'))
        
        for idx, path_netcdf in enumerate(paths_netcdf):
            
            print(str(idx+1)+'/'+str(len(paths_netcdf)))
            
            var_raw = path_netcdf.split('\\')[-1].split('_')[0]
            
            if var_raw =='DRAINC':
                var = 'REC'
            if var_raw =='RUNOFFC':
                var = 'RUN'
            if var_raw =='EVAPC':
                var = 'ETP'
            if var_raw == 'tasAdjust':
                var = 'TAS'
            if var_raw == 'prtotAdjust':
                var = 'PPT'
            
            if (var == 'REC') | (var == 'RUN') | (var == 'ETP'):
                sce = path_netcdf.split('\\')[-1].split('_')[-4]
                gcm_raw = path_netcdf.split('\\')[-1].split('_')[2]
                rcm_raw = path_netcdf.split('\\')[-1].split('_')[3]
                
            if (var == 'PPT') | (var == 'TAS'):
                sce = path_netcdf.split('\\')[-1].split('_')[-7]
                gcm_raw = path_netcdf.split('\\')[-1].split('_')[2]
                rcm_raw = path_netcdf.split('\\')[-1].split('_')[3]
            
            if (sce == 'Historique') | (sce == 'Historical'):
                sce = 'historic'
            else:
                sce = sce.upper()
                        
            if 'CNRM' in gcm_raw :
                gcm = 'CNR'
            if 'MPI' in gcm_raw :
                gcm = 'MPI'
            if 'MOHC' in gcm_raw :
                gcm = 'HAD'
            if 'ICHEC' in gcm_raw :
                gcm = 'ECE'
            if 'IPSL' in gcm_raw :
                gcm = 'IPS'
            if 'NCC' in gcm_raw :
                gcm = 'NOR'
                
            if 'ALADIN' in rcm_raw :
                rcm = 'ALA'
            if 'CCLM' in rcm_raw :
                rcm = 'CCL'
            if 'Reg' in rcm_raw :
                rcm = 'REG'
            if 'RCA' in rcm_raw :
                rcm = 'RCA'
            if 'WRF' in rcm_raw :
                rcm = 'WRF'
            if 'REMO2015' in rcm_raw :
                rcm = 'R15'
            if 'RACMO' in rcm_raw :
                rcm = 'RAC'
            if 'REMO2009' in rcm_raw :
                rcm = 'R09'
            if 'HIRH' in rcm_raw :
                rcm = 'HIR'
                            
            with xr.open_dataset(path_netcdf, decode_coords = 'all') as clipped_ds:
                clipped_ds.load()
                
            name_col = var+'_'+gcm+'-'+rcm+'_'+sce
            print(name_col)
            if name_col not in df:
                df[name_col] = ""
                
            dates = clipped_ds.time.data
            dates = pd.Series(dates)
            
            var_ds = clipped_ds[var_raw]
            x_mean = np.nanmean(var_ds.mean(dim='x').values, axis=1)
            y_mean = np.nanmean(var_ds.mean(dim='y').values, axis=1)
            serie = pd.Series(( x_mean + y_mean ) / 2 )
            serie.index = dates
            
            if (var == 'PPT') :
                serie = serie * 3600 * 24
                
            if (var == 'TAS') :
                serie = serie - 273.15
                
            df[name_col] = serie
            
        df.to_csv(data_folder+'/'+'_ALL_D.csv', sep=';')
        # df.to_csv('C:/Users/ronan/OneDrive/_HydroDataPy/CLIMATE/France/DRIAS/Bretagne/results_stable/drias/'+
        #           '_ALL_D.csv', sep=';')

#%% KEEP

def time_series(*, input_file, epsg = None,
                coords = None, mask = None, 
                dates = None, **kwargs): 
    """
    # % DESCRIPTION:
    # This function extracts the temporal data in one location given by 
    # coordinate.
    """  
    with xr.open_dataset(input_file) as _dataset:
        _dataset.load() # to unlock the resource
    if 'fields' in kwargs:
        fields = kwargs['fields']
        if isinstance(fields, str): fields = [fields]
        else: fields = list(fields) # in case fields are string or tuple
    else:
        fields = list(_dataset.data_vars) # if not input_arg, fields = all
    if dates is not None:
        if not isinstance(dates, tuple): fields = tuple(fields)
    if coords is not None:
        if not isinstance(coords, tuple): coords = tuple(coords)
    if 'lon' in list(_dataset.dims) or 'lat' in list(_dataset.dims):
        print('Renaming lat/lon coordinates')
        _dataset = _dataset.rename(lat = 'latitude', lon = 'longitude')
    if 'X' in list(_dataset.dims) or 'Y' in list(_dataset.dims):
        print('Renaming X/Y coordinates')
        _dataset = _dataset.rename(X = 'x', Y = 'y')
    if coords is not None:
        print('Coordinates = {} in epsg:{}'.format(str(coords), str(epsg)))
        if 'spatial_ref' in _dataset.coords or 'spatial_ref' in _dataset.data_vars:
            _data_epsg = int(_dataset.spatial_ref.crs_wkt[-7:-3]) #?? always valid??
            coords_conv = rasterio.warp.transform(rasterio.crs.CRS.from_epsg(epsg), 
                                                  rasterio.crs.CRS.from_epsg(_data_epsg), 
                                                  coords[0], coords[1])
        _dataset = _dataset[fields]
        if dates is not None:
            _dataset = _dataset.sel(time = slice(dates[0], dates[1]))
        if 'longitude' in list(_dataset.dims) or 'latitude' in list(_dataset.dims):
            results = _dataset.sel(longitude = coords_conv[0], 
                                   latitude = coords_conv[1],
                                   method = 'nearest')
        elif 'x' in list(_dataset.dims) or 'y' in list(_dataset.dims):
            results = _dataset.sel(x = coords_conv[0], 
                                   y = coords_conv[1],
                                   method = 'nearest')
    elif mask is not None:
        if mask == 'all':
            print('All cells are considered')
            results = _dataset.mean(dim = list(_dataset.dims)[-2:], 
                                    skipna = True, keep_attrs = True)
        else:
            print('Cells of the watershed')
    return results

#%% TEST

'''
list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
               'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
list_vars = ['prtotAdjust']

Drias('C:/Users/ronan/OneDrive/_HydroDataPy/CLIMATE/France/DRIAS/Bretagne/', # INPUT
      'G:/DRIAS/georeferenced/', # OUTPUT
      'C:/Users/ronan/OneDrive/_HydroDataPy/MISCELLANEOUS/France/bzh.shp', # CLIP
      list_models,
      list_vars)
'''

#%% NOTES

'''

path_qgis = 'G:/DRIAS/georeferenced/Model_01/DRAINC_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_METEO-FRANCE_ADAMONT-France_SAFRAN_MF-SIM2_Historique_day_19500801-20050731_QGIS.nc'
# path_qgis = 'G:/DRIAS/georeferenced/Model_01/tasAdjust_France_MPI-M-MPI-ESM-LR_CLMcom-CCLM4-8-17_Historical_METEO-FRANCE_ADAMONT-France_SAFRAN_day_1950-2005_QGIS.nc'
shp_path = 'C:/Users/ronan/OneDrive/_HydroDataPy/MISCELLANEOUS/France/bzh.shp'

with xr.open_dataset(path_qgis, decode_coords = 'all') as ds:
    ds.load()
# ds.sel(x = 76000, y = 2273000)

# val = ds.DRAINC.values[0]
# val = val[::-1]

geodf = gpd.read_file(shp_path)
geom = geodf.geometry.apply(mapping)
clipped_ds = ds.rio.clip(geom, geodf.crs, all_touched = True, drop = True)

clip_drain = clipped_ds.copy()

# geotif = './watershed.tif'
# with xr.open_dataset(geotif) as mask_ds:
#     mask_ds.load()
# clipped_ds = ds.where(mask_ds, drop = True)

### Treatment data
# leng = clipped_ds.DRAINC.shape[0]
# for i in range(leng):
#     print(str(i)+'/'+str(leng))
#     val = clipped_ds.DRAINC.values[i]
#     val = val[::-1]
#     val = val[:,~np.all(np.isnan(val), axis=0)]
#     try:
#         val = val[:,~np.all(np.isnan(val), axis=1)]
#     except:
#         pass
#     mean = np.nanmean(val)
#     mean = float(clipped_ds['DRAINC'][i].mean().values)

# res = var_ds.mean(dim = 'time', skipna = True, keep_attrs = True)

'''

