# coding:utf-8
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""
#%% LIBRAIRIES

import geopandas as gpd
import pandas as pd
import os
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
from hydromodpy.tools import get_logger

logger = get_logger(__name__)

# df = dirname(dirname(abspath(__file__)))
# sys.path.append(df)

#%% CLASS

class Driasclimat:

    #%% INIT

    def __init__(self, out_path, driasclimat_path, watershed_shp, list_models='all', list_vars='all'):
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

        list_vars = ['prtotAdjust',
                     'prsnAdjust',
                     'tasAdjust',
                     'tasmaxAdjust',
                     'tasminAdjust',
                     'hussAdjust',
                     'sfcWindAdjust',
                     'rldsAdjust',
                     'rsdsAdjust',
                     'evspsblpotAdjust', # # 'FAO' at the end
                     'evspsblpotAdjust'] # 'Hg0175' at the end

        prtot : précipitations totale |kg/m2/s]
        prsn : chute de neige à grande échelle |kg/m2/s]
        tas : température moyenne journalière à 2m [K]
        tas-max : température maximale journalière à 2m [K]
        tas-min : température minimale journalière à 2m [K]
        huss : humidité spécifique à 2m [kg/kg]
        sfc-Wind : vitesse du vent en surface [m/s]
        rlds : rayonnement infrarouge incident à la surface [W/m2]
        rsds : rayonnement visible incident à la surface [W/m2]
        etpFAO : evapotranspiration potentielle calculée par la méthode FAO [kg.m-2.s-1]
        etpHg : evapotranspiration potentielle calculée par la méthode Hargreaves [kg.m-2.s-1]

        Returns
        -------
        None.

        """

        data_folder = os.path.join(out_path, 'results_stable/driasclimat')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)

        logger.info('Extracting Drias climat datasets from %s', driasclimat_path)

        df = pd.DataFrame()
        df.index = pd.date_range(start="1950-01-01",end="2100-12-31")


        if list_models == ['all']:
            list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
                           'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']

        if list_vars == ['all']:
            list_vars = ['prtotAdjust',
                         'prsnAdjust',
                         'tasAdjust',
                         'tasmaxAdjust',
                         'tasminAdjust',
                         'hussAdjust',
                         'sfcWindAdjust',
                         'rldsAdjust',
                         'rsdsAdjust',
                         'FAO', # # 'FAO' at the end
                         'Hg0175']

        logger.info('Selected climate models: %s', ', '.join(list_models))
        logger.info('Selected variables: %s', ', '.join(list_vars))

        for model in list_models:
            models_path = glob.glob(os.path.join(driasclimat_path, model + '*'))
            # print(os.path.join(driasclimat_path, model))
            # print(models_path)
            for model in models_path:
                logger.debug('Processing model path %s', model)
                for var in list_vars: # ['DRAINC','RUNOFF','EVAPC']
                    files_path = glob.glob(model + '/' + var + '*' + '.nc') # 'QGIS.nc'
                    if (var == 'FAO'):
                        files_path = glob.glob(model + '/' + '*' + var + '.nc') # 'QGIS.nc'
                    if (var == 'Hg0175'):
                        files_path = glob.glob(model + '/' + '*' + var + '.nc') # 'QGIS.nc'
                    # print(files_path)
                    for en, file_path in enumerate(files_path):
                        if not os.path.exists(os.path.join(data_folder, file_path.split('\\')[-1])):
                            logger.debug('Clipping dataset %s', file_path)
                            self.clip_netcdf(data_folder, file_path, watershed_shp, var)
                    # except:
                    #     print('NOT FOUND : '+model+'  -  '+var)
                    #     pass

        # self.extract_values(data_folder, df)

    #%% TIME FUNCTION

    def select_period(df, first, last):
        df = df[(df.index.year>=first) & (df.index.year<=last)]
        return df

    #%% CLIP DATA

    def clip_netcdf(self, data_folder, path_qgis, shp_path, var):

        with xr.open_dataset(path_qgis, decode_coords = 'all') as ds:
            ds.load()
        # ds.sel(x = 76000, y = 2273000)

        try:
            # Comme les latitudes sont fausses, il vaut mieux les supprimer :
            ds = ds.drop_vars('lon')
            ds = ds.drop_vars('lat')
        except:
            pass
        try:
            # Créer les coordonnées 'x' et 'y' à partir de i et j
            ds = ds.assign_coords(
                x = ('i', 52000 + ds.i.values*8000))
            ds = ds.assign_coords(
                y = ('j', 1609000 + ds.j.values*8000))
        except:
            pass
        try:
            # Remplacer i et j par x et y comme coordonnées
            ds = ds.swap_dims(i = 'x', j = 'y')
        except:
            pass
        try:
            # Ajouter les attributs standards
            ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                                'long_name': 'x coordinate of projection',
                                'units': 'Meter'}
            ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                                'long_name': 'y coordinate of projection',
                                'units': 'Meter'}
        except:
            pass
        try:
            ds.rio.write_crs("epsg:27572", inplace = True)
        except:
            pass

        geodf = gpd.read_file(shp_path)
        geom = geodf.geometry.apply(mapping)
        # try :
        clipped_ds = ds.rio.clip(geom, geodf.crs, all_touched = True, drop = True)
        # except :
        #     pass
        # clipped_ds = ds.clip(geom, geodf.crs, all_touched = True, drop = True)
        # ds.rio.write_crs("epsg:2154", inplace = True)

        del ds

        outfile_path = os.path.join(data_folder, path_qgis.split('\\')[-1])

        try:
            # if (var == 'tasAdjust') | (var == 'prtotAdjust') :
            clipped_ds.lat.attrs['missing_value'] = np.nan
            clipped_ds.lon.attrs['missing_value'] = np.nan
            # del clipped_ds.lat.attrs['_FillValue']
            clipped_ds['lat'] = clipped_ds['lat'].where(pd.notnull(clipped_ds['lat']), -9999).astype('int32')
            clipped_ds['lon'] = clipped_ds['lon'].where(pd.notnull(clipped_ds['lon']), -9999).astype('int32')
            # del clipped_ds.lon.attrs['_FillValue']
        except:
            pass

        clipped_ds.to_netcdf(outfile_path)

        del clipped_ds

        gc.collect()

    #%% CSV DATA

def driasclimat_extract_values(data_folder, list_of_paths, df):

    # paths_netcdf = glob.glob(os.path.join(data_folder, '*.nc'))

    for idx, path_netcdf in enumerate(list_of_paths):

        logger.info('Processing Drias NetCDF %d/%d', idx + 1, len(list_of_paths))

        var_init = path_netcdf.split('\\')[-1].split('_')[0]

        var_raw = None
        if var_init == 'evspsblpotAdjust':
            var_raw = path_netcdf.split('\\')[-1].split('_')[-1].split('.nc')[0]
            # print(var_raw)

        # list_vars = ['prtotAdjust',
        #              'prsnAdjust',
        #              'tasAdjust',
        #              'tasmaxAdjust',
        #              'tasminAdjust',
        #              'hussAdjust',
        #              'sfcWindAdjust',
        #              'rldsAdjust',
        #              'rsdsAdjust',
        #              'evspsblpotAdjust', # # 'FAO' at the end
        #              'evspsblpotAdjust'] # 'Hg0175' at the end

        # prtot : précipitations totale |kg/m2/s]
        # prsn : chute de neige à grande échelle |kg/m2/s] or mm/day
        # tas : température moyenne journalière à 2m [K]
        # tas-max : température maximale journalière à 2m [K]
        # tas-min : température minimale journalière à 2m [K]
        # huss : humidité spécifique à 2m [kg/kg]
        # sfc-Wind : vitesse du vent en surface [m/s]
        # rlds : rayonnement infrarouge incident à la surface [W/m2]
        # rsds : rayonnement visible incident à la surface [W/m2]
        # etpFAO : evapotranspiration potentielle calculée par la méthode FAO [kg.m-2.s-1]
        # etpHg : evapotranspiration potentielle calculée par la méthode Hargreaves [kg.m-2.s-1]

        if var_init == 'prtotAdjust':
            var = 'PPTT'
        if var_init == 'prsnAdjust':
            var = 'SNOW'
        if var_init == 'tasAdjust':
            var = 'TASM'
        if var_init == 'tasmaxAdjust':
            var = 'TASX'
        if var_init == 'tasminAdjust':
            var = 'TASN'
        if var_init == 'hussAdjust':
            var = 'HUSS'
        if var_init == 'sfcWindAdjust':
            var = 'WIND'
        if var_init == 'rlds':
            var = 'RAYI'
        if var_init == 'rsds':
            var = 'RAYV'
        if var_raw == 'FAO':
            var = 'ETPF'
        if var_raw == 'Hg0175':
            var = 'ETPH'

        sce = path_netcdf.split('\\')[-1].split('_')[3]
        gcm_raw = path_netcdf.split('\\')[-1].split('_')[2]
        rcm_raw = path_netcdf.split('\\')[-1].split('_')[5]

        if (sce == 'historical'):
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
        logger.debug('Aggregating column %s', name_col)
        if name_col not in df:
            df[name_col] = ""

        dates = clipped_ds.time.data
        dates = pd.Series(dates)

        try:
            var_ds = clipped_ds[var_init]
            x_mean = np.nanmean(var_ds.mean(dim='x').values, axis=1)
            y_mean = np.nanmean(var_ds.mean(dim='y').values, axis=1)
            serie = pd.Series(( x_mean + y_mean ) / 2 )
            serie.index = dates

            # if (var == 'PPTT') :
            #     serie = serie * 3600 * 24 # kg/m2/s to mm per day
            # if (var == 'SNOW') :
            #     serie = serie * 3600 * 24
            if (var == 'TASM') :
                serie = serie - 273.15
            if (var == 'TASX') :
                serie = serie - 273.15
            if (var == 'TASN') :
                serie = serie - 273.15
            # if (var == 'ETPF') :
            #     serie = serie * 3600 * 24
            # if (var == 'ETPH') :
            #     serie = serie * 3600 * 24

            df[name_col] = serie

        except:
            df[name_col] = np.nan
            pass

    df.to_csv(data_folder+'/'+'_ALL_D.csv', sep=';')
    # df.to_csv('C:/Users/ronan/OneDrive/_HydroDataPy/CLIMATE/France/DRIAS/Bretagne/results_stable/drias/'+
    #           '_ALL_D.csv', sep=';')

#%% NOTES
