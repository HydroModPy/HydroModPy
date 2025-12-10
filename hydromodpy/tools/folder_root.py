# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

import os
import sys as sys
import time as time
import pathlib
from hydromodpy.tools.log_manager import get_logger

logger = get_logger(__name__)

#%% FUNCTION

# Gets or defines folder result
def root_folder_results(user_folder_path = None):
    """
    Get the environment variable containing the result folder path, or define
    it. Note that in that second case, the environment variable will be updated
    in the next conda session (if spyder is closed and opened again without
    restarting the conda console, the effective environment variable will be
    the old one).

    Parameters
    ----------
    folder_path : str, optional
        This function can take a user-defined path as the function parameter.
        If None (default), the user is asked to define the path as text input.

    Returns
    -------
    folder : str
        Result folder path.
    """

    env_name = "HYDROMODPY_RESULTS"

    # Gets environment variable
    folder = os.getenv(env_name)

    if (folder != None) & (isinstance(user_folder_path, str)):
        logger.warning(
            "Result folder %s already defined via environment variable; use update_root_folder_results() to change it",
            os.getenv(env_name),
        )

    # If environment variable does not exist, define it
    if folder == None :
        if user_folder_path == None :
            folder = pathlib.Path(input(r"Enter the path of the results folder: "))
        elif isinstance(user_folder_path, str):
            folder = pathlib.Path(user_folder_path)
        folder = str(folder)

        if os.name == 'nt':
            # folder = folder.replace('\\', '//')
            exp='setx ' + env_name + ' "' + folder + '"'
        else :
            # folder = folder.replace('/', '\')
            exp='export ' + env_name + '="' + folder + '"'
        os.system(exp)
        os.environ[env_name] = folder
        logger.info("Environment variable %s registered for results folder", env_name)
        logger.debug("%s = %s", env_name, folder)
        logger.info("Restart the conda session before relaunching Spyder to use the new results folder")

    # Creates folder if folder does not exist
    isExist = os.path.exists(folder)
    if not isExist:
        # Create a new directory because it does not exist
        os.makedirs(folder)
        logger.info("Created results folder at %s", folder)

    # Returns folder
    return folder

#%% UPDATE

# Update folder result
def update_root_folder_results(user_folder_path = None):
    env_name = "HYDROMODPY_RESULTS"
    os.environ.pop(env_name, None)
    # folder = None
    folder = root_folder_results(user_folder_path)

    return folder

#%% HIDE

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

#%% NOTES
