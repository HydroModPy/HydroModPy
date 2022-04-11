#!/usr/bin/env python
"""
    Provides functions to manipulate the inputfile which is given as input to the flow model. 
    It is then parsed for the embedded information to be given to the modflow executable.
    DEPRECIATED !!!!
"""
import pandas as pd
import re
import numpy as np
import argparse
import pandas as pd

__author__ = "June Sallou"
__maintainer__ = "June Sallou"
__credits__ = ["June Sallou"]
__license__ = "MIT"
__version__ = "0.0.1"
__date__ = "04/30/2019"
__email__ = "june.benvegnu-sallou@univ-rennes1.fr"

def concatErrorCSVFilesForASimulation(sitename, modelname, chronicle):  ## TO DO : list of startTime and endTime
    Repo = "/DATA/These/Projects/Model/app/" + sitename + "/"
    ref = "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Perioddaily_Step1"
    if chronicle:
        ref+= "_chronicle"

    #model= modelname #"model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Perioddaily_Step1"

    te = [[0,5000]] #5000], [5001,10000],[10000,

    reconstr = pd.DataFrame()
    for it in range(0,len(te)):
        file = modelname + "_Ref_" + ref + "_errorsresult_interpolation_" + str(te[it][0]) + "_" + str(te[it][1]) +".csv"
        dt = pd.read_csv(Repo + modelname + "/" + file, sep=";")
        reconstr = pd.concat([reconstr, dt])

    reconstr.to_csv(Repo + modelname + "/" + modelname + "_Ref_" + ref + "_errorsresult_interpolation" + ".csv", sep=";", index=False)



def getExecutionTimeFromListFile(file):
    with open(file,'r') as f:
        lines = f.readlines()
        if lines:
            beforelast_line = lines[-2]
    beforelast_line=beforelast_line.rstrip()

    m = re.search(r'\sElapsed run time:\s+(?:(\d*)?(?:\sDays,\s*))?(?:(\d*)(?:\s*Hours,\s*))?(?:(\d*)(?:\s*Minutes,\s*))?(\d*[.]*\d*)\sSeconds', beforelast_line)
    if (m.group(1) is None) and (m.group(2) is None) and (m.group(3) is None):
        exec_time = float(m.group(4))
    elif (m.group(1) is None) and (m.group(2) is None):
        exec_time = int(m.group(3))*60 + float(m.group(4))      
    elif (m.group(1) is None):
        exec_time = int(m.group(2))*60*60 + int(m.group(3))*60 + float(m.group(4))
    else:
        exec_time = int(m.group(1))*24*60*60 + int(m.group(2))*60*60 + int(m.group(3))*60 + float(m.group(4))
    return int(exec_time)

def createGlobalCSVFile(sitename, chronicle=False, refValues=True, outliers=True):

#Agon-Coutainville
#Saint-Germain-Sur-Ay
    mainRepo = "/DATA/These/Projects/Model/app/" + sitename + "/"
    
    ref = "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Perioddaily_Step1"

    modelnames = ["model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodmonthly_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodweekly_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodtenyear_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodtrimester_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodyear_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodtwoyear_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodtwodays_Step1",
                "model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Periodsemester_Step1"          
            ]
    
    approx = ["30",
            "7",
            "3652",
            "91",
            "365",
            "730",
            "2",
            "182"
            ]
    
    if refValues:
        modelnames.append("model_time_0_geo_0_thick_1_K_86.4_Sy_0.1_Perioddaily_Step1")
    if chronicle:
        ref += "_chronicle"
        approx.append("1")

    
    dfglob = pd.DataFrame()

    for ind in range(len(modelnames)):

        simuRepo = modelnames[ind]
        filename = modelnames[ind] + "_Ref_" + ref + "_errorsresult_interpolation.csv"
        
        if chronicle :
            simuRepo += "_chronicle"
            filename = modelnames[ind]  + "_chronicle" + "_Ref_" + ref + "_errorsresult_interpolation.csv"

        df = pd.read_csv(mainRepo + simuRepo + "/" + filename, sep=";")

        if outliers is False:
            q75, q25 = np.percentile(df['RMSE'].dropna(), [75 ,25])
            iqr = q75 - q25
    
            min = q25 - (iqr*1.5)
            max = q75 + (iqr*1.5)
        
            df['Outlier'] = 0
            df.loc[df['RMSE'] < min, 'Outlier'] = 1
            df.loc[df['RMSE'] > max, 'Outlier'] = 1
        
            df = df[df['Outlier']!=1]

        taille = len(df.index)
        df_dur = pd.DataFrame(data=[approx[ind]]*taille, index=df.index, columns=['Approximation'])
        exec_time = getExecutionTimeFromListFile(mainRepo + simuRepo + "/" + simuRepo + ".list")
        df_time = pd.DataFrame(data=[exec_time]*taille, index=df.index, columns=['Execution Time'])
        df = pd.concat([df, df_dur, df_time], axis=1)
        dfglob = pd.concat([dfglob,df])

    output = "exps_initExcluded_Diffwatertable_AllApproximations_" + sitename

    if outliers is False:
        output += "_withoutOutliers"
    if refValues:
        output+= "_withref"
    if chronicle :
        output+= "_chronicle"
    
    dfglob.to_csv("/DATA/These/Projects/Model/app/exps/" + output + ".csv")


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-sitename", "--sitename", type=str, required=True)
    parser.add_argument("-outliers", "--outliers", action='store_true')
    parser.add_argument("-refval", "--refvalues", action='store_true')
    parser.add_argument("-chr", "--chronicle", action='store_true')    
    args = parser.parse_args()

    # Parameters
    sitename = args.sitename
    outliers = args.outliers
    refval = args.refvalues
    chr = args.chronicle

    createGlobalCSVFile(sitename, chronicle=chr, refValues=refval, outliers=outliers)