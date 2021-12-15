# -*- coding: utf-8 -*-
"""
Created on Mon Mar 22 09:29:57 2021

@author: dreuzy
"""

import abc
import copy as copy
import math
import matplotlib.pyplot as plt         # Plots
import numpy as np                      # Arrays
import os
import pandas as pd                     # Tables-Arrays
from scipy import integrate             # Quadrature
from scipy import optimize
import sys
       

class LPM(abc.ABC): 
    """  
    Lumped Parameter Model, pure virtual class

    Inheritance
    -----------
    LPMDist : class
        Class containing distribution of values of LPM

    Attributes, public
    ----------
    name : str
        name of LPM 
    p : dictionary
        p["parameter name"] = parameter values 

    Attributes, private
    ----------
    __u : dictionary 
        p["parameter name"] = parameter unit
    __p_min : dictionary
        __p_min["parameter name"] = parameter lower bound 
        Loaded from external file 
    __p_max : dictionary
        __p_max["parameter name"] = parameter higher bound
        Loaded from external file 
    __directory_lpm_data : str
        directory of the parameters necessary for the models 
    
    Methods (defined in this class)
    -------
    param_within_bounds(self,param)
        Test whether parameters are in the [lower,higher] intervals
    random_uniform(self,rng=None)
        Random uniform generation of lpm within parametr range defined by get_param_interval(), modifies self
    set_param_from_array(self, param)
        Sets parameters from array with same ordered required 
    get_parameters_to_array(self)
        Gets parameters to an array (same order as in the dictionary)
    __moment_k(self,k)
        Computes and returns the moment of order k
    __support_range(self)
        define typical [min,max] interval on which the pdf is defined   
        
    Methods-Pure Virtual (defined in the daughter classes, required)
    --------------------
    pdf(self,t)
        probability density function: should be defined in daughter class

    Methods-Virtual (defined in the daughter classes, when relevant, template alternative given in mother class)
    ---------------
    cdf(self,t)
        cuumative density function 
    cdf_inv(self,p)
        inverse of the cumulative density function
    mean(self):
        Returns mean of distribution
    std(self):
        Returns std of distribution
    
    """
    
    def __init__( self, name, parameter_values, parameter_units, directory_lpm_data):
        """ 
        Constructor
        
        Arguments
        ---------
        name: str
            LPM name
        parameter_values: dictionary 
            parameter_values["parameter name"] = parameter values 
        parameter_units : dictionary 
            parameter_units["parameter name"] = parameter unit 
        directory_lpm_data : str
            directory of the parameters necessary for the models        
        """
        # Name of LPM (e.g. IG, EXP)
        self.name = name
        # Parameter Values
        self.p = parameter_values     
        # Parameter Units 
        self.__u = parameter_units  
        # Bounds of distribution parameters
        self.__p_min = {}
        self.__p_max = {}
        if directory_lpm_data == None : 
            print("pb in the LPM data directory definition, should not be proceeded")
            # sys.exit()
        self.__directory_lpm_data = directory_lpm_data
        # Load lower and higher bounds 
        self.__load_bounds()


    @abc.abstractmethod
    def pdf(self,t):
        """ 
        Probability Density Function
        Should be defined in the daughter class 
        
        Arguments
        ---------
        t : scalar or vector
        
        Returns
        -------
        pdf: scalar of vector (same size as input t)
            Probability density function 
        """
        pass
        # print("CRITICAL ERROR, pdf should not be called in LPM mother class")
        # sys.exit()

        
    def __moment_k(self,k): 
        """ 
        Returns moment k of distribution (discretized)
        """
        [tmin,tmax]=self.__support_range()
        t = np.linspace(tmin, tmax, 1000)
        pdf = self.pdf(t)
        return integrate.simps(t**k * pdf, t, even='first')

    
    def mean(self):
        """ 
        Returns mean of distribution 
        """
        return self.__moment_k(1)
    
    
    def std(self):
        """ 
        Returns std of distribution 
        """
        return np.sqrt(self.__moment_k(2)-self.__moment_k(1)**2)
        
        
    def random_uniform(self,rng=None):
        """ 
        Random uniform generation of lpm 
            Modifies self with unifom random generation of parameters 
            Parameters are drawn from get_param_interval()
        """
        # Gets parameter range
        res=self.get_param_interval(); pmin = res[0]; pmax = res[1]
        # Generation of parameter within the range 
        if(rng==None):
            rng = np.random.default_rng()
        param=[]
        for i in range(0,len(pmin)):
            param.append(pmin[i] + (pmax[i] - pmin[i]) * rng.random())
        # Loads parameters in self
        self.set_param_from_array(param)


    def param_init(self):
        """ 
        Initialization parameters in an array
            Does not change the parameters in self
                
        Returns
        -------
        array
            Parameters in an array format
        
        """
        lpm_temp = copy.deepcopy(self)
        lpm_temp.load_param_values(self.lpm_parameter_file("simplex_init.txt"))
        return lpm_temp.get_parameters_to_array()
        
    
    def lpm_parameter_file(self,file_name): 
        """ 
        Directory + File where the lpm parameters are defined
        
        Arguments
        ---------
        File Name 
        
        Returns
        -------
        Full directory + file name 
        """
        return os.path.join(self.__directory_lpm_data,self.name,file_name)
        
    
    def load_param_values(self,file_name):
        """ 
        Loads parameter file 
            From file called LPM_"name"_bounds.txt
        File structure
            param_name,param_value,unit
        File example 
            mu1,5,year
            mu2,10,year
            rate,0.25,-
        
        Argument
        --------
        file_name : str
            Name of the file
        
        Returns
        -------
        dictionary
            p["param_name"]=param_value
        """
        # Loads file in which parameters are stored   
        temp = pd.read_csv(file_name,header=None)
        # Affects param_values to the distribution
        for i in range(len(temp.values[:,0])):
            self.p[temp.values[i,0]] = temp.values[i,1]         
        
    
    def __load_bounds(self):
        """ 
        Loads lower and higher bounds of each of the distribution parameter 
            From file called LPM_"name"_bounds.txt
        File structure
            param_name,lower_bound,higher_bound,unit
        File example 
            mu1,0,100,year
            mu2,0,100,year
            rate,0,1,-
        """
        # Loads file in which the bounds of the parameters are stored   
        temp = pd.read_csv(self.lpm_parameter_file("bounds.txt"),header=None)
        # Affects bounds to the distribution
        for i in range(len(temp.values[:,0])):
            self.__p_min[temp.values[i,0]] = temp.values[i,1]
            self.__p_max[temp.values[i,0]] = temp.values[i,2]         
        
        
    def param_within_bounds(self,params):
        """ 
        Test whether parameters are within the defined bounds
        
        Arguments
        ---------
        params: dictionary 
            params to be tested, same structure as self.p
        Returns
        -------
        bool: test 
        """
        test = True
        for pname in params: 
            val = params[pname]
            if(val < self.__p_min[pname] or val > self.__p_max[pname]):
                test = test * False
        return test


    def param_within_bounds_array(self,params):
        """ 
        Test whether parameters are within the defined bounds
        
        Arguments
        ---------
        params: array 
            params to be tested
            parameters should be in the same order as in the dictionary self.p
        Returns
        -------
        bool: test 
        """
        test = True
        ikey = 0 
        for pname in self.p: 
            val = params[ikey]
            if(val < self.__p_min[pname] or val > self.__p_max[pname]):
                test = test *False
            ikey = ikey + 1
        return test

    
    def cdf(self,t):
        """ 
        Cumulative Density Function
            Should be defined in the daughter class 
            Can be called here as the integration of the pdf 
            Function does not critically intervene in the code, mostly plotting purposes
        
        Arguments
        ---------
        t : scalar or vector
        
        Returns
        -------
        cdf: scalar of vector (same size as input t)
            Cumulative density function 
        """
        val=[0]*len(t)
        for i in range(len(t)):
            val[i]=integrate.quadrature(self.pdf, 0.0, t[i])[0]
        return val
                

    def cdf_minus_p(self,t,p): 
        """ 
        Instrumental function for cdf_inv """
        return (self.cdf(t)-p)**2

    
    def cdf_inv(self,p):
        """ 
        Inverse of the Cumulative Density Function, t=cdf^-1(p)
            Usefull for the computation of quantiles
            Should be defined in the daughter class (this function should never be called, only the template)
        
        Arguments
        ---------
        p : float
            probability
        
        Returns
        -------
        float
            time corresponding to cdf^-1(p)
        """
        t0=10
        res=optimize.root(self.cdf_minus_p, t0, args=(p), method='hybr', jac=None, tol=None, callback=None, options=None)
        return res.x[0]
    
    
    def set_param_from_array(self, param):
        """ Sets parameters from array 
            From array to dictionary
        """
        k = 0
        for key in self.p:
            self.p[key]=param[k]
            k = k + 1
    
    
    def get_parameters_to_array(self):
        """ Gets parametes from array
        """
        param=[]
        for key in self.p:
            param.append(self.p[key])
        return param
    
     
    def get_param_names(self): 
        """ Returns parameter names 
        """
        param=[]
        for key in self.p.keys(): 
            param.append(key)
        return param
    
      
    def get_param_range(self,param_name): 
        """
        Gets the range of parameters
        
        Arguments
        ---------
        param_name: str
            name of parameter
        
        Returns
        -------
        float
            Range of parameter values 
        """
        return self.__p_max[param_name] - self.__p_min[param_name]
        
    
    def get_param_interval(self): 
        """
        Gets the interval of parameters
        
        Arguments
        ---------
        
        Returns
        -------
        pmin: array
            Values of the parameters lower bouds
        pmin: array
            Values of the parameters higher bounds
        """
        pmin=[]; pmax=[]
        for key in self.__p_min :
            pmin.append(self.__p_min[key])
            pmax.append(self.__p_max[key])
        return pmin, pmax
    
    
    def get_p_max(self,key): 
        return self.__p_max[key]
    
    
    def get_p_min(self,key): 
        return self.__p_min[key]
    
    
    def display(self,display_options):
        """ Displays LPM
        """
        if display_options.text : 
            print("LPM type:", self.name)
            print("Parameters:")
            for key in self.p.keys() : 
                print("\t", key,"\t=", self.p[key], self.__u[key])

    
    def __support_range(self):
        """ 
        Defines Support Time Range 
            Specific to the distribution itself and to its parameters
        
        Returns
        -------
        tmin: float
            Minimum time of support range
        tmax: float
            Maximum time of support range 

        """
        tmin = 0 # factor * self.ppf(0.05)
        tmax = 1.2 * self.cdf_inv(0.98) 
        return tmin, tmax
    

    def discret_pdf_cdf(self,type_pc,n):
        """ 
        discretization of pdf or cdf 
            discretization in n steps in the range defined by the __support_range function 
        
        Arguments
        ---------
        type_pc : str either "pdf" or "cdf"
            type of density function to discretization
        n : int
            number of diescretization setps
        
        Returns
        -------
        t: array
            discret values of times
        val: array
            disret values of pdf or cdf
            
        """
        tmin, tmax = self.__support_range()
        t = np.linspace(tmin, tmax, n)
        if(type_pc=='pdf'):
            values = self.pdf(t)
        elif(type_pc=='cdf'): 
            values = self.cdf(t)
        else: 
            print('error for display plot')
        return t, values
    
    
    def plot(self,type_pc,display_options):
        """ 
        Plots distribution (pdf or cdf)
            discretization in n steps in the range defined by the __support_range function 
        
        Arguments
        ---------
        type_pc : str either "pdf" or "cdf"
            type of density function to discretization
        display_options : display_options class instance
            figures that should displayed
            
        """
        if display_options.figure : 
            # Plotting the pdf or the cdf
            # Getting pdf or cdf values
            t,values = self.discret_pdf_cdf(type_pc,1000)
            # defines figure style to be applied to all callign figures
            plt.figure()#(figsize=(4,4))
            plt.xlabel('t',fontsize=16,fontweight='bold'); plt.xticks(fontsize=14)
            plt.ylabel('f(t)',fontsize=14,fontweight='bold'); plt.yticks(fontsize=14); 
            plt.title(type_pc+" of "+self.name,fontsize=22,fontweight='bold'); plt.grid(True)
            if len(t) != len(values): 
                print("Problem in the dimenstion of t and values")
                sys.exit()
            plt.plot(t, values, 'r', label=self.name); plt.show()
            # limits x,y range
            plt.xlim((0,max(t)))
            if max(t)==0 : 
                print(max(t))
            if(max(values)<=0): 
                ylim = 1
            else: 
                ylim = max(values)*1.1
            if math.isnan(ylim) == False and math.isinf(ylim) == False : 
                plt.ylim((0,ylim))
            display_options.figure_close_fx(self.name+"_"+type_pc)
            # axe des ordonnées en échelle logarithmique
            # plt.yscale('log')
    
    
    def display_parameters(self,lpm_reference=None) :
        """ Display values of parameters of the lpm
        """
        if lpm_reference == None :
            for key in self.p:
                print(key, '\t', '%.2f' % self.p[key])
        else :
            for key in self.p:
                print(key, '\t', 'target ', '%.2f' % lpm_reference.p[key], '\t calibrated', '%.2f' % self.p[key], '\t', 
                      'difference rate', '%.1e' % (self.p[key]/lpm_reference.p[key]-1))
           
                
    def display_pdf_cdf(self,display_options):
        """ Checks consistency of distribution
        """
        self.display(display_options)
        self.plot('pdf',display_options)
        self.plot('cdf',display_options)
        
        
    def write_name(self,file): 
        """ write lpm name to file
        """
        file.write("lpm\t"+self.name+"\n")
        
        
    def write(self,file,open_file=False): 
        """ 
        write lpm name and values to file
        
        Arguments
        ---------
        file: str or opened file
            open_file == True: Name of the file
            open_file == False: Opened file
        open_file: bool
        
        """
        if open_file == True : file = open(file, "w")
        self.write_name(file)
        for key in self.p:
            file.write(key+'\t'+str(self.p[key])+'\t'+str(self.__u[key])+'\n')
        if open_file == True: file.close()
                 

    def load_from_dist_file(self,dist,option,rng):
        """ 
        Loads random parameter values from distribution file 

        Arguments
        ---------
        dist : pandas dataframe
            distribution of parameter values
        option : str
            "random", choice of a random line
            any other str, first line 
        
        Returns
        -------
        bool
            instantiation success
        line
            corresponding line of the file
        
        """
        if len(dist.index)==0: 
            return [False,0]
        else: 
            # Choice of line of file
            if option == "random": 
                line = int(rng.random()*len(dist.index))
            else: 
                line = 1
            if line > len(dist.index) :
                line = len(dist.index)
            # Instantiates parameter values
            for key in self.p.keys(): 
                self.p[key]=dist[key][line]
            return [True,line]
        
        
    def moments_name(self):
        """ 
        Returns moment names 
        """
        return ['mean','std','quart25','median','quart75']
        
    
    def moments(self):
        """ Compute the statsitical characteristic of the distribution
        """
        return [self.mean(),self.std(),self.cdf_inv(0.25),self.cdf_inv(0.5),self.cdf_inv(0.75)]
    
    
    def display_moments(self):
        """ Displays computed moments 
        """
        print("\nmoments")
        names = self.moments_name()
        values = self.moments()
        for i in range(0,len(names)): 
            print(names[i],"",values[i])
        print("\n")
        
        
    def output_dataframe(self): 
        """ Outputs model in dataframe
        """
        data={'LPM_name':self.name}
        for key in self.p: 
            data[key]=self.p[key]
        return pd.DataFrame(data,index=[0])
        


