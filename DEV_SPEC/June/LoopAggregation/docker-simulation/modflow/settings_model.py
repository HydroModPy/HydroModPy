# coding:utf-8
import os,sys
import pandas as pd
import threading
import subprocess
import argparse

# Custom imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'model_modflow'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'model_modpath'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'model_seawat'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'vtk_export_grid'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'vtk_export_watertable'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'vtk_export_pathlines'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'custom_utils'))
from model_modflow import model_modflow as modflow
from model_modpath import model_modpath as modpath
from model_seawat import model_seawat as seawat
from vtk_export_grid import vtk_export_grid as vtk_grid
from vtk_export_watertable import vtk_export_watertable as vtk_watertable
from vtk_export_pathlines import vtk_export_pathlines as vtk_pathlines
from custom_utils import helpers as utils

########################################################################################################################
#                                                      MODEL SETTINGS                                                  #
########################################################################################################################

# FOLDER
folder_path = os.path.dirname(os.path.abspath(__file__)) + '/' #'/'.join(.split('/')[:-1])
print("folder_path : ", folder_path)

# STUDY SITES
print("folder + string : ", folder_path + "data/study_sites.txt")
sites = pd.read_table(folder_path + "data/study_sites.txt", sep=',', header=0, index_col=0) #\\s+
#site_number = 2 #Select site number
# coordinates = sites._get_values[site_number,1:5]

permeability = [8.64] #0.864  #K  ## Ref = 86.4
theta = [0.1]  #Porosity
geology = [0]
time = [0]

def setting(permeability, time, geology, theta, input_file, step, ref, chronicle, approx, rate, rep, steady, site=2):
    """_summary_

    Args:
        permeability (float): value of the permeability of the model
        time (int): time discretisation type (use 0 => chronicle, cf Alexandre Gauvain)
        geology (int): use 0 (cf Alexandre Gauvain)
        theta (_type_): Porosity value (use 0.1, cf Alexandre Gauvain)
        input_file (_type_): _description_
        step (_type_): _description_
        ref (_type_): _description_
        chronicle (_type_): _description_
        approx (_type_): _description_
        rate (_type_): _description_
        rep (_type_): _description_
        steady (_type_): _description_
        site (int, optional): _description_. Defaults to 2.
    """
    site_number = site
    row_site = sites.loc[sites['number']==site_number]
    coordinates = [row_site.iloc[0]["xmin"], row_site.iloc[0]["xmax"],row_site.iloc[0]["ymin"], row_site.iloc[0]["ymax"]]
   # coordinates = sites._get_values[site_number,1:5]

    # TIME DISCRETIZATION
    time_param = time  # 0: chronicle | 1: mean (1 day Steady State) | 2: min (1 day SS) | 3: max (1 day SS)

    # STRUCTURE
    geology_param = geology  # 0: homogeneous geology | 1: heterogeneous geology
    permeability_param = permeability  # m^2/d | only if geology_param = 0
    theta_param = theta # Porosity in %
    thickness_param = 1  # 0: homogeneous thickness | 1: flat bottom (heterogeneous thickness)

    # MODEL NAME
    print("site_number :", site_number)
    print("site name formule :", sites.index._data[site_number])
    site_name = sites.index._data[site_number] + '/'
    model_name = utils.generate_model_name(chronicle, approx, rate, ref, steady, site, permeability_param=permeability)
    if rep:
        model_name = model_name + "_" + str(rep)

    model_folder = model_name + '/'


    
    if (input_file is None):
        if ref:
            chronicle_file = pd.read_table(folder_path + "data/chronicles.txt", sep=',', header=0, index_col=0)
            input_file = chronicle_file.template[chronicle]

        else:
            #input_name = utils.generate_model_name(chronicle, approx, rate, ref=False, steady=steady, permeability_param=permeability)
            input_file = utils.get_input_file_name(chronicle, approx, rate, ref, steady, site=None, step=None)
            #input_file = "input_file_" + input_name + ".txt" ## CHANGE the _no_agg !! + "_no_agg" 
        
    
    # SIMULATION
    modflow_param = 1  # 0: disabled | 1: enabled
    seawat_param = 0  # 0: disabled | 1: enabled
    if time ==1:
        modpath_param = 1  # 0: disabled | 1: enabled
    else:
        modpath_param = 0
        # VTK OUTPUT
    grid = 0  # 0: disabled | 1: enabled
    watertable = 0  # 0: disabled | 1: enabled
    pathlines = 0 # 0: disabled | 1: enabled

    #print(input_file)
    print(folder_path)
    # CREATE AND RUN MODFLOW MODEL - SEAWAT MODEL - MODPATH MODEL
    if modflow_param == 1:
        print("file :" + input_file)
        print("site_name : ", site_name)
        print("folder_path : ", folder_path)
        print("model_folder : ", model_folder)
        modflow(input_file, file_name=folder_path, model_name=model_name, model_folder=folder_path + "outputs/" + site_name + model_folder,
                coord=coordinates, tdis=time_param, geo=geology_param, permea=permeability_param, thick=thickness_param, port=int(row_site["port_number"]), porosity=theta_param, ref=ref)
    if seawat_param == 1:
        seawat(filename=folder_path,modelfolder=folder_path + site_name + model_folder, modelname=model_name)
    if modpath_param == 1:
        modpath(filename=folder_path, modelname=model_name + '_swt', modelfolder=folder_path + site_name + model_folder)

    # CREATE OUTPUT FILES
    if not os.path.exists(folder_path + "outputs/" + site_name + model_folder + 'output_files'):
        os.makedirs(folder_path+ "outputs/" + site_name + model_folder + 'output_files')
    if grid == 1:
        vtk_grid(modelname=model_name, modelfolder=folder_path + "outputs/" + site_name + model_folder, coord=coordinates)
    if watertable == 1:
        vtk_watertable(modelname=model_name, modelfolder=folder_path + "outputs/" + site_name + model_folder, coord=coordinates)
    if pathlines == 1:
        vtk_pathlines(modelname=model_name + '_swt', modelfolder=folder_path + "outputs/" + site_name + model_folder, coord=coordinates)



if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--inputfile", type=str, required=False)
    parser.add_argument("-ts", "--timestep", type=int, required=False)
    parser.add_argument("-ref", "--reference", action='store_true')
    parser.add_argument("-chr", "--chronicle", type=int, required=True)
    parser.add_argument("-site", "--site", type=int, required=False)
    parser.add_argument("-rate", "--rate", type=float, required=False)
    parser.add_argument("-approx", '--approximation', type=int, required=False)
    parser.add_argument("-rep", '--rep', type=int, required=False)
    parser.add_argument("-perm", "--permeability", type=float, required=False)
    parser.add_argument("-sd", "--steady", type=int, required=False)
    args = parser.parse_args()

    input_file = args.inputfile
    step = args.timestep
    rate = args.rate
    reference = args.reference
    site=args.site
    chronicle = args.chronicle
    approx = args.approximation
    rep=args.rep
    perm = args.permeability
    steady=args.steady 

    if rep==0:
        rep=None

    if site:
        if perm:
            setting(perm, time[0], geology[0], theta[0], input_file, step, reference, chronicle, approx, rate, rep, steady, site=site)
        else:
            setting(permeability[0], time[0], geology[0], theta[0], input_file, step, reference, chronicle, approx, rate, rep, steady, site=site)
    else:
        if perm:
            setting(perm, time[0], geology[0], theta[0], input_file, step, reference, chronicle, approx, rate, rep, steady)
        else:
            setting(permeability[0], time[0], geology[0], theta[0], input_file, step, reference, chronicle, approx, rate, rep, steady)
