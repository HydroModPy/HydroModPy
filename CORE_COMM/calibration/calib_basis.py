# -*- coding: utf-8 -*-
"""

"""

#%% LIBRAIRIES

import pickle
import numpy as np
import matplotlib.pyplot as plt
import os
import pandas as pd                                     
from datetime import datetime
                    
# from calibration import tools_figures_additional as figadd                                     
from calibration import calib_objective_function, calib_params
from groundwater_flow import visualization, modflow_display

from tools import toolbox

#%% CLASS

class CalibrationBasis: 
    """ 
    
    Class for the calibration of a LPM of type LPM_type on sampled concentrations in "concentration_sampled
        Only the formulation of the problem 
        Calibration methods are defined in daughter classes 
        
    Attributes
    ----------
    concentration_sampled: Concentrations
        target concentrations 
    LPM_type: str
        type of LPM, which will be calibratited (e.g. exp,ig,gamma)
    lpm: LPM
        lpm that will be calibrated 
    tracers: ConvolutionTracers
        Tracers and Convolution method (affected by the constructor)
    
    Methods
    -------
    
    """

    #%% INIT

    def __init__(self, file_name, watershed, observations, calibration_folder):
        """ 
        
        Constructor
        
        Parameters
        ----------
        concentration_sampled: Concentrations
            target concentrations and dates at which they were taken
        LPM_type: str
            type of LPM, which will be calibratited (e.g. exp,ig,gamma)
        directory_resutls: str
            Directory for the storage of results
        directory_lpm: str
            Directory of lpm details #JR 05/08: no longer used? Obsolete
            
        """
        
        self.params = calib_params.CalibParams(file_name, watershed)
        self.watershed = watershed
        self.observations = observations
        
        self.param_ident = self.params.file_name
        
        self.param_folder = os.path.join(calibration_folder, self.param_ident)
        if not os.path.exists(self.param_folder):
            toolbox.create_folder(self.param_folder)
        
        self.ident = "_".join(self.observations) +  '_calibration'
        
        self.directory_results = os.path.join(self.param_folder, self.ident)
        if not os.path.exists(self.directory_results):
            toolbox.create_folder(self.directory_results)
                
        self.data_ind = {}
        self.data_sim = {}
        self.data_obs = {}
        self.data_cri = {}
        
        for i in self.observations:
            self.data_ind[i] = []
            self.data_sim[i] = []
            self.data_obs[i] = []
            self.data_cri[i] = []
        # self.__dict__.update(calparam.__dict__)
        # self.parameters = []
        
        self.dic_simulated_results = {}
        self.params_synt = []

    #%% CALL OBJECTIVE FUNCTIONS
    
    def objective_function(self, params):
        """
        
        Updates values of parameters according to params
            Should be separated from objective function 

        Parameters
        ----------
        params : TYPE
            DESCRIPTION.

        Returns
        -------
        TYPE
            DESCRIPTION.

        """
        
        # self.parameters.append(params)

        # Heterogeneity of hydraulic conductivities: 
        # Updates the (hydraulic conductivies, porisities, thicknesses)
        #   of the grid according to the geological zones defined 
        # Would also be possible externally to calibration
        
        #%% MODEL PARAMS
        
        for i in range(0,len(self.params.name)):
            if self.params.name[i][0] == 'k':
                # Update hydrodynamic parameters
                if self.params.num_zone[i] > 0 :
                    self.watershed.hydrodynamic.update_hyd_cond_from_calib_zones(self.params.num_zone[i], params[i])
                if self.params.num_zone[i] == 0 :
                    self.watershed.hydrodynamic.update_hyd_cond(params[i])
                    
            if self.params.name[i][0] == 'n':
                # Update hydrodynamic parameters
                self.watershed.hydrodynamic.update_porosity_from_calib_zones(self.params.num_zone[i], params[i])
                if self.params.num_zone[i] == 0 :
                    self.watershed.hydrodynamic.update_porosity(params[i])
            if self.params.name[i][0] == 't':
                # Update hydrodynamic parameters
                self.watershed.hydrodynamic.update_thickness(params[i])
        
        #%% RUN MODEL

        # Run model: seeks the parameters automatically in the elements of self.watershed
        succes, mf = self.watershed.run_modflow(self.ident, 
                                                verbose=True,
                                                calib=self.param_folder)
        
        # Use objective function from the type of observation
        if succes == True:
            indicator = []
            
            #%% STREAMS

            if 'streams' in self.observations:
                self.watershed.matrix_modflow(succes,
                       mf,
                       first_only=True,
                       watertable_elevation = True,
                       watertable_depth=False, 
                       seepage_areas = True,
                       outflow_drain = False,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = False,
                       perenn_intermit_shp = False,
                       verbose = False,
                       export_tif = True)
                self.watershed.results_modflow(ident=self.ident,
                                               actual_date=True,
                                               calib=self.param_folder)
                obj_func = calib_objective_function.Streams(self.watershed, 
                                                            hydrology_stable=os.path.join(self.watershed.stable_folder, 'hydrology'),
                                                            calibration_folder=self.directory_results)
                ind, obs, sim = obj_func.get_indicator()
                indicator.append(ind)
                self.data_ind['streams'].append(ind)
                self.data_obs['streams'].append(obs)
                self.data_sim['streams'].append(sim)
            
            #%% PIEZOMETRY

            if 'piezometry' in self.observations:
                self.watershed.matrix_modflow(succes,
                       mf,
                       watertable_elevation = True,
                       watertable_depth=False, 
                       seepage_areas = False,
                       outflow_drain = False,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = False,
                       perenn_intermit_shp=False,
                       verbose = False,
                       export_tif = True)
                self.watershed.results_modflow(ident=self.ident,
                                               actual_date=True,
                                               calib=self.param_folder)
                obj_func = calib_objective_function.Piezometry(self.watershed,
                                                               self.ident,
                                                               self.param_folder)
                ind, obs, sim, = obj_func.get_indicator()
                indicator.append(ind)
                self.data_ind['piezometry'].append(ind)
                self.data_obs['piezometry'].append(obs)
                self.data_sim['piezometry'].append(sim)
              
            #%% HYDROMETRY

            if 'hydrometry' in self.observations:
                self.watershed.matrix_modflow(succes,
                       mf,
                       first_only = True,
                       watertable_elevation = True,
                       watertable_depth= True, 
                       seepage_areas = True,
                       outflow_drain = True,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = True,
                       perenn_intermit_shp = False,
                       verbose = True,
                       export_tif = True)
                simulated_results = self.watershed.results_modflow(ident=self.ident,
                                                                   recharge=self.watershed.forcing.recharge,
                                                                   runoff=self.watershed.forcing.runoff,
                                                                   actual_date=True,
                                                                   calib=self.param_folder)
                # print(simulated_results)
                # print(params)
                params_synt = ";".join(str(x) for x in params)
                self.dic_simulated_results[params_synt] = simulated_results
                
                obj_func = calib_objective_function.Hydrometry(self.watershed,
                                                               self.ident,
                                                               self.param_folder)
                ind, obs, sim, cri = obj_func.get_indicator()
                indicator.append(ind)
                self.data_ind['hydrometry'].append(ind)
                self.data_obs['hydrometry'].append(obs)
                self.data_sim['hydrometry'].append(sim)
                self.data_cri['hydrometry'].append(cri)
                self.params_synt.append(params_synt)
                
                # plt.plot(obs, color='b')
                # plt.plot(sim, color='r')
                
            #%% INTERMITTENCY  
            
            if 'intermittency' in self.observations:
                self.watershed.matrix_modflow(succes,
                       mf,
                       first_only = True,
                       watertable_elevation = True,
                       watertable_depth= False, 
                       seepage_areas = True,
                       outflow_drain = True,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = True,
                       perenn_intermit_shp = True,
                       verbose = True,
                       export_tif = True)
                self.watershed.results_modflow(ident=self.ident,
                                               actual_date=True,
                                               calib=self.param_folder)
                
                
                
                obj_func = calib_objective_function.Intermittency(self.watershed,
                                                               self.ident,
                                                               self.param_folder)
                ind, sim, obs = obj_func.get_indicator()
                self.data_ind['intermittency'].append(ind)
                self.data_sim['intermittency'].append(sim)
                self.data_obs['intermittency'].append(obs)
                
                # plt.plot(obs, color='b')
                # plt.plot(sim, color='r')
        
        #%% INDICATORS SUM
        
        if succes == False:
            indicator = np.inf
        try:
            if len(params) == 1:
                params_print = str([round(num, 5) for num in params])
                succes_print = str(succes)
                indicator_print = str([round(num, 5) for num in indicator])
                indicatorlog_print = str([round(num, 5) for num in np.log10(indicator)])
            if len(params) == 2:
                params_print = str([round(num, 5) for num in params])
                succes_print = str(succes)
                indicator_print = str([round(num, 5) for num in indicator[0]])
                indicatorlog_print = str([round(num, 5) for num in np.log10(indicator[0])])
            to_print = params_print+' | '+succes_print+' | '+indicator_print+' | '+indicatorlog_print
            print(to_print)
        except:
            pass
        #Pondération entre les indicateurs à réaliser
        return np.sum(indicator)

    #%% CREATE RESULTS CALIB FILE

    def write_results(self, name, obj_function, params_values, params_xyz):
        """ 
        A garder
        Writes parameters of calibration
        """
        #Save file
        store = {}
        store['name'] = name
        store['observations'] = self.observations
        # Parameter Values
        self.name = []
        # Parameter Units 
        self.u = []
        # Bounds of parameters
        self.p_init = []
        self.p_min = []
        self.p_max = []
        store['file_name'] = self.params.file_name # # 'calib_explo_hom_2v_k1-n1'
        store['params_name'] = self.params.name # name k1, k2, n1...
        store['params_min'] = self.params.p_min # bounds min
        store['params_max'] = self.params.p_max # bounds min
        store['params_values'] = params_values # linspace of parameters
        store['data_obs'] = self.data_obs # data_obs each simulation
        store['data_sim'] = self.data_sim # data_sim each simulation
        store['data_ind'] = self.data_ind # indicator each simulation
        store['objective_function'] = obj_function
        store['recharge'] = self.watershed.forcing.recharge
        store['calib_zone'] = self.watershed.hydrodynamic.calib_zones
        store['params_xyz'] = params_xyz
        try : 
            store['sim_results'] = self.dic_simulated_results
            store['params_synt'] = self.params_synt
        except:
            pass
        try : 
            store['list_criteria'] = self.data_cri
        except:
            pass
        with open(os.path.join(self.directory_results, name + '.calib'), 'xb') as config_dictionary_file:
            pickle.dump(store, config_dictionary_file)
        config_dictionary_file.close()

#%% NOTES


