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
root_dir = dirname(dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy modules
#from watershed.data import  climatic, oceanic, piezometry, hydrology
import climatic, oceanic, piezometry, hydrology
from groundwater_flow import modflow, modpath
from tools import file_adds
from watershed import forcing, geographic, geology, hydrodynamic, subbasins, watershed_display
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
                 out_path: str, library_path: str = 'watershed_library.csv',
                 surfex_path: str = None, oceanic_path: str = None, 
                 geology_path: str = None, hydrology_path: str = None, 
                 piezometry_path: bool = False, modflow_path: str = None,
                 save_object: bool = True, load: bool = False,
                 types_obs: list = ['streams'], fields_obs: list = ['FID']):
        """  
        Constructor
        """
        self.watershed_name = watershed_name
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
        
        self.types_obs = types_obs
        self.fields_obs = fields_obs
        
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
        
        #self.hillslope = hillslope() #1D Doesn't exist
        
        if self.hydrology_path != None:
            self.hydrology = hydrology.Hydrology(out_path=self.watershed_folder, types_obs=self.types_obs, fields_obs=self.fields_obs, geographic=self.geographic, hydro_path=self.hydrology_path)
            self.elt_def.append('hydrology')
            
        if self.geology_path != None:
            self.geology =  geology.Geology(out_path=self.watershed_folder, geographic=self.geographic, geo_path = self.geology_path, landsea=None)
            self.elt_def.append('geology')

        #MODELING DATA
        self.oceanic = oceanic.Oceanic()
        if self.oceanic_path != None:
            self.oceanic.extract_data(out_path=self.watershed_folder, oceanic_path=self.oceanic_path,geographic=self.geographic)
            self.elt_def.append('oceanic')

        if self.surfex_path != None:
            self.climatic = climatic.Climatic(out_path=self.watershed_folder, surfex_path=self.surfex_path,watershed_shp=self.geographic.watershed_shp)
            climatic.Merge(out_path=self.watershed_folder)
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
        
        :meta public:
        """
        if os.path.exists(os.path.join(self.watershed_folder,'python_object')):
            os.remove(os.path.join(self.watershed_folder,'python_object'))
        with open(os.path.join(self.watershed_folder,'python_object'), 'xb') as config_dictionary_file:
            pickle.dump(self, config_dictionary_file)
        config_dictionary_file.close()
        # pickle.dump(self, open(self.watershed_folder + '/python_object', "wb"))
    
    def generate_subbasins(self, file_name='data.txt', fonction_column='fonction', type_data='hydro',
                                 code_column='code', label_column='name',
                                 x_column=0, y_column=1,
                                 start_column=1990, end_column=2000,
                                 snap_dist=100):
        """
        AG: à déplacer dans géographic ? ou hydrology? car on l'utilise pour les débits'
        """
        sub = subbasins.Subbasins(self.geographic)
        df_auto = sub.automatic_coord(self.hydrology_path, os.path.join(self.stable_folder, 'hydrology'))
        try:
            sub.manual_coord(os.path.join(self.stable_folder, 'add_data'), 
                                         file_name,  
                                         fonction_column,
                                         type_data,
                                         code_column,
                                         label_column,
                                         x_column,
                                         y_column,
                                         start_column,
                                         end_column)
        except:
            pass
        sub.extract_subbasins(snap_dist, self.stable_folder)
        return df_auto
    
    def run_modflow(self, ident: str = 'modflow', modpath_sim: bool = False, 
                    calib: bool = True, sink_fill: bool = False, lay_number: int = 1, 
                    bottom: float = None, thick_exp: float = 1., cond_decay: float = 0., verbose: bool = True):
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
        flow_model = modflow.Modflow(self.geographic, calib=calib, sink_fill=sink_fill,
                                    lay_number=lay_number, thick=self.hydrodynamic.thickness, thick_exp=thick_exp, bottom=bottom,
                                    hyd_cond=self.hydrodynamic.hyd_cond, cond_decay=cond_decay, porosity=self.hydrodynamic.porosity,
                                    climatic=self.forcing.recharge, sea_level=self.oceanic.MSL,
                                    model_name=ident, model_folder=self.simulations_folder, 
                                    exe=self.modflow_path +'/bin/mfnwt.exe')
        flow_model.pre_processing()
        succes = flow_model.processing(verbose = verbose)
        if succes == True:
            flow_model.post_processing()
        
            if modpath_sim == True:
                transit_model = modpath.Modpath(model_name=ident,  
                                            model_folder=self.simulations_folder,
                                            exe=self.modflow_path + '/bin/mp6.exe')
                transit_model.pre_processing()
                transit_model.processing(verbose = verbose)
                #transit_model.post_processing()
        return succes
               
    def chronics_modflow(self, ident='modflow', mask=False, outlet_type='hydrometric',
                         calib_only=False, first=1960, last=2020, time_step='monthly'):
        """
        AG: je ne pense pas que ce soit sa place.
        Pour moi c'est une method de la class Modflow.
        Il faudrait peut être faire un object modflow ou l'on pourrait appeler Chronics
        style : BV.modflow.chronics
        """
        self.chronics = modflow.Chronics(self.geographic, watershed_name=self.watershed_name,
                                        mask=mask, outlet_type=outlet_type, calib_only=calib_only,
                                        subbasins_folder=os.path.join(self.stable_folder, 'subbasins'),
                                        first=first, last=last, time_step=time_step,
                                        model_name=ident, model_folder=self.simulations_folder,
                                        hydrology_path=self.hydrology_path)
        self.chronics.extract_chronic()
                        
    def calib_dichotomy(self, ident='modflow', type_river='streams', calib=True, climatic=8e-4, 
                        lay_number=1, thick=50, bottom=None, thick_exp=1., 
                        first=1, last=10000, gap=1, porosity=0.01, sea_level=None, cond_decay=0.):
        """
        AG: Destiné à disparaitre
        
        :meta private:
        """
        self.diff = last - first
        half = (first + last) / 2
        self.gap = gap
        
        self.df = pd.DataFrame()
        
        compt = 0
        while (self.diff > ((gap/100) * half)):
            half = (first + last) / 2
            hyd_cond = half * climatic
            
            ident = str('dic')+'-'+str(type_river)+'-'+str(round(half,3))+'-'+str(round(climatic,3))+'-'+str(round(thick,3))
            
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
                                              type_river=type_river,
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
            print('    Gap = '+str(round((gap/100) * half, 2)))
            
            self.df.loc[compt,'KR'] = round(half, 4)
            self.df.loc[compt,'K'] = round(hyd_cond, 4)
            self.df.loc[compt,'Sflow'] = round(mean_sim_to_obs, 4)
            self.df.loc[compt,'Oflow'] = round(mean_obs_to_sim, 4)
            self.df.loc[compt,'Cond'] = round(condition, 4)    
            
            compt += 1
        
        self.df.to_csv(os.path.join(self.simulations_folder, '_dichotomy_'+type_river+'.csv'), sep=';', index=True)
        
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


            
            
            
