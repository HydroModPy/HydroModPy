#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import pandas as pd 


folder_results_path = os.sep.join((os.sep.join(os.path.dirname(__file__).split(os.sep)[:-1]), "LoopAgregation", "docker_simulation", "modflow", "outputs")) #os.path.realpath(__file__)



def create_data_file_w_H_indicator_for_all_rates_all_sites():
    nb_rates = 30
    nb_sites = 40
    data = pd.DataFrame(columns = ['Site', 'Rate', 'H Error'])
    site_numbers = range(1, nb_sites+1)
    #site_numbers = range(1,2)
    #rates = [1, 2, 7, 15, 21, 30, 45, 50, 60, 75, 90, 100, 125, 150, 182, 200, 250, 300, 330, 365, 550, 640, 730, 1000, 1500, 2000, 2250, 3000, 3182, 3652]
    if nb_rates == 9:
        rates = [1, 2, 7, 30, 90, 182, 365, 730, 3652]
    else:
        rates = [1, 2, 7, 15, 21, 30, 45, 50, 60, 75, 90, 100, 125, 150, 182, 200, 250, 300, 330, 365, 550, 640, 730, 1000, 1500, 2000, 2250, 3000, 3182, 3652]
    for site_number in site_numbers:
        site_name = get_site_name_from_site_number(site_number)
        print("site number: ", site_number)
        data_site = pd.DataFrame(columns = ['Site', 'Rate', 'H Error'])
        for rate in rates:
            H_error = retrieve_H_error(site_number, site_name, rate)
            if H_error is not False:
                data_site.loc[len(data_site.index)] = [site_number, rate, H_error]
        data_site = data_site.dropna()
        #print(len(data_site))
        if len(data_site)==nb_rates:
            data = pd.concat([data, data_site], ignore_index=True)

    data.to_csv("data" + os.sep + "Data_Complete_Rates_" + str(nb_rates) + "_Sites_HError_wo_Features_BVE.csv", sep=";", index=None)

def get_site_name_from_site_number(site_number):
    sites = pd.read_csv(
        os.path.dirname(__file__) + os.sep + "data"+ os.sep + "study_sites.txt",
        sep=",",
        header=0,
        index_col=0,
    ) 
    site_name = sites.index._data[site_number]
    return site_name


def retrieve_H_error(site_number, site_name, rate):
    if rate == 1:
        folder = "model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0"
        file_name_BV = "model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0_Ref_model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0_errorsresult_H_BVE.csv"
    else:
        folder = "model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0_Approx0_Period" + str(float(rate))
        file_name_BV = "model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0_Approx0_Period" + str(float(rate)) + "_Ref_model_time_0_geo_0_thick_1_K_27.32_Sy_0.1_Step1_site" + str(site_number) + "_Chronicle0_errorsresult_H_BVE.csv"
        
    result_file = folder_results_path + os.sep + site_name + os.sep + folder + os.sep + file_name_BV
    try:
        df = pd.read_csv(result_file, sep=";")
    except:
        print("no file", site_number, site_name, rate)
        return False
    H = df.iloc[0][0]
    #print(H)
    return H




