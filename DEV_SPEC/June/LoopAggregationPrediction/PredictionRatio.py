import pandas as pd   
import numpy as np


# nb_rates = 30
# feature = "Geomorph"
# scale = "BVE"
# nb_replication = 100
# size = 5


def get_percentage_perdiction_error_equals_zero(scale, nb_rates, feature, size, nb_replication=100):
    try:
        data = pd.read_csv("data/Output_Data/Replication/Prediction_data_complete_Rates_"+ str(nb_rates) +"_Features_" +  str(feature) + "_" + str(scale) + "_Replication_" + str(nb_replication) + "_OneCase_Size_" + str(size) + ".csv", sep=";", index_col=None)
        #if scale == "BVE" and nb_rates == 30:
            #print("data/Output_Data/Replication/Prediction_data_complete_Rates_"+ str(nb_rates) +"_Features_" +  str(feature) + "_" + str(scale) + "_Replication_" + str(nb_replication) + "_OneCase_Size_" + str(size) + ".csv")
            #print(data["Quality Metric"])
        nb_zero_errors = (data["Quality Metric"] != 0).sum()
        print((data["Quality Metric"] != 0).sum())
        print((data["Quality Metric"] == float(0)).sum())
        print("SUM", (data["Quality Metric"] != 0).sum() + (data["Quality Metric"] == float(0)).sum())
        ratio = round(float(nb_zero_errors / len(data))*100, 2)
        # print(ratio)
        return ratio
    except:
        #print("Could not open: ", "data/Output_Data/Replication/Prediction_data_complete_Rates_"+ str(nb_rates) +"_Features_" +  str(feature) + "_" + str(scale) + "_Replication_" + str(nb_replication) + "_OneCase_Size_" + str(size) + ".csv")
        return None


scales = ["BVE", "SUB"]
nb_replication = 100
sizes = [5, 10, 15, 20, 25, 30, 35, 40, 45]
features = ["Geomorph", "Geomorph_CVHV"]
nbs_rates = [9, 30]



result = pd.DataFrame(columns=["Scale","Number of Rates","Features","Number of Cases","Number of Replication", "Percentage of Overestimation Predictions"])
for scale in scales:
    for nb_rates in nbs_rates:
        for feature in features:
            if feature == "Geomorph":
                feat = "Geomorphology"
            elif feature == "Geomorph_CVHV":
                feat = "Geomorphology + Vulnerability"
            for size in sizes:
                percentage_pred_zero = get_percentage_perdiction_error_equals_zero(scale, nb_rates, feature, size, nb_replication)
                
                result.loc[len(result.index)] = [scale, nb_rates, feat, size, nb_replication, percentage_pred_zero]
#print(result)
result.to_csv("Result_Percentage_Valid_Prediction_Data.csv", sep=";", index=False)



    
