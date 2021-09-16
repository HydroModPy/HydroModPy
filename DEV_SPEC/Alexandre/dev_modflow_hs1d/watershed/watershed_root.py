# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 14:52:56 2021

@author: Alexandre Gauvain
"""

# Modules
import os
import pandas as pd
import pickle
import sys
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy modules
from data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import modflow
from tools import file_adds
from watershed import geographic, geology, hydrodynamic

class Watershed:
    """
    class Watershed is used to extract watershed and its data from regional DEM

    Attributes
    ----------
    name: str
        name of watershed
    dem_path : str
        folder of the regional DEM
    x_outlet : float
        x coordinate of the outlet of the watershed
    y_outlet : float
        y coordiante of the outlet of the watershed
    snap_dist : float
        distance of the outlet can be mooved to join the closest river
    buff_dist : float
        distance to increase the boundary of the watershed
    out_path : str
        root directory of results
    surfex_path : str
        root directory of surfex data
    hydrology_path : str
        root directory of hydrology data
    oceanic_path : str
        root directory of oceanic data
    geology_path : str
        root directory of geology data
    modflow_path : str
        root directory of modflow executable
    watershed_folder : str
        root directory of results of watershed class
    add_data_folder : str
        folder if you want add data manually
    simulations_folder : str
        root directory of simulation results
    elt_def : list
        list of elements in the python object

    Methods
    -------
    load_object(self)
        load python object if is already created
    create_object(self)
        create watershed object
    save_object(self)
        save watershed object in the watershed folder (python_object)
    run_modflow(self,name, climatic=8e-4, lay_number=1, thick=100, bottom=None,
                thick_exp=1., hyd_cond=8.64e-2, porosity=0.01, 
                sea_level = None, cond_decay=0.)
        run groundwater flow model using Modflow and Flopy
    """
    def __init__(self, watershed_name, library_path, dem_path, 
                 out_path = os.path.dirname(os.path.dirname(__file__))+'\\output\\', 
                 surfex_path = None, oceanic_path = None, geology_path = None, 
                 hydrology_path = None, modflow_path = None, load = False):
        """ 
        Constructor
        
        Arguments
        ---------
        watershed_name: str
            name of watershed
        dem_path : str
            folder of the regional DEM
        out_path : str
            root directory of results
        surfex_path : str
            root directory of surfex data
        hydrology_path : str
            root directory of hydrology data
        oceanic_path : str
            root directory of oceanic data
        geology_path : str
            root directory of geology data
        modflow_path : str
            root directory of modflow executable
        load : bool
            True to load the python object. False to create.
        """
        self.name = watershed_name
        self.library_path = library_path
        self.load_watershed_csv()

        self.dem_path = dem_path
        self.out_path = out_path
        
        self.surfex_path = surfex_path
        self.hydrology_path = hydrology_path
        self.oceanic_path = oceanic_path
        self.geology_path = geology_path
        self.modflow_path = modflow_path
        
        self.watershed_folder = os.path.join(out_path, watershed_name)
        file_adds.create_folder(self.watershed_folder)
        self.add_data_folder = os.path.join(self.watershed_folder, 'data/add_data')
        file_adds.create_folder(self.add_data_folder)
        self.simulations_folder = os.path.join(self.watershed_folder, 'simulations')
        file_adds.create_folder(self.simulations_folder)
        self.elt_def = []

        if load==True:
             succes = self.load_object()
             if succes == False:
                print("Object was not loaded as demanded but created from scratch")
                self.create_object()
        else:
            self.create_object()    

    
    def load_watershed_csv(self):
        """
        Load watershed informations from watershed.csv file
        """
        try:
            # watershed_list = pd.read_csv('../watershed.csv', delimiter=';')
            watershed_list = pd.read_csv(self.library_path, delimiter=';')
            watershed_info = watershed_list.loc[watershed_list['name'] == self.name]
            self.x_outlet = watershed_info.iloc[0]['x_outlet']
            self.y_outlet = watershed_info.iloc[0]['y_outlet']
            self.snap_dist = watershed_info.iloc[0]['snap_dist']
            self.buff_dist = watershed_info.iloc[0]['buff_dist']
        except:
            print("Warning : The name of watershed is not in the watershed list")
            sys.exit()
            return watershed_list
        
    def load_object(self):
        """
        Loads python object
        """
        if not os.path.exists(self.watershed_folder + 'python_object'):
            with open(self.watershed_folder + 'python_object', 'rb') as config_dictionary_file:
              BV = pickle.load(config_dictionary_file)
            if ('geographic' in BV.__dir__()) == True:
                self.geographic = BV.geographic
                self.elt_def.append('geographic')
            else:
                print("Warning : geographic doesn't exist in object")
                return False
            if ('climatic' in BV.__dir__()) == True:
                self.climatic = BV.climatic
                self.elt_def.append('climatic')
            if ('hydrology' in BV.__dir__()) == True:
                self.hydrology = BV.hydrology
                self.elt_def.append('hydrology')
            if ('piezometry' in BV.__dir__()) == True:
                self.piezometry = BV.piezometry
                self.elt_def.append('piezometry')
            if ('geology' in BV.__dir__()) == True:
                self.geology = BV.geology
                self.elt_def.append('geology')
            if ('oceanic' in BV.__dir__()) == True:
                self.oceanic = BV.oceanic
                self.elt_def.append('oceanic')
            return True 
        else:
            print("Warning : file doesn't exist, python_object", self.watershed_folder)
            return False


    def create_object(self):
        """
        Creates python object
        """
        #STURCUTRE DATA
        self.geographic = geographic.Geographic(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet, snap_dist=self.snap_dist, buff_dist=self.buff_dist,
                 out_path=self.watershed_folder) #2D
        self.elt_def.append('geographic')
        
        self.hydrodynamic = hydrodynamic.Hydrodynamic()
        self.elt_def.append('hydrodynamic')
        
        #self.hillslope = hillslope() #1D Doesn't exist
        
        if self.hydrology_path != None:
            self.hydrology = hydrology.Hydrology(out_path=self.watershed_folder,type_obs='streams', geographic=self.geographic, hydro_path=self.hydrology_path)
            self.elt_def.append('hydrology')

        if self.geology_path != None:
            self.geology =  geology.Geology(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path)
            self.elt_def.append('geology')

        #MODELING DATA
        if self.oceanic_path != None:
            self.oceanic = oceanic.Oceanic(out_path=self.watershed_folder,oceanic_path=self.oceanic_path,geographic=self.geographic)
            self.elt_def.append('oceanic')

        if self.surfex_path != None:
            self.climatic = climatic.Climatic(out_path=self.watershed_folder,surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
            self.elt_def.append('surfex')

        #FIELD DATA
        self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,geographic=self.geographic)
        self.elt_def.append('piezometry')
        #self.hydrometry = hydrometry() #doesn't exist
        #self.geochemistry = geochemistry() #doesn't exist

    def save_object(self):
        """
        Saves python object
        """
        with open(self.watershed_folder + 'python_object', 'wb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        

    def run_modflow(self, ident='temporary', climatic=8e-4, lay_number=1, thick=100, bottom=None, thick_exp=1., 
                    hyd_cond=8.64e-2, porosity=0.01, sea_level = None, cond_decay=0.):
        """ 
        build and run modflow model
        
        Arguments
        ---------
        ident: str
            identity name of the model
        climatic: float or list of float
            recharge chronicle of the model in m/d
        lay_number: int
            number of layer of the model
        thick: float
            thickness of the model
        bottom : None or float (default is None)
            if bottom is None, the model has a constant thickness
            if bottom is float, the model hast à flat bottom at the float elevation
        hyd_cond: float or array of float
            hydraulic conductivity of the model. The array must be the same size of the dem
        porosity: float or array of float
            porosity of the model. The array must be the same size of the dem
        sea_level: None or float (default is None)
            sea level in meters
        cond_decay: float    
            changes the hydraulic conductivity exponentially whit the depth
        thick_exp: float (default is 1)
            changes the thickness of the layers exponentially
        """
        if type(sea_level) != type(climatic):
            print('Error : sea_level and climatic chronicles must be the same length')
        else:
            model = modflow.Modflow(self.geographic, watershed=self.name, 
                                    climatic=climatic, lay_number=lay_number, thick=thick, bottom=bottom, thick_exp=thick_exp, 
                                    hyd_cond=hyd_cond, porosity=porosity, sea_level = sea_level, cond_decay=cond_decay,
                                    time_step='monthly', model_name=ident, model_folder=self.simulations_folder, 
                                    exe=self.modflow_path +'/bin/mfnwt.exe')
        
        model.build()
        model.run()
        model.extract_model(self.dem_path)

        # model.save(self.geographic, watershed='sim_modflow', model_name=name, model_folder=self.watershed_folder,
        #            param=True, watertable=True, seepage=True, gwflux=True, outflow=True, spedisch=True)
        
    def run_hs1D(self):
        return self

