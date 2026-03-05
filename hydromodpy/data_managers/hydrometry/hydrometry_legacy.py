# -*- coding: utf-8 -*-
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

# Python
import os
import datetime
import pandas as pd
import geopandas as gpd
import whitebox
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

logger = get_logger(__name__)

#%% CLASS

class Hydrometry:
    """
    Add hydrometry data in the watershed object.
    """
    
    def __init__(self, out_path: str, hydrometry_path: str, file_name: str, geographic: object):
        """
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs.
        hydrometry_path : str
            Path of the folder with the hydrometry data.
        file_name : str
            Shapefile name of hydrometric station.
            Function for a specific vector at the France scale.
        geographic : object
            Variable object of the model domain (watershed).
        """
        
        logger.info('Extracting hydrometry data from %s', hydrometry_path)
        
        data_folder = os.path.join(out_path,'results_stable','hydrometry')
        if not os.path.exists(data_folder):
                os.makedirs(data_folder)
        self.fig_hydromet = os.path.join(out_path,'results_stable','_figures','hydrometry')
        if not os.path.exists(self.fig_hydromet):
                os.makedirs(self.fig_hydromet)
        self.code_bh = []
        self.label = []
        self.x_coord = []
        self.y_coord = []
        self.date_inst = []
        self.date_ferm = []
        try:
            self.extract_hydrometry_from_watershed(data_folder, hydrometry_path, file_name, geographic)
        except:
            pass
        try:
            self.download_data_from_code_bh(data_folder)
            self.load_hydrometric_data(data_folder)
        except:
            pass
    
    def extract_hydrometry_from_watershed(self, data_folder, hydrometry_path, file_name, geographic):
        """
        Clip hydrometric stations at the watershed scale (model domain).
        
        Parameters
        ----------
        data_folder : str
            Path of stable results for hydrometry.
        """
        hydrometric_data = os.path.join(hydrometry_path, file_name)
        self.hydrometric_clip = os.path.join(data_folder, file_name)
        wbt.clip(hydrometric_data, geographic.watershed_shp, self.hydrometric_clip)
        # try:
        hydromet_bv = gpd.read_file(self.hydrometric_clip)
        hydromet_bv = hydromet_bv.copy()
        self.label = hydromet_bv['LbStationH'].to_list()
        self.x_coord = hydromet_bv['CoordXStat'].tolist()
        self.y_coord = hydromet_bv['CoordYStat'].to_list()
        hydromet_bv['CdStationH'] = hydromet_bv['CdStationH'].apply(
            lambda value: value[0:8] if pd.notnull(value) else None
        )
        hydromet_bv['timePositi'] = hydromet_bv['timePositi'].apply(
            lambda value: value[0:10] if pd.notnull(value) else None
        )
        today_str = datetime.datetime.today().strftime('%Y-%m-%d')
        hydromet_bv['DtFermetur'] = hydromet_bv['DtFermetur'].apply(
            lambda value: today_str if pd.isna(value) else value[0:10]
        )
        # self.date_inst = pd.to_datetime(hydromet_bv['timePositi'][0:10], format='%Y-%m-%d').to_list()
        # self.date_ferm = pd.to_datetime(hydromet_bv['DtFermetur'][0:10], format='%Y-%m-%d').to_list()            
        self.code_bh = hydromet_bv['CdStationH'].to_list()
        self.date_inst = hydromet_bv['timePositi'].to_list()
        self.date_ferm = hydromet_bv['DtFermetur'].to_list()
       
#%% NOTES
