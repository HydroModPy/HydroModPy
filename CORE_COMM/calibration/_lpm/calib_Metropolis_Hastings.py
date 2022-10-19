# -*- coding: utf-8 -*-
"""
Created on Wed Mar 24 20:35:54 2021

@author: dreuzy
"""

import copy as copy
import numpy as np
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd                                     
import sys as sys  

import calibration_basis as calbas
import calibration_synthetic_test as cst
import LPM_dist
import global_parameters as gp                              



def gauss(x, x0, sigma):
    """ Classical Gaussian function """
    num = math.exp( - ( x - x0 )**2 / ( 2.0 * sigma **2 ) )
    den = math.sqrt( 2 * math.pi * sigma **2)
    return  num / den


class MH_Trajectory: 
    """ 
        Trajectory of optimization function
            Used for monitoring
            Adds significant numerical load, Should not be run systematically
        
        Attributes
        ----------
        path: dataframe
            Storage of Trajectory 
            Example
        
        Methods
        -------
        
        
    """
    
    def __init__(self,params,nstep):
        """
        """
        names = []
        for t in params:
            names.append(t)
        names.append('-log_posterior')
        self.n_inc = len(names)
        names.append('incrementation')
        self.path = pd.DataFrame(data=None, index=range(nstep), columns=names, dtype=None, copy=False)
     
        
    def update(self,i,params,log_posterior):
        """ Updates strucutre at step i 
        """
        temp = copy.deepcopy(params)
        temp.append(-log_posterior)
        temp.append(0)
        self.path.iloc[i,:]=temp
        
        
    def inc_one(self,i):
        self.path.iloc[i,self.n_inc] = 1
        
        
    def check(self): 
        """ A posteriori distribution should give values of cocnentration in the expected range
            With expected variance
        """
        columns = list(self.path)
        for t in columns:
            temp = self.path.iloc[:][t]
            temp_mean = np.nanmean(self.path.iloc[:][t].to_numpy(),dtype='float')
            temp_var = np.nanvar(self.path.iloc[:][t].to_numpy(),dtype='float')
            print('%.4f' % temp_mean, '%.4f' % np.sqrt(temp_var), '<> & \u03C3 of', t)
        
        
    def plot(self,directory_name):
        """ Graphical Representation of Trajectory
        """
        columns = list(self.path)
        for t in columns:
            if(t=='-log_posterior' or t=='objective_function'):
                ax = self.path.plot.line(y=t,logy=False)
            else: 
                ax = self.path.plot.line(y=t,logy=False)
            fig = ax.get_figure()
            if directory_name != None : 
                fig.savefig(os.path.join(directory_name,'MH_trajectory_'+t))
                plt.close(fig)


    def validation_MH_prior(self,MHapriori_dist,MHapriori_para,lpm): 
        """ A posteriori distribution should give values of cocnentration in the expected range
            With expected variance
        """
        MH_difference = copy.deepcopy(MHapriori_para)
        columns = list(self.path)
        for key in lpm.p.keys():
            temp = self.path.iloc[:][key]
            temp_mean = np.nanmean(self.path.iloc[:][key].to_numpy(),dtype='float')
            temp_var = np.nanvar(self.path.iloc[:][key].to_numpy(),dtype='float')
            # print('%.4f' % temp_mean, '%.4f' % np.sqrt(temp_var), '<> & \u03C3 of', key, 'computed')
            # print('%.4f' % MHapriori_para[key][0], '%.4f' % MHapriori_para[key][1], '<> & \u03C3 of', key, 'target')
            apriori_mean = 0
            apriori_std = 0
            if MHapriori_dist[key] == 'normal':
                apriori_mean = MHapriori_para[key][0]
                apriori_std = MHapriori_para[key][1]
            elif MHapriori_dist[key] == 'uniform':
                apriori_mean = (MHapriori_para[key][0] + MHapriori_para[key][1]) / 2
                apriori_std = (MHapriori_para[key][1] - MHapriori_para[key][0]) / np.sqrt(12)
                
            MH_difference[key][0] = 100 * (1-temp_mean/apriori_mean)
            MH_difference[key][1] = 100 * (1-np.sqrt(temp_var)/apriori_std)
            print('\nCheck MH prior distribution\n')
            print('%.4f' % MH_difference[key][0], '%.4f' % MH_difference[key][1], ' Diff-Percent <> & \u03C3 of', key)
            

class MH_step: 
    """ Computation Method of Metropolis Hastings Step"""
    def __init__(self):
        self.method = "prop"     # selection by proportionality of the boundary interval "prop" OR by value "value"
        self.value = 1
        self.prop = 0.1
        self.interval = 0 
        
    def define_by_value(self): 
        self.method = "value"
        
    def define_by_prop(self,prop): 
        self.method = "prop"
        self.prop = prop
        
    def define_value_by_interval(self,lpm):
        self.interval={}
        self.value={}
        for key in lpm.p.keys():
            # Perturbation factor of the MCMC MH algorithm, key of the convergence of the algorihm
            self.interval[key] = lpm.get_param_range(key)
            self.value[key] = self.prop * self.interval[key]
      
    def load_MHsteps(self,lpm):
        # Loads file in which the bounds of the parameters are stored
        temp = pd.read_csv(lpm.lpm_parameter_file("MHstep.txt"),header=None)
        # A priori distribution for each of the parameters
        self.value={}
        for i in range(len(temp.values[:,0])): 
            self.value[temp.values[i,0]] = temp.values[i,1]

    def prepare(self,lpm):
        """ Driving prepration function """
        if self.method == "prop" : 
            self.define_value_by_interval(lpm)
        else:
            self.load_MHsteps(lpm)

    def save_param(self,data):
        """ writes delta step parameters in data for parameter outputs """
        data['MH_delta_method'] = self.method
        for param in self.value : 
            data['MH_delta_'+param] = self.value[param]



class CalibrationMetropolisHastings(calbas.CalibrationBasis) : 
    """ 
    Metropolis_Hastings Monte-Carlo Markov Chain Algorithm (MH MCMC)
        to calibrate lpm accounting for uncertainty in the data and possibly for a-priori distributions on parameters 
        Requires large number of evaluations of the objective function (10^5-10^6-10^7)
        
    Reference in groundwater dating litterature: 
        Massoudieh, A., S. Sharifi, and D. K. Solomon (2012), 
            Bayesian evaluation of groundwater age distribution using radioactive tracers 
            and anthropogenic chemicals, Water Resources Research, 48, doi:10.1029/2012wr011815.
            posterior distribution: equation (16)
    Reference for the importance of jumping rules and stepsize
    In a nutshell, stepsize of MH is large enough to ensure a good space coverage at the cost of computational under-optimality
            Optimatlly, stepsize is of the order of 2.5 times the variance of the posterior distribution (Liu, 2021)
            Automatic adaptation of the stepsize may bias the algorithm with no guarantee of convergence (Beskos, 2013)
            Optimality is reached when acceptance rate is around 0.234 (Atchade, 2011)
        Beskos, A., N. Pillai, G. Roberts, J. M. Sanz-Serna, and A. Stuart (2013), 
            Optimal tuning of the hybrid Monte Carlo algorithm, Bernoulli, 19(5A), 1501-1534, doi:10.3150/12-bej414.
        Liu, J. S., and C. Dai Metropolis Jumping Rules, in Wiley StatsRef: 
            Statistics Reference Online, edited, pp. 1-12, doi:https://doi.org/10.1002/9781118445112.stat08237.
        Atchade, Y. F., G. O. Roberts, and J. S. Rosenthal (2011), 
            Towards optimal scaling of metropolis-coupled Markov chain Monte Carlo, Stat. Comput., 21(4), 555-568, doi:10.1007/s11222-010-9192-1.
        
    Attributes, public
    -------------------
        method: str
            "Metropolis_Hastings", necessary for the parent class 
        MH_step: MH_step Class
            Stepping determination method (a critical point of the methodology)
    
    Attributes, private
    -------------------
        __nstep: int
            number of steps 
        __burn_in: float
            Fraction of the nstep used for the burn-in phase 
            Number of burn in steps = burn_in * nstep
        __prior_option: bool
            Should prior be included in the calibration 
        __likelyhood_option: bool
            Should likelyhood be included in the calibration 
        __seed: int
            Seed of the Random Number Generator
        __succes_rate: float
            Rate of success of Metropolis Hastings algorithm (should be between 0.2 and 0.45)
        __traj_monitor: bool
            monitoring of trajectory of MCMC Algorithm, activation of the trajectory class
        __traj_display: bool 
            display trajectory
        __traj_text: bool 
            display trajectory comments #JR 05/08: Necessary to have 2 options __traj_display and __traj_text ? 
    
    Methods
    -------
        self.lpm.p_dist : LPMdist
            distribution of parameter values
            
    """   
    
    def __init__(self,nstep=10000,burn_in=0.2,nskip=10,prior=True,likelyhood=True,monitor=True,display_traj=False,display_text=False):
        """ Constructor: definition of  MH parameters 
        """
        # Parameters
        self.method="Metropolis_Hastings"
        self.__nstep = nstep
        self.__burn_in = burn_in
        self.__nskip = nskip 
        self.__traj_monitor = monitor
        self.__traj_display = display_traj
        self.__traj_text = display_text
        self.__prior_option = prior
        self.__likelyhood_option = likelyhood 
        self.__seed = 12345
        # MH step = delta * Delta (parameter bounds)
        self.MH_step = MH_step()
        # A priori distributions
        self.MHapriori_dist = {}
        self.MHapriori_para = {}        
        # Results
        self.__success_rate = 0
        self.time_perform = 0 
    
    
    def update_calibbasis(self,calib_basis): 
        """
        Updates parent class CalibrationBasis with calib_basis
        
        Arguments
        ---------
        calib_basis: CalibrationBasis
            Base Class Calibration Problem
        
        """
        super(CalibrationMetropolisHastings,self).__dict__.update(calib_basis.__dict__)
    
    
    def __prior_load(self,lpm): 
        """ Loads a priori of the parameter distribution 
        """
        # Loads file in which the bounds of the parameters are stored
        temp = pd.read_csv(lpm.lpm_parameter_file("MHapriori.txt"),header=None)
        # A priori distribution for each of the parameters
        for i in range(len(temp.values[:,0])):
            self.MHapriori_dist[temp.values[i,0]] = temp.values[i,1]
            self.MHapriori_para[temp.values[i,0]] = []
            self.MHapriori_para[temp.values[i,0]].append(temp.values[i,2])  
            self.MHapriori_para[temp.values[i,0]].append(temp.values[i,3])   
    
    
    def __prior_eval(self,lpm,params):
        """ Posterior distribution 
            Metropolis_Hastings
            May be specific to the distribution type, explaining why it is in LPM class or its daughter classes
        """
        proba = 1
        ikey = 0
        for key in lpm.p.keys(): 
            if self.MHapriori_dist[key] == 'normal': 
                proba = proba * gauss(params[ikey], self.MHapriori_para[key][0], self.MHapriori_para[key][1])
            elif self.MHapriori_dist[key] == 'uniform':
                if(params[ikey] > self.MHapriori_para[key][0] and params[ikey] < self.MHapriori_para[key][1]):
                    proba = proba / np.abs(self.MHapriori_para[key][1] - self.MHapriori_para[key][0])
                else : 
                    proba = 0 
            else : 
                print('Problem in __prior_eval of lpm, option ', self.MHapriori_dist[key], 'not defined')
                sys.exit()
            ikey = ikey + 1
        # To avoid any issue by taking the next log of the probability 
        if proba == 0 : 
            proba = 1e-300
        return proba
    
    
    def __param_inc(self, p0, lpm, rng):
        """ Increment parameters  
            Metropolis_Hastings
        """
        # Required deepcopy to avoid p0 to be modified if not chosen eventually
        p1 = []
        k = 0
        # pf = self.MH_step.delta()
        for key in lpm.p.keys():
            # Perturbation factor of the MCMC MH algorithm, key of the convergence of the algorihm
            p1.append(p0[k] + self.MH_step.value[key] * rng.standard_normal())
            k = k + 1
        return p1


    def __posterior_eval(self,params,data_c,data_error) : 
        """ posterior distribution 
        """
        proba = 0
        # If parameters are out of bounds, returns immediatly 0 
        if self.lpm.param_within_bounds_array(params) == False : 
            return -math.inf, math.inf
        if(self.__likelyhood_option): 
            objfunc = self.objective_function( params, data_c, data_error)
            proba = proba - 0.5 * objfunc #1
        else :
            objfunc = 0
        if(self.__prior_option):
            proba = proba + np.log(self.__prior_eval(self.lpm,params)) 
        return proba, objfunc

    
    def __prepare_storage(self): 
        """ 
        Prepares array for storage of results
        
        Returns 
        -------
        sto: np.array
            with the required shape for the storage
        """
        line=0
        for i in range(self.__nstep):        
            if i > self.__burn_in * self.__nstep and i % self.__nskip == 0:
                line = line + 1
        column = len(self.lpm.p) + 1 + len(self.concentration_sampled.names_dates()) + 1
        return np.zeros((line,column),dtype=float)
    
    
    def perform(self):
        """
        Metropolis_Hastinvs Monte-Carlo Markov Chain Algorithm (MH MCMC)
            Main function
            Monitor run time necessary
        
        Modifies
        -------
            self.lpm.p_dist : LPMdist
                distribution of parameter values
                
        Returns
        -------
        lpm_results: LPMDist (class)
            lpm Parameters, objective function and concentration solutions
        """   

        # --------------- PREPARATION PHASE ------------------------
        # Forces monitoring to true for the test of the algorithm on the sole prior
        if self.__likelyhood_option == False and self.__prior_option == True : 
            self.__traj_monitor = True
        # Initialization of random number generator
        rng = np.random.default_rng(self.__seed)
        # Concentration values as array: necessary for optimal numerical efficiency
        data_c = self.concentration_sampled.cv.values[:,gp.CONCENTRATION]
        data_error = self.concentration_sampled.cv.values[:,gp.ERROR]        
        # Initialization of stepping interval 
        self.MH_step.prepare(self.lpm)
        # Trajectory monitorting
        if self.__traj_monitor : 
            traj = MH_Trajectory(self.lpm.p.keys(),self.__nstep)  
        # Loads a priori for the distribution of parameters
        self.__prior_load(self.lpm)
        # Initialization of results structure 
        array_results = self.__prepare_storage()
        
        # --------------- INITIALIZATION PHASE ----------------------
        # Initialization of calibration parameters with default parameters of distribution 
        self.lpm.param_init()
        # Gets parameters in an array (compulsory for performance of the loop)
        params = self.lpm.get_parameters_to_array()
        # Value of the posterior distribution for initial set of parameters
        temp = self.__posterior_eval(params,data_c,data_error); p=temp[0]; obj_func = temp[1]
        n=0
        nsuccess=0
        
        # --------------- MONTE CARLO MARKOV CHAIN LOOP ------------
        line=0
        for i in range(self.__nstep):
            # Modification of parameter values: 
            params_n = self.__param_inc(params,self.lpm,rng)
            # Value of the posterior distribution for the new set of parameters (attention: expression in log because of a loss of values with large negative values of arguments for the exponential function)
            temp = self.__posterior_eval(params_n,data_c,data_error); pn=temp[0]; obj_func_n = temp[1]
            success = False
            if pn >= p:
                success = True
            else:
                u = rng.random()
                if np.log(u) < pn-p:
                    success = True
            if success == True : 
                params = params_n
                p = pn   
                obj_func = obj_func_n
                nsuccess=nsuccess+1
            if i > self.__burn_in * self.__nstep and i % self.__nskip == 0:
                # Storage : everything relative to params and not params !!! (sources of errors to take params_n)
                conc = self.tracers.convolution_from_param(params, self.lpm)
                array_results[line] = params + \
                                      [np.sqrt(obj_func/len(conc))] + \
                                      conc + \
                                      [1.0]
                line=line+1
                # lpm_results.dist_append_array(params,obj_function=np.sqrt(obj_func/len(conc)),
                #                               concentrations=conc,param_in_bounds=True) 
                if self.__traj_monitor :
                    traj.update(n,params,-p)
                    traj.inc_one(n)
                    n = n + 1
        
        # --------------- POSTPROCESSING PHASE -------------------
        # Results consolidation
        self.__success_rate=nsuccess/self.__nstep
        lpm_results = LPM_dist.LPMDist(self.lpm,c_names=self.concentration_sampled.names_dates())
        lpm_results.fill_np_array(array_results,self.lpm.get_param_names() + \
                                                ['obj_function'] + \
                                                self.concentration_sampled.names_dates() + \
                                                ['param_in_bounds'])
        
        # Displays Trajectory
        if self.__traj_monitor : 
            if self.__traj_display : 
                traj.plot(self.directory_results)
            if self.__traj_text : 
                traj.check()
            
        # Checks algorithm with prior distribution 
        if self.__likelyhood_option == False and self.__prior_option == True : 
            traj.validation_MH_prior(self.MHapriori_dist,self.MHapriori_para,self.lpm)
    
        return lpm_results
    
    
    def write_parameters(self,file_name):
        """ 
        Writes parameters of calibration
        """
        data={}
        data['method']=self.method
        data['nstep'] = self.__nstep
        data['burn-in'] = self.__burn_in
        data['prior_option'] = self.__prior_option
        data['likelyhood_option'] = self.__likelyhood_option
        self.MH_step.save_param(data)
        data['seed'] = self.__seed
        file = open(file_name,"w")
        for key, val in data.items():
            file.write(key+'\t'+str(val)+'\n')
        file.close()
        
        
    def write_results_spec(self,data):
        """
        Specific contribution of the daughter class to the calibration results
        
        Argumments
        ----------
        data: dictionary
            results to be stored
        
        """
        data['success_rate'] = self.__success_rate


def test_calibration_MH_prior(display_options): 
    """ 
    Tests MH Calibration
        on a priori distribution of lpm parameters 
        distribution are generally uniform or Gaussian
        They are defined in the files of folder LPM_data in the directory sources/ of the repository
    """
    display = copy.deepcopy(display_options)
    display.figure = False
    display.text = False 
    display.directory = gp.results_directory(display.directory,"Metropolis_Hastings_validation")

    print('\nVALIDATION OF METROPOLIS-HASTINGS ON PRIOR ONLY')
    models_calib = ['exp','uniform','dirac','gamma','ig']
    for lpm in models_calib:  
        calib_MH = CalibrationMetropolisHastings(nstep=10000,prior=True,likelyhood=False,
                                                 monitor=True,display_traj=True)
        calib = cst.CalibrationSyntheticTest(calib_strategy=calib_MH,ncase=1,error=0.0,tracer_names=["cfc11"],
                                                 date=2000,lpm=lpm,display_options=display)
        calib.perform_ncase()
