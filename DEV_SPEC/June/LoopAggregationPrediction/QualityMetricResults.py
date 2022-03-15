import pandas as pd

def generate_dict_of_qualities(scales, nbs_rates, features, sizes, nb_replication=100):
#{scale : {nb_rates: {feature: {size: quality}}}}
    qualities = {}
    for scale in scales:
        qualities[scale] = {}
        for nb_rates in nbs_rates:
            qualities[scale][nb_rates] = {}
            for feature in features:
                qualities[scale][nb_rates][feature] = {}
                for size in sizes:
                    try:
                        data = pd.read_csv("data/Output_Data/Replication/Prediction_data_complete_Rates_"+ str(nb_rates) +"_Features_" +  str(feature) + "_" + str(scale) + "_Replication_" + str(nb_replication) + "_OneCase_Size_" + str(size) + ".csv", sep=";", index_col=None)
                        qualities[scale][nb_rates][feature][size] = [float(data["Mean quality metric"][0]), float(data["STD quality metric"][0])]
                    except:
                        continue

    return qualities

def create_dataframe_from_qualities_dict(qualities):
    result = pd.DataFrame(columns=["Scale","Number of Rates","Features","Number of Cases","Mean of Quality Metric", "Std of Quality Metric"])
    for scale in qualities:
        for nb_rates in qualities[scale]:
            for feature in qualities[scale][nb_rates]:
                for size in qualities[scale][nb_rates][feature]:
                    if feature == "Geomorph":
                        feat = "Geomorphology"
                    elif feature == "Geomorph_CVHV":
                        feat = "Geomorphology + Vulnerability"
                    elif feature == "Geomorph_CVHV_Saturation":
                        feat = "Geomorphology + Vulnerability + Saturation"
                    else:
                        feat = feature
                    result.loc[len(result.index)] = [scale, nb_rates, feat, size, qualities[scale][nb_rates][feature][size][0], qualities[scale][nb_rates][feature][size][1]]
    return result

scales = ["BVE", "SUB"]
nb_replication = 100
sizes = [5, 10, 15, 20, 25, 30, 35, 40, 45]
features = ["Geomorph", "Saturation", "Geomorph_CVHV", "Geomorph_CVHV_Saturation"]
nbs_rates = [9, 30]

qualities = generate_dict_of_qualities(scales, nbs_rates, features, sizes, nb_replication=100)
result = create_dataframe_from_qualities_dict(qualities)
result.to_csv("Result_Data.csv", sep=";", index=False)
print(result)