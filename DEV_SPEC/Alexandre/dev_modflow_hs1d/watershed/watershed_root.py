# -*- coding: utf-8 -*-
"""
Created on Thu Sep  9 14:52:56 2021

@author: Alexandre Gauvain
"""

# Modules
import os
import pandas as pd
import pickle
import _pickle as cPickle
import sys
from os.path import dirname, abspath
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy modules
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import modflow
from tools import file_adds
from watershed import geographic, geology, hydrodynamic, subbasins, watershed_display
from calibration import calib_dichotomy

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
    def __init__(self, watershed_name, dem_path, library_path = os.path.join(root_dir, 'watershed_library.csv'),
                 out_path = os.path.dirname(os.path.dirname(__file__))+'\\output\\', 
                 surfex_path = None, oceanic_path = None, geology_path = None, 
                 hydrology_path = None, piezometry_path = False, modflow_path = None, 
                 load = False):
        """ 
        Constructor
        
        Arguments
        ---------
        watershed_name: str
            name of watershed
        dem_path : str
            folder of the regional DEM
        library_path: str
            path of the library file
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
        self.piezometry_path = piezometry_path
        self.oceanic_path = oceanic_path
        self.geology_path = geology_path
        self.modflow_path = modflow_path
        
        self.watershed_folder = os.path.join(out_path, watershed_name)
        file_adds.create_folder(self.watershed_folder)
        
        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        file_adds.create_folder(self.stable_folder)                
        self.add_data_folder = os.path.join(self.stable_folder, 'add_data/')
        file_adds.create_folder(self.add_data_folder)
        self.figure_folder = os.path.join(self.stable_folder, '_figures/watershed/')
        file_adds.create_folder(self.figure_folder)
        
        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        file_adds.create_folder(self.simulations_folder)
        
        self.elt_def = []
        
        if load==True:
             succes = self.load_object()
             if succes == True:
                print("Object was loaded successfully")
             if succes == False:
                print("Object was not loaded as demanded but created from scratch")
                self.create_object()
                self.save_object()
        else:
            print("Create new object")
            self.create_object()
            self.save_object()
        
    def load_watershed_csv(self):
        """
        Load watershed informations from watershed.csv file
        """
        watershed_list = pd.read_csv(self.library_path, delimiter=';')
        try:
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
        if os.path.exists(os.path.join(self.watershed_folder, 'python_object')):
            with open(os.path.join(self.watershed_folder, 'python_object'), 'rb') as config_dictionary_file:
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
        self.geographic = geographic.Geographic(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet,
                                                snap_dist=self.snap_dist, buff_dist=self.buff_dist,
                                                out_path=self.watershed_folder) #2D
        self.elt_def.append('geographic')
        
        self.hydrodynamic = hydrodynamic.Hydrodynamic()
        self.elt_def.append('hydrodynamic')
        
        #self.hillslope = hillslope() #1D Doesn't exist
        
        if self.hydrology_path != None:
            self.hydrology = hydrology.Hydrology(out_path=self.watershed_folder,type_obs='streams', geographic=self.geographic, hydro_path=self.hydrology_path)
            self.elt_def.append('hydrology')

        if self.geology_path != None:
            self.geology =  geology.Geology(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path, landsea=None)
            self.elt_def.append('geology')

        #MODELING DATA
        if self.oceanic_path != None:
            self.oceanic = oceanic.Oceanic(out_path=self.watershed_folder,oceanic_path=self.oceanic_path,geographic=self.geographic)
            self.elt_def.append('oceanic')

        if self.surfex_path != None:
            self.climatic = climatic.Climatic(out_path=self.watershed_folder,surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
            self.elt_def.append('surfex')

        #FIELD DATA
        if self.piezometry_path == True:
            self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,geographic=self.geographic)
            self.elt_def.append('piezometry')
        #self.hydrometry = hydrometry() #doesn't exist
        #self.geochemistry = geochemistry() #doesn't exist

    def save_object(self):
        """
        Saves python object
        """
        with open(self.watershed_folder + '/python_object', 'wb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        # pickle.dump(self, open(self.watershed_folder + '/python_object', "wb"))
    
    def generate_subbasins(self, file_name='data', type_data='environmental',
                                 code_column='ABC', label_column='ABC',
                                 x_column=0, y_column=1,
                                 start_column=1990, end_column=2000,
                                 snap_dist=100):
        sub = subbasins.Subbasins(self.geographic)
        df_auto = sub.automatic_coord(self.hydrology_path, os.path.join(self.stable_folder, 'hydrology'))
        df_auto = 'x'
        df_manual = sub.manual_coord(os.path.join(self.stable_folder, 'add_data'), 
                                     file_name,  
                                     type_data,
                                     code_column,
                                     label_column,
                                     x_column,
                                     y_column,
                                     start_column,
                                     end_column)
        sub.extract_subbasins(snap_dist, self.stable_folder)
        return df_auto, df_manual    
    
    def run_modflow(self, ident='modflow', calib=True, climatic=8e-4,
                    lay_number=1, thick=100, bottom=None, thick_exp=1., 
                    hyd_cond=8.64e-2, porosity=0.01, sea_level=None, cond_decay=0.):
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
        
        if (sea_level == None) | (type(sea_level) == type(climatic)):
            model = modflow.Modflow(self.geographic, time_step='monthly', calib=calib,
                                    lay_number=lay_number, thick=thick, thick_exp=thick_exp, bottom=bottom,
                                    hyd_cond=hyd_cond, cond_decay=cond_decay, porosity=porosity,
                                    climatic=climatic, sea_level=sea_level,
                                    model_name=ident, model_folder=self.simulations_folder, 
                                    exe=self.modflow_path +'/bin/mfnwt.exe')
            # model.pre_processing()
            # model.processing()
            # model.post_processing()
            
        else:
            print('Error : sea_level and climatic chronicles must be the same length')
                                        
    def calib_dichotomy(self, ident='modflow', calib=True, climatic=8e-4, lay_number=1, thick=50, bottom=None, thick_exp=1., 
                        first=1, last=10000, gap=10, porosity=0.01, sea_level=None, cond_decay=0.):

        self.diff = last - first
        
        self.df = pd.DataFrame()
        
        compt = 0
        while (self.diff > gap):
            half = (first + last) / 2
            hyd_cond = half * climatic.values[0]
            
            ident = str('dic')+'-'+str(round(half,3))+'-'+str(round(climatic.values[0],3))+'-'+str(round(thick,3))
            
            model = modflow.Modflow(self.geographic, calib=calib, time_step='monthly',
                                    lay_number=lay_number, thick=thick, thick_exp=thick_exp, bottom=bottom,
                                    hyd_cond=hyd_cond, cond_decay=cond_decay, porosity=porosity,
                                    climatic=climatic, sea_level=sea_level, 
                                    model_name=ident, model_folder=self.simulations_folder, 
                                    exe=self.modflow_path +'/bin/mfnwt.exe')
            model.pre_processing()
            model.processing()
            model.post_processing()
            
            dicot = calib_dichotomy.Dichotomy(self.geographic,
                                              type_river='streams',
                                              hydrology_stable=os.path.join(self.stable_folder, 'hydrology'), 
                                              simulations_folder=os.path.join(self.simulations_folder, ident))
            mean_obs_to_sim, mean_sim_to_obs, condition = dicot.mean_distances()
            
            if condition > 1:
                first = half
            else:
                last = half
                
            self.diff = last - first
            
            print('==> Simulation : '+str(compt))            
            print('    Ecart = '+str(round(self.diff,2)))
            print('    K/R = '+str(round(half, 2)))
            print('    Condition = '+str(condition))
            
            self.df.loc[compt,'KR'] = round(half, 4)
            self.df.loc[compt,'K'] = round(hyd_cond, 4)
            self.df.loc[compt,'Sflow'] = round(mean_sim_to_obs, 4)
            self.df.loc[compt,'Oflow'] = round(mean_obs_to_sim, 4)
            self.df.loc[compt,'Cond'] = round(condition, 4)    
            
            # Condition d'arrêt + message
            
            compt += 1
        
        self.df.to_csv(os.path.join(self.simulations_folder, '_dichotomy.csv'), sep=';', index=True)

    def chronics_modflow(self, ident='modflow', first=1960, last=2020, time_step='monthly'): 
            chronics = modflow.Chronics(self.geographic,
                                        first=first, last=last, time_step=time_step,
                                        model_name=ident, model_folder=self.simulations_folder)
            
    def run_hs1D(self):
        return self
    
    def display(self, type = 'watershed'):
        if type == 'watershed_dem':
            watershed_display.watershed_dem(self)
        if type == 'watershed_geology':
            watershed_display.watershed_geology(self)    


            
            
            
