# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 17:55:02 2021

@author: Alexandre Gauvain
"""
import os
import pickle
from calibration import tools_figures_additional as figadd
import matplotlib.pyplot as plt
import numpy as np

class CalibAnalysis:
    def __init__(self, calib_file):
        self.load_file(calib_file)
        
    def load_file(self, calib_file):
        with open(calib_file, 'rb') as file:
            self.calib = pickle.load(file)
        self.names = self.calib['params_name'] 
        self.params_min = self.calib['params_min']
        self.params_max = self.calib['params_max']
        self.params_values = self.calib['params_values'] 
        self.obj_function = self.calib['objective_function']
        self.recharge = self.calib['recharge']
        self.calib_zones = self.calib['calib_zone']
        self.data_sim = self.calib['data_sim']
        self.data_obs = self.calib['data_obs']
        self.data_ind = self.calib['data_ind']
        self.find_best_values()
    
    def find_best_values(self):
        loc = np.where(self.obj_function == np.min(self.obj_function))
        self.p1 = self.params_values[0][loc[0][0]]
        self.p2 = self.params_values[1][loc[1][0]]
        loc_data = np.where(self.data_ind['piezometry'] == np.min(self.data_ind['piezometry']))
        self.best_data_obs = self.data_obs['piezometry'][loc_data[0][0]]
        self.best_data_sim = self.data_sim['piezometry'][loc_data[0][0]]
    
    def display_best_data(self):
        fig, (ax1, ax2) = plt.subplots(1, 2)
        ax1.plot(self.best_data_obs, self.best_data_sim,'ok')
        ax1.plot([min(self.best_data_obs),max(self.best_data_obs)],[min(self.best_data_obs),max(self.best_data_obs)],'-k')
        ax2.plot(self.best_data_obs, self.best_data_obs - self.best_data_sim,'ok')
        ax2.plot([min(self.best_data_obs),max(self.best_data_obs)],[0,0],'-k')
            
    def display_objective_function(self, save = None):
        if len(self.names) == 1 : 
            # 1 parameter
            figadd.figure_init(xlab=self.names[0],ylab="",figname='Objective function 1D of ' + self.names++++[0])
            plt.plot(self.params_values,self.obj_function)
            plt.yscale("log")
            if self.names[0] == 'k':
                plt.xscale("log")
            if save != None:
                plt.savefig(os.path.join(self.directory_results,"objfunction"),dpi=300)
        elif len(self.names) == 2 : 
            X,Y = np.meshgrid(self.params_values[0], self.params_values[1])
            Z=self.obj_function
            figadd.figure_init(xlab=self.names[0],ylab=self.names[1],figname='Objective function 2D')
            plt.pcolor(Y,X,Z,cmap='jet')#figadd.cmap_white_jet()
            plt.colorbar()
            # Whatevert the dimension, saves figure
            if save != None:
                plt.savefig(save,dpi=300)
        elif len(self.names) >= 3 : 
            # 3 parameters
            for k in range(len(self.names)):
                k1=(k+1)%len(self.names)
                #k2=(k+2)%len(self.names)
                X,Y= np.meshgrid(self.params_values[k], self.params_values[k1])
                Z=self.obj_function
                # Figure Initialization
                figadd.figure_init(xlab=self.names[k],ylab=self.names[k1],figname='objective function 3D')
                # colorbar
                plt.pcolor(X,Y,Z,cmap=figadd.cmap_white_jet())
                plt.colorbar()
                # Whatevert the dimension, saves figure
                plt.savefig(os.path.join(self.directory_results,"objfunction_"+str(k)),dpi=300)