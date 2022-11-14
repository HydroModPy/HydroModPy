# -*- coding: utf-8 -*-
"""
Created on Wed Jun  1 17:24:43 2022

@author: Martin
"""

# /!\ RN2100_steady must be ran in transient mode to compute recharge values before running this script

#[R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85
#R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85]

#%% Group by month and year

import statistics

R_MPI_CCL_RCP26_month = R_MPI_CCL_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RCA_RCP26_month = R_ECE_RCA_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RAC_RCP26_month = R_ECE_RAC_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_CNR_RAC_RCP26_month = R_CNR_RAC_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_NOR_R15_RCP26_month = R_NOR_R15_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_CNR_ALA_RCP26_month = R_CNR_ALA_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP26_month = R_HAD_REG_RCP26.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP26_month[R_HAD_REG_RCP26_month==0] = float("NaN")
R_MPI_R09_RCP26_month = R_MPI_R09_RCP26.groupby(pd.Grouper(freq="M")).sum()

DRIAS_models_list = ['MPI_CCL', 'ECE_RCA', 'ECE_RAC', 'CNR_RAC',
                     'NOR_R15', 'CNR_ALA', 'HAD_REG', 'MPI_R09']

R_DRIAS_26_month_dict = {
    0 : R_MPI_CCL_RCP26_month,
    1 : R_ECE_RCA_RCP26_month,
    2 : R_ECE_RAC_RCP26_month,
    3 : R_CNR_RAC_RCP26_month,
    4 : R_NOR_R15_RCP26_month,
    5 : R_CNR_ALA_RCP26_month,
    6 : R_HAD_REG_RCP26_month,
    7 : R_MPI_R09_RCP26_month}

R_DRIAS_26_month_med = []
for i in range(0,len(R_MPI_CCL_RCP26_month)) :
    R_DRIAS_26_month_med.append(statistics.median([R_MPI_CCL_RCP26_month[i],
                                                  R_ECE_RCA_RCP26_month[i],
                                                  R_ECE_RAC_RCP26_month[i],
                                                  R_CNR_RAC_RCP26_month[i],
                                                  R_NOR_R15_RCP26_month[i],
                                                  R_CNR_ALA_RCP26_month[i],
                                                  R_HAD_REG_RCP26_month[i],
                                                  R_MPI_R09_RCP26_month[i]]))

R_MPI_CCL_RCP85_month = R_MPI_CCL_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RCA_RCP85_month = R_ECE_RCA_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_ECE_RAC_RCP85_month = R_ECE_RAC_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_CNR_RAC_RCP85_month = R_CNR_RAC_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_NOR_R15_RCP85_month = R_NOR_R15_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_CNR_ALA_RCP85_month = R_CNR_ALA_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP85_month = R_HAD_REG_RCP85.groupby(pd.Grouper(freq="M")).sum()
R_HAD_REG_RCP85_month[R_HAD_REG_RCP85_month==0] = float("NaN")
R_MPI_R09_RCP85_month = R_MPI_R09_RCP85.groupby(pd.Grouper(freq="M")).sum()

R_DRIAS_85_month_dict = {
    0 : R_MPI_CCL_RCP85_month,
    1 : R_ECE_RCA_RCP85_month,
    2 : R_ECE_RAC_RCP85_month,
    3 : R_CNR_RAC_RCP85_month,
    4 : R_NOR_R15_RCP85_month,
    5 : R_CNR_ALA_RCP85_month,
    6 : R_HAD_REG_RCP85_month,
    7 : R_MPI_R09_RCP85_month}

R_DRIAS_85_month_med = []
for i in range(0,len(R_MPI_CCL_RCP85_month)) :
    R_DRIAS_85_month_med.append(statistics.median([R_MPI_CCL_RCP85_month[i],
                                                  R_ECE_RCA_RCP85_month[i],
                                                  R_ECE_RAC_RCP85_month[i],
                                                  R_CNR_RAC_RCP85_month[i],
                                                  R_NOR_R15_RCP85_month[i],
                                                  R_CNR_ALA_RCP85_month[i],
                                                  R_HAD_REG_RCP85_month[i],
                                                  R_MPI_R09_RCP85_month[i]]))


R_MPI_CCL_RCP26_year = R_MPI_CCL_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RCA_RCP26_year = R_ECE_RCA_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RAC_RCP26_year = R_ECE_RAC_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_RAC_RCP26_year = R_CNR_RAC_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_NOR_R15_RCP26_year = R_NOR_R15_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_ALA_RCP26_year = R_CNR_ALA_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_HAD_REG_RCP26_year = R_HAD_REG_RCP26.groupby(pd.Grouper(freq="Y")).sum()
R_MPI_R09_RCP26_year = R_MPI_R09_RCP26.groupby(pd.Grouper(freq="Y")).sum()

R_MPI_CCL_RCP85_year = R_MPI_CCL_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RCA_RCP85_year = R_ECE_RCA_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_ECE_RAC_RCP85_year = R_ECE_RAC_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_RAC_RCP85_year = R_CNR_RAC_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_NOR_R15_RCP85_year = R_NOR_R15_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_CNR_ALA_RCP85_year = R_CNR_ALA_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_HAD_REG_RCP85_year = R_HAD_REG_RCP85.groupby(pd.Grouper(freq="Y")).sum()
R_MPI_R09_RCP85_year = R_MPI_R09_RCP85.groupby(pd.Grouper(freq="Y")).sum()


#%% Recharge values for 2030 horizon
import statistics
import numpy

# 2030 annual recharge (m/yr): mean of 2028-2032  years
R_MPI_CCL_RCP26_2030 = R_MPI_CCL_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_MPI_CCL_RCP85_2030 = R_MPI_CCL_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_ECE_RCA_RCP26_2030 = R_ECE_RCA_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_ECE_RCA_RCP85_2030 = R_ECE_RCA_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_ECE_RAC_RCP26_2030 = R_ECE_RAC_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_ECE_RAC_RCP85_2030 = R_ECE_RAC_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_CNR_RAC_RCP26_2030 = R_CNR_RAC_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_CNR_RAC_RCP85_2030 = R_CNR_RAC_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_NOR_R15_RCP26_2030 = R_NOR_R15_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_NOR_R15_RCP85_2030 = R_NOR_R15_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_CNR_ALA_RCP26_2030 = R_CNR_ALA_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_CNR_ALA_RCP85_2030 = R_CNR_ALA_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_HAD_REG_RCP26_2030 = R_HAD_REG_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_HAD_REG_RCP85_2030 = R_HAD_REG_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4
R_MPI_R09_RCP26_2030 = R_MPI_R09_RCP26.loc['2028-09-01':'2032-08-31'].sum()/4
R_MPI_R09_RCP85_2030 = R_MPI_R09_RCP85.loc['2028-09-01':'2032-08-31'].sum()/4

month_2030_4y_idx_list = [i for i in range(8*12, 12*12, 12)]

#RCP 2.6 recharge nalysis
R_DRIAS_26_2030_mean_list = [R_MPI_CCL_RCP26_2030, R_ECE_RCA_RCP26_2030, R_ECE_RAC_RCP26_2030,
                          R_CNR_RAC_RCP26_2030, R_NOR_R15_RCP26_2030, R_CNR_ALA_RCP26_2030,
                          R_HAD_REG_RCP26_2030, R_MPI_R09_RCP26_2030]

R_DRIAS_26_2030_min = min(R_DRIAS_26_2030_mean_list)
index_min_R_26_2030 = min(range(len(R_DRIAS_26_2030_mean_list)), key=R_DRIAS_26_2030_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2030]
R_DRIAS_26_2030_max = max(R_DRIAS_26_2030_mean_list)
index_max_R_26_2030 = max(range(len(R_DRIAS_26_2030_mean_list)), key=R_DRIAS_26_2030_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2030]
# R_DRIAS_26_2030_med = statistics.median(R_DRIAS_26_2030_mean_list)

R_DRIAS_26_2030_mean_list_temp = R_DRIAS_26_2030_mean_list
for i in range(3):
    idx_max_R_26_2030 = max(range(len(R_DRIAS_26_2030_mean_list_temp)), key=R_DRIAS_26_2030_mean_list_temp.__getitem__)
    R_DRIAS_26_2030_mean_list_temp[idx_max_R_26_2030] = 0
index_4th_R_26_2030 = max(range(len(R_DRIAS_26_2030_mean_list_temp)), key=R_DRIAS_26_2030_mean_list_temp.__getitem__)    
R_DRIAS_26_month_4th = R_DRIAS_26_month_dict[index_4th_R_26_2030]

R_DRIAS_26_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_26_month_min[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_26_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_26_month_max[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_26_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_26_month_4th[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+11 for i in month_2030_4y_idx_list]])]

# R_DRIAS_26_month_mean_med = [
#     numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2030_4y_idx_list])]

#RCP 8.5 recharge nalysis
R_DRIAS_85_2030_mean_list = [R_MPI_CCL_RCP85_2030, R_ECE_RCA_RCP85_2030, R_ECE_RAC_RCP85_2030,
                          R_CNR_RAC_RCP85_2030, R_NOR_R15_RCP85_2030, R_CNR_ALA_RCP85_2030,
                          R_HAD_REG_RCP85_2030, R_MPI_R09_RCP85_2030]

R_DRIAS_85_2030_min = min(R_DRIAS_85_2030_mean_list)
index_min_R_85_2030 = min(range(len(R_DRIAS_85_2030_mean_list)), key=R_DRIAS_85_2030_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2030]
R_DRIAS_85_2030_max = max(R_DRIAS_85_2030_mean_list)
index_max_R_85_2030 = max(range(len(R_DRIAS_85_2030_mean_list)), key=R_DRIAS_85_2030_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2030]
# R_DRIAS_85_2030_med = statistics.median(R_DRIAS_85_2030_mean_list)

R_DRIAS_85_2030_mean_list_temp = R_DRIAS_85_2030_mean_list
for i in range(3):
    idx_max_R_85_2030 = max(range(len(R_DRIAS_85_2030_mean_list_temp)), key=R_DRIAS_85_2030_mean_list_temp.__getitem__)
    R_DRIAS_85_2030_mean_list_temp[idx_max_R_85_2030] = 0
index_4th_R_85_2030 = max(range(len(R_DRIAS_85_2030_mean_list_temp)), key=R_DRIAS_85_2030_mean_list_temp.__getitem__)    
R_DRIAS_85_month_4th = R_DRIAS_85_month_dict[index_4th_R_85_2030]

R_DRIAS_85_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_85_month_min[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_85_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_85_month_max[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2030_4y_idx_list]])]
R_DRIAS_85_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_85_month_4th[month_2030_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+1 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+2 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+3 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+4 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+5 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+6 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+7 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+8 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+9 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+10 for i in month_2030_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+11 for i in month_2030_4y_idx_list]])]

# R_DRIAS_85_month_mean_med = [
#     numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2030_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2030_4y_idx_list])]


# Plot
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_26_2030])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2030])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_26_2030])
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_85_2030])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2030])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_85_2030])
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2030 forecast recharges (mm/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')

#%% Recharge values for 2050 horizon

# 2050 annual recharge (m/yr): mean of 2048-2052 years
R_MPI_CCL_RCP26_2050 = R_MPI_CCL_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_MPI_CCL_RCP85_2050 = R_MPI_CCL_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_ECE_RCA_RCP26_2050 = R_ECE_RCA_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_ECE_RCA_RCP85_2050 = R_ECE_RCA_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_ECE_RAC_RCP26_2050 = R_ECE_RAC_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_ECE_RAC_RCP85_2050 = R_ECE_RAC_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_CNR_RAC_RCP26_2050 = R_CNR_RAC_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_CNR_RAC_RCP85_2050 = R_CNR_RAC_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_NOR_R15_RCP26_2050 = R_NOR_R15_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_NOR_R15_RCP85_2050 = R_NOR_R15_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_CNR_ALA_RCP26_2050 = R_CNR_ALA_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_CNR_ALA_RCP85_2050 = R_CNR_ALA_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_HAD_REG_RCP26_2050 = R_HAD_REG_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_HAD_REG_RCP85_2050 = R_HAD_REG_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4
R_MPI_R09_RCP26_2050 = R_MPI_R09_RCP26.loc['2048-09-01':'2052-08-31'].sum()/4
R_MPI_R09_RCP85_2050 = R_MPI_R09_RCP85.loc['2048-09-01':'2052-08-31'].sum()/4

month_2050_4y_idx_list = [i for i in range(28*12, 32*12, 12)]

#RCP 2.6 recharge nalysis
R_DRIAS_26_2050_mean_list = [R_MPI_CCL_RCP26_2050, R_ECE_RCA_RCP26_2050, R_ECE_RAC_RCP26_2050,
                          R_CNR_RAC_RCP26_2050, R_NOR_R15_RCP26_2050, R_CNR_ALA_RCP26_2050,
                          R_HAD_REG_RCP26_2050, R_MPI_R09_RCP26_2050]

R_DRIAS_26_2050_min = min(R_DRIAS_26_2050_mean_list)
index_min_R_26_2050 = min(range(len(R_DRIAS_26_2050_mean_list)), key=R_DRIAS_26_2050_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2050]
R_DRIAS_26_2050_max = max(R_DRIAS_26_2050_mean_list)
index_max_R_26_2050 = max(range(len(R_DRIAS_26_2050_mean_list)), key=R_DRIAS_26_2050_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2050]
# R_DRIAS_26_2050_med = statistics.median(R_DRIAS_26_2050_mean_list)

R_DRIAS_26_2050_mean_list_temp = R_DRIAS_26_2050_mean_list
for i in range(3):
    idx_max_R_26_2050 = max(range(len(R_DRIAS_26_2050_mean_list_temp)), key=R_DRIAS_26_2050_mean_list_temp.__getitem__)
    R_DRIAS_26_2050_mean_list_temp[idx_max_R_26_2050] = 0
index_4th_R_26_2050 = max(range(len(R_DRIAS_26_2050_mean_list_temp)), key=R_DRIAS_26_2050_mean_list_temp.__getitem__)    
R_DRIAS_26_month_4th = R_DRIAS_26_month_dict[index_4th_R_26_2050]

R_DRIAS_26_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_26_month_min[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_26_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_26_month_max[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_26_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_26_month_4th[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+11 for i in month_2050_4y_idx_list]])]

# R_DRIAS_26_month_mean_med = [
#     numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2050_4y_idx_list])]

#RCP 8.5 recharge nalysis
R_DRIAS_85_2050_mean_list = [R_MPI_CCL_RCP85_2050, R_ECE_RCA_RCP85_2050, R_ECE_RAC_RCP85_2050,
                          R_CNR_RAC_RCP85_2050, R_NOR_R15_RCP85_2050, R_CNR_ALA_RCP85_2050,
                          R_HAD_REG_RCP85_2050, R_MPI_R09_RCP85_2050]

R_DRIAS_85_2050_min = min(R_DRIAS_85_2050_mean_list)
index_min_R_85_2050 = min(range(len(R_DRIAS_85_2050_mean_list)), key=R_DRIAS_85_2050_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2050]
R_DRIAS_85_2050_max = max(R_DRIAS_85_2050_mean_list)
index_max_R_85_2050 = max(range(len(R_DRIAS_85_2050_mean_list)), key=R_DRIAS_85_2050_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2050]
# R_DRIAS_85_2050_med = statistics.median(R_DRIAS_85_2050_mean_list)

R_DRIAS_85_2050_mean_list_temp = R_DRIAS_85_2050_mean_list
for i in range(3):
    idx_max_R_85_2050 = max(range(len(R_DRIAS_85_2050_mean_list_temp)), key=R_DRIAS_85_2050_mean_list_temp.__getitem__)
    R_DRIAS_85_2050_mean_list_temp[idx_max_R_85_2050] = 0
index_4th_R_85_2050 = max(range(len(R_DRIAS_85_2050_mean_list_temp)), key=R_DRIAS_85_2050_mean_list_temp.__getitem__)    
R_DRIAS_85_month_4th = R_DRIAS_85_month_dict[index_4th_R_85_2050]

R_DRIAS_85_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_85_month_min[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_85_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_85_month_max[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2050_4y_idx_list]])]
R_DRIAS_85_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_85_month_4th[month_2050_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+1 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+2 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+3 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+4 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+5 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+6 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+7 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+8 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+9 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+10 for i in month_2050_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+11 for i in month_2050_4y_idx_list]])]

# R_DRIAS_85_month_mean_med = [
#     numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2050_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2050_4y_idx_list])]

# Plot
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_26_2050])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2050])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_26_2050])
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_85_2050])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2050])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_85_2050])
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2050 forecast recharges (mm/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')

#%% Recharge values for 2100 horizon

# 2100 annual recharge (m/yr): mean of 2096-2099 years
R_MPI_CCL_RCP26_2100 = R_MPI_CCL_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_MPI_CCL_RCP85_2100 = R_MPI_CCL_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_ECE_RCA_RCP26_2100 = R_ECE_RCA_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_ECE_RCA_RCP85_2100 = R_ECE_RCA_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_ECE_RAC_RCP26_2100 = R_ECE_RAC_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_ECE_RAC_RCP85_2100 = R_ECE_RAC_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_CNR_RAC_RCP26_2100 = R_CNR_RAC_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_CNR_RAC_RCP85_2100 = R_CNR_RAC_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_NOR_R15_RCP26_2100 = R_NOR_R15_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_NOR_R15_RCP85_2100 = R_NOR_R15_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_CNR_ALA_RCP26_2100 = R_CNR_ALA_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_CNR_ALA_RCP85_2100 = R_CNR_ALA_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_HAD_REG_RCP26_2100 = R_HAD_REG_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_HAD_REG_RCP85_2100 = R_HAD_REG_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4
R_MPI_R09_RCP26_2100 = R_MPI_R09_RCP26.loc['2095-09-01':'2099-08-31'].sum()/4
R_MPI_R09_RCP85_2100 = R_MPI_R09_RCP85.loc['2095-09-01':'2099-08-31'].sum()/4

month_2100_4y_idx_list = [i for i in range(76*12, 80*12, 12)]

#RCP 2.6 recharge nalysis
R_DRIAS_26_2100_mean_list = [R_MPI_CCL_RCP26_2100, R_ECE_RCA_RCP26_2100, R_ECE_RAC_RCP26_2100,
                          R_CNR_RAC_RCP26_2100, R_NOR_R15_RCP26_2100, R_CNR_ALA_RCP26_2100,
                          R_HAD_REG_RCP26_2100, R_MPI_R09_RCP26_2100]

R_DRIAS_26_2100_min = min(R_DRIAS_26_2100_mean_list)
index_min_R_26_2100 = min(range(len(R_DRIAS_26_2100_mean_list)), key=R_DRIAS_26_2100_mean_list.__getitem__)
R_DRIAS_26_month_min = R_DRIAS_26_month_dict[index_min_R_26_2100]
R_DRIAS_26_2100_max = max(R_DRIAS_26_2100_mean_list)
index_max_R_26_2100 = max(range(len(R_DRIAS_26_2100_mean_list)), key=R_DRIAS_26_2100_mean_list.__getitem__)
R_DRIAS_26_month_max = R_DRIAS_26_month_dict[index_max_R_26_2100]
R_DRIAS_26_2100_med = statistics.median(R_DRIAS_26_2100_mean_list)

R_DRIAS_26_2100_mean_list_temp = R_DRIAS_26_2100_mean_list
for i in range(3):
    idx_max_R_26_2100 = max(range(len(R_DRIAS_26_2100_mean_list_temp)), key=R_DRIAS_26_2100_mean_list_temp.__getitem__)
    R_DRIAS_26_2100_mean_list_temp[idx_max_R_26_2100] = 0
index_4th_R_26_2100 = max(range(len(R_DRIAS_26_2100_mean_list_temp)), key=R_DRIAS_26_2100_mean_list_temp.__getitem__)    
R_DRIAS_26_month_4th = R_DRIAS_26_month_dict[index_4th_R_26_2100]

R_DRIAS_26_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_26_month_min[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_min[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_26_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_26_month_max[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_max[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_26_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_26_month_4th[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_26_month_4th[[i+11 for i in month_2100_4y_idx_list]])]

# R_DRIAS_26_month_mean_med = [
#     numpy.nanmean([R_DRIAS_26_month_med[x] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+1] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+2] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+3] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+4] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+5] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+6] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+7] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+8] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+9] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+10] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_26_month_med[x+11] for x in month_2100_4y_idx_list])]


#RCP 8.5 recharge nalysis
R_DRIAS_85_2100_mean_list = [R_MPI_CCL_RCP85_2100, R_ECE_RCA_RCP85_2100, R_ECE_RAC_RCP85_2100,
                          R_CNR_RAC_RCP85_2100, R_NOR_R15_RCP85_2100, R_CNR_ALA_RCP85_2100,
                          R_HAD_REG_RCP85_2100, R_MPI_R09_RCP85_2100]

R_DRIAS_85_2100_min = min(R_DRIAS_85_2100_mean_list)
index_min_R_85_2100 = min(range(len(R_DRIAS_85_2100_mean_list)), key=R_DRIAS_85_2100_mean_list.__getitem__)
R_DRIAS_85_month_min = R_DRIAS_85_month_dict[index_min_R_85_2100]
R_DRIAS_85_2100_max = max(R_DRIAS_85_2100_mean_list)
index_max_R_85_2100 = max(range(len(R_DRIAS_85_2100_mean_list)), key=R_DRIAS_85_2100_mean_list.__getitem__)
R_DRIAS_85_month_max = R_DRIAS_85_month_dict[index_max_R_85_2100]
# R_DRIAS_85_2100_med = statistics.median(R_DRIAS_85_2100_mean_list)

R_DRIAS_85_2100_mean_list_temp = R_DRIAS_85_2100_mean_list
for i in range(3):
    idx_max_R_85_2100 = max(range(len(R_DRIAS_85_2100_mean_list_temp)), key=R_DRIAS_85_2100_mean_list_temp.__getitem__)
    R_DRIAS_85_2100_mean_list_temp[idx_max_R_85_2100] = 0
index_4th_R_85_2100 = max(range(len(R_DRIAS_85_2100_mean_list_temp)), key=R_DRIAS_85_2100_mean_list_temp.__getitem__)    
R_DRIAS_85_month_4th = R_DRIAS_85_month_dict[index_4th_R_85_2100]

R_DRIAS_85_month_mean_min = [
    1000*numpy.nanmean(R_DRIAS_85_month_min[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_min[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_85_month_mean_max = [
    1000*numpy.nanmean(R_DRIAS_85_month_max[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_max[[i+11 for i in month_2100_4y_idx_list]])]
R_DRIAS_85_month_mean_4th = [
    1000*numpy.nanmean(R_DRIAS_85_month_4th[month_2100_4y_idx_list]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+1 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+2 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+3 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+4 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+5 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+6 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+7 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+8 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+9 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+10 for i in month_2100_4y_idx_list]]),
    1000*numpy.nanmean(R_DRIAS_85_month_4th[[i+11 for i in month_2100_4y_idx_list]])]

# R_DRIAS_85_month_mean_med = [
#     numpy.nanmean([R_DRIAS_85_month_med[x] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+1] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+2] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+3] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+4] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+5] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+6] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+7] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+8] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+9] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+10] for x in month_2100_4y_idx_list]),
#     numpy.nanmean([R_DRIAS_85_month_med[x+11] for x in month_2100_4y_idx_list])]


# Plot
import matplotlib.pyplot as plt

fig, axs = plt.subplots(2, 1)
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_26_2100])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2100])
axs[0].plot(range(1, 12+1), R_DRIAS_26_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_26_2100])
axs[0].set_title('RCP 2.6', fontsize=14)
axs[0].legend(loc = 'upper center')
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_max, label = 'Humid: ' + DRIAS_models_list[index_max_R_85_2100])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_4th, label = 'Interm: ' + DRIAS_models_list[index_4th_R_26_2100])
axs[1].plot(range(1, 12+1), R_DRIAS_85_month_mean_min, label = 'Dry: ' + DRIAS_models_list[index_min_R_85_2100])
axs[1].set_title('RCP 8.5', fontsize=14)
axs[1].legend(loc = 'upper center')

fig.suptitle('2100 forecast recharges (mm/month)', fontsize=18)
plt.setp(axs[-1], xlabel='Month')


#%% Synthesis table

# pip install tabulate
from tabulate import tabulate

data = [["2030 (RCP2.6)", DRIAS_models_list[index_max_R_26_2030], DRIAS_models_list[index_4th_R_26_2030], DRIAS_models_list[index_min_R_26_2030]], 
        ["2050 (RCP2.6)", DRIAS_models_list[index_max_R_26_2050], DRIAS_models_list[index_4th_R_26_2050], DRIAS_models_list[index_min_R_26_2050]], 
        ["2100 (RCP2.6)", DRIAS_models_list[index_max_R_26_2100], DRIAS_models_list[index_4th_R_26_2100], DRIAS_models_list[index_min_R_26_2100]],
        ["2030 (RCP8.5)", DRIAS_models_list[index_max_R_85_2030], DRIAS_models_list[index_4th_R_85_2030], DRIAS_models_list[index_min_R_85_2030]], 
        ["2050 (RCP8.5)", DRIAS_models_list[index_max_R_85_2050], DRIAS_models_list[index_4th_R_85_2050], DRIAS_models_list[index_min_R_85_2050]], 
        ["2100 (RCP8.5)", DRIAS_models_list[index_max_R_85_2100], DRIAS_models_list[index_4th_R_85_2100], DRIAS_models_list[index_min_R_85_2100]]]
  
col_names = ["Horizon", "Humid", "Interm.", "Dry"]
  
print(tabulate(data, headers=col_names, tablefmt="fancy_grid"))

#%% PLOT Recharges

import matplotlib.pyplot as plt

# plt.plot(R_MPI_CCL_RCP26_year)
# plt.plot(R_ECE_RCA_RCP26_year)
# plt.plot(R_ECE_RAC_RCP26_year)
# plt.plot(R_CNR_RAC_RCP26_year)
# plt.plot(R_NOR_R15_RCP26_year)
# plt.plot(R_CNR_ALA_RCP26_year)
# plt.plot(R_HAD_REG_RCP26_year)
# plt.plot(R_MPI_R09_RCP26_year)


fig, axs = plt.subplots(4, 2)
axs[0, 0].plot(R_MPI_CCL_RCP26_year)
axs[0, 0].set_title('MPI_CCL')
axs[1, 0].plot(R_ECE_RCA_RCP26_year)
axs[1, 0].set_title('ECE_RCA')
axs[2, 0].plot(R_ECE_RAC_RCP26_year)
axs[2, 0].set_title('ECE_RAC')
axs[3, 0].plot(R_CNR_RAC_RCP26_year)
axs[3, 0].set_title('CNR_RAC')
axs[0, 1].plot(R_NOR_R15_RCP26_year)
axs[0, 1].set_title('NOR_R15')
axs[1, 1].plot(R_CNR_ALA_RCP26_year)
axs[1, 1].set_title('CNR_ALA')
axs[2, 1].plot(R_HAD_REG_RCP26_year)
axs[2, 1].set_title('HAD_REG')
axs[3, 1].plot(R_MPI_R09_RCP26_year)
axs[3, 1].set_title('MPI_R09')

fig.suptitle('Forecast Recharge (m/yr), DRIAS models')
plt.setp(axs[-1, :], xlabel='Year')


#%% Plot

#[R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85
#R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85]

import matplotlib.pyplot as plt

x = range(1, 12+1)
y1 = R_monthly_mmd_MPI_CCL_RCP85
y2 = R_monthly_mmd_ECE_RCA_RCP85
y3 = R_monthly_mmd_ECE_RAC_RCP85
y4 = R_monthly_mmd_CNR_RAC_RCP85
y5 = R_monthly_mmd_NOR_R15_RCP85
y6 = R_monthly_mmd_CNR_ALA_RCP85
y7 = R_monthly_mmd_HAD_REG_RCP85
y8 = R_monthly_mmd_MPI_R09_RCP85
y0 = R_monthly_mmd_REA
# y9 = [R_DRIAS_85*1000] * len(x)

fig, ax = plt.subplots()

ax.plot(x, y0, label = 'Observed 1960-2020', linewidth=4)
ax.plot(x, y1, label = 'MPI_CCL 2020-2050')
ax.plot(x, y2, label = 'ECE_RCA 2020-2050')
ax.plot(x, y3, label = 'ECE_RAC 2020-2050')
ax.plot(x, y4, label = 'CNR_RAC 2020-2050')
ax.plot(x, y5, label = 'NOR_R15 2020-2050')
ax.plot(x, y6, label = 'CNR_ALA 2020-2050')
ax.plot(x, y7, label = 'HAD_REG 2020-2050')
ax.plot(x, y8, label = 'MPI_R09 2020-2050')
# ax.plot(x, y9, label = 'Mean DRIAS  2020-2050', linestyle='dashed')

plt.xlabel('Month')
plt.ylabel('Recharge (mm/d)')
ax.legend(loc = 'upper center')
plt.show()

plt.hist(R_hist)
plt.hist(R_MPI_R09_RCP85)

from matplotlib import pyplot

pyplot.hist(R_hist, alpha=0.5, label='Hist')
pyplot.hist(R_HAD_REG_RCP85, alpha=0.5, label='HAD_REG')
pyplot.legend(loc='upper right')
pyplot.show()
