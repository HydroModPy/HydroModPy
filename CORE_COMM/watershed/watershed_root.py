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
data_dir = os.path.join(dirname(abspath(__file__)),'data')
sys.path.append(data_dir)
root_dir = dirname(abspath(__file__))
sys.path.append(root_dir)

# HydroModPy modules
#from watershed.data import  climatic, oceanic, piezometry, hydrology
import climatic, oceanic, piezometry, hydrology, geology, hydrometry, intermittency
from groundwater_flow import modflow, modpath, modflow_results
from tools import toolbox
from watershed import forcing, geographic, hydrodynamic, watershed_display
from calibration import calib_dichotomy

class Watershed:
    """
    class Watershed is used to extract watershed and its data from regional DEM

    :param str name: name of watershed.
    :param dem_path: folder of the regional DEM.
    :param out_path: root directory of results.
    :library_path: path of the watershed_library.csv file.
    :param surfex_path: root directory of surfex data.
    :param oceanic_path: root directory of oceanic data.
    :param geology_path: root directory of geology data.
    :param hydrology_path: root directory of hydrology data.
    :param piezometry_path: download franch piezometric data.
    :param modflow_path: root directory of modflow executable.
    :param save_object: save the watershed object in pickle file.
    :param load: load the pickle file. Doesn't build the watershed object.
    :param types_obs: list of observations data. Only if hydrology_path is not None.
    :param fields_obs: list of observations fields. Only if hydrology_path is not None.
    
    :ivar str watershed_folder: root directory of results of watershed class
    :ivar add_data_folder: folder if you want add data manually
    :vartype add_data_folder: :class:`str`
    :ivar simulations_folder: root directory of simulation results
    :vartype simulations_folder: :class:`str`
    :ivar stable_folder: root directory of stable results
    :vartype stable_folder: :class:`str`
    :ivar figure_folder: root directory of figures folder
    :vartype figure_folder: :class:`str`
    :ivar elt_def: list of elements in the python object
    :vartype elt_def: :class:`list`
    :ivar geographic: geographic object
    :vartype geographic: :class:`object`
    :ivar hydrodynamic: hydrodynamic object
    :vartype hydrodynamic: :class:`object`
    :ivar forcing: forcing object
    :vartype forcing: :class:`object`
    :ivar climatic: climatic object
    :vartype climatic: :class:`object`
    :ivar hydrology: hydrology object
    :vartype hydrology: :class:`object`
    :ivar oceanic: oceanic object
    :vartype oceanic: :class:`object`
    :ivar geology: geology object
    :vartype geology: :class:`object`
    :ivar piezometry: piezometry object
    :vartype piezometry: :class:`object`
    :ivar x_outlet: x coordinate of the watershed outlet.
    :vartype x_outlet: :class:`float`
    :ivar y_outlet: y coordinate of the watershed outlet.
    :vartype y_outlet: :class:`float`
    :ivar snap_dist: maximum distance snappin of the watershed outlet.
    :vartype snap_dist: :class:`float`
    :ivar buff_percent: percentage of the watershed to build the buffer around it.
    :vartype buff_percent: :class:`float`
    :ivar crs_proj: coordiante system of projection
    :vartype crs_proj: :class:`str`
    
    :meta public:
    """
    def __init__(self, watershed_name: str, dem_path: str, 
                 out_path: str, library_path: str = os.path.join(root_dir,'watershed_library.csv'), 
                 modflow_path: str = None, save_object: bool = True, load: bool = False):
        """  
        Constructor
        """
        self.watershed_name = watershed_name
        self.library_path = library_path
        self.load_watershed_csv()

        self.dem_path = dem_path
        self.out_path = out_path
        self.modflow_path = modflow_path

        self.watershed_folder = os.path.join(out_path, watershed_name)
        toolbox.create_folder(self.watershed_folder)
        
        self.stable_folder = os.path.join(self.watershed_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)
        
        self.add_data_folder = os.path.join(self.stable_folder, 'add_data/')
        toolbox.create_folder(self.add_data_folder)
        
        self.figure_folder = os.path.join(self.stable_folder, '_figures/watershed/')
        toolbox.create_folder(self.figure_folder)
        
        self.simulations_folder = os.path.join(self.watershed_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)
        
        self.elt_def = []
        
        if load==True:
             succes = self.load_object()
             if succes == True:
                print("Object was loaded successfully")
             if succes == False:
                print("Object was not loaded as demanded but created from scratch")
                self.create_object()
                if save_object == True:
                    self.save_object()
        else:
            print("Create new object")
            self.create_object()
            if save_object == True:
                self.save_object()
        
    def load_watershed_csv(self):
        """
        Load watershed informations from watershed.csv file
        
        :meta public:
        """
        watershed_list = pd.read_csv(self.library_path, delimiter=';')
        try:
            watershed_list = pd.read_csv(self.library_path, delimiter=';')
            watershed_info = watershed_list.loc[watershed_list['watershed_name'] == self.watershed_name]
            self.x_outlet = watershed_info.iloc[0]['x_outlet']
            self.y_outlet = watershed_info.iloc[0]['y_outlet']
            self.snap_dist = watershed_info.iloc[0]['snap_dist']
            self.buff_percent = watershed_info.iloc[0]['buff_percent']
            self.crs_proj = watershed_info.iloc[0]['crs_proj']
        except:
            print("Warning : The name of watershed is not in the watershed list")
            sys.exit()
            return watershed_list
        
    def load_object(self):
        """
        Loads python object
        
        :meta public:
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
            if ('hydrodynamic' in BV.__dir__()) == True:
                self.hydrodynamic = BV.hydrodynamic
                self.elt_def.append('hydrodynamic')
            if ('climatic' in BV.__dir__()) == True:
                self.climatic = BV.climatic
                self.elt_def.append('climatic')
            if ('hydrology' in BV.__dir__()) == True:
                self.hydrology = BV.hydrology
                self.elt_def.append('hydrology')
            if ('forcing' in BV.__dir__()) == True:
                self.forcing = BV.forcing
                self.elt_def.append('forcing')
            if ('piezometry' in BV.__dir__()) == True:
                self.piezometry = BV.piezometry
                self.elt_def.append('piezometry')
            if ('geology' in BV.__dir__()) == True:
                self.geology = BV.geology
                self.elt_def.append('geology')
            if ('oceanic' in BV.__dir__()) == True:
                self.oceanic = BV.oceanic
                self.elt_def.append('oceanic')
            if ('hydrometry' in BV.__dir__()) == True:
                self.hydrometry = BV.hydrometry
                self.elt_def.append('hydrometry')
            if ('intermittency' in BV.__dir__()) == True:
                self.intermittency = BV.intermittency
                self.elt_def.append('intermittency')
            if ('subbasin' in BV.__dir__()) == True:
                self.subbasin = BV.subbasin
                self.elt_def.append('subbasin')
            return True 
        else:
            print("Warning : file doesn't exist, python_object", self.watershed_folder)
            return False

    def create_object(self):
        """
        Creates python object
        
        :meta public:
        """
        #STURCUTRE DATA
        self.geographic = geographic.Geographic(dem_path=self.dem_path, x=self.x_outlet, y=self.y_outlet,
                                                snap_dist=self.snap_dist, buff_percent=self.buff_percent,
                                                out_path=self.watershed_folder) #2D
        self.elt_def.append('geographic')
        
        self.forcing = forcing.Forcing(out_path=self.watershed_folder)
        self.elt_def.append('forcing')
        
        self.hydrodynamic = hydrodynamic.Hydrodynamic(self.geographic.y_pixel, self.geographic.x_pixel)
        self.elt_def.append('hydrodynamic')
        self.oceanic = oceanic.Oceanic()
        #self.hillslope = hillslope() #1D Doesn't exist
        
    def add_hydrology(self, hydrology_path, types_obs = ['streams'], fields_obs = ['FID'], reset = False):
        self.hydrology_path = hydrology_path
        self.types_obs = types_obs
        self.fields_obs = fields_obs
        self.hydrology = hydrology.Hydrology(out_path=self.watershed_folder, types_obs=self.types_obs, fields_obs=self.fields_obs, geographic=self.geographic, hydro_path=self.hydrology_path)
        self.elt_def.append('hydrology')
        self.save_object()
            
    def add_geology(self, geology_path):
        self.geology_path = geology_path
        self.geology =  geology.Geology(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path, landsea=None)
        self.elt_def.append('geology')
        self.save_object()

    def add_oceanic(self, oceanic_path):
        self.oceanic_path = oceanic_path
        self.oceanic.extract_data(out_path=self.watershed_folder, oceanic_path=self.oceanic_path,geographic=self.geographic)
        self.elt_def.append('oceanic')
        self.save_object()

    def add_surfex(self, surfex_path):
        self.surfex_path = surfex_path
        self.climatic = climatic.Climatic(out_path=self.watershed_folder, surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
        climatic.Merge(out_path=self.watershed_folder)
        self.elt_def.append('surfex')
        self.save_object()

    def add_piezometry(self):
        self.piezometry = piezometry.Piezometry(out_path=self.watershed_folder,geographic=self.geographic)
        self.elt_def.append('piezometry')
        self.save_object()
        
    def add_hydrometry(self, hydrometry_path):
        self.hydrometry_path = hydrometry_path
        self.hydrometry = hydrometry.Hydrometry(out_path=self.watershed_folder, hydrometry_path=self.hydrometry_path, geographic=self.geographic)
        self.elt_def.append('hydrometry')
            
    def add_intermittency(self, intermittency_path):
        self.intermittency_path = intermittency_path
        self.intermittency = intermittency.Intermittency(out_path=self.watershed_folder, intermittency_path=self.intermittency_path, geographic=self.geographic)
        self.elt_def.append('intermittency')
            
    def add_subbasin(self):
        self.subbasin = geographic.Subbasin(geographic=self.geographic, hydrometry=self.hydrometry, intermittency=self.intermittency, out_path=self.watershed_folder)
        self.elt_def.append('subbasin')

    def save_object(self):
        """
        Saves python object
        
        :meta public:
        """
        if os.path.exists(os.path.join(self.watershed_folder,'python_object')):
            os.remove(os.path.join(self.watershed_folder,'python_object'))
        with open(os.path.join(self.watershed_folder,'python_object'), 'xb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        # pickle.dump(self, open(self.watershed_folder + '/python_object', "wb"))
        
    def run_modflow(self, ident: str = 'modflow', modpath_sim: bool = False, box: bool = True,
                    first_only: bool = True, sink_fill: bool = False, lay_number: int = 1, 
                    bottom: float = None, thick_exp: float = 1., cond_decay: float = 0., verbose: bool = False):
        """ 
        Build and run modflow model
        
        :param ident: identity name of the model
        :param modpath_sim: run modapth model
        :param lay_number: number of layer of the model
        :param bottom: if bottom is None, the model has a constant thickness.if bottom is float, the model has a flat bottom at the float elevation
        :param cond_decay: changes the hydraulic conductivity exponentially with the depth. lay_number must be >1.
        :param thick_exp: changes the thickness of the layers exponentially. lay_number must be >1.
        
        :return succes: True if the simulation is succesfully
        
        :meta public:
        """
        flow_model = modflow.Modflow(self.geographic, first_only=first_only, sink_fill=sink_fill, box=box,
                                     lay_number=lay_number, thick=self.hydrodynamic.thickness, thick_exp=thick_exp, bottom=bottom,
                                     hyd_cond=self.hydrodynamic.hyd_cond, cond_decay=cond_decay, porosity=self.hydrodynamic.porosity,
                                     climatic=self.forcing.recharge, sea_level=self.oceanic.MSL,
                                     model_name=ident, model_folder=self.simulations_folder, 
                                     exe=self.modflow_path +'/bin/mfnwt.exe')
        flow_model.pre_processing(verbose = verbose)
        succes = flow_model.processing(verbose = verbose)
        if succes == True:
            flow_model.post_processing(verbose = verbose)
        
            if modpath_sim == True:
                transit_model = modpath.Modpath(self.geographic,model_name=ident,  
                                            model_folder=self.simulations_folder,
                                            exe=self.modflow_path + '/bin/mp6.exe')
                transit_model.pre_processing(verbose = verbose)
                transit_model.processing(verbose = verbose)
                #transit_model.post_processing()
        return succes
    
    def results_modflow(self, ident='modflow', actual_date=True, start='2010-01-01', time_step='M'):

        modflow_results.Results(self.geographic,
                                          recharge=self.forcing.recharge,
                                          actual_date=actual_date,
                                          start=start,
                                          time_step=time_step,
                                          stable_folder=self.stable_folder,
                                          model_name=ident,
                                          model_folder=self.simulations_folder)
                
    def run_hs1D(self):
        """
        Coming soon !
        """
        return self
    
    def display(self,dtype: str = 'watershed_dem'):
        """
        Display watershed figure

        :param dtype: type of figure. Can be 'watershed_dem' or 'watershed_geology'
        """
        if dtype == 'watershed_dem':
            watershed_display.watershed_dem(self)
        if dtype == 'watershed_geology':
            watershed_display.watershed_geology(self)    


            
            
            
