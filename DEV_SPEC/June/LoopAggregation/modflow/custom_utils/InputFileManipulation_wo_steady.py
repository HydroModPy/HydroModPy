"""
TO DO : function to create file from a chronicle

"""
import os, sys
import pandas as pd
import argparse
import numpy as np

# sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'helpers'))
import helpers as hlp

def extract_df_from_ref_input_file(input_name):
    input_path = os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]), "data", input_name)
    df = pd.read_csv(input_path, sep='\t', dtype=np.float64)
    return df


def get_indexes_to_remain(number_lines, period):
    ligne = 1
    indexes = [0,1]
    taille_period = len(period)
    i = 0
    while (ligne < number_lines-1):
        ligne += period[i]
        if (ligne < number_lines-1):
            indexes.append(ligne)
        if (i == (taille_period-1)):
            i = 0
        else:
            i += 1
    return indexes

def get_indexes_to_remain_for_rech_threshold(df, number_lines, rech_thr):
    '''
        TODO

    '''
    indexes = [0,1]
    rech_compt = 0
    for ligne in range(1, number_lines):
        rl = df['rech'][ligne]
        pred_compt = rech_compt + rl
        if (ligne != number_lines-1):
            if (pred_compt > rech_thr):
                if (pred_compt - rech_thr) < (rech_thr - rech_compt):
                    indexes.append(ligne+1) # the line number ligne is included in perforation. The following line is the line to remain
                else:
                    if indexes[-1] != ligne:
                        indexes.append(ligne) # the line number ligne is not included in perforation and is the next line to remain
                rech_compt = 0
            else:
                rech_compt = pred_compt
        else: # Last line
            if (pred_compt > rech_thr):
                if (pred_compt - rech_thr) >= (rech_thr - rech_compt):
                    indexes.append(ligne)
    return indexes


def aggregate_values(df, indexes, nb_rows):
    '''
        TODO
    '''
    df.loc[0,'rech'] = float(df['rech'].mean()) #df['rech'][0]
    print("mean init for inputfile: ", df.loc[0,'rech'])

    for i in range(1, len(indexes)):
        #print(i)
       #  print(indexes[3+1], indexes[3]) #Initialisation has to remain so strating at period number 1. Initialisation period is number 0.
        if i < (len(indexes)-1):
            for z in range(indexes[i]+1, indexes[i+1]): #+1 pour ne pas compter la valeur df.iat[indexes[i]] une deuxième fois
                df.iat[indexes[i], 4] += df['rech'][z]
            df.iat[indexes[i], 4] = float(df.iat[indexes[i], 4]) / (indexes[i+1] - indexes[i])
            df.iat[indexes[i], 1] = indexes[i+1] - indexes[i]
        else:
            for z in range(indexes[i]+1, nb_rows):
                df.iat[indexes[i], 4] += df['rech'][z]
            df.iat[indexes[i], 4] = df.iat[indexes[i], 4] / (nb_rows - indexes[i])
            df.iat[indexes[i], 1] = nb_rows-indexes[i]
    return df

def modifyValuesInLinesToRemainWithSeaLvl(df, indexes, nb_rows):
    for i in range(len(indexes)):
        if i < (len(indexes)-1):
            for z in range(indexes[i]+1, indexes[i+1]):
                df.iat[indexes[i], 4] += df['rech'][z]
            df.iat[indexes[i], 4] = df.iat[indexes[i], 4] / \
                (indexes[i+1] - indexes[i])
            df.iat[indexes[i], 1] = indexes[i+1] - indexes[i]
        else:
            for z in range(indexes[i]+1, nb_rows):
                df.iat[indexes[i], 4] += df['rech'][z]
            df.iat[indexes[i], 4] = df.iat[indexes[i], 4] / (nb_rows - indexes[i])
            df.iat[indexes[i], 1] = nb_rows - indexes[i]
    return df


def keep_only_rows_with_indexes(df, indexes):
    index_remove = []
    for y in range(0, len(df.index)):
        index_remove.append(y)

    for z in indexes[:]:
        if z in index_remove:
            index_remove.remove(z)

    df.drop(df.index[index_remove], inplace=True)
    return df


def change_time_step(df, timestepValue):
    df["time_step"][1:] = timestepValue #[1:] when initialisation was conserved
    return df


def write_custom_input_file(modelname, df):
    outputname = "input_file_" + modelname + ".txt"
    filepath = os.path.join('/'.join(os.path.realpath(__file__).split('/')[:-2]) , "data", outputname)
    df.to_csv(filepath, sep="\t", index=False)
    return outputname

def manipulate_ref_input_file(template_name,  approx, rate, time_step=None): #, periodValue
    df = extract_df_from_ref_input_file(template_name)

    if approx==0:
            period = [int(rate)] #getNumberOfLinesToReduceInLoop(prd)
            indexes = get_indexes_to_remain(len(df.index), period)
    elif approx==1:
            indexes = get_indexes_to_remain_for_rech_threshold(df, len(df.index), rate)    

    df = aggregate_values(df, indexes, len(df.index))
    df = keep_only_rows_with_indexes(df, indexes)
    
    if time_step is not None:
        df = change_time_step(df, time_step)

    return df

def generate_custom_input_file(model_name, input_name, approx, rate, chronicle, time_step=None):
    folder_path = '/'.join((os.path.dirname((os.path.abspath(__file__)))).split('/')[:-1])
    chronicle_file = pd.read_table(folder_path + "/data/chronicles.txt", sep=',', header=0, index_col=0)
    template_file = chronicle_file.template[chronicle]
    df = manipulate_ref_input_file(template_file,  approx, rate, time_step=time_step)
    if model_name is None:
        model_name = hlp.generate_model_name(chronicle, approx, rate, ref=False)
    output_name = write_custom_input_file(model_name, df)
    return output_name

if __name__ == '__main__':
    ### Parser ###
    parser = argparse.ArgumentParser()
    parser.add_argument("-rate", "--rate", type=float, required=True, help="Rate to which aggregate lines of the input file")
    parser.add_argument("-ts", "--timestep", type=int, required=False)
    parser.add_argument("-chr", "--chronicle", type=int, required=True)
    parser.add_argument("-m", "--modelname", type=str, required=False)
    parser.add_argument("-templ", "--template", help="Name of the input file to take as reference", type=str, required=False)
    parser.add_argument("-approx", '--approximation', type=int, required=True)
    args = parser.parse_args()

    input_name = args.template
    time_step = args.timestep
    model_name = args.modelname
    rate = args.rate
    approx = args.approximation
    chronicle = args.chronicle

    if time_step is None:
        out = generate_custom_input_file(model_name, input_name, approx, rate, chronicle)
    else:
        out = generate_custom_input_file(model_name, input_name, approx, rate, chronicle, time_step=time_step)
    print("custom input file name : ", out)

# By default time_step = None