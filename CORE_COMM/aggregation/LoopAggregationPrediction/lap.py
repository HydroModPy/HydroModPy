#!/usr/bin/python
# -*- coding: utf-8 -*-


import argparse
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.metrics import r2_score
import csv
import random
random.seed(42)


### TO DO : save training data set in a file

def workflow_mix_split_train_test_SUB(nb_rates, features, scale, size_data, nb_replication=1):
    #random.seed(42)
    quality_metric_replication = []
    for replication in range(1, nb_replication+1):
        print("Replication n° ", replication)
        data_no_na = retrieve_and_clean_data(nb_rates, features, scale)
        #print(data_no_na)
        nb_sites, nb_subs =  extract_nb_sites_and_subs(data_no_na)
        #print(nb_sites, nb_subs)
        data_complete, sub_completes = extract_complete_data(data_no_na, nb_subs, nb_rates)
        #print(sub_completes)
        training_nb_sub, lst_couple_site_sub = split_subs_into_training_test_datasets(sub_completes)
        #print(training_nb_sub, len(lst_couple_site_sub))
        data_train, data_test, training_cases, test_cases = build_training_and_test_datasets(data_complete, lst_couple_site_sub, training_nb_sub)
        #print(data_train)
        X_train, y_train, X_test, y_test = extract_features_and_outputs_datasets_SUB(data_train, data_test)
        #print(X_train, y_train)
        forest = train_forest(X_train, y_train)
        y_test_pred = forest.predict(X_test)
        mse, r2 = compute_standard_metrics(y_test, y_test_pred)
        print("MSE: ", mse)
        print("R2: ", r2)
        #print(training_cases)
        data_test = update_and_store_data_with_h_pred(data_test, y_test, y_test_pred, training_cases, scale, size_data, one_case=False)
        #print(test_cases)
        #print(data_test.loc[(data_test['Site'] == 19)])
        #print(data_test.loc[(data_test['Site'] == 19) & (data_test['SubCatch'] == 1)])

        p_reals, p_preds = extract_preals_and_ppreds(data_test, test_cases, nb_rates)
        #print(p_reals, p_preds)
        hreal_preals, hreal_ppreds, quality_metric = extract_hreal_for_preal_and_ppred_and_quality_metric(data_test, test_cases, p_reals, p_preds)
        #print(hreal_preals, hreal_ppreds)
        #print(quality_metric)
        quality_metric_no_nan = [x for x in quality_metric if np.isnan(x) == False]
        quality_metric_sum = round(sum(quality_metric_no_nan),3)
        print("Quality metric (sum of introduced error): ", quality_metric_sum)
        quality_metric = [0 if x != x else x for x in quality_metric]
        store_metrics(test_cases, training_cases, lst_couple_site_sub, mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size_data)
        quality_metric_replication.append(quality_metric_sum)
    store_metrics_replication(quality_metric_replication, nb_replication, nb_rates, features, scale, size_data)

def workflow_mix_split_train_test_SUB_one_case(nb_rates, features, scale, size_data, nb_replication=1):
    quality_metric_replication = []
    data_no_na = retrieve_and_clean_data(nb_rates, features, scale)
    #print(data_no_na)
    nb_sites, nb_subs =  extract_nb_sites_and_subs(data_no_na)
    #print(nb_sites, nb_subs)
    data_complete, sub_completes = extract_complete_data(data_no_na, nb_subs, nb_rates)
    #print(sub_completes)
    lst_couple_site_sub = []
    for site in sub_completes:
        for sub in sub_completes[site]:
            lst_couple_site_sub.append([site, sub])

    print(lst_couple_site_sub)
    for replication in range(1, nb_replication+1):
        print("Replication: ", replication)
        lst_reduced_cases = reduce_size_BVE(lst_couple_site_sub, size_data)
        for case in lst_reduced_cases:
            training_nb_sub = 1
            data_train, data_test, training_cases, test_cases = retrieve_list_cases_and_pick_training_cases_SUB_one_case(data_complete, case, lst_reduced_cases)    

            X_train, y_train, X_test, y_test = extract_features_and_outputs_datasets_SUB(data_train, data_test)
    #print(X_train, y_train)
            forest = train_forest(X_train, y_train)
            y_test_pred = forest.predict(X_test)
            mse, r2 = compute_standard_metrics(y_test, y_test_pred)
            print("MSE: ", mse)
            print("R2: ", r2)
    #print(training_cases)
            data_test = update_and_store_data_with_h_pred(data_test, y_test, y_test_pred, training_cases, scale, size_data, one_case=True)

            p_reals, p_preds = extract_preals_and_ppreds(data_test, test_cases, nb_rates)
            print(p_reals, p_preds)
            hreal_preals, hreal_ppreds, quality_metric = extract_hreal_for_preal_and_ppred_and_quality_metric(data_test, test_cases, p_reals, p_preds)
            print(hreal_preals, hreal_ppreds)
            print(quality_metric)
            quality_metric_no_nan = [x for x in quality_metric if np.isnan(x) == False]
            quality_metric_sum = round(sum(quality_metric_no_nan),3)
            print("Quality metric (sum of introduced error): ", quality_metric_sum)
            quality_metric = [0 if x != x else x for x in quality_metric]
            store_metrics(test_cases, training_cases, lst_reduced_cases, mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size_data, one_case=True)
            quality_metric_replication.append(quality_metric_sum)
    store_metrics_replication(quality_metric_replication, nb_replication, nb_rates, features, scale, size_data, one_case=True)




def workflow_mix_split_train_test_BVE(nb_rates, features, scale, size_data, nb_replication=1, seed=42):
    quality_metric_replication = []
    for replication in range(1, nb_replication+1):
        print("Replication n° ", replication)
        data_no_na = retrieve_and_clean_data(nb_rates, features, scale)
        data_complete = extract_complete_data_for_BVE(data_no_na, nb_rates)
        input_data = reduce_size(data_complete, size_data)
        #print(input_data)
        data_train, data_test, training_cases, test_cases = retrieve_list_cases_and_pick_training_cases_BVE(input_data)
        X_train, y_train, X_test, y_test = extract_features_and_outputs_datasets_BVE(data_train, data_test)
        forest = train_forest(X_train, y_train)
        y_test_pred = forest.predict(X_test)
        mse, r2 = compute_standard_metrics(y_test, y_test_pred)
        print("MSE: ", mse)
        print("R2: ", r2)
        data_test = update_and_store_data_with_h_pred(data_test, y_test, y_test_pred, training_cases, scale, size_data)
        p_reals, p_preds = extract_preals_and_ppreds_BVE(data_test, test_cases, nb_rates)
        hreal_preals, hreal_ppreds, quality_metric = extract_hreal_for_preal_and_ppred_and_quality_metric_BVE(data_test, test_cases, p_reals, p_preds)
        quality_metric_no_nan = [x for x in quality_metric if np.isnan(x) == False]
        quality_metric_sum = round(sum(quality_metric_no_nan),3)
        print("Quality metric (sum of introduced error): ", quality_metric_sum)
        store_metrics_BVE(test_cases, training_cases, input_data.Site.unique(), mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size_data)
        quality_metric_replication.append(quality_metric_sum)
    store_metrics_replication(quality_metric_replication, nb_replication, nb_rates, features, scale, size_data)


def workflow_mix_split_train_test_BVE_one_case(nb_rates, features, scale, size_data, nb_replication=1, seed=42):
    quality_metric_replication = []
    #for replication in range(1, nb_replication+1):
    data_no_na = retrieve_and_clean_data(nb_rates, features, scale)
    data_complete = extract_complete_data_for_BVE(data_no_na, nb_rates)
    for replication in range(1, nb_replication+1):
        print("Replication: ", replication)
        input_data = reduce_size(data_complete, size_data)
        sites_completes = input_data.Site.unique()
        print(sites_completes)
        for site in sites_completes:
            data_train, data_test, training_cases, test_cases = retrieve_list_cases_and_pick_training_cases_BVE_one_case(input_data, site)
            print("Testing Cases: ", test_cases)
            print("Training cases: ", training_cases)
            X_train, y_train, X_test, y_test = extract_features_and_outputs_datasets_BVE(data_train, data_test)
            forest = train_forest(X_train, y_train)
            y_test_pred = forest.predict(X_test)
            mse, r2 = compute_standard_metrics(y_test, y_test_pred)
            print("MSE: ", mse)
            print("R2: ", r2)
            data_test = update_and_store_data_with_h_pred(data_test, y_test, y_test_pred, training_cases, scale, size_data, one_case=True)
            p_reals, p_preds = extract_preals_and_ppreds_BVE(data_test, test_cases, nb_rates)
            # print(p_reals)
            # print(p_preds)
            hreal_preals, hreal_ppreds, quality_metric = extract_hreal_for_preal_and_ppred_and_quality_metric_BVE(data_test, test_cases, p_reals, p_preds)
            # print(hreal_preals)
            # print(hreal_ppreds)
            quality_metric_no_nan = [x for x in quality_metric if np.isnan(x) == False]
            quality_metric_sum = round(sum(quality_metric_no_nan),3)
            print("Quality metric (sum of introduced error): ", quality_metric_sum)
            #print("", np.average(quality_metric_sums))
            store_metrics_BVE(test_cases, training_cases, input_data.Site.unique(), mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size_data, one_case=True)
            quality_metric_replication.append(quality_metric_sum)
    store_metrics_replication(quality_metric_replication, nb_replication, nb_rates, features, scale, size_data, one_case=True)


def retrieve_list_cases_and_pick_training_cases_BVE_one_case(data_complete, case):
    sites_completes = data_complete.Site.unique()

    #Build training data
    data_test = data_complete.loc[(data_complete['Site'] == case)]

    #Build test data
    training_cases = [x for x in sites_completes.tolist() if x not in [case]] + [x for x in [case] if x not in sites_completes.tolist()]
    data_train = pd.DataFrame(columns=data_complete.columns)
    for cas in training_cases:
        train = data_complete.loc[(data_complete['Site'] == cas)]
        data_train = pd.concat([data_train, train], sort=False)

    return data_train, data_test, training_cases, [case]


def retrieve_list_cases_and_pick_training_cases_SUB_one_case(data_complete, case, sites_completes):

    #Build training data
    data_test = data_complete.loc[(data_complete['Site'] == case[0]) & (data_complete['SubCatch'] == case[1])]

    #Build test data
    training_cases = [x for x in sites_completes if x not in [case]] + [x for x in [case] if x not in sites_completes]
    data_train = pd.DataFrame(columns=data_complete.columns)
    for cas in training_cases:
        train = data_complete.loc[(data_complete['Site'] == cas[0]) & (data_complete['SubCatch'] == cas[1])]
        data_train = pd.concat([data_train, train], sort=False)

    return data_train, data_test, training_cases, [case]



def retrieve_and_clean_data(nb_rates, features, scale):
    data = pd.read_csv("data/Input_Data/Input_Data_Complete_Rates_" + str(nb_rates) + "_Features_" + str(features) + "_" + str(scale) + "_Comparable.csv", sep=";",
        header=0)

    data.replace(' ', np.nan, inplace=True)
    data_no_na = data.dropna()

    return data_no_na

def extract_nb_sites_and_subs(data_no_na):
    nb_sites = data_no_na["Site"].max()
    # Number of subcatch per site
    nb_subs = {}
    for site_number in range(1, nb_sites+1):
        nb_sub = data_no_na[data_no_na["Site"]==site_number]['SubCatch'].max()
        if pd.isna(nb_sub):
            continue
        nb_subs[site_number] = nb_sub

    return nb_sites, nb_subs



def extract_complete_data(data_no_na, nb_subs, nb_rates):
    # Build data with data for all 30 rates
    data_complete = pd.DataFrame(columns=data_no_na.columns)
    sub_completes = {}
    for site in nb_subs.keys():
        for sub in range(1, int(nb_subs[site])+1):
            data_site_sub = data_no_na.loc[(data_no_na['Site'] == site) & (data_no_na['SubCatch'] == sub)]
            if data_site_sub.empty:
                continue
            if len(data_site_sub) == nb_rates:
                data_complete = pd.concat([data_complete, data_site_sub], sort=False)
                #print(sub_completes[site].empty)
                if site in sub_completes.keys():
                    sub_completes[site].append(sub)
                else:
                    sub_completes[site] = [sub]
    data_complete.to_csv("data/Data_Input_Sub_Complete_Rate_test.csv", index=False, sep=";")

    return data_complete, sub_completes


def extract_complete_data_for_BVE(data_no_na, nb_rates):
    data_complete = pd.DataFrame(columns=data_no_na.columns)
    sub_completes = {}
    nb_max_sites = int(data_no_na["Site"].max())

    for site in range(1, nb_max_sites+1):
        data_site = data_no_na.loc[(data_no_na['Site'] == site)]
    #if data_site_sub.empty:
    #    continue
        if len(data_site) == nb_rates:
            data_complete = pd.concat([data_complete, data_site], sort=False)
    return data_complete

def reduce_size(data_complete, size_data):
    #print(size_data)
    if size_data is not None:
        selected_sites = random.sample(data_complete.Site.unique().tolist(), size_data)
        print("Selected sites: ", selected_sites)
        input_data = pd.DataFrame(columns=data_complete.columns)
        for site in selected_sites:
            data_site = data_complete.loc[(data_complete['Site'] == site)]
            input_data = pd.concat([input_data, data_site], sort=False)
        #print(input_data)
        return input_data


def reduce_size_BVE(lst_couple_site_sub, size_data):
    if (size_data is not None) and (len(lst_couple_site_sub) > size_data):
        selected_sites = random.sample(lst_couple_site_sub, size_data)
        print("Selected sites: ", selected_sites)
        return selected_sites

def split_subs_into_training_test_datasets(sub_completes):
# Get number of subcatch for the split of data training / test : 80 / 20
    nb_subs_complete = 0
    for site in sub_completes:
        nb_subs_complete += len(sub_completes[site])
    training_nb_sub = round((nb_subs_complete * 80)/100)

    lst_couple_site_sub = []
    for site in sub_completes:
        for sub in sub_completes[site]:
            lst_couple_site_sub.append([site, sub])

    return training_nb_sub, lst_couple_site_sub


def split_subs_into_training_test_datasets_SUB_one_case(sub_completes):
# Get number of subcatch for the split of data training / test : 1 case
    nb_subs_complete = 0
    for site in sub_completes:
        nb_subs_complete += len(sub_completes[site])
    training_nb_sub = 1

    lst_couple_site_sub = []
    for site in sub_completes:
        for sub in sub_completes[site]:
            lst_couple_site_sub.append([site, sub])

    return training_nb_sub, lst_couple_site_sub


def retrieve_list_cases_and_pick_training_cases_BVE(data_complete):
    sites_completes = data_complete.Site.unique()
    training_nb_cases = round((len(sites_completes) * 80)/100)


    training_cases = random.sample(sites_completes.tolist(), training_nb_cases)

    #Build training data
    data_train = pd.DataFrame(columns=data_complete.columns)
    for case in training_cases:
        train = data_complete.loc[(data_complete['Site'] == case)]
        data_train = pd.concat([data_train, train], sort=False)

    #Build test data
    test_cases = [x for x in sites_completes.tolist() if x not in training_cases] + [x for x in training_cases if x not in sites_completes.tolist()]
    data_test = pd.DataFrame(columns=data_complete.columns)
    for case in test_cases:
        test = data_complete.loc[(data_complete['Site'] == case)]
        data_test = pd.concat([data_test, test], sort=False)

    return data_train, data_test, training_cases, test_cases


def build_training_and_test_datasets(data_complete, lst_couple_site_sub, training_nb_sub):
    # Build training dataset
    training_couples = random.sample(lst_couple_site_sub, training_nb_sub)
    data_train = pd.DataFrame(columns=data_complete.columns)
    for couple in training_couples:
        train = data_complete.loc[(data_complete['Site'] == couple[0]) & (data_complete['SubCatch'] == couple[1])]
        data_train = pd.concat([data_train, train], sort=False)

    # Build Testing dataset
    test_couples = [x for x in lst_couple_site_sub if x not in training_couples] + [x for x in training_couples if x not in lst_couple_site_sub]
    data_test = pd.DataFrame(columns=data_complete.columns)
    for couple in test_couples:
        test = data_complete.loc[(data_complete['Site'] == couple[0]) & (data_complete['SubCatch'] == couple[1])]
        data_test = pd.concat([data_test, test], sort=False)

    return data_train, data_test, training_couples, test_couples


def build_training_and_test_datasets_one_case(data_complete, lst_couple_site_sub, training_nb_sub):
    # Build training dataset
    training_couples = random.sample(lst_couple_site_sub, training_nb_sub)
    data_train = pd.DataFrame(columns=data_complete.columns)
    for couple in training_couples:
        train = data_complete.loc[(data_complete['Site'] == couple[0]) & (data_complete['SubCatch'] == couple[1])]
        data_train = pd.concat([data_train, train], sort=False)

    # Build Testing dataset
    test_couples = [x for x in lst_couple_site_sub if x not in training_couples] + [x for x in training_couples if x not in lst_couple_site_sub]
    data_test = pd.DataFrame(columns=data_complete.columns)
    for couple in test_couples:
        test = data_complete.loc[(data_complete['Site'] == couple[0]) & (data_complete['SubCatch'] == couple[1])]
        data_test = pd.concat([data_test, test], sort=False)

    return data_train, data_test, training_couples, test_couples



def extract_features_and_outputs_datasets_SUB(data_train, data_test):
    y_train = data_train.filter(["Site", "SubCatch", "H Error"], axis=1)
    X_train = data_train.drop("H Error", axis=1)
    del y_train["Site"]
    del y_train["SubCatch"]
    del X_train["Site"]
    del X_train["SubCatch"]

    y_test = data_test.filter(["Site", "SubCatch", "H Error"], axis=1)
    X_test = data_test.drop("H Error", axis=1)
    del y_test["Site"]
    del y_test["SubCatch"]
    del X_test["Site"]
    del X_test["SubCatch"]

    return X_train, y_train, X_test, y_test

def extract_features_and_outputs_datasets_BVE(data_train, data_test):
    y_train = data_train.filter(["Site", "H Error"], axis=1)
    X_train = data_train.drop("H Error", axis=1)
    del y_train["Site"]
    del X_train["Site"]

    y_test = data_test.filter(["Site", "H Error"], axis=1)
    X_test = data_test.drop("H Error", axis=1)
    del y_test["Site"]
    del X_test["Site"]

    return X_train, y_train, X_test, y_test 



def train_forest(X_train, y_train):
    forest = RandomForestRegressor(
        n_estimators=1000, criterion="mse", random_state=1, n_jobs=-1, oob_score = True, bootstrap = True
    )
    forest.fit(X_train, y_train.values.ravel())

    return forest


def compute_standard_metrics(y_test, y_test_pred):

    mse = mean_squared_error(y_test.values.ravel(), y_test_pred)
    r2 = r2_score(y_test.values.ravel(), y_test_pred)

    return mse, r2

def get_suffixe(scale, training_cases, data_size, one_case=False):
    suffixe = ""
    if scale == "_BVE":
        suffixe = "_".join(map(str,list(map(int, training_cases))))
    if one_case:
        suffixe += "_OneCase"
    if data_size is not None:
        suffixe += "_Size_" + str(data_size)
    return suffixe


def update_and_store_data_with_h_pred(data_test, y_test, y_test_pred, training_cases, scale, data_size, one_case=False):
    suffixe = get_suffixe(scale, training_cases, data_size, one_case)
    data_test = data_test.assign(Htest=y_test.values.ravel())
    data_test = data_test.assign(HtestPred=y_test_pred)
    data_test.to_csv("data/Output_Data/Data_Test_With_Htest_pred_Rates_" + str(nb_rates) + "_Features_" + str(features) + "_" + str(scale)  + "" + str(suffixe) + ".csv", index=False, sep=";")
    return data_test

def extract_preals_and_ppreds(data_test, test_couples, nb_rates):
    p_reals = []
    p_preds = []
    threshold = 0.1
    for couple in test_couples:
        test = data_test.loc[(data_test['Site'] == int(couple[0])) & (data_test['SubCatch'] == couple[1])]
        #print(test)
        htest_valid = True
        htestpred_valid = True
        preal = 0
        ppred = 0
        for i_rate in range(nb_rates):
            #print("i_rate", i_rate)
            htest = test["Htest"].tolist()[i_rate]
            #print(htest, i_rate)
            htest_pred = test["HtestPred"].tolist()[i_rate]
            if (float(htest) > threshold) & (htest_valid):
                #print("float(htest) > threshold!")
                htest_valid = False
                #print(test["Rate"].tolist()[i_rate-1])
                preal = test["Rate"].tolist()[i_rate-1]
                p_reals.append(preal)
            if (float(htest_pred) > threshold) & (htestpred_valid):
                htestpred_valid = False
                ppred = test["Rate"].tolist()[i_rate-1]
                p_preds.append(ppred)
            if (i_rate == nb_rates-1) & htest_valid:
                preal = test["Rate"].tolist()[i_rate]
                p_reals.append(preal)
            if (i_rate == nb_rates-1) & htestpred_valid:
                ppred = test["Rate"].tolist()[i_rate]
                p_preds.append(ppred)

    return p_reals, p_preds


def extract_preals_and_ppreds_BVE(data_test, test_cases, nb_rates):
    p_reals = []
    p_preds = []
    threshold = 0.1
    for case in test_cases:
        test = data_test.loc[(data_test['Site'] == case)]
        #print(test)
        htest_valid = True
        htestpred_valid = True
        preal = 0
        ppred = 0
        for i_rate in range(nb_rates):
            htest = test["Htest"].tolist()[i_rate]
            htest_pred = test["HtestPred"].tolist()[i_rate]
            if (float(htest) > threshold) & (htest_valid):
                htest_valid = False
                preal = test["Rate"].tolist()[i_rate-1]
                p_reals.append(preal)
            if (float(htest_pred) > threshold) & (htestpred_valid):
                htestpred_valid = False
                ppred = test["Rate"].tolist()[i_rate-1]
                p_preds.append(ppred)
            if (i_rate == nb_rates-1) & htest_valid:
                preal = test["Rate"].tolist()[i_rate]
                p_reals.append(preal)
            if (i_rate == nb_rates-1) & htestpred_valid:
                ppred = test["Rate"].tolist()[i_rate]
                p_preds.append(ppred)

    return p_reals, p_preds

def extract_hreal_for_preal_and_ppred_and_quality_metric(data_test, test_couples, p_reals, p_preds):
    hreal_preals = []
    hreal_ppreds = []
    quality_metric = []
    for i_sub in range(len(test_couples)):
        d_preal = data_test.loc[(data_test['Site'] == test_couples[i_sub][0]) & (data_test['SubCatch'] == test_couples[i_sub][1]) & (data_test['Rate'] == p_reals[i_sub])]
        hreal_preal = d_preal["H Error"]
        d_ppred = data_test.loc[(data_test['Site'] == test_couples[i_sub][0]) & (data_test['SubCatch'] == test_couples[i_sub][1]) & (data_test['Rate'] == p_preds[i_sub])]
        hreal_ppred = d_ppred["H Error"]
        #print(hreal_preal, hreal_ppred)
        hreal_preals.append(float(hreal_preal))
        hreal_ppreds.append(float(hreal_ppred))
        if p_preds[i_sub] > p_reals[i_sub]:
            quality_metric.append(float(hreal_ppred)-float(hreal_preal))
        else:
            quality_metric.append(np.nan)

    return hreal_preals, hreal_ppreds, quality_metric


def extract_hreal_for_preal_and_ppred_and_quality_metric_BVE(data_test, test_cases, p_reals, p_preds):
    hreal_preals = []
    hreal_ppreds = []
    quality_metric = []
    for i_case in range(len(test_cases)):
        d_preal = data_test.loc[(data_test['Site'] == test_cases[i_case]) & (data_test['Rate'] == p_reals[i_case])]
        hreal_preal = d_preal["H Error"]
        d_ppred = data_test.loc[(data_test['Site'] == test_cases[i_case])  & (data_test['Rate'] == p_preds[i_case])]
        hreal_ppred = d_ppred["H Error"]
        #print(hreal_preal, hreal_ppred)
        hreal_preals.append(float(hreal_preal))
        hreal_ppreds.append(float(hreal_ppred))
        if p_preds[i_case] > p_reals[i_case]:
            quality_metric.append(float(hreal_ppred)-float(hreal_preal))
        else:
            quality_metric.append(np.nan)

    return hreal_preals, hreal_ppreds, quality_metric


def store_metrics(test_cases, training_cases, sites_completes, mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size, one_case=False):
    suffixe = ""
    if scale == "BVE":
        suffixe = "_".join(map(str,list(map(int, training_cases))))
    if one_case:
        suffixe += "_OneCase"
    if size is not None:
        suffixe = "_Size_" + str(size)
    MYDIR = "data/Output_Data"
    with open(
        MYDIR
        + "/"
        + "Prediction_data_complete_Rates_" + str(nb_rates) + "_Features_" + str(features) + "_" + str(scale) + "_" + str(suffixe) + ".csv",
        "w",
    ) as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            [
                "Site",
                "SubCatch",
                "Number Data Training",
                "Number Global Data",
                "MSE Test",
                "R2 Test",
                "Quality Metric",
                "Quality Sum",
                "P Real",
                "P pred",
                "H Real Preal",
                "H Real Ppred"
            ]
        )
        for ind in range(len(test_cases)):
            writer.writerow(
                [
                    test_cases[ind][0],
                    test_cases[ind][1],
                    len(training_cases),
                    len(sites_completes),
                    mse,
                    r2,
                    quality_metric[ind],
                    quality_metric_sum,
                    p_reals[ind],
                    p_preds[ind],
                    hreal_preals[ind],
                    hreal_ppreds[ind]
                ]
            )


def store_metrics_BVE(test_cases, training_cases, sites_completes, mse, r2, quality_metric, quality_metric_sum, p_reals, p_preds, hreal_preals, hreal_ppreds, scale, size, one_case=False):
    suffixe = ""
    if scale == "BVE":
        suffixe = "_".join(map(str,list(map(int, training_cases))))
    if one_case:
        suffixe += "_OneCase"
    if size is not None:
        suffixe = "_Size_" + str(size)
    MYDIR = "data/Output_Data"
    with open(
        MYDIR
        + "/"
        + "Prediction_data_complete_Rates_" + str(nb_rates) + "_Features_" + str(features) + "_" + str(scale) + "_" + str(suffixe) + ".csv",
        "w",
    ) as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            [
                "Site",
                "Number Data Training",
                "Number Global Data",
                "MSE Test",
                "R2 Test",
                "Quality Metric",
                "Quality Sum",
                "P Real",
                "P pred",
                "H Real Preal",
                "H Real Ppred"
            ]
        )
        for ind in range(len(test_cases)):
            writer.writerow(
                [
                    test_cases[ind],
                    len(training_cases),
                    len(sites_completes),
                    mse,
                    r2,
                    quality_metric[ind],
                    quality_metric_sum,
                    p_reals[ind],
                    p_preds[ind],
                    hreal_preals[ind],
                    hreal_ppreds[ind]
                ]
            )

def store_metrics_replication(quality_metric_sums, nb_replication, nb_rates, features, scale, size, one_case=False):
    suffixe = "Replication_" + str(nb_replication)
    if one_case:
        suffixe += "_OneCase"
    if size is not None:
        suffixe += "_Size_" + str(size)
    #print(suffixe)
    MYDIR = "data/Output_Data/Replication"
    with open(
        MYDIR
        + "/"
        + "Prediction_data_complete_Rates_" + str(nb_rates) + "_Features_" + str(features) + "_" + str(scale) + "_" + str(suffixe) + ".csv",
        "w",
    ) as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            [   "Quality Metric",
                "Sum quality metric",
                "Mean quality metric",
                "Median quality metric",
                "STD quality metric",
                "Min quality metric",
                "Max quality metric"
            ]
        )
        for ind in range(len(quality_metric_sums)):
            writer.writerow(
                [
                    quality_metric_sums[ind],
                    round(sum(quality_metric_sums), 3),
                    np.average(quality_metric_sums),
                    np.median(quality_metric_sums),
                    np.std(quality_metric_sums),
                    min(quality_metric_sums),
                    max(quality_metric_sums)
                ]
            )


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--features", type=str, required=True)
    parser.add_argument("-nbrate", type=int, required=True)
    parser.add_argument("-sc", type=str, required=True)
    parser.add_argument("-onecase", action='store_true')
    parser.add_argument("-rep", type=int, required=False)
    parser.add_argument("-seed", type=int, required=False)
    parser.add_argument("-size", type=int, required=False)
    args = parser.parse_args()

    features = args.features
    nb_rates = args.nbrate
    scale = args.sc
    nb_replication = args.rep
    seed = args.seed
    one_case = args.onecase
    size = args.size

    # nb_rates = 30
    # features =  "Saturation" #"Geomorph" #Saturation
    # scale = "BVE"
    #workflow_sub_mix_split_train_test(nb_rates, features, scale)

    #workflow_mix_split_train_test_BVE(nb_rates, features, scale, nb_replication, seed)
    if scale == "BVE":
        if one_case:
            workflow_mix_split_train_test_BVE_one_case(nb_rates, features, scale, size, nb_replication, seed)
        else:
            workflow_mix_split_train_test_BVE(nb_rates, features, scale, size, nb_replication, seed)
    else:
        if one_case:
            workflow_mix_split_train_test_SUB_one_case(nb_rates, features, scale, size, nb_replication)
        else:
            workflow_mix_split_train_test_SUB(nb_rates, features, scale, size, nb_replication)
