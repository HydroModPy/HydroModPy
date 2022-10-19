# -*- coding: utf-8 -*-
"""
Created on Tue May 18 21:14:24 2021

@author: dreuzy
"""
import numpy as np
import os
import pandas as pd

import convolution_tracers as convolution_tracers                     
import global_parameters as gp
import LPM_generate as LPM_generate

import calibration_basis as calbas


class CalibrationSyntheticTest:
    """ 
    Synthetic Testing of Calibration algorithms 
        For any type of lpm
        1. Generates a lpm
        2. Computes synthetic concentrations by convolution of the tracer at the given date
        3. Definition of error for these syntetic "data" using a dedicated random number generator (for reproductibility)
        4. Use these data to calibrate a lpm of the same type with the calibration properties defined in self.calib_strategy
    
    Attributes
    ----------
    __lpm_type: str
        Name of lpm with which the test will be performed 
    __tracer_names: array of str
        Name of tracers with which the test will be performed 
    __ncase: int
        Number of synthetic cases handled 
    __error: float
        Level of errors to add to the synthetic data (in fraction, eg 0.01 is 1%)
    __directory: str
        folder to store results
    calib_strategy: CalibrationSimplex, CalibrationMH
        Daughter Class of CalibrationBasis
        Only the methods of mother class CalibrationBasis will be called 
        
    Methods
    -------

    
    """
    
    def __init__(self,calib_strategy=None,display_options=gp.display_options(),lpm='exp',tracer_names=["cfc11","kr85"],
                 ncase=10,error=0.0,date=2010,directory = "test_calibration_"):
        """ 
        Constructor
            Attribute affectations
            Initialization of rng, tracers, storage structure
        
        Parameters
        ----------
        """
        # Attribute affectations
        self.__display_options = display_options
        self.__lpm_type = lpm
        self.__tracer_names = tracer_names
        self.__ncase = ncase
        self.__error = error
        self.__date = date
        self.seed_rng = 1234
        self.calib_strategy = calib_strategy

        # Directory for the storage of test details        
        self.__directory = gp.results_directory(self.__display_options.directory,calib_strategy.method+"_"+self.__lpm_type)
        # Initialization of random number generator
        self.rng = np.random.default_rng(self.seed_rng)
        # Initialization of tracers
        self.tracers = convolution_tracers.ConvolutionTracers(names=self.__tracer_names,date=self.__date)
        # Initialization of storage sructure 
        names=['case','error_concentration_%','objective_mean','objective_std','parameter_name','target','estim_mean','estim_std','estim_min','estim_max',]
        self.store = pd.DataFrame(columns=names)
                       
        
    def __storage_one_case(self,lpm_target,lpm_calib,i):
        """ 
        Storage of results in dataframe
        """
        for t in lpm_target.p:
            # Statistics on results of parameters 
            stats = lpm_calib.get_stats().describe()
            data = {'case':i}
            for key in lpm_target.p : 
                data[key+"_" + "target"] = [lpm_target.p[key]]
                data[key+"_" + "difference"] = [stats.loc['mean'][key] - lpm_target.p[key]]
            for col in stats.columns: 
                for row in stats.index :
                    data[col+"_"+row] = [stats.loc[row][col]]
            # Adds new line
            if i == 0:
                self.store = pd.DataFrame(data)
            else:
                temp = pd.DataFrame(data)
                self.store = self.store.append(temp)            
    
        
    def get_directory(self): 
        """ Accessor to display.directory """
        return self.__directory
    
        
    def write_results(self):
        """ 
        Write synthesis results for all n tests
        File Example: 
            #JR 06/08: Revoir la documentation des résultats synthétiques 
            	case	mu_target	            mu_difference	 scale_target	scale_difference	mu_count	mu_mean	mu_std	mu_min	mu_25%	mu_50%	mu_75%	mu_max	scale_count	scale_mean	scale_std	scale_min	scale_25%	scale_50%	scale_75%	scale_max	obj_function_count	obj_function_mean	obj_function_std	obj_function_min	obj_function_25%	obj_function_50%	obj_function_75%	obj_function_max
        0	    0	   78.13831135918156		30.477639228067464		0.0								0.0								0.0							
        0	    1	   73.86737407774004		21.009224666697182		0.0								0.0								0.0							
        0	    1	   73.86737407774004		21.009224666697182		0.0								0.0								0.0							

        """
        self.store.to_csv(os.path.join(self.__directory,"results.txt"),sep='\t')
        self.store.describe().to_csv(os.path.join(self.__directory,"results_stats.txt"),sep='\t')
        
        
    def write_parameters_test(self):
        """ 
        Write calibration parameters
        File Example: 
            error	       0.01
            date	       [1990, 2010]
            calibration_method	Simplex
            lpm_type	   ig
            tracer_0	   cfc11
            tracer_1	   Li
        """
        data={}
        data['error']=self.__error
        data['date']=self.__date
        data['calibration_method']=self.calib_strategy.method
        data['lpm_type']=self.__lpm_type
        comp = 0
        for t in self.__tracer_names:
            data['tracer_'+str(comp)]=t
            comp = comp + 1
        file = open(os.path.join(self.__directory,"parameters.txt"),"w")
        for key, val in data.items():
            file.write(key+'\t'+str(val)+'\n')
        file.close()

        
    def perform_one_case(self,i):
        """ 
        Performs one test case
        
        Arguments
        ---------
        i: int
            lable of test case
        
        Returns
        -------
        lpm_init: LPM
            Initial conditions of the calibration 
        lpm_calibration: LPM
            Calibrated LPM models 
        data_c
            Concentration Synthetic "data"
        """
        # Preparation: Results directory
        directory_test = gp.results_directory(self.__directory,str(i))
        
        # 1. Generates a lpm
        lpm_init = LPM_generate.LPM_generate_random_uniform(self.__lpm_type,rng=self.rng)
        # 2. Computes synthetic concentrations by convolution of the tracer at the given date, concentration set with this lpm
        data_c = self.tracers.convolution(lpm_init,return_type="concentrations_set")
        # 3. Adds some percentage of uncertainty to these syntetic "data" using a dedicated random number generator (for reproductibility)
        data_c.error_affect_from_value(self.__error)
        
        # 4. Use these data to calibrate a lpm of the same type with the calibration properties defined in calib_strategy
        calib_basis=calbas.CalibrationBasis(data_c,self.__lpm_type,directory_results=directory_test)
        self.calib_strategy.update_calibbasis(calib_basis)
        lpm_results = self.calib_strategy.perform()
        
        # 5. Posprocessing
        # Displays and Writes target and calibrated lpms
        self.calib_strategy.display_lpms(self.__display_options,lpm_results,lpm_reference = lpm_init)
        lpm_init.write(os.path.join(directory_test,"lpm_target.txt"),open_file=True)
        self.calib_strategy.write_calibrated_lpm(lpm_results)
        data_c.cv.to_csv(os.path.join(directory_test,"concentrations.txt"),sep='\t') 
        # Results stores 
        self.__storage_one_case(lpm_init,lpm_results,i)
        return lpm_init, self.calib_strategy, data_c, lpm_results
        

    def perform_ncase(self):
        """ 
        Performs n test
        """
        for i in range(self.__ncase):
            [lpm_init,lpm_calibration,data_c,lpm_results] = self.perform_one_case(i)
        # Writes synthetis on parameters and results
        lpm_calibration.write_parameters(os.path.join(self.__directory,"parameters_calibration.txt"))
        self.write_parameters_test()
        self.write_results()
            
        
