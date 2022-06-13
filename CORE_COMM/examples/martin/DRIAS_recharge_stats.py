# -*- coding: utf-8 -*-
"""
Created on Wed Jun  1 17:24:43 2022

@author: Martin
"""

# /!\ RN2100_steady must be ran in transient mode to compute recharge values before running this script

#[R_MPI_CCL_RCP85, R_ECE_RCA_RCP85, R_ECE_RAC_RCP85, R_CNR_RAC_RCP85, R_NOR_R15_RCP85
#R_CNR_ALA_RCP85, R_HAD_REG_RCP85, R_MPI_R09_RCP85]

#%% MPI_CCL

R_01_MPI_CCL_RCP85 = []
R_02_MPI_CCL_RCP85 = []
R_03_MPI_CCL_RCP85 = []
R_04_MPI_CCL_RCP85 = []
R_05_MPI_CCL_RCP85 = []
R_06_MPI_CCL_RCP85 = []
R_07_MPI_CCL_RCP85 = []
R_08_MPI_CCL_RCP85 = []
R_09_MPI_CCL_RCP85 = []
R_10_MPI_CCL_RCP85 = []
R_11_MPI_CCL_RCP85 = []
R_12_MPI_CCL_RCP85 = []

for i in range(R_MPI_CCL_RCP85.size):
    if R_MPI_CCL_RCP85.index[i].month == 1:
        R_01_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 2:
        R_02_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 3:
        R_03_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 4:
        R_04_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 5:
        R_05_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 6:
        R_06_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 7:
        R_07_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 8:
        R_08_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 9:
        R_09_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 10:
        R_10_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 11:
        R_11_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    elif R_MPI_CCL_RCP85.index[i].month == 12:
        R_12_MPI_CCL_RCP85.append(R_MPI_CCL_RCP85[i])
    else:
        print("invalid month")

R_monthly_MPI_CCL_RCP85 = [statistics.mean(R_01_MPI_CCL_RCP85), statistics.mean(R_02_MPI_CCL_RCP85), statistics.mean(R_03_MPI_CCL_RCP85), statistics.mean(R_04_MPI_CCL_RCP85), statistics.mean(R_05_MPI_CCL_RCP85), statistics.mean(R_06_MPI_CCL_RCP85), statistics.mean(R_07_MPI_CCL_RCP85), statistics.mean(R_08_MPI_CCL_RCP85), statistics.mean(R_09_MPI_CCL_RCP85), statistics.mean(R_10_MPI_CCL_RCP85), statistics.mean(R_11_MPI_CCL_RCP85), statistics.mean(R_12_MPI_CCL_RCP85)]
R_monthly_mmd_MPI_CCL_RCP85 = np.array(R_monthly_MPI_CCL_RCP85) * 1000



#%% ECE_RCA

R_01_ECE_RCA_RCP85 = []
R_02_ECE_RCA_RCP85 = []
R_03_ECE_RCA_RCP85 = []
R_04_ECE_RCA_RCP85 = []
R_05_ECE_RCA_RCP85 = []
R_06_ECE_RCA_RCP85 = []
R_07_ECE_RCA_RCP85 = []
R_08_ECE_RCA_RCP85 = []
R_09_ECE_RCA_RCP85 = []
R_10_ECE_RCA_RCP85 = []
R_11_ECE_RCA_RCP85 = []
R_12_ECE_RCA_RCP85 = []

for i in range(R_ECE_RCA_RCP85.size):
    if R_ECE_RCA_RCP85.index[i].month == 1:
        R_01_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 2:
        R_02_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 3:
        R_03_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 4:
        R_04_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 5:
        R_05_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 6:
        R_06_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 7:
        R_07_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 8:
        R_08_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 9:
        R_09_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 10:
        R_10_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 11:
        R_11_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    elif R_ECE_RCA_RCP85.index[i].month == 12:
        R_12_ECE_RCA_RCP85.append(R_ECE_RCA_RCP85[i])
    else:
        print("invalid month")

R_monthly_ECE_RCA_RCP85 = [statistics.mean(R_01_ECE_RCA_RCP85), statistics.mean(R_02_ECE_RCA_RCP85), statistics.mean(R_03_ECE_RCA_RCP85), statistics.mean(R_04_ECE_RCA_RCP85), statistics.mean(R_05_ECE_RCA_RCP85), statistics.mean(R_06_ECE_RCA_RCP85), statistics.mean(R_07_ECE_RCA_RCP85), statistics.mean(R_08_ECE_RCA_RCP85), statistics.mean(R_09_ECE_RCA_RCP85), statistics.mean(R_10_ECE_RCA_RCP85), statistics.mean(R_11_ECE_RCA_RCP85), statistics.mean(R_12_ECE_RCA_RCP85)]
R_monthly_mmd_ECE_RCA_RCP85 = np.array(R_monthly_ECE_RCA_RCP85) * 1000



#%% ECE_RAC

R_01_ECE_RAC_RCP85 = []
R_02_ECE_RAC_RCP85 = []
R_03_ECE_RAC_RCP85 = []
R_04_ECE_RAC_RCP85 = []
R_05_ECE_RAC_RCP85 = []
R_06_ECE_RAC_RCP85 = []
R_07_ECE_RAC_RCP85 = []
R_08_ECE_RAC_RCP85 = []
R_09_ECE_RAC_RCP85 = []
R_10_ECE_RAC_RCP85 = []
R_11_ECE_RAC_RCP85 = []
R_12_ECE_RAC_RCP85 = []

for i in range(R_ECE_RAC_RCP85.size):
    if R_ECE_RAC_RCP85.index[i].month == 1:
        R_01_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 2:
        R_02_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 3:
        R_03_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 4:
        R_04_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 5:
        R_05_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 6:
        R_06_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 7:
        R_07_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 8:
        R_08_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 9:
        R_09_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 10:
        R_10_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 11:
        R_11_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    elif R_ECE_RAC_RCP85.index[i].month == 12:
        R_12_ECE_RAC_RCP85.append(R_ECE_RAC_RCP85[i])
    else:
        print("invalid month")

R_monthly_ECE_RAC_RCP85 = [statistics.mean(R_01_ECE_RAC_RCP85), statistics.mean(R_02_ECE_RAC_RCP85), statistics.mean(R_03_ECE_RAC_RCP85), statistics.mean(R_04_ECE_RAC_RCP85), statistics.mean(R_05_ECE_RAC_RCP85), statistics.mean(R_06_ECE_RAC_RCP85), statistics.mean(R_07_ECE_RAC_RCP85), statistics.mean(R_08_ECE_RAC_RCP85), statistics.mean(R_09_ECE_RAC_RCP85), statistics.mean(R_10_ECE_RAC_RCP85), statistics.mean(R_11_ECE_RAC_RCP85), statistics.mean(R_12_ECE_RAC_RCP85)]
R_monthly_mmd_ECE_RAC_RCP85 = np.array(R_monthly_ECE_RAC_RCP85) * 1000


#%% CNR_RAC

R_01_CNR_RAC_RCP85 = []
R_02_CNR_RAC_RCP85 = []
R_03_CNR_RAC_RCP85 = []
R_04_CNR_RAC_RCP85 = []
R_05_CNR_RAC_RCP85 = []
R_06_CNR_RAC_RCP85 = []
R_07_CNR_RAC_RCP85 = []
R_08_CNR_RAC_RCP85 = []
R_09_CNR_RAC_RCP85 = []
R_10_CNR_RAC_RCP85 = []
R_11_CNR_RAC_RCP85 = []
R_12_CNR_RAC_RCP85 = []

for i in range(R_CNR_RAC_RCP85.size):
    if R_CNR_RAC_RCP85.index[i].month == 1:
        R_01_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 2:
        R_02_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 3:
        R_03_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 4:
        R_04_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 5:
        R_05_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 6:
        R_06_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 7:
        R_07_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 8:
        R_08_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 9:
        R_09_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 10:
        R_10_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 11:
        R_11_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    elif R_CNR_RAC_RCP85.index[i].month == 12:
        R_12_CNR_RAC_RCP85.append(R_CNR_RAC_RCP85[i])
    else:
        print("invalid month")

R_monthly_CNR_RAC_RCP85 = [statistics.mean(R_01_CNR_RAC_RCP85), statistics.mean(R_02_CNR_RAC_RCP85), statistics.mean(R_03_CNR_RAC_RCP85), statistics.mean(R_04_CNR_RAC_RCP85), statistics.mean(R_05_CNR_RAC_RCP85), statistics.mean(R_06_CNR_RAC_RCP85), statistics.mean(R_07_CNR_RAC_RCP85), statistics.mean(R_08_CNR_RAC_RCP85), statistics.mean(R_09_CNR_RAC_RCP85), statistics.mean(R_10_CNR_RAC_RCP85), statistics.mean(R_11_CNR_RAC_RCP85), statistics.mean(R_12_CNR_RAC_RCP85)]
R_monthly_mmd_CNR_RAC_RCP85 = np.array(R_monthly_CNR_RAC_RCP85) * 1000


#%% NOR_R15

R_01_NOR_R15_RCP85 = []
R_02_NOR_R15_RCP85 = []
R_03_NOR_R15_RCP85 = []
R_04_NOR_R15_RCP85 = []
R_05_NOR_R15_RCP85 = []
R_06_NOR_R15_RCP85 = []
R_07_NOR_R15_RCP85 = []
R_08_NOR_R15_RCP85 = []
R_09_NOR_R15_RCP85 = []
R_10_NOR_R15_RCP85 = []
R_11_NOR_R15_RCP85 = []
R_12_NOR_R15_RCP85 = []

for i in range(R_NOR_R15_RCP85.size):
    if R_NOR_R15_RCP85.index[i].month == 1:
        R_01_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 2:
        R_02_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 3:
        R_03_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 4:
        R_04_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 5:
        R_05_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 6:
        R_06_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 7:
        R_07_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 8:
        R_08_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 9:
        R_09_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 10:
        R_10_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 11:
        R_11_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    elif R_NOR_R15_RCP85.index[i].month == 12:
        R_12_NOR_R15_RCP85.append(R_NOR_R15_RCP85[i])
    else:
        print("invalid month")

R_monthly_NOR_R15_RCP85 = [statistics.mean(R_01_NOR_R15_RCP85), statistics.mean(R_02_NOR_R15_RCP85), statistics.mean(R_03_NOR_R15_RCP85), statistics.mean(R_04_NOR_R15_RCP85), statistics.mean(R_05_NOR_R15_RCP85), statistics.mean(R_06_NOR_R15_RCP85), statistics.mean(R_07_NOR_R15_RCP85), statistics.mean(R_08_NOR_R15_RCP85), statistics.mean(R_09_NOR_R15_RCP85), statistics.mean(R_10_NOR_R15_RCP85), statistics.mean(R_11_NOR_R15_RCP85), statistics.mean(R_12_NOR_R15_RCP85)]
R_monthly_mmd_NOR_R15_RCP85 = np.array(R_monthly_NOR_R15_RCP85) * 1000


#%% CNR_ALA

R_01_CNR_ALA_RCP85 = []
R_02_CNR_ALA_RCP85 = []
R_03_CNR_ALA_RCP85 = []
R_04_CNR_ALA_RCP85 = []
R_05_CNR_ALA_RCP85 = []
R_06_CNR_ALA_RCP85 = []
R_07_CNR_ALA_RCP85 = []
R_08_CNR_ALA_RCP85 = []
R_09_CNR_ALA_RCP85 = []
R_10_CNR_ALA_RCP85 = []
R_11_CNR_ALA_RCP85 = []
R_12_CNR_ALA_RCP85 = []

for i in range(R_CNR_ALA_RCP85.size):
    if R_CNR_ALA_RCP85.index[i].month == 1:
        R_01_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 2:
        R_02_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 3:
        R_03_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 4:
        R_04_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 5:
        R_05_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 6:
        R_06_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 7:
        R_07_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 8:
        R_08_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 9:
        R_09_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 10:
        R_10_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 11:
        R_11_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    elif R_CNR_ALA_RCP85.index[i].month == 12:
        R_12_CNR_ALA_RCP85.append(R_CNR_ALA_RCP85[i])
    else:
        print("invalid month")

R_monthly_CNR_ALA_RCP85 = [statistics.mean(R_01_CNR_ALA_RCP85), statistics.mean(R_02_CNR_ALA_RCP85), statistics.mean(R_03_CNR_ALA_RCP85), statistics.mean(R_04_CNR_ALA_RCP85), statistics.mean(R_05_CNR_ALA_RCP85), statistics.mean(R_06_CNR_ALA_RCP85), statistics.mean(R_07_CNR_ALA_RCP85), statistics.mean(R_08_CNR_ALA_RCP85), statistics.mean(R_09_CNR_ALA_RCP85), statistics.mean(R_10_CNR_ALA_RCP85), statistics.mean(R_11_CNR_ALA_RCP85), statistics.mean(R_12_CNR_ALA_RCP85)]
R_monthly_mmd_CNR_ALA_RCP85 = np.array(R_monthly_CNR_ALA_RCP85) * 1000


#%% HAD_REG

R_01_HAD_REG_RCP85 = []
R_02_HAD_REG_RCP85 = []
R_03_HAD_REG_RCP85 = []
R_04_HAD_REG_RCP85 = []
R_05_HAD_REG_RCP85 = []
R_06_HAD_REG_RCP85 = []
R_07_HAD_REG_RCP85 = []
R_08_HAD_REG_RCP85 = []
R_09_HAD_REG_RCP85 = []
R_10_HAD_REG_RCP85 = []
R_11_HAD_REG_RCP85 = []
R_12_HAD_REG_RCP85 = []

for i in range(R_HAD_REG_RCP85.size):
    if R_HAD_REG_RCP85.index[i].month == 1:
        R_01_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 2:
        R_02_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 3:
        R_03_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 4:
        R_04_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 5:
        R_05_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 6:
        R_06_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 7:
        R_07_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 8:
        R_08_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 9:
        R_09_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 10:
        R_10_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 11:
        R_11_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    elif R_HAD_REG_RCP85.index[i].month == 12:
        R_12_HAD_REG_RCP85.append(R_HAD_REG_RCP85[i])
    else:
        print("invalid month")

R_monthly_HAD_REG_RCP85 = [statistics.mean(R_01_HAD_REG_RCP85), statistics.mean(R_02_HAD_REG_RCP85), statistics.mean(R_03_HAD_REG_RCP85), statistics.mean(R_04_HAD_REG_RCP85), statistics.mean(R_05_HAD_REG_RCP85), statistics.mean(R_06_HAD_REG_RCP85), statistics.mean(R_07_HAD_REG_RCP85), statistics.mean(R_08_HAD_REG_RCP85), statistics.mean(R_09_HAD_REG_RCP85), statistics.mean(R_10_HAD_REG_RCP85), statistics.mean(R_11_HAD_REG_RCP85), statistics.mean(R_12_HAD_REG_RCP85)]
R_monthly_mmd_HAD_REG_RCP85 = np.array(R_monthly_HAD_REG_RCP85) * 1000


#%% MPI_R09

R_01_MPI_R09_RCP85 = []
R_02_MPI_R09_RCP85 = []
R_03_MPI_R09_RCP85 = []
R_04_MPI_R09_RCP85 = []
R_05_MPI_R09_RCP85 = []
R_06_MPI_R09_RCP85 = []
R_07_MPI_R09_RCP85 = []
R_08_MPI_R09_RCP85 = []
R_09_MPI_R09_RCP85 = []
R_10_MPI_R09_RCP85 = []
R_11_MPI_R09_RCP85 = []
R_12_MPI_R09_RCP85 = []

for i in range(R_MPI_R09_RCP85.size):
    if R_MPI_R09_RCP85.index[i].month == 1:
        R_01_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 2:
        R_02_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 3:
        R_03_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 4:
        R_04_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 5:
        R_05_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 6:
        R_06_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 7:
        R_07_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 8:
        R_08_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 9:
        R_09_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 10:
        R_10_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 11:
        R_11_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    elif R_MPI_R09_RCP85.index[i].month == 12:
        R_12_MPI_R09_RCP85.append(R_MPI_R09_RCP85[i])
    else:
        print("invalid month")

R_monthly_MPI_R09_RCP85 = [statistics.mean(R_01_MPI_R09_RCP85), statistics.mean(R_02_MPI_R09_RCP85), statistics.mean(R_03_MPI_R09_RCP85), statistics.mean(R_04_MPI_R09_RCP85), statistics.mean(R_05_MPI_R09_RCP85), statistics.mean(R_06_MPI_R09_RCP85), statistics.mean(R_07_MPI_R09_RCP85), statistics.mean(R_08_MPI_R09_RCP85), statistics.mean(R_09_MPI_R09_RCP85), statistics.mean(R_10_MPI_R09_RCP85), statistics.mean(R_11_MPI_R09_RCP85), statistics.mean(R_12_MPI_R09_RCP85)]
R_monthly_mmd_MPI_R09_RCP85 = np.array(R_monthly_MPI_R09_RCP85) * 1000



#%% Reanalysis

R_01_REA = []
R_02_REA = []
R_03_REA = []
R_04_REA = []
R_05_REA = []
R_06_REA = []
R_07_REA = []
R_08_REA = []
R_09_REA = []
R_10_REA = []
R_11_REA = []
R_12_REA = []

R_REA = R_hist

for i in range(R_REA.size):
    if R_REA.index[i].month == 1:
        R_01_REA.append(R_REA[i])
    elif R_REA.index[i].month == 2:
        R_02_REA.append(R_REA[i])
    elif R_REA.index[i].month == 3:
        R_03_REA.append(R_REA[i])
    elif R_REA.index[i].month == 4:
        R_04_REA.append(R_REA[i])
    elif R_REA.index[i].month == 5:
        R_05_REA.append(R_REA[i])
    elif R_REA.index[i].month == 6:
        R_06_REA.append(R_REA[i])
    elif R_REA.index[i].month == 7:
        R_07_REA.append(R_REA[i])
    elif R_REA.index[i].month == 8:
        R_08_REA.append(R_REA[i])
    elif R_REA.index[i].month == 9:
        R_09_REA.append(R_REA[i])
    elif R_REA.index[i].month == 10:
        R_10_REA.append(R_REA[i])
    elif R_REA.index[i].month == 11:
        R_11_REA.append(R_REA[i])
    elif R_REA.index[i].month == 12:
        R_12_REA.append(R_REA[i])
    else:
        print("invalid month")

R_monthly_REA = [statistics.mean(R_01_REA), statistics.mean(R_02_REA), statistics.mean(R_03_REA), statistics.mean(R_04_REA), statistics.mean(R_05_REA), statistics.mean(R_06_REA), statistics.mean(R_07_REA), statistics.mean(R_08_REA), statistics.mean(R_09_REA), statistics.mean(R_10_REA), statistics.mean(R_11_REA), statistics.mean(R_12_REA)]
R_monthly_mmd_REA = np.array(R_monthly_REA) * 1000



#%% PLOT

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

