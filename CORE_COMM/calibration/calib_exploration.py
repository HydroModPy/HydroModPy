# -*- coding: utf-8 -*-
"""
Created on Wed Mar 24 20:35:54 2021

@author: dreuzy
"""

import threading
import multiprocessing as mp


from math import ceil
                                     
from calibration import global_parameters as gp

import copy as copy
import numpy as np     
import pandas as pd                            
from scipy.optimize import minimize, Bounds
import time
import datetime

from calibration import global_parameters as gp                          
from calibration import calib_basis as calbas

import pickle
import numpy as np
import matplotlib.pyplot as plt
import os
import pandas as pd                                     
from datetime import datetime
                    
from calibration import tools_figures_additional as figadd                                     
from calibration import calib_objective_function, calib_params, calib_exploration       

class CalibrationExploration(calbas.CalibrationBasis):
    
    def __init__(self, calib_basis=None, resolution=10, parallel=False):
        
        self.parallel = parallel
                
        # Affectation of parent class 
        if(calib_basis!=None): 
            self.update_calibbasis(calib_basis)
            
        self.resolution = resolution
        
    def update_calibbasis(self, calib_basis): 
        """
        Updates parent class CalibrationBasis with calib_basis
        
        Arguments
        ---------
        calib_basis: CalibrationBasis
            Base Class Calibration Problem
        
        """
        super(CalibrationExploration,self).__dict__.update(calib_basis.__dict__)
    
    def perform(self):
        exploration_results = self.__Exploration()
        return exploration_results


    def __Exploration(self): 
        
        def systematic_sampling(pmin, pmax, nmodels):
            """ Systematic sampling in the range of pmin-pmax
                    Cartesian Product
                Parameters
                ----------
                pmin: array of floats
                    vector of min for each of the dimensions to investigate 
                pmax: array of floats
                    vector of max for each of the dimensions to investigate
                nmodels: int
                    total number of models to investigate
            """
            # Number of parameters to vary for the cartesian product
            np = len(pmin)
            # Resolution in each of the dimentions (parameters) to investigate
            n=ceil(nmodels**(1/np))
            # Cartesian Product for the different dimension cases 
            if np == 1:
                p1 = gp.arange_n(pmin[0],pmax[0],n) 
                return [[i] for i in p1]
            elif np == 2:
                p1 = gp.arange_n(pmin[0],pmax[0],n)
                p2 = gp.arange_n(pmin[1],pmax[1],n)
                return [[i,j] for i in p1 for j in p2]
            elif np == 3:
                p1 = gp.arange_n(pmin[0],pmax[0],n)
                p2 = gp.arange_n(pmin[1],pmax[1],n)
                p3 = gp.arange_n(pmin[2],pmax[2],n)
                return [[i,j,k] for i in p1 for j in p2 for k in p3]
            elif np == 4:
                p1 = gp.arange_n(pmin[0],pmax[0],n)
                p2 = gp.arange_n(pmin[1],pmax[1],n)
                p3 = gp.arange_n(pmin[2],pmax[2],n)
                p4 = gp.arange_n(pmin[3],pmax[3],n)
                return [[i,j,k,l] for i in p1 for j in p2 for k in p3 for l in p4]
        
        """ 
        A garder
        Build Objective Function 
        """
        
        now = datetime.now()
        name = self.param_ident + '_' + now.strftime("%Y-%m-%d_%Hh%Mm%Ss") 
        params_values = []
        compt=1
        pmin = self.params.p_min
        pmax = self.params.p_max
        column_names = list()
        
        for i in self.params.name:
            column_names.append(i)
            
        if len(self.params.name) == 1 : 
                        
            # 1 parameter
            # params = systematic_sampling(pmin, pmax, self.resolution)
            if self.params.name[0][0]=='k':
                params = np.geomspace(pmin[0], pmax[0], self.resolution)
            else:
                params = np.linspace(pmin[0], pmax[0], self.resolution)
            params = [[i] for i in params]
            params_values.append(params)
            column_names.append('diff')
            obj_function = pd.DataFrame(columns=column_names)
            
            params_xyz = []
            # Use of proxy to avoid modification of self.lpm
            cpt = 0
            for i in range(len(params)):
                print(str(compt)+'/'+str(self.resolution))
                temp = params[i]        
                if self.parallel == True:
                    # compt=0
                    coeur=mp.cpu_count()
                    # for var3 in range (0, len(fix)): # permit to fix recharge
                    cpt += 1
                    t = threading.Thread(target=self.objective_function, args=(params[i]))
                    t.start()
                    if int(cpt / coeur) == cpt / coeur:  # Si compt est multiple de 3
                        t.join()  # alors on attend que les modèles soient terminées pour recommencer
                        print(cpt)
                    t.join() # On attend que les modèles soient finis pour terminer le calcul
                else:
                    temp.append(self.objective_function(params[i]))
                obj_function.loc[i] = temp
                params_xyz.append(temp)
                compt += 1
                
            # Graphical Representation 
            # figadd.figure_init(xlab=column_names[0],ylab="",figname='objective function 1D of ' + self.params.name[0])
            # plt.plot(obj_function.values[:,0],obj_function.values[:,1])
            # plt.yscale("log")
            # if self.params.name[0] == 'k':
            #     plt.xscale("log")
            # plt.savefig(os.path.join(self.directory_results,name),dpi=300)
            
        elif len(self.params.name) == 2 : 
                        
            # 2 parameters            
            
            n = int(np.ceil(self.resolution**(1/2)))     
            # p1 = pmin[0] + (pmax[0] - pmin[0]) * np.arange(0,n+1) / n
            # p2 = pmin[1] + (pmax[1] - pmin[1]) * np.arange(0,n+1) / n
            if self.params.name[0][0]=='k':
                p1 = np.geomspace(pmin[0], pmax[0], n)
            else:
                p1 = np.linspace(pmin[0], pmax[0], n)
            if self.params.name[1][0]=='k':
                p2 = np.geomspace(pmin[1], pmax[1], n)
            else:
                p2 = np.linspace(pmin[1], pmax[1], n)
            p2 = p2[::-1]
            params_values.append(p1)
            params_values.append(p2)
            obj_function = np.zeros((len(p1),len(p2)))
            temp=[None]*2
            params_xyz = []
            for i in range(len(p1)):
                for j in range(len(p2)):
                    print(str(compt)+'/'+str(len(p1)*len(p2)))
                    temp = [p1[i],p2[j]]
                    params_xyz.append(temp)
                    obj_function[j][i] = self.objective_function(temp)
                    compt += 1
                    
            # colormap
            # X,Y= np.meshgrid(p1, p2)
            # Z=obj_function.reshape((len(p1),len(p2)))
            # figadd.figure_init(xlab=column_names[0],ylab=column_names[1],figname='Objective function 2D')
            # plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
            # plt.colorbar()            
            # Whatevert the dimension, saves figure
            # plt.savefig(os.path.join(self.directory_results,name),dpi=300)
            
        elif len(self.params.name) > 2 : 
            
            # 3 parameters
            
            for k in range(len(self.params.name)):
                k1=(k+1)%len(self.params.name)
                #k2=(k+2)%len(self.params.name)
                n = int(np.ceil(self.resolution**(1/2))) 
                p1 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n 
                p2 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n 
                p3 = pmin[k] + (pmax[k] - pmin[k]) * np.arange(0,n+1) / n
                params_values.append(p1)
                params_values.append(p2)
                params_values.append(p3)
                obj_function = np.zeros((len(p1),len(p2)))
                temp=[None]*len(self.params.name)
                for i in range(len(p1)):
                    for j in range(len(p2)):
                        temp = [p1[i],p2[j],p3[int(len(p3)/2)]]
                        obj_function[j][i] = self.objective_function(temp)
                X,Y= np.meshgrid(p1, p2)
                Z=obj_function.reshape((len(p1),len(p2)))
                
                # figadd.figure_init(xlab=column_names[k],ylab=column_names[k1],figname='objective function 3D')
                # # colorbar
                # plt.pcolor(X,Y,Z,cmap=figadd.cmap_white_jet())
                # plt.colorbar()
                # # Whatevert the dimension, saves figure
                # plt.savefig(os.path.join(self.directory_results,name),dpi=300)
        
        self.write_results(name, obj_function, params_values, params_xyz)


