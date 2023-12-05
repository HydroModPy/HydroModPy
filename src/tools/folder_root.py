# -*- coding: utf-8 -*-
"""
Created on Tue Mar 23 21:20:39 2021

@author: dreuzy
"""

from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np
import os
import sys as sys
import time as time



# Gets or defines folder result
def root_folder_results():
    env_name = "HYDROMODPY_RESUTLS"
    
    # Gets environment variable 
    folder = os.getenv(env_name)
        
    # If environment variable does not exist, define it 
    if folder == None :
        folder = input("Enter the path of the results folder, use // as delimiter in windows and \ in linux\n")
        if os.name == 'nt': 
            exp='setx ' + env_name + ' "' + folder + '"'
        else :
            exp='export ' + env_name + '="' + folder + '"'
        os.system(exp)
        print("Environement variable set for folder resuts")
        print(env_name, "=", folder)
    
    # Creates folder if folder does not exist
    isExist = os.path.exists(folder)
    if not isExist:
        # Create a new directory because it does not exist
        os.makedirs(folder)
        print("The folder has been created!")
    
    # Returns folder 
    return folder


# def name_dhms():
#     now = datetime.now()
#     dt_string = now.strftime("%Y_%m_%d-%H_%M_%S")
#     return dt_string

# def results_directory_dhms(sub_directory,directory=ROOT_DIRECTORY_RESULTS):
#     # Sub-directory
#     path = results_directory(directory,sub_directory)
#     # Sub-directory with date and time
#     return results_directory(path,sub_directory)


# class simulation_time:
#     """
#     Elapsed and remaining times of simulation
#     JR 06/08: classe à revoir, effective?
#     """
#     def __init__(self,nsim=1):
#         self.simul_total=nsim
#         self.time_start=0
#         self.time_inter_start=0
#         self.time_inter_end=0
#         self.simul_current=0
#         self.init_yes = False

#     def initialize(self,nb):
#         if self.init_yes == False:
#             self.time_start=time.time()
#             self.time_inter_start=time.time()
#             self.simul_total=nb * self.simul_total
#             self.init_yes = True

#     def actualize(self,nb=1):
#         self.time_inter_end=time.time()
#         self.simul_current=self.simul_current+nb
#         print('time elapsed = ', (self.time_inter_end - self.time_start)/3600, " heures")
#         print('time remaining = ', (self.time_inter_end - self.time_start) * (self.simul_total/self.simul_current-1) / 3600, " heures")


# def setup_path():
#     """ Adds to path source directory and sub directories """
#     pypath = ROOT_DIRECTORY_SRC

#     for dir_name in os.listdir(pypath):
#         dir_path = os.path.join(pypath, dir_name)
#         if os.path.isdir(dir_path):
#             sys.path.insert(0, dir_path)
