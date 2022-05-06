import os
import pandas as pd
import InputFileManipulation as ifm
import pickle
import random

IS_BISS_YEAR = [False, False, True, False]

def create_custom_random_chronicle_from_years_of_chronicle0():

    NB_YEARS = 42 
    chronicle_by_year_std, chronicle_by_year_biss = load_pickle_chronicle_by_year()

    custom_chronicle = pd.DataFrame({"stress_period": [0],"sp_length": [1],"time_step": [1],"study (0 : TS or 1 : SS)": [1], "rech":[0.00000]})

    nb_days = 1
    combinaison_name = ""

    for _ in range(1, NB_YEARS+1):
        if nb_days != 3:
            nb_random_year = random.randint(1, len(chronicle_by_year_std))
            print("taille année standard", len(chronicle_by_year_std[nb_random_year]))
            custom_chronicle = pd.concat([custom_chronicle, chronicle_by_year_std[nb_random_year]])
            combinaison_name += "_S" + str(nb_random_year)
        else:
            nb_random_year = random.randint(1, len(chronicle_by_year_biss))
            print("taille année biss", len(chronicle_by_year_biss[nb_random_year]))
            custom_chronicle = pd.concat([custom_chronicle, chronicle_by_year_biss[nb_random_year]])
            combinaison_name += "_B" + str(nb_random_year)
        if nb_days < 4:
            nb_days += 1
        else:
            nb_days = 1

    return custom_chronicle, combinaison_name







def cut_chronicle_into_years(chronicle):
    years = [365, 365, 366, 365]

    folder_path = '/'.join((os.path.dirname((os.path.abspath(__file__)))).split('/')[:-1])
    chronicle_file = pd.read_table(folder_path + "/data/chronicles.txt", sep=',', header=0, index_col=0)
    template_file = chronicle_file.template[chronicle]
    df = ifm.extract_df_from_ref_input_file(template_file)

    chronicle_by_year_std = {}
    chronicle_by_year_biss = {}
    ind_day_start_year = 0
    ind_day_end_year = 0
    nb_days = 0
    nb_year_std = 1
    nb_year_biss = 1
    for _ in range(1, 43):
        ind_day_start_year = ind_day_end_year + 1  #1
        ind_day_end_year = ind_day_end_year + years[nb_days] # 365
        df_chronicle_year = df.iloc[ind_day_start_year:ind_day_end_year+1,:] 
        
        if nb_days == 2:
            chronicle_by_year_biss[nb_year_biss] = df_chronicle_year
            nb_year_biss += 1
        else:
            chronicle_by_year_std[nb_year_std] = df_chronicle_year
            nb_year_std += 1

        if nb_days < len(years)-1:
            nb_days += 1
        else:
            nb_days = 0

    return chronicle_by_year_std, chronicle_by_year_biss


def save_pickle_chronicle_by_year(chronicle_by_year_std, chronicle_by_year_biss):
    outfile = open(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "Pickle/chronicle_by_year_std.pickle") ,'wb')
    pickle.dump(chronicle_by_year_std, outfile)
    outfile.close()
    outfile = open(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "Pickle/chronicle_by_year_biss.pickle") ,'wb')
    pickle.dump(chronicle_by_year_biss, outfile)
    outfile.close()
#save_pickle_chronicle_by_year(chronicle_by_year)

def load_pickle_chronicle_by_year():
    infile = open(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "Pickle/chronicle_by_year_std.pickle") ,'rb')
    chronicle_by_year_std = pickle.load(infile)
    infile.close()
    infileb = open(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "Pickle/chronicle_by_year_biss.pickle") ,'rb')
    chronicle_by_year_biss = pickle.load(infileb)
    infileb.close()
    return chronicle_by_year_std, chronicle_by_year_biss

# chronicle_by_year_std, chronicle_by_year_biss = cut_chronicle_into_years(0)
# save_pickle_chronicle_by_year(chronicle_by_year_std, chronicle_by_year_biss)
# chronicle_by_year_std, chronicle_by_year_biss = load_pickle_chronicle_by_year()

custom_chronicle, combinaison_name = create_custom_random_chronicle_from_years_of_chronicle0()
# print(len(custom_chronicle))
ifm.write_custom_input_file("ref" + combinaison_name, custom_chronicle)

file_references_chronicles = pd.read_csv(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "chronicles.txt"), sep=",")
row= {"number":len(file_references_chronicles), "chronicle": "Custom" + combinaison_name, "template" : "input_file_" + "ref" + combinaison_name + ".txt"}
file_references_chronicles =file_references_chronicles.append(row, ignore_index=True)
print(file_references_chronicles)
file_references_chronicles.to_csv(os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", "chronicles.txt"), sep=",", index=False)
