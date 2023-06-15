# -*- coding: utf-8 -*-
"""
Created on Wed May  3 11:35:03 2023

@author: Martin Le Mesnil
"""
def SHOM(maregraph, first_yr, last_yr):

    import os
    import pandas as pd
    
    ZH_dict = {'Dielette': -4.912,
               'St-Malo': -6.289}
    ZH = ZH_dict[maregraph]
    
    list_filenames = os.listdir(os.path.join(r'C:\Users\Martin Le Mesnil\Travail\data\SHOM', maregraph))
    list_path = []
    for name in list_filenames:
        if name.endswith('.txt') and int(name[-8:-4])>=first_yr and int(name[-8:-4])<=last_yr:
            path = os.path.join(r'C:\Users\Martin Le Mesnil\Travail\data\SHOM', maregraph, name)
            list_path.append(path)
    
    SHOM_df_list = []
    for m in range(len(list_path)):
        SHOM_data = pd.read_csv(list_path[m], sep = ";", header = 13)
        SHOM_df_list.append(SHOM_data)
    
    SHOM_df_h = pd.concat(SHOM_df_list)
    SHOM_df_h['Valeur'] = SHOM_df_h['Valeur'] + ZH
    SHOM_df_h = SHOM_df_h.rename(columns={"# Date": "Date"})
    SHOM_df_h['Date'] = pd.to_datetime(SHOM_df_h['Date'], dayfirst=True)
    SHOM_df = SHOM_df_h.groupby(pd.Grouper(key='Date',freq='D')).max()
    SHOM_df = SHOM_df.drop(columns=['Source'])
    shift = SHOM_df.mean() - SHOM_df_h.Valeur.mean()
    SHOM_df = SHOM_df - shift
    
    return SHOM_df

    # import matplotlib.pyplot as plt
    # plt.plot(SHOM_df['Valeur'])
    # plt.plot(SHOM_df_h['Date'], SHOM_df_h['Valeur'])
