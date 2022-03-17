# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 17:55:02 2021

@author: Alexandre Gauvain
"""
import os
import pickle
from calibration import tools_figures_additional as figadd
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from matplotlib import ticker
import numpy as np

from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20)

class CalibAnalysis:
    
    def __init__(self, calib_file):
        self.load_file(calib_file)
        
    def load_file(self, calib_file):
        with open(calib_file, 'rb') as file:
            self.calib = pickle.load(file)
        self.names = self.calib['params_name']
        self.observations = self.calib['observations']
        self.params_min = self.calib['params_min']
        self.params_max = self.calib['params_max']
        self.params_values = self.calib['params_values']
        self.obj_function = self.calib['objective_function']
        self.recharge = self.calib['recharge']
        self.calib_zones = self.calib['calib_zone']
        self.data_sim = self.calib['data_sim']
        self.data_obs = self.calib['data_obs']
        self.data_ind = self.calib['data_ind']
        self.params_xyz = self.calib['params_xyz']
        self.sim_results = self.calib['sim_results']
        self.params_synt = self.calib['params_synt']
        if len(self.names) == 2:
            self.find_best_2Dvalues()
        try:
            if len(self.names) == 1:
                self.find_best_1Dvalues()
        except:
            pass
        try:
            self.list_criteria = self.calib['list_criteria']
        except:
            pass
    
    def find_best_1Dvalues(self):
        self.p = []
        loc = np.where(self.obj_function == np.min(self.obj_function['diff']))
        self.p.append(self.params_values[0][loc[0][0]][0])
        loc_data = np.where(self.obj_function['diff'] == np.min(self.obj_function['diff']))
        self.best_data_obs = self.obj_function['diff'][loc_data[0][0]]
        self.best_data_sim = self.obj_function['diff'][loc_data[0][0]]
    
    def find_best_2Dvalues(self):
        self.p = []
        loc = np.where(self.obj_function == np.min(self.obj_function))
        loc = loc[::-1]
        for i in range(len(loc)):
            self.p.append(self.params_values[i][loc[i][0]])
        loc_data = np.where(self.obj_function == np.min(self.obj_function))
        self.best_data_obs = self.obj_function[loc_data[0][0]]
        self.best_data_sim = self.obj_function[loc_data[0][0]]
        return(self.best_data_obs,self.best_data_sim)
    
    def display_best_data(self):
        fig, (ax1, ax2) = plt.subplots(1, 2)
        ax1.plot(self.best_data_obs, self.best_data_sim,'ok')
        ax1.plot([min(self.best_data_obs),max(self.best_data_obs)],[min(self.best_data_obs),max(self.best_data_obs)],'-k')
        ax2.plot(self.best_data_obs, self.best_data_obs - self.best_data_sim,'ok')
        ax2.plot([min(self.best_data_obs),max(self.best_data_obs)],[0,0],'-k')
            
    def display_objective_function(self, save = None,vmin= None, vmax=None, log=False):
        # plt.rcParams.update({
        #     "text.usetex": True,
        #     "font.family": "Helvetica"
        #     })

        if len(self.names) == 1 : 
            
            # 1 parameter
            
            figadd.figure_init(xlab=self.names[0],
                               ylab="",)
            if type(self.obj_function) == list:
                plt.plot(self.params_values,
                         self.obj_function,
                         lw=2, color='b')
            else:
                plt.plot(self.obj_function.iloc[:, 0].values,
                         self.obj_function.iloc[:, 1].values,
                         lw=2, color='b') # problem with list params_values ?
                
            plt.yscale("log")
            if self.observations == ['piezometry']:
                plt.ylabel(r'$RMSE$')
            if self.observations == ['streams']:
                plt.ylabel(r'$log(D_{SO}/D_{OS})^{2}$')
            
            if self.names[0][0] == 'k':
                plt.xscale("log")
                plt.xlabel(r'$K$ $[m.j^{-1}]$')
            if save != None:
                plt.savefig(save,dpi=300, bbox_inches = "tight")
                
        elif len(self.names) == 2 : 
            
            X,Y = np.meshgrid(self.params_values[0], self.params_values[1])
            Z=self.obj_function
            figadd.figure_init(xlab=self.names[0],
                               ylab=self.names[1],
                               figname=None)
            #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
            #plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
            self.find_best_2Dvalues()
            plt.plot(self.p[0],self.p[1],'ow',markersize=10)
            levels = 1000
            #plt.contourf(X, Y, Z,levels,cmap='jet', shading='auto',vmax=vmax, vmin=vmin)
            if log == True:
                plt.pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax, vmin=vmin, norm=colors.LogNorm())
            else:
                plt.pcolor(X, Y, Z,cmap='jet', shading='auto',vmax=vmax, vmin=vmin)
            
            for i in range(0,len(self.names)):
                if self.names[i][0] == 'k':
                    if i == 0:
                        plt.xscale("log")
                        plt.xlabel(r'$K$'+str(self.names[i][1])+' $[m.j^{-1}]$')
                    if i == 1:
                        plt.yscale("log")
                        plt.ylabel(r'$K$'+str(self.names[i][1])+' $[m.j^{-1}]$')
                if self.names[i][0] == 'n':
                    if i == 0:
                        if self.names[i][1]=='0':
                            plt.xlabel(r'$n$ $[-]$')
                        else:
                            plt.xlabel(r'$n$'+str(self.names[i][1])+' $[-]$')
                    if i == 1:
                        if self.names[i][1] == '0':
                            plt.ylabel(r'$n$ $[-]$')
                        else:
                            plt.ylabel(r'$n$'+str(self.names[i][1])+' $[-]$')
            
            if self.observations == ['piezometry']:
                plt.colorbar(label=r'$RMSE$')
            if self.observations == ['streams']:
                plt.colorbar(label=r'$log(D_{SO}/D_{OS})^{2}$')
            
            # Whatevert the dimension, saves figure
            if save != None:
                plt.savefig(save,dpi=300, bbox_inches = "tight")
                
        elif len(self.names) >= 3 : 
            
            # 3 parameters
            
            for k in range(len(self.names)):
                k1=(k+1)%len(self.names)
                #k2=(k+2)%len(self.names)
                X,Y= np.meshgrid(self.params_values[k], self.params_values[k1])
                Z=self.obj_function
                
                # Figure Initialization
                figadd.figure_init(xlab=self.names[k],
                                   ylab=self.names[k1],
                                   figname='objective function 3D')
                
                # colorbar
                plt.pcolor(X,Y,Z,cmap=figadd.cmap_white_jet())
                plt.colorbar()
                
                # Whatevert the dimension, saves figure
                plt.savefig(save,dpi=300, bbox_inches = "tight")