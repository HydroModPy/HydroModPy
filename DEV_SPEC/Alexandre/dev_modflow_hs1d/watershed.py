# coding:utf-8

import os
import geopandas as gpd
from osgeo import gdal, osr
from shutil import copyfile
import numpy as np
import deepdish as dd
from IPython.core.debugger import set_trace as st
import geographic
import geology
import hydrology
import climatic
import oceanic
import piezometry
import modflow
import pickle

class build:
    """
    explication fonction
    entrée
    sortie
    """
    def __init__(self, watershed_name, dem_path, x_outlet, y_outlet, snap_dist=150, 
        buff_dist=1000, out_path=os.path.dirname(os.path.dirname(__file__))+'\\output\\', 
        surfex_path = None, oceanic_path = None, geology_path = None, 
        hydrology_path = None, modflow_path = None, load = False):

        self.name = watershed_name
        self.dem_path = dem_path
        self.x_outlet = x_outlet
        self.y_outlet = y_outlet
        self.snap_dist = snap_dist
        self.buff_dist = buff_dist
        self.out_path = out_path
        self.surfex_path = surfex_path
        self.hydrology_path = hydrology_path
        self.oceanic_path = oceanic_path
        self.geology_path = geology_path
        self.modflow_path = modflow_path
        self.watershed_folder = out_path + '/' + watershed_name + '/'
        self.create_folder(self.watershed_folder)
        self.add_data_folder = self.watershed_folder + '/data/add_data/'
        self.create_folder(self.add_data_folder)
        self.modeling_data_folder = self.watershed_folder + '/modeling_data/'
        f = open(self.modeling_data_folder + 'params_to_calibrate.csv', 'w')
        f.write('k,theta,e')
        f.close
        self.create_folder(self.modeling_data_folder)
        self.modflow_models = []

        if load==True:
            self.load_object()
        else:
            self.create_object()

    def load_object(self):
        with open(self.watershed_folder + 'python_object', 'rb') as config_dictionary_file:
            BV = pickle.load(config_dictionary_file)
        if ('geographic' in BV.__dir__()) == True:
            self.geographic = BV.geographic
        if ('climatic' in BV.__dir__()) == True:
            self.climatic = BV.climatic
        if ('hydrology' in BV.__dir__()) == True:
            self.hydrology = BV.hydrology
        if ('piezometry' in BV.__dir__()) == True:
            self.piezometry = BV.piezometry
        if ('geology' in BV.__dir__()) == True:
            self.geology = BV.geology
        if ('oceanic' in BV.__dir__()) == True:
            self.oceanic = BV.oceanic
        if ('modflow_models' in BV.__dir__()) == True:
            self.modflow_models = BV.modflow_models
        if ('stream_het_calibration' in BV.__dir__()) == True:
            self.stream_het_calibration = BV.stream_het_calibration



    def create_object(self):
        #STURCUTRE DATA
        self.geographic = geographic.extract(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet, snap_dist=self.snap_dist, buff_dist=self.buff_dist,
                 out_path=self.watershed_folder) #2D
        #self.hillslope = hillslope() #1D
        if self.hydrology_path != None:
            self.hydrology = hydrology.extract(out_path=self.watershed_folder,type_obs='streams', geographic=self.geographic, hydro_path=self.hydrology_path)

        if self.geology_path != None:
            self.geology =  geology.extract(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path)

        #MODELING DATA
        if self.oceanic_path != None:
            self.oceanic = oceanic.extract(out_path=self.watershed_folder,oceanic_path=self.oceanic_path,geographic=self.geographic)
        
        if self.surfex_path != None:
            self.climatic = climatic.extract(out_path=self.watershed_folder,surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
            
        #FIELD DATA
        self.piezometry = piezometry.extract(out_path=self.watershed_folder,geographic=self.geographic)
        #self.hydrometry = hydrometry() #doesn't exist
        #self.geochemistry = geochemistry() #doesn't exist

    def save_object(self):
        with open(self.watershed_folder + 'python_object', 'wb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()

    def add_piezometry_data(self):
        self.piezometry.add_data(self.add_data_folder, self.geographic)
        return self

    def run_modflow(self,name,climatic=8e-4, lay_number=1, thick=100, bottom=None, thick_exp=1., 
        hyd_cond=8.64e-2, porosity=0.01, sea_level = None, cond_decay=0.):
        '''if type(sea_level) != type(climatic):
            print('sea_level and climatic chronicles must be the same length')
        else:'''
        modflow.run_model(self.geographic, watershed='sim_modflow', 
            climatic=climatic, lay_number=lay_number, thick=thick, bottom=bottom, thick_exp=thick_exp, 
            hyd_cond=hyd_cond, porosity=porosity, sea_level = sea_level, cond_decay=cond_decay,
            time_step='daily', model_name=name, model_folder= self.watershed_folder , 
            exe= self.modflow_path +'/bin/mfnwt.exe')

        self.modflow_models[name]= modflow.extract_model(self.geographic, 
            watershed='sim_modflow', model_name=name, model_folder=self.watershed_folder,
            param=True, watertable=True, seepage=True, gwflux=True, outflow=True, spedisch=True)
        return self

    def load_modflow_model(self, name):
        self.modflow_models = {}
        modflow_folder = self.watershed_folder + '/sim_modflow/'
        return self

    
    def run_calibration(self,geographic, geology, climatic=[8e-4], type_obs='streams',
        type_mod='het', first=1, last=10000, gap=100, compt=0, watershed='name', 
        lay_number=1, thick=100, porosity=0.01, sea_level=None):
        '''
        obs_type = 'streams', 'piezos', 'ages'...
        mod_type = 'het'
        '''
        if type_obs == 'streams' and type_mod == 'het':
            self.stream_het_calibration = calibration.run_stream_het_calibration(geographic, geology, climatic,
                folder=self.watershed_folder, 
                first=first, last=last, gap=gap, sea_level=sea_level,
                lay_number=1, thick=thick, porosity=0.01, type_obs='streams', 
                type_time='s', exe= self.modflow_path +'/bin/mfnwt.exe')
        return self

    def create_folder(self,path):
        if not os.path.exists(path):
            os.makedirs(path)
        return self

    def run_hs1D(self):
        return self

