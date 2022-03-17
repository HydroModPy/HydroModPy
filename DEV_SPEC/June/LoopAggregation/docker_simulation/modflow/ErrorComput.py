# -*- coding: utf-8 -*-
"""
    Provides functions to compute error rate between the reference simulation and an alternative simulation.
"""

import os
import numpy as np
import argparse
import sys
import flopy.utils.binaryfile as fpu
import math
import csv
import pandas as pd
import math
import flopy
import pickle
import statistics
from osgeo import gdal
from osgeo import osr, ogr
from .custom_utils import helpers as utils
import pickle

__author__ = "June Sallou"
__maintainer__ = "June Sallou"
__credits__ = ["June Sallou"]
__license__ = "MIT"
__version__ = "0.0.3"
__date__ = "04/30/2019"
__email__ = "june.benvegnu-sallou@univ-rennes1.fr"


MAIN_APP_REPO = os.path.dirname(os.path.abspath(__file__)) + '/'

# Simulation features
NB_YEARS = 42 # Duration
START_TIME = 0
END_TIME = {0:15340, 1: 15340, 2:15340, 3:15340, 4:15340, 5: 15340, 6:15340, 7:15340, 8:15340, 9:15340, 10:18262, 11:18262, 12:18262, 13:18262, 14:18262, 15:18262, 16:18262, 17:18262, 18: 18262, 19:18262, 20:18262, 21:18262, 22:18262, 23:18262, 24: 18262, 25:18262, 26:18262, 27:18262} # end of the 42 years of the simulation
# H indicator computation features
#tsmax = 121  # 4 months = 121,75 days
#max_diff_threshold = 7 # max discrancy of the duration of flood episode
CRITICAL_DEPTH = 0.3  # depth of threshold for the undeground vulnerable zone
ALPHA = float(1/3)


def cut_hds_ref_file_into_one_day_hds_files(site_number, chronicle, approx, rate, folder, steady, permeability):
    ref_name = utils.get_model_name(site_number, chronicle, approx, rate, ref=True, steady=steady, permeability=permeability)
    if folder is None:
        repo_ref = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=True)
    else :
        site_name = utils.get_site_name_from_site_number(site_number)
        repo_ref = folder + site_name + ref_name

    ref_hds = fpu.HeadFile(repo_ref + '/' + ref_name + '.hds')  
    os.makedirs(repo_ref + "/HDS", exist_ok=True)

    for day in range(START_TIME, END_TIME[chronicle]+1):
        refHead = ref_hds.get_data(kstpkper=(0, day))
        np.save(repo_ref + '/' + 'HDS' + '/' + 'hds_' + str(day) + '.npy', refHead)
        print((day/END_TIME[chronicle])*100, "%")


def get_non_dry_cell_hds_value(hds, nrow, ncol, nlayer):
    layer = 0
    head = hds[layer][nrow][ncol]
    while (math.isclose(abs(head)/1e+30, 1, rel_tol=1e-3)) and layer < nlayer:
        if layer == nlayer-1:
            print("cell completely dry")
        else:
            head = hds[layer+1][nrow][ncol]
            layer += 1
    return head


def getWeightToSurface(altitudeSurface, head, CRITICAL_DEPTH, ALPHA):
    """
        altitudeSurface : value of soil surface at the point x
        head : head value for watertable at the x point
        CRITICAL_DEPTH : critical depth
        ALPHA : ratio of critical depth for calculating the width of transition zone
    """
    ddc = ALPHA * CRITICAL_DEPTH  # Alpha must be not null

    borneInf = altitudeSurface - (CRITICAL_DEPTH + (ddc / 2))
    borneSup = altitudeSurface - (CRITICAL_DEPTH - (ddc / 2))

    if head <= borneInf:
        Ws = 0
    elif head >= borneSup:
        Ws = 1
    else:
        Ws = math.sin((math.pi * (head - borneInf)) / (2*ddc))

    return Ws


def getNonDryCellHdsValue(hds, nrow, ncol, nlayer):
    layer = 0
    h = hds[layer][nrow][ncol]
    while (math.isclose(abs(h)/1e+30, 1, rel_tol=1e-3)) and layer < nlayer:
        if layer == nlayer-1:
            print("cell completely dry")
        else:
            h = hds[layer+1][nrow][ncol]
            layer += 1
    return h

def get_mask_data_for_a_site(site_number):
    mask_file = os.path.join(MAIN_APP_REPO, "data/Masks/", str(site_number) + "_basins.tif")
    ds = gdal.Open(mask_file)
    cols = ds.RasterXSize
    rows = ds.RasterYSize
    mask_array = np.array(ds.GetRasterBand(1).ReadAsArray())
    # print("cols mask:", cols)
    # print("rows mask:", rows)
    return mask_array, cols, rows


def get_soil_surface_values_for_a_simulation(repo_simu, model_name):
    """
        Retrieve the matrix of the topographical altitude.
    """
    mf = flopy.modflow.Modflow.load(repo_simu + "/" + model_name + '.nam')
    dis = flopy.modflow.ModflowDis.load(
        repo_simu + "/" + model_name + '.dis', mf)
    topo = dis.top._array
    return topo

def topo_file(site_number, chronicle, approx, rate, ref, folder, steady, permeability):
    model_name = utils.get_model_name(site_number, chronicle, approx, rate, ref, steady, permeability)
    if folder is None:
        repo = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=True)
    else:
        site_name = utils.get_site_name_from_site_number(site_number)
        repo = folder + "/" + site_name + "/" + model_name
    topo = get_soil_surface_values_for_a_simulation(repo, model_name)
    np.save(repo + "/soil_surface_topo_"+ model_name + ".npy", topo)
    print(repo + "/soil_surface_topo_"+ model_name + ".npy")

def get_model_size(coord):
    r_dem = MAIN_APP_REPO + "/data/MNT_TOPO_BATH_75m.tif"
    xmin = coord[0]
    xmax = coord[1]
    ymin = coord[2]
    ymax = coord[3]
    dem = gdal.Open(r_dem)
    dem_geot = dem.GetGeoTransform()
    dem_Xpos = np.ones((dem.RasterXSize))
    dem_Ypos = np.ones((dem.RasterYSize))
    for i in range(0, dem.RasterYSize):
        yp = dem_geot[3] + (dem_geot[5] * i)
        dem_Ypos[i] = yp
    for j in range(0, dem.RasterXSize):
        xp = dem_geot[0] + (dem_geot[1] * j)
        dem_Xpos[j] = xp
    ulX = (np.abs(dem_Xpos - xmin)).argmin()
    lrX = (np.abs(dem_Xpos - xmax)).argmin()
    ulY = (np.abs(dem_Ypos - ymax)).argmin()
    lrY = (np.abs(dem_Ypos - ymin)).argmin()
    clip_dem_x = dem_Xpos[ulX:lrX]
    clip_dem_y = dem_Ypos[ulY:lrY]
    return ulY, lrY, ulX, lrX, clip_dem_x, clip_dem_y


def get_clip_dem(coord):
    r_dem = MAIN_APP_REPO + "/data/MNT_TOPO_BATH_75m.tif"
    ulY, lrY, ulX, lrX, clip_dem_x, clip_dem_y = get_model_size(coord)
    dem = gdal.Open(r_dem)
    dem_geot = dem.GetGeoTransform()
    dem_data = dem.GetRasterBand(1).ReadAsArray()
    clip_dem = dem_data[ulY:lrY, ulX:lrX]
    return dem_geot, clip_dem_x, clip_dem_y, clip_dem


def save_clip_dem(site_number, sat, vul, folder, steady, permeability):
    sites = pd.read_csv(MAIN_APP_REPO + "data/study_sites.txt", sep=',', header=0, index_col=0)
    model_name = utils.get_model_name(site_number, chronicle, approx, rate, ref, steady, permeability)
    site_name = utils.get_site_name_from_site_number(site_number)
    repo_simu = folder + site_name + "/" + model_name

    coord = sites._get_values[site_number, 1:5]
    print(coord)
    geot, geotx, geoty, demData = get_clip_dem(coord)
    drv = gdal.GetDriverByName("GTiff")
    if sat:
        ds = drv.Create(repo_simu + '/' + "SaturationZones_" + site_name + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) +  '_MNT.tif',
                    demData.shape[1], demData.shape[0], 1, gdal.GDT_Float32)
    if vul:
        ds = drv.Create(repo_simu + '/' + "VulnerabilityZones_" + site_name + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) +  '_MNT.tif',
                    demData.shape[1], demData.shape[0], 1, gdal.GDT_Float32)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2154)
    ds.SetProjection(srs.ExportToWkt())
    gt = [geotx[0], geot[1], 0, geoty[1], 0, geot[5]]
    ds.SetGeoTransform(gt)
    if sat:
        values = np.load(repo_simu + "/SaturationZones_" + site_name + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy")
    if vul:
        values = np.load(repo_simu + "/VulnerabilityZones_" + site_name + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy")

    ds.GetRasterBand(1).WriteArray(values)


def compute_h_error_by_interpolation(site_number, chronicle, approx, rate, ref, folder, permeability, steady, time_step=1):
    # Get data for reference simulation
    # Path to repository 
    print("folder: ", folder)
    ref_name = utils.get_model_name(site_number, chronicle, approx, rate, ref=True, steady=steady, permeability=permeability)
    if folder is None:
        repo_ref = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=True) #get_path_to_simulation_directory(site_number, chronicle, approx, rate, ref=True)
    else:
        site_name = utils.get_site_name_from_site_number(site_number)
        print("site_name: ", site_name)
        repo_ref = folder + "/" + site_name + "/" + ref_name

    topo_ref = np.load(repo_ref + "/soil_surface_topo_"+ ref_name + ".npy")
    # Watertable altitude
    ref_hds = fpu.HeadFile(repo_ref + '/' + ref_name + '.hds')
    #print("kstpkper: ", ref_hds.get_kstpkper()
    if ref:
        # Get data for alternate simulation
        # Path to repository
        repo_simu = repo_ref 
        simu_name = ref_name
        # Topographical altitude
        topoSimu = topo_ref
        # Get heads values for simulation
        simu_hds = ref_hds
    else:
        # Get data for alternate simulation
        # Path to repository
        simu_name = utils.get_model_name(site_number, chronicle, approx, rate, ref=False, steady=steady, permeability=permeability)
        #simu_name += "_no_agg"
        if folder is None:
            repo_simu = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=False)
        else:
            repo_simu = folder + '/' + site_name + '/' + simu_name
        # Topographical altitude
        topoSimu = get_soil_surface_values_for_a_simulation(repo_simu, simu_name)
        # Get heads values for simulation
        simu_hds = fpu.HeadFile(repo_simu + '/' + simu_name + '.hds')

    #Mask to decide which cell to compute
    mask_array, mask_ncol, mask_nrow = get_mask_data_for_a_site(site_number)
    
    infile_sub = open(MAIN_APP_REPO + "data/Pickle/ExcludedSubB_Site" + str(site_number) + '.pickle','rb')
    subcatch_exluded = pickle.load(infile_sub)
    infile_sub.close()
    print("Excluded SubCatchs: ", subcatch_exluded)
     
    # Duration of simulated periods
    simu_times = simu_hds.get_times()
    ref_init_head = ref_hds.get_data(kstpkper=(0, 0))
    # Initialisation of error computing variables
    smWs = {}
    sherrorsup = {}
    generic_error = {}
    area = {}
    saturated_zones = np.zeros(shape=(ref_init_head.shape[1], ref_init_head.shape[2]))
    vulnerable_zones = np.zeros(shape=(ref_init_head.shape[1], ref_init_head.shape[2]))

    dict_WsRef = {}
    dict_WsSimu = {}
    dict_simuWatertableAltitude = {}
    dict_r = {}
    dict_depth = {}



    # For every day, we have to compare the reference and alternate simulations
    for day in range(START_TIME, END_TIME[chronicle] + 1): 
        print("Progress:", round((day/END_TIME[chronicle])*100, 2), "%")
        print("day :", day)
        dict_WsRef[day] = {}
        dict_WsSimu[day] = {}
        dict_simuWatertableAltitude[day] = {}
        dict_r[day] = {}
        dict_depth[day] = {}

        # Retrieve the watertable altitude values for the reference simulation for the considered day
        refHead = ref_hds.get_data(kstpkper=(0, day))

        # Compute the number of the simulated period of the alternate simulation for the considered day
        nbPeriod = 0
        while (simu_times[nbPeriod] < day+1) and (nbPeriod < len(simu_times)):
            nbPeriod += 1
        # print("nbPeriod : " + str(nbPeriod))

        # When the considered day match with the duration of the corresponding simulated period
        # We retrieve the value of the watertable altitude from the corresponding matrix
        if math.isclose(simu_times[nbPeriod], day+1, rel_tol=1e-3):
            altHeadSup = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod))
            altHeadInf = altHeadSup
            duree = int(simu_times[nbPeriod])
            pas = 0
        # Otherwise, we have to interpolate the watertable altitude value for the considered day
        else:
            # The considered day is situated between the simulated period number 'nbPeriod-1' and number 'nbPeriod'
            altHeadSup = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod))
            altHeadInf = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod-1))
            duree = int(simu_times[nbPeriod] - simu_times[nbPeriod-1])
            pas = day - simu_times[nbPeriod-1]

        nbrowtot = altHeadInf.shape[1]
        nbcoltot = altHeadInf.shape[2]

        # mask to only get the data of the "equivalent watershed"
        # if mask_nrow == nbrowtot:
        #     print("same number of rows")
        # else:
        #     print("Not same number of rows!")
        # if mask_ncol == nbcoltot:
        #     print("Same number of cols")
        # else:
        #     print("Not same number of columns!")

        # We want to store the presence of cells part of a flood episode
        # We go through all the cells of the matrix representing the study site
        for nrow in range(nbrowtot):
            dict_WsRef[day][nrow] = {}
            dict_WsSimu[day][nrow] = {}
            dict_simuWatertableAltitude[day][nrow] = {}
            dict_r[day][nrow] = {}
            dict_depth[day][nrow] = {}
            for ncol in range(nbcoltot):

                if (mask_array[nrow][ncol] <0) or (mask_array[nrow][ncol] in subcatch_exluded): # <0 avec nouveaux masks basins.tif
                    #print("test hors BVE")
                    continue

                # Watertable altitude value for simulated period with duration lower than considered day
                simuWatertableAltitudeLowerPeriod = get_non_dry_cell_hds_value(
                    altHeadInf, nrow, ncol, altHeadInf.shape[0])
                # Watertable altitude value for simulated period with duration higher than considered day
                simuWatertableAltitudeHigherPeriod = get_non_dry_cell_hds_value(
                    altHeadSup, nrow, ncol, altHeadInf.shape[0])
                ajoutSimu = (simuWatertableAltitudeHigherPeriod - simuWatertableAltitudeLowerPeriod) / duree
                # Watertable altitude value for considered day being interpolated
                simuWatertableAltitudeInterpolated = simuWatertableAltitudeLowerPeriod + (ajoutSimu * pas)
                # Saving value of s
                dict_simuWatertableAltitude[day][nrow][ncol] = simuWatertableAltitudeInterpolated

                # depth : topographical altitude  - watertable altitude
                depth = topoSimu[nrow][ncol] - simuWatertableAltitudeInterpolated
                dict_depth[day][nrow][ncol] = depth

                if depth <= CRITICAL_DEPTH:
                    saturated_zones[nrow][ncol] += 1

                # Watertable altitude value for simulated period for reference simulation
                r = get_non_dry_cell_hds_value(
                    refHead, nrow, ncol, refHead.shape[0])
                dict_r[day][nrow][ncol] = r

                WsRef = getWeightToSurface(topo_ref[nrow][ncol], r, CRITICAL_DEPTH, ALPHA)
                WsSimu = getWeightToSurface(topoSimu[nrow][ncol], simuWatertableAltitudeInterpolated, CRITICAL_DEPTH, ALPHA)
                dict_WsRef[day][nrow][ncol] = WsRef
                dict_WsSimu[day][nrow][ncol] = WsSimu

                vulnerable_zones[nrow][ncol] += WsSimu

                if mask_array[nrow][ncol] not in sherrorsup:
                    #print(mask_array[nrow][ncol], " not in dictionnary sherrrorsup.")
                    sherrorsup[mask_array[nrow][ncol]] = 0
                    generic_error[mask_array[nrow][ncol]] = 0
                    area[mask_array[nrow][ncol]] = 0
                if mask_array[nrow][ncol] not in smWs:
                    #print(mask_array[nrow][ncol], " not in dictionnary smWs.")
                    smWs[mask_array[nrow][ncol]] = 0

                mWs = max(WsRef, WsSimu)
                sherrorsup[mask_array[nrow][ncol]] += (mWs * (r-simuWatertableAltitudeInterpolated)**2)
                smWs[mask_array[nrow][ncol]] += mWs

                generic_error[mask_array[nrow][ncol]] += abs(r-simuWatertableAltitudeInterpolated)

                area[mask_array[nrow][ncol]] += 1

    print("sherrorsup: ", sherrorsup)
    print("smWs: ", smWs)

    hErrorGlobalSub = {}
    for key in sherrorsup:
        hErrorGlobalSub[key] = math.sqrt(sherrorsup[key] / smWs[key])

    generic_error_Sub = {}
    for key in generic_error:
        generic_error_Sub[key] = (generic_error[key] / (area[key] * (END_TIME[chronicle]+1)))

    print("Error H Sub: ", hErrorGlobalSub)

    sherror = sum(sherrorsup.values())
    print("sherror: ", sherror)
    sWs = sum(smWs.values())
    print("sWs: ", sWs)
    if sWs == 0:
        hErrorGlobal = 0
    else:
        hErrorGlobal = math.sqrt(sherror/ sWs)
    print("hErrorGlobal: ", hErrorGlobal)


    with open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE_SUB.csv', 'w') as f:
        for key in hErrorGlobalSub.keys():
            f.write("%s; %s\n" % (key, hErrorGlobalSub[key]))

    with open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_generic_error_SUB.csv', 'w') as f:
        for key in generic_error_Sub.keys():
            f.write("%s; %s\n" % (key, generic_error_Sub[key]))


    with open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE.csv', 'w') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['H Error'])
        writer.writerow([hErrorGlobal])
    print("Results saved here:", repo_simu) # + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE.csv')

    # print("Saving files...")
    # outfile_s = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_s' +'.pickle','wb')
    # pickle.dump(dict_simuWatertableAltitude,outfile_s)
    # outfile_s.close()
    # print("Saved files:", "1/6")

    # print("Saving files...")
    # outfile_r = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_r' +'.pickle','wb')
    # pickle.dump(dict_r,outfile_r)
    # outfile_r.close()
    # print("Saved files:", "2/6")

    # print("Saving files...")
    # outfile_d = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_d' +'.pickle','wb')
    # pickle.dump(dict_depth,outfile_d)
    # outfile_d.close()
    # print("Saved files:", "3/6")

    # print("Saving files...")
    # outfile_WsRef = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_WsRef' +'.pickle','wb')
    # pickle.dump(dict_WsRef,outfile_WsRef)
    # outfile_WsRef.close()
    # print("Saved files:", "4/6")

    # print("Saving files...")
    # outfile_WsSimu = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_WsSimu' +'.pickle','wb')
    # pickle.dump(dict_WsSimu,outfile_WsSimu)
    # outfile_WsSimu.close()
    # print("Saved files:", "5/6")

    # print("Saving files...")
    # outfile_generic_error = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_generic_error' +'.pickle','wb')
    # pickle.dump(generic_error,outfile_generic_error)
    # outfile_generic_error.close()
    # print("Saved files:", "6/6")

    # np.save(repo_simu + "/SaturationZones_Site_" + str(site_number) + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy", saturated_zones)
    # np.save(repo_simu + "/VulnerabilityZones_Site_" + str(site_number) + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy", vulnerable_zones)
    
    return nbrowtot, nbcoltot



def get_generic_indicator():
    pass




def dev_computeH(site_number, chronicle, approx, rate, ref, folder, permeability, steady, time_step=1):
    # Get data for reference simulation
    # Path to repository 
    print("folder: ", folder)
    ref_name = utils.get_model_name(site_number, chronicle, approx, rate, ref=True, steady=steady, permeability=permeability)
    if folder is None:
        repo_ref = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=True) #get_path_to_simulation_directory(site_number, chronicle, approx, rate, ref=True)
    else:
        site_name = utils.get_site_name_from_site_number(site_number)
        print("site_name: ", site_name)
        repo_ref = folder + "/" + site_name + "/" + ref_name

    topo_ref = np.load(repo_ref + "/soil_surface_topo_"+ ref_name + ".npy")
    # Watertable altitude
    ref_hds = fpu.HeadFile(repo_ref + '/' + ref_name + '.hds')
    #print("kstpkper: ", ref_hds.get_kstpkper()
    if ref:
        # Get data for alternate simulation
        # Path to repository
        repo_simu = repo_ref 
        simu_name = ref_name
        # Topographical altitude
        topoSimu = topo_ref
        # Get heads values for simulation
        simu_hds = ref_hds

    else:
        # Get data for alternate simulation
        # Path to repository
        simu_name = utils.get_model_name(site_number, chronicle, approx, rate, ref=False, steady=steady, permeability=permeability)
        #simu_name += "_no_agg"
        if folder is None:
            repo_simu = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref=False)
        else:
            repo_simu = folder + '/' + site_name + '/' + simu_name
        # Topographical altitude
        topoSimu = get_soil_surface_values_for_a_simulation(repo_simu, simu_name)
        # Get heads values for simulation
        simu_hds = fpu.HeadFile(repo_simu + '/' + simu_name + '.hds')

    #Mask to decide which cell to compute
    mask_array, mask_ncol, mask_nrow = get_mask_data_for_a_site(site_number)
    
    infile_sub = open(MAIN_APP_REPO + "data/Pickle/ExcludedSubB_Site" + str(site_number) + '.pickle','rb')
    subcatch_exluded = pickle.load(infile_sub)
    infile_sub.close()
    print("Excluded SubCatchs: ", subcatch_exluded)
     
    # Duration of simulated periods
    simu_times = simu_hds.get_times()
    ref_init_head = ref_hds.get_data(kstpkper=(0, 0))
    # Initialisation of error computing variables
    smWs = {}
    sherrorsup = {}
    saturated_zones = np.zeros(shape=(ref_init_head.shape[1], ref_init_head.shape[2]))
    vulnerable_zones = np.zeros(shape=(ref_init_head.shape[1], ref_init_head.shape[2]))

    dict_WsRef = {}
    dict_WsSimu = {}
    dict_s = {}
    dict_r = {}
    dict_d = {}



    # For every day, we have to compare the reference and alternate simulations
    for day in range(START_TIME, 2):
        print((day/2)*100, "%")
        dict_WsRef[day] = {}
        dict_WsSimu[day] = {}
        dict_s[day] = {}
        dict_r[day] = {}
        dict_d[day] = {}

        # Retrieve the watertable altitude values for the reference simulation for the considered day
        refHead = ref_hds.get_data(kstpkper=(0, day))

        # Compute the number of the simulated period of the alternate simulation for the considered day
        nbPeriod = 0
        while (simu_times[nbPeriod] < day+1) and (nbPeriod < len(simu_times)):
            nbPeriod += 1
        # print("nbPeriod : " + str(nbPeriod))

        # When the considered day match with the duration of the corresponding simulated period
        # We retrieve the value of the watertable altitude from the corresponding matrix
        if math.isclose(simu_times[nbPeriod], day+1, rel_tol=1e-3):
            altHeadSup = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod))
            altHeadInf = altHeadSup
            duree = int(simu_times[nbPeriod])
            pas = 0
        # Otherwise, we have to interpolate the watertable altitude value for the considered day
        else:
            # The considered day is situated between the simulated period number 'nbPeriod-1' and number 'nbPeriod'
            altHeadSup = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod))
            altHeadInf = simu_hds.get_data(kstpkper=(time_step-1, nbPeriod-1))
            duree = int(simu_times[nbPeriod] - simu_times[nbPeriod-1])
            pas = day - simu_times[nbPeriod-1]

        nbrowtot = altHeadInf.shape[1]
        nbcoltot = altHeadInf.shape[2]

        # mask to only get the data of the "equivalent watershed"
        if mask_nrow == nbrowtot:
            print("same number of rows")
        else:
            print("Not same number of rows!")
        if mask_ncol == nbcoltot:
            print("Same number of cols")
        else:
            print("Not same number of columns!")

        # We want to store the presence of cells part of a flood episode
        # We go through all the cells of the matrix representing the study site
        for nrow in range(nbrowtot):
            dict_WsRef[day][nrow] = {}
            dict_WsSimu[day][nrow] = {}
            dict_s[day][nrow] = {}
            dict_r[day][nrow] = {}
            dict_d[day][nrow] = {}
            for ncol in range(nbcoltot):

                if (mask_array[nrow][ncol] <0) or (mask_array[nrow][ncol] in subcatch_exluded): # <0 avec nouveaux masks basins.tif
                    #print("test hors BVE")
                    continue

                # Watertable altitude value for simulated period with duration lower than considered day
                ss = get_non_dry_cell_hds_value(
                    altHeadInf, nrow, ncol, altHeadInf.shape[0])
                # Watertable altitude value for simulated period with duration higher than considered day
                se = get_non_dry_cell_hds_value(
                    altHeadSup, nrow, ncol, altHeadInf.shape[0])
                ajoutSimu = (se - ss) / duree
                # Watertable altitude value for considered day being interpolated
                s = ss + (ajoutSimu * pas)
                # Saving value of s
                dict_s[day][nrow][ncol] = s

                # depth : topographical altitude  - watertable altitude
                d = topoSimu[nrow][ncol] - s
                dict_d[day][nrow][ncol] = d

                if d<= CRITICAL_DEPTH:
                    saturated_zones[nrow][ncol] += 1

                # Watertable altitude value for simulated period for reference simulation
                r = get_non_dry_cell_hds_value(
                    refHead, nrow, ncol, refHead.shape[0])
                dict_r[day][nrow][ncol] = r

                WsRef = getWeightToSurface(topo_ref[nrow][ncol], r, CRITICAL_DEPTH, ALPHA)
                WsSimu = getWeightToSurface(topoSimu[nrow][ncol], s, CRITICAL_DEPTH, ALPHA)
                dict_WsRef[day][nrow][ncol] = WsRef
                dict_WsSimu[day][nrow][ncol] = WsSimu

                vulnerable_zones[nrow][ncol] += WsSimu

                if mask_array[nrow][ncol] not in sherrorsup:
                    #print(mask_array[nrow][ncol], " not in dictionnary sherrrorsup.")
                    sherrorsup[mask_array[nrow][ncol]] = 0
                if mask_array[nrow][ncol] not in smWs:
                    #print(mask_array[nrow][ncol], " not in dictionnary smWs.")
                    smWs[mask_array[nrow][ncol]] = 0

                mWs = max(WsRef, WsSimu)
                sherrorsup[mask_array[nrow][ncol]] += (mWs * (r-s)**2)
                smWs[mask_array[nrow][ncol]] += mWs

    print("sherrorsup: ", sherrorsup)
    print("smWs: ", smWs)
    #hErrorGlobal = math.sqrt(sherrorsup / smWs)

    hErrorGlobalSub = {}
    for key in sherrorsup:
        if sherrorsup[key] == 0 or smWs[key] == 0:
            hErrorGlobalSub[key] = 0
        else:
            hErrorGlobalSub[key] = math.sqrt(sherrorsup[key] / smWs[key])

    print("Error H Sub: ", hErrorGlobalSub)

    sherror = sum(sherrorsup.values())
    print("sherror: ", sherror)
    sWs = sum(smWs.values())
    print("sWs: ", sWs)
    hErrorGlobal = math.sqrt(sherror/ sWs)
    print("hErrorGlobal: ", hErrorGlobal)


    with open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE_SUB_TEST.csv', 'w') as f:
        for key in hErrorGlobalSub.keys():
            f.write("%s; %s\n" % (key, hErrorGlobalSub[key]))

    with open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE.csv_TEST', 'w') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['H Error'])
        writer.writerow([hErrorGlobal])
    print(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_errorsresult_H_BVE.csv_TEST')

    # variables = [dict_s, dict_d, dict_r, dict_WsRef, dict_WsSimu]
    # var_names = ['s', 'd', 'r', 'WsRef', 'WsSimu']

    outfile_s = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_s' +'.pickle_TEST','wb')
    pickle.dump(dict_s,outfile_s)
    outfile_s.close()

    outfile_r = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_r' +'.pickle_TEST','wb')
    pickle.dump(dict_r,outfile_r)
    outfile_r.close()


    outfile_d = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_d' +'.pickle_TEST','wb')
    pickle.dump(dict_d,outfile_d)
    outfile_d.close()

    outfile_WsRef = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_WsRef' +'.pickle_TEST','wb')
    pickle.dump(dict_WsRef,outfile_WsRef)
    outfile_WsRef.close()

    outfile_WsSimu = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_WsSimu' +'.pickle_TEST','wb')
    pickle.dump(dict_WsSimu,outfile_WsSimu)
    outfile_WsSimu.close()

    # infile_s = open(repo_simu + "/" + simu_name + '_Ref_' + ref_name + '_' + 's' +'.pickle','rb')
    # reload_s = pickle.load(infile_s)
    # infile_s.close()
    # print("dict_s", dict_s[0][55][55])
    # print("reload dict_s: ", reload_s[0][55][55])
 


    np.save(repo_simu + "/SaturationZones_Site_" + str(site_number) + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy_TEST", saturated_zones)
    np.save(repo_simu + "/VulnerabilityZones_Site_" + str(site_number) + "_Chronicle_"+ str(chronicle) + "_Approx_" + str(approx) + "_Rate_" + str(rate) + ".npy_TEST", vulnerable_zones)

    return nbrowtot, nbcoltot

def getSaturatedZoneArea(site_number, chronicle, approx, rate, folder, ref, steady, permeability, timestep=1):
    
    model_name = utils.get_model_name(site_number, chronicle, approx, rate, ref, steady, permeability)

    if folder is None:
        repo_simu = utils.get_path_to_simulation_directory(site_number, chronicle, approx, rate, permeability, steady, ref)
    else :
        site_name = utils.get_site_name_from_site_number(site_number)
        repo_simu = folder + site_name + "/" + model_name

    topoSimu = get_soil_surface_values_for_a_simulation(repo_simu, model_name)

    simuHds = fpu.HeadFile(repo_simu + '/' + model_name + '.hds')
    # simuTimes = simuHds.get_times()
    # simuKstpkper = simuHds.get_kstpkper()
    # print(simuTimes, simuKstpkper)
    hds_data = simuHds.get_data(kstpkper=(0,0))
    # print(hds_data)

    nbrowtot = hds_data.shape[1]        
    nbcoltot = hds_data.shape[2]

    size_site = nbrowtot * nbcoltot
    Ws_sum = 0
    saturated_area = 0

    for nrow in range(nbrowtot):
        for ncol in range(nbcoltot):

            Zs = topoSimu[nrow][ncol]
            h = getNonDryCellHdsValue(hds_data, nrow, ncol, hds_data.shape[0])
            d =  Zs - h
            if d<= CRITICAL_DEPTH:
                saturated_area += 1
            Ws_sum += getWeightToSurface(Zs, h, CRITICAL_DEPTH, ALPHA)
    


    with open(repo_simu + "/" + model_name + '_extracted_features.csv', 'w') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['Satured Zone Area', 'Vulnerability Sum', 'Vulnerability Rate', 'Global Area of site (in cells)'])
        writer.writerow([saturated_area, Ws_sum, Ws_sum/size_site, size_site])
    print("Site :", site_name, " ", site_number)
    print("Rate :", rate)
    print("Saturated Area : ", saturated_area)
    print("Vulnerability Sum : ", Ws_sum)
    print("Vulnerability Rate : ", Ws_sum/size_site)
    print("Global Area of site :", size_site)


def dev_get_computed_bassin_Mask(site_number):
    mask_array, cols, rows = get_mask_data_for_a_site(site_number)
    # print("mask array", mask_array)
    # print(mask_array[0][0])
    # print(mask_array[0][cols-1])

    subs_to_exclude = []
    for row in [0, rows-1]:
        for col in range(cols):
            if (mask_array[row][col] > 0) and (mask_array[row][col] not in subs_to_exclude):
                subs_to_exclude.append(mask_array[row][col])
    
    for col in [0, cols-1]:
        for row in range(rows):
            if (mask_array[row][col] > 0) and (mask_array[row][col] not in subs_to_exclude):
                subs_to_exclude.append(mask_array[row][col])
    #print(subs_to_exclude)

    with open(MAIN_APP_REPO + "data/Pickle/ExcludedSubB_Site" + str(site_number) + '.csv', 'w') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(subs_to_exclude)


    # for row in range(rows):
    #     for col in range(cols):
    #         if mask_array[row][col] == 0:
    #             print("0")
    #         if np.isnan(mask_array[row][col]):
    #             print("nan")

    outfile = open(MAIN_APP_REPO + "data/Pickle/ExcludedSubB_Site" + str(site_number) + '.pickle','wb')
    pickle.dump(subs_to_exclude,outfile)
    outfile.close()



if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-chr", "--chronicle", type=int, required=True)
    parser.add_argument("-approx", "--approximation", type=int, required=False)
    parser.add_argument("-rate", "--rate", type=float, required=False)
    parser.add_argument("-site", "--sitenumber", type=int, required=True)
    parser.add_argument("-ref", "--ref", action='store_true')
    parser.add_argument("-perm", "--permeability", type=float, required=False)
    parser.add_argument("-sd", "--steady", type=int, required=False)

    # For evolutivity
    parser.add_argument("-step", "--step", type=int, required=False)
    parser.add_argument("-f", "--folder", type=str, required=False)
    parser.add_argument("-topo", "--topo", action='store_true')
    parser.add_argument("-dev", "--dev", action='store_true')
    parser.add_argument("-test", "--test", action='store_true')
    parser.add_argument("-hfeats", "--hfeats", action='store_true')
    parser.add_argument("-noagg", "--noagg", action='store_true')


    args = parser.parse_args()

    approx = args.approximation
    chronicle = args.chronicle
    site_number = args.sitenumber
    rate = args.rate
    ref = args.ref
    folder = args.folder
    topo = args.topo
    noagg = args.noagg
    perm = args.permeability
    steady=args.steady
    hfeats = args.hfeats
    dev = args.dev
    test = args.test
    # CRITICAL_DEPTH = args.criticaldepth
    # ALPHA = args.alpha

    ## Condition steady --> getSaturatedZoneArea

    if topo:
        topo_file(site_number, chronicle, approx, rate, ref=True, folder=folder, steady=steady, permeability=perm)
    elif hfeats:
        getSaturatedZoneArea(site_number, chronicle, approx, rate, folder, ref=False, steady=steady, permeability=perm, timestep=1)
    elif dev:
        dev_get_computed_bassin_Mask(site_number)
    elif test:
        dev_computeH(site_number, chronicle, approx, rate, ref, folder, permeability=perm, steady=steady, time_step=1)
    else:
        #topo_file(site_number, chronicle, approx, rate, ref=True, folder=folder, steady=steady, permeability=perm)
        nbrowtot, nbcoltot = compute_h_error_by_interpolation(site_number, chronicle, approx, rate, ref=ref, steady=steady, permeability=perm, folder=folder)
        #print(nbrowtot, nbcoltot)
    #cut_hds_ref_file_into_one_day_hds_files(site_number, chronicle, approx, rate, folder)
    # topo_file(site_number, chronicle, approx, rate, ref, folder)
    
