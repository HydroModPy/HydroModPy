# -*- coding: utf-8 -*-
"""
Created on Wed Mar 24 20:35:54 2021

@author: dreuzy
"""

import pickle
import numpy as np
import matplotlib.pyplot as plt
import os
import pandas as pd                                     
from datetime import datetime
                    
from calibration import tools_figures_additional as figadd                                     
from calibration import calib_objective_function, calib_params,calib_exploration          



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
    
    """

    def __init__(self, file_name, watershed, observations ,directory_results = None):
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
        # Name of model
        self.ident = "_".join(self.observations) +  '_calibration'
        if directory_results == None:
            self.directory_results = os.path.join(watershed.simulations_folder, self.ident)
        
        self.data_ind = {}
        self.data_sim = {}
        self.data_obs = {}
        for i in self.observations:
            self.data_ind[i] = []
            self.data_sim[i] = []
            self.data_obs[i] = []
        # self.__dict__.update(calparam.__dict__)
    
    
    def objective_function(self, params):
        """ 
        Objective Function: Squared difference of concentrations normalized by data errors
            Inverse Problem Theory and Methods for Model Parameter Estimation, Albert Tarantola, SIAM, 2005
            http://www.ipgp.fr/~tarantola/Files/Professional/Books/InverseProblemTheory.pdf
            sum((di-mi)^2/sigma_errori^2)
        
        Arguments
        --------
        param: array
            array of parameter values (order should correspond to that of the lpm)
        concentrations_sampled_c: array
            target concentrations
        concentrations_sampled_error: array
            target concentrations errors
        lpm: LPM
            template LPM (parameters are updated with param)
        tracers: ConvolutionTracers
            convolution class 
            
        Returns
        -------
        float
            value of objective function
        """

        for i in range(0,len(self.params.name)):
            if self.params.name[i][0] == 'k':
                # Update hydrodynamic parameters
                self.watershed.hydrodynamic.update_hyd_cond_from_calib_zones(self.params.num_zone[i], self.params.log_to_linear(params[i]))
            if self.params.name[i][0] == 't':
                # Update hydrodynamic parameters
                self.watershed.hydrodynamic.update_porosity_from_calib_zones(self.params.num_zone[i], params[i])
            if self.params.name[i][0] == 'e':
                # Update hydrodynamic parameters
                self.watershed.hydrodynamic.update_thickness(params[i])
            if self.params.name[i][0] == 'r':
                # Update recharge parameters
                self.watershed.hydrodynamic.update_recharge(params[i])
                
        # Run model
        succes, mf = self.watershed.run_modflow(self.ident, verbose=False)
        
        # Use objective function from the type of observation
        if succes == True:
            indicator = []
            if 'streams' in self.observations:
                self.watershed.matrix_modflow(succes,
                       mf,
                       watertable_elevation = True,
                       watertable_depth=False, 
                       seepage_areas = True,
                       outflow_drain = False,
                       groundwater_flux = False,
                       specific_discharge = False,
                       accumulation_flux = False,
                       perenn_intermit=False,
                       verbose = False,
                       export_tif = True)
                obj_func = calib_objective_function.Streams(self.watershed, 
                                   hydrology_stable=os.path.join(self.watershed.stable_folder, 'hydrology'), 
                                   simulations_folder=os.path.join(self.watershed.simulations_folder, self.ident))
                ind, obs, sim = obj_func.get_indicator()
                indicator.append(ind)
                self.data_ind['streams'].append(ind)
                self.data_obs['streams'].append(obs)
                self.data_sim['streams'].append(sim)
            
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
                       perenn_intermit=False,
                       verbose = False,
                       export_tif = True)
                obj_func = calib_objective_function.Piezometry(self.watershed, self.ident)
                ind, obs, sim = obj_func.get_indicator()
                indicator.append(ind)
                self.data_ind['piezometry'].append(ind)
                self.data_obs['piezometry'].append(obs)
                self.data_sim['piezometry'].append(sim)
            
        if succes == False:
            indicator = np.inf
        print(params, succes, np.log10(indicator))  
        #Pondération entre les indicateurs à réaliser
        return np.sum(indicator)


    def display_concentrations(self):
        """ 
        Dislays concentration results 
        """
        self.lpm.display()
        self.concentration_sampled.display()
        concentration_computed = self.tracers.convolution(self.lpm,return_type="concentrations_set")
        concentration_computed.display()
        print("J=",self.concentration_sampled.sqrt_quadratic_mean_diff(concentration_computed))
  
        
    def display_lpms(self,display_options,lpm_results,lpm_reference=None):
        """
        #A garder
        Display lpm results
        
        Arguments
        ---------
        display_options: 
            Options for the display
        lpm_results: LPMDist
            All results of the calibration
        lpm_reference: LPM
            Target LPM (if existing, eg )
        """
        if self.method == "Simplex" or self.method == "Simplex_init_multipes": 
            # Comparison of parameters
            if display_options.text and lpm_reference != None : 
                lpm_results.get_best_lpm().display_parameters(lpm_reference)
        if self.method == "forward_uncertainty_quantification" or self.method == "Metropolis_Hastings" :
            # Distribution of parameters
            if display_options.figure : 
                lpm_results.display_parameters_dist(self_method=self.method,lpm_reference=lpm_reference,bins=100,directory=self.directory_results)
                self.build_objective_function(display_options)


    def write_calibrated_lpm(self,lpm_results): 
        """ 
        A Garder
        Writes the calibrated lpms
        """ 
        # Writes calibration parameters and efficiencty results
        self.write_parameters(os.path.join(self.directory_results,"parameters_calibration.txt"))
        self.write_results(os.path.join(self.directory_results,"results_calibration.txt"))
        # Writes "best" lpm
        lpm_results.get_best_lpm().write(os.path.join(self.directory_results,"lpm_calibrated.txt"),open_file=True)
        # Writes distribution of "best" lpm
        if self.method != "Simplex" : 
            lpm_results.write_dist(os.path.join(self.directory_results,"lpm_dist_calibrated.txt"))
            lpm_results.write_stats(os.path.join(self.directory_results,"lpm_stats_calibrated.txt"))


    def write_results(self,file_name):
        """ 
        A garder
        Writes parameters of calibration
        """
        data={}
        # Generic results for all calibration methods
        data['time_perform'] = self.time_perform
        # Specific results to this calibration method
        self.write_results_spec(data)
        # Writing in file
        file = open(file_name,"w")
        for key, val in data.items():
            file.write(key+'\t'+str(val)+'\n')
        file.close()
        
        
    def build_objective_function(self,resolution=10000): 
        """ 
        A garder
        Build Objective Function 
        """
        name = 'exp_' + str(len(self.params.name)) + 'p_res_' + str(resolution) + '_'
        now = datetime.now()
        name = name + now.strftime("%d_%m_%Y_%Hh%M") 
        params_values = []
        compt=1
        pmin = self.params.p_min
        pmax = self.params.p_max
        column_names = list()
        for i in self.params.name:
            column_names.append(i)
        if len(self.params.name) == 1 : 
            # Figure Initialization
            # 1 parameter
            params = calib_exploration.systematic_sampling(pmin,pmax,resolution)
            params_values.append(params)
            column_names.append('diff')
            obj_function = pd.DataFrame(columns=column_names)
            # Use of proxy to avoid modification of self.lpm
            for i in range(len(params)):
                print(str(compt)+'/'+str(resolution))
                temp = params[i]
                temp.append(self.objective_function(params[i]))
                obj_function.loc[i] = temp
                compt += 1
            # Graphical Representation 
            figadd.figure_init(xlab=column_names[0],ylab="",figname='objective function 1D of ' + self.params.name[0])
            plt.plot(obj_function.values[:,0],obj_function.values[:,1])
            plt.yscale("log")
            if self.params.name[0] == 'k':
                plt.xscale("log")
            plt.savefig(os.path.join(self.directory_results,name),dpi=300)
        elif len(self.params.name) == 2 : 
            # 2 parameters
            # Figure Initialization
            n = int(np.ceil(resolution**(1/2)))     
            p1 = pmin[0] + (pmax[0] - pmin[0]) * np.arange(0,n+1) / n
            p2 = pmin[1] + (pmax[1] - pmin[1]) * np.arange(0,n+1) / n
            p2 = p2[::-1]
            params_values.append(p1)
            params_values.append(p2)
            obj_function = np.zeros((len(p1),len(p2)))
            temp=[None]*2
            for i in range(len(p1)):
                for j in range(len(p2)):
                    print(str(compt)+'/'+str(len(p1)*len(p2)))
                    temp = [p1[i],p2[j]]
                    obj_function[j][i] = np.log10(self.objective_function(temp))
                    compt += 1
            # colormap
            X,Y= np.meshgrid(p1, p2)
            Z=obj_function.reshape((len(p1),len(p2)))
            figadd.figure_init(xlab=column_names[0],ylab=column_names[1],figname='Objective function 2D')
            plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
            plt.colorbar()
            # Whatevert the dimension, saves figure
            plt.savefig(os.path.join(self.directory_results,name),dpi=300)
        elif len(self.params.name) == 3 : 
            # 3 parameters
            for k in range(len(self.params.name)):
                k1=(k+1)%len(self.params.name)
                #k2=(k+2)%len(self.params.name)
                n = int(np.ceil(resolution**(1/2))) 
                p1 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n 
                p2 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n 
                p3 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n
                p2 = p2[::-1]
                params_values.append(p1)
                params_values.append(p2)
                params_values.append(p3)
                obj_function = np.zeros((len(p1),len(p2)))
                temp=[None]*len(self.params.name)
                for i in range(len(p1)):
                    for j in range(len(p2)):
                        temp = [p1[i],p2[j],p3[int(len(p3)/2)]]
                        obj_function[i][j] = self.objective_function(temp)
                X,Y= np.meshgrid(p1, p2)
                Z=obj_function.reshape((len(p1),len(p2)))
                # Figure Initialization
                figadd.figure_init(xlab=column_names[k],ylab=column_names[k1],figname='objective function 3D')
                # colorbar
                plt.pcolor(X,Y,Z,cmap=figadd.cmap_white_jet())
                plt.colorbar()
                # Whatevert the dimension, saves figure
                plt.savefig(os.path.join(self.directory_results,name),dpi=300)
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
        store['params_name'] = self.params.name
        store['params_min'] = self.params.p_min
        store['params_max'] = self.params.p_max
        store['params_values'] = params_values
        store['data_obs'] = self.data_obs
        store['data_sim'] = self.data_sim
        store['data_ind'] = self.data_ind
        store['objective_function'] = obj_function
        store['recharge'] = self.watershed.forcing.recharge
        store['calib_zone'] = self.watershed.hydrodynamic.calib_zones
        with open(os.path.join(self.directory_results, name + '.calib'), 'xb') as config_dictionary_file:
            pickle.dump(store, config_dictionary_file)
        config_dictionary_file.close()


