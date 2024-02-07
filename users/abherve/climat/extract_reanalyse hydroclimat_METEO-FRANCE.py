# -*- coding: utf-8 -*-
"""
Created on Wed Jan 17 16:45:57 2024

@author: ronan
"""

#%% INFO

# Portail meteo.data.gouv.fr - Données climatiques quotidienne (SIM2 = SAFRAN-ISBA) - Extraction de série chronologique pour une maille (1x1 km)

# Auparavant, télécharger les données depuis le portail ci-dessous (chaque décennie repésente 1.1 Go en archive et 5 Go décompressé)

#     Lecture du fichier de la décennie voulue
#     Extraction du point voulu et tracé de la carte de situation
#     Tracé du graphique chronologique de la décennie pour les paramètres et le point de maille choisis (par exemple 10 paramètres pour limiter l'occupation en mémoire vive)
#     Sauvegarde des séries chronologiques avec le graphique dans un fichier Excel
#     Le graphique dynamique est également sauvegardé en Html

# data: https://meteo.data.gouv.fr/

# Auteur: https://github.com/loicduffar

#%% 0) Load BV and paths

folder_clim = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/12_Data/SIM2_MeteoFrance/'
# out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'
# watershed_name = 'Lasset'
out_path = 'D:/Users/abherve/SIMULATIONS/'
watershed_name = 'PETITE_EMPRISE'
watershed_name = 'GRANDE_EMPRISE'

# Import HydroModPy modules
import os
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)
import src
import importlib
importlib.reload(src)
from src import watershed_root
dem_path = None
subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_shp = None
load = True
from_xyv = [None,None,None,None,None]
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              from_xyv=from_xyv)

# ================ Personalisation ====================
# folder_in= r"X:\1-COMMUN\DIS\Documentation\Hydrologie\Documentation externe\Climat France\Météo-France\meteo.data\reference\SIM2"
# # Chemin d'accès au fichier d'entrée des métadonnées de coordonnées des mailles SIM2
# fld_meta= r'X:\1-COMMUN\DIS\Documentation\Hydrologie\Documentation externe\Climat France\Météo-France\meteo.data\reference\SIM2\metada'
# # Chemin d'accès aux fichiers de sortie
# folder_out= r"X:\1-COMMUN\DIS\Documentation\Hydrologie\Documentation externe\Climat France\Météo-France\meteo.data\reference\SIM2"

# Chemin d'accès au fichier d'entrée des données quotidiennes
folder_in= folder_clim + '_raw/'
# Chemin d'accès au fichier d'entrée des métadonnées de coordonnées des mailles SIM2
fld_meta=  folder_clim + '_mesh/'
# Chemin d'accès aux fichiers de sortie
folder_out=  folder_clim + watershed_name +'/'
if not os.path.exists(folder_out):
    os.makedirs(folder_out)

#%% 1) Lecture du fichier CSV

# Chaque fichier contient une décennie de données journalières depuis 1958 (à part le premier et le dernier dont les décennies sont incomplètes)
# La taille d'un fichier est donc très importante (5 Go environ), et le temps de lecture est environ de 13 minutes pour 10 paramètres

#     Renseignez le fichier de la décennie à lire (et son chemin d'accès)
#     Définir les paramètres désirés (par exemple 10 sous peine de satuer une mémoire vive de 8 Go)

# ATENTION: La personalisation du point à lire est à faire ultérieurement dans la 2ème cellule (pour permettre d'interroger plusieurs points sans relire le fichier)

############ Auteur: L. Duffar ###########
############ Décembre 2023 ###########
# python 3.8.12

# Lecture du fichier au format suivant dans un dataframe pandas

# LAMBX;LAMBY;DATE;PRENEI_Q;PRELIQ_Q;T_Q;FF_Q;Q_Q;DLI_Q;SSI_Q;HU_Q;EVAP_Q;ETP_Q;PE_Q;SWI_Q;DRAINC_Q;RUNC_Q;RESR_NEIGE_Q;RESR_NEIGE6_Q;HTEURNEIGE_Q;HTEURNEIGE6_Q;HTEURNEIGEX_Q;SNOW_FRAC_Q;ECOULEMENT_Q;WG_RACINE_Q;WGI_RACINE_Q;TINF_H_Q;TSUP_H_Q
# 600;24010;20200101;0.0;0.4;9.9;2.1;7.414;3161.6;111.1;98.4;0.1;0.3;0.3;0.940;2.2;0.1;0.0;0.0;0.000;0.000;0.000;0.0;0.0;0.315;0.000;9.5;10.9
# 600;24010;20200102;0.0;0.6;11.3;5.5;7.396;2955.5;55.2;89.8;0.7;0.4;-0.1;0.933;2.0;0.0;0.0;0.0;0.000;0.000;0.000;0.0;0.0;0.314;0.000;9.5;11.9
# 600;24010;20200103;0.0;0.8;9.6;6.1;6.458;3066.2;56.5;87.2;1.0;0.7;-0.2;0.926;1.9;0.1;0.0;0.0;0.000;0.000;0.000;0.0;0.0;0.313;0.000;8.8;10.6
# Etc…

import pandas as pd
import os
import datetime

# Nom du fichier CSV de métadonnées de coordonnées des mailles SIM2
file_meta= 'coordonnees_grille_safran_lambert-2-etendu.csv'
# Nom du fichier CSV de données à lire
# file_name= 'QUOT_SIM2_latest-20231101-20231212.csv' # novembre 2023 jusqu'au jour précédent le teléchargement
# file_name= 'QUOT_SIM2_2010_2019.csv'
# file_name= 'QUOT_SIM2_latest-2020-202311.csv' # janvier 2020 jusqu'au mois précédent le teléchargement
# file_name = 'SIM2_2020_2023.csv'

for file_name in ['SIM2_1958_1959.csv',
                  'SIM2_1960_1969.csv',
                  'SIM2_1970_1979.csv',
                  'SIM2_1980_1989.csv',
                  'SIM2_1990_1999.csv',
                  'SIM2_2000_2009.csv',
                  'SIM2_2010_2019.csv',
                  'SIM2_2020_2023.csv',
                  'SIM2_2023_2024.csv']:

    # file_name = 'SIM2_2023_2024.csv'
    
    # Colonnes à lire (pour économiser la mémoire vive) - Les 3 premières sont obligatoires (LAMBX, LAMBY, DATE)
    usecols= ['LAMBX', 'LAMBY', 'DATE', 'PRENEI_Q', 'PRELIQ_Q', 'T_Q', 'FF_Q', 'Q_Q', 'DLI_Q', 'SSI_Q', 'HU_Q', 'EVAP_Q', 'ETP_Q', 'PE_Q', 'SWI_Q', 'DRAINC_Q', 'RUNC_Q', 'RESR_NEIGE_Q', 'RESR_NEIGE6_Q', 'HTEURNEIGE_Q', 'HTEURNEIGE6_Q', 'HTEURNEIGEX_Q', 'SNOW_FRAC_Q', 'ECOULEMENT_Q', 'WG_RACINE_Q', 'WGI_RACINE_Q', 'TINF_H_Q', 'TSUP_H_Q']
    # usecols= ['LAMBX', 'LAMBY', 'DATE', 'PRENEI_Q', 'PRELIQ_Q', 'T_Q',                'DLI_Q',          'HU_Q',           'ETP_Q',          'SWI_Q',                       'RESR_NEIGE_Q',                                                                                                                                 'TINF_H_Q', 'TSUP_H_Q']
    
    # ================ Initialisation ====================
    # Associe aux paramètres une unité et un nom long grâce à un dictionnaire (tiré de liste_parametres.odt https://www.data.gouv.fr/fr/datasets/r/d1ffaf5e-7d15-4fb5-a34c-f76aaf417b46)
    dict_units= {'Precip': ['mm', 'Précipitations totales (06-06 UTC)'], 'PRENEI_Q': ['mm', 'Précipitations solides (06-06 UTC)'], 'PRELIQ_Q': ['mm', 'Précipitations liquides (06-06 UTC))'], 
                 'T_Q': ['°C','Température moyenne'], 'FF_Q': ['m/s', 'Vit. vent'], 'Q_Q': ['g/kg','Humidité spécifique '], 'DLI_Q': ['J/cm2', 'Rayonnement atmosphérique '],
                 'SSI_Q': ['J/cm2', 'Rayonnement visible '], 'HU_Q': ['%', 'Humidité relative '], 'EVAP_Q': ['mm', 'ETR (cumul quotidien 06-06 UTC)'], 
                 'ETP_Q': ['mm', 'ETP (Penman-Monteith)'], 'PE_Q': ['mm', 'Pluies efficaces'], 'SWI_Q': ['%', 'Indice humidité des sols (06-06 UTC)'],
                 'DRAINC_Q': ['mm', 'Drainage (06-06 UTC)'], 'RUNC_Q': ['mm', 'Ruissellement (06-06 UTC)'], 'RESR_NEIGE_Q': ['mm', 'Equivalent eau manteau neigeux (06-06 UTC)'], 
                 'RESR_NEIGE6_Q': ['mm', 'Equivalent eau manteau neigeux à 06 UTC'], 'HTEURNEIGE_Q': ['m', 'Epaisseur manteau neigeux (moyenne 06-06 UTC)'], 
                 'HTEURNEIGE6_Q': ['m', 'Epaisseur du manteau neigeux à 06 UTC)'], 'HTEURNEIGEX_Q': ['m', 'Epaisseur manteau neigeux maximum dans journée'], 
                 'SNOW_FRAC_Q': ['%', 'Fraction maille recouverte par neige (moyenne 06-06 UTC)'], 'ECOULEMENT_Q': ['mm', 'Ecoulement en base manteau neigeux'], 
                 'WG_RACINE_Q': ['mm','Contenu en eau liquide dans couche racinaire à 06 UTC'], 'WGI_RACINE_Q': ['mm', 'Contenu en eau gelée dans la couche de racinaire à 06 UTC'], 
                 'TINF_H_Q': ['°C', 'Température minimale des 24 valeurs horaires'], 'TSUP_H_Q': ['°C', 'Température maximale des 24 valeurs horaires']}
    
    # ================ Lecture des données quotidiennes ====================
    # afficher l'heure 
    start = datetime.datetime.now()
    print("Heure de démarrage : ", start.strftime("%Y-%m-%d %H:%M"))
    print("Attendez l'affichage des données et soyez patient ! La lecture prend environ 13 minutes pour une décennie entière et 10 paramètres...")
    
    file_path = os.path.join(folder_in, file_name)
    # Lit un fichier csv comportant des données météo dans un dataframe pandas, en précisant les champs à lire
    df = pd.read_csv(file_path, sep=';', header=0, parse_dates=True, decimal='.', usecols= usecols)
    
    # Ajoute une colonne 'ID' avec la concaténation des 2 colonnes  LAMBX et LAMBY
    df['ID'] = df['LAMBX'].astype(str) + '_' + df['LAMBY'].astype(str)
    df.drop(['LAMBX', 'LAMBY'], axis=1, inplace=True)
    # index sur les 2 colonnes 'DATE' et 'ID'
    df['DATE']= pd.to_datetime(df["DATE"].values, format='%Y%m%d').values
    
    # df = df.set_index(['ID', 'DATE'])
    df = df.set_index(['ID', 'DATE'])
    print(df.columns)
    # afficher la durée d'éxécution
    now = datetime.datetime.now()
    print("Heure de fin : ", now.strftime("%Y-%m-%d %H:%M"))
    # affiche la différence entre les instants de début et de fin
    print("Durée d'éxécution : ", now - start)
    
    # ================ lit le fichier csv de métadonnées des coordonnées lat long des mailles
    file_path = os.path.join(fld_meta, file_meta)
    
    # Lit un fichier csv comportant des données météo dans un dataframe pandas
    df_meta = pd.read_csv(file_path, sep=';', header=0, decimal=',')
    # Ajoute une colonne 'ID' avec la concaténation des 2 colonnes  LAMBX et LAMBY
    df_meta['ID'] = df_meta['LAMBX (hm)'].astype(str) + '_' + df_meta['LAMBY (hm)'].astype(str)
    # supprime les colonnes 'LAMBX (hm)' et 'LAMBY (hm)'
    df_meta.drop(['LAMBX (hm)', 'LAMBY (hm)'], axis=1, inplace=True)
    # index sur la colonne 'ID'
    df_meta = df_meta.set_index(['ID'], drop=True)
    # display(df_meta)
    
    # jointure des 2 dataframes en plaçant les nouvelles colonnes au début
    df = df_meta.join(df, how='inner')
    
    df
    
    #%% 3) Extrait les lignes à partir d'un shpaefile (mailles qui intersectent le shapefile)
    
    import geopandas as gpd
    import matplotlib.pyplot as plt
    import rasterio
    import numpy as np
    from rasterio.plot import show
    
    # ================ Personalisation ====================
    # ID cells pour lequel extraire les données
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)
    shp_mesh = gpd.read_file(fld_meta+'maille_meteo_fr_pr93.shp')
    shp_catch = gpd.read_file(BV.geographic.watershed_shp)
    shp_site = gpd.read_file(BV.stable_folder+'/'+'geographic/box_buff.shp')
    shp_clip = shp_mesh.clip(shp_catch)
    cells_ID = list(shp_clip['ET_ID'])
    cells_X = list((shp_clip['Xlamb']/100))
    cells_Y = list((shp_clip['Ylamb']/100))
    SIM_ID = []
    for i in range(len(cells_ID)):
        SIM_ID.append(str(int(cells_X[i]))+'_'+str(int(cells_Y[i])))
    
    # ================ Traitement ====================
    # ----------- Initialisation
    # duplique le dataframe
    df_temp = df.copy(deep=True)
    
    df_temp = df_temp[df_temp.index.get_level_values(0).isin(SIM_ID)]
    
    fig, ax = plt.subplots(1,1, dpi=300)
    mnt = show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
               ax=ax, transform=dem.transform,
               cmap='terrain', alpha=0.55, zorder=0, aspect="auto")
    shp_site.plot(ax=ax, alpha=1,facecolor='None')
    shp_catch.plot(ax=ax, alpha=1,facecolor='None')
    shp_clip.plot(ax=ax, facecolor='None')
    
    # ----------- Affichage
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    # display(df_temp)
    # fig.show()
    
    name_end = os.path.splitext(file_name)[0][-10:]
    
    df_temp.to_csv(folder_out+'QUOT_SIM2' + name_end + '.csv', sep=';')

#%% 2) Extrait les lignes de la maille voulue (maille la plus proches des coordonnées lat lon)
"""
# Extrait les lignes de la maille voulue (maille la plus proches des coordonnées lat lon)
import plotly.express as px
import plotly.graph_objects as go

# ================ Personalisation ====================
# coordonnées du point pour lequel extraire les données
# lat, lon= [43.529910019461035, 5.424477733642604]# Aix Galice
# lat, lon= [44.70307665682509, 6.600304257413277] # St Crépin
# lat, lon= [42.871478, 1.833721] # Montsegur
lat, lon = [42.824307, 1.777387] # Etang du Diable

# ================ Traitement ====================
# ----------- Initialisation
# duplique le dataframe
df_temp = df.copy(deep=True)

# calcule la distance entre chaque ligne et les coordonnées lat lon
df_temp['distance'] = ((df['LAT_DG'] - lat)**2 + (df['LON_DG'] - lon)**2)**0.5
# sélectionne la ligne avec la distance minimale
minimum = df_temp['distance'].min()

df_temp = df_temp.loc[df_temp['distance'] == minimum]

# supprime la colonne 'distance'
df_temp.drop(['distance'], axis=1, inplace=True)

# -----------trace une carte plotly avec le point de maille en spécifiant le nom de la trace pour la légende   

fig = px.scatter_mapbox(lat= [df_temp['LAT_DG'][0]], lon= [df_temp['LON_DG'][0]], mapbox_style= "open-street-map", 
                        title= 'Maille SAFRAN la plus proche des coordonnées fournies', height= 500, width= 700,
                        color_discrete_sequence= [ 'red'], size= [1 for i in [1]], size_max= 10,
                        # labels= 'Maille la plus proche'
                       hover_name= ['Maille la plus proche'], 
                      )

# Ajoute les coordonnées cibles avec le nom de la trace en légente
fig.add_trace(go.Scattermapbox(lat= [lat], lon= [lon], mode= 'markers', marker= {'size': 10, 'color': 'blue'}, name= 'Coordonnées cibles', ))

# sauvegarde la carte au format png et html
map_file= "SIM2_map"
fig.write_image(os.path.join(folder_out, map_file + '.png'))
fig.write_html(os.path.join(folder_out, map_file + '.html'))

# ----------- Affichage
print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
# display(df_temp)
fig.show()

name_end = os.path.splitext(file_name)[0][-10:]

df_temp.to_csv(folder_out+'QUOT_SIM2' + name_end + '.csv', sep=';')
"""

#%% 4) Extrait les lignes à partir du centroid d'un shpaefile (maille qui intersecte le point)
"""
import geopandas as gpd
import matplotlib.pyplot as plt
import rasterio
import numpy as np
from rasterio.plot import show

# ================ Personalisation ====================
# ID cells pour lequel extraire les données
shp_catch = gpd.read_file(BV.geographic.watershed_shp)
shp_catch["center"] = shp_catch["geometry"].centroid

from pyproj import Transformer
transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326")
center_latlon = transformer.transform(shp_catch["center"].x.values[0],shp_catch["center"].y.values[0])

# Extrait les lignes de la maille voulue (maille la plus proches des coordonnées lat lon)
import plotly.express as px
import plotly.graph_objects as go

# ================ Personalisation ====================
# coordonnées du point pour lequel extraire les données
# lat, lon = [42.824307, 1.777387] # Etang du Diable
lat, lon = [center_latlon[0], center_latlon[1]] # Etang du Diable

# ================ Traitement ====================
# ----------- Initialisation
# duplique le dataframe
df_temp = df.copy(deep=True)

# calcule la distance entre chaque ligne et les coordonnées lat lon
df_temp['distance'] = ((df['LAT_DG'] - lat)**2 + (df['LON_DG'] - lon)**2)**0.5
# sélectionne la ligne avec la distance minimale
minimum = df_temp['distance'].min()

df_temp = df_temp.loc[df_temp['distance'] == minimum]

# supprime la colonne 'distance'
df_temp.drop(['distance'], axis=1, inplace=True)

# -----------trace une carte plotly avec le point de maille en spécifiant le nom de la trace pour la légende   

fig = px.scatter_mapbox(lat= [df_temp['LAT_DG'][0]], lon= [df_temp['LON_DG'][0]], mapbox_style= "open-street-map", 
                        title= 'Maille SAFRAN la plus proche des coordonnées fournies', height= 500, width= 700,
                        color_discrete_sequence= [ 'red'], size= [1 for i in [1]], size_max= 10,
                        # labels= 'Maille la plus proche'
                       hover_name= ['Maille la plus proche'], 
                      )

# Ajoute les coordonnées cibles avec le nom de la trace en légente
fig.add_trace(go.Scattermapbox(lat= [lat], lon= [lon], mode= 'markers', marker= {'size': 10, 'color': 'blue'}, name= 'Coordonnées cibles', ))

# sauvegarde la carte au format png et html
map_file= "SIM2_map"
fig.write_image(os.path.join(folder_out, map_file + '.png'))
fig.write_html(os.path.join(folder_out, map_file + '.html'))

# ----------- Affichage
print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
# display(df_temp)
fig.show()

name_end = os.path.splitext(file_name)[0][-10:]

df_temp.to_csv(folder_out+'QUOT_SIM2' + name_end + '.csv', sep=';')
"""
#%% 5) Trace le graphique chronologique des paramètres

# Affiches des subplots multiples plotly superposé de tous des paramètres
# (température par exemple car pour les précipitations il faut choisir liquide ou solide ou en faire la somme)

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ================ Traitement ====================
param_list= df_temp.columns.values[2:]
# Création d'un graphique plotly
fig = make_subplots(rows= len(param_list), cols= 1, shared_xaxes= True, vertical_spacing= 0.02, subplot_titles= param_list)

for i, param in enumerate(param_list):
    fig.add_trace(go.Scatter(x= df_temp.index.get_level_values(1).values, y= df_temp[param], name= param), row= i+1, col= 1)

    fig.update_yaxes(title_text= dict_units[param][0], row= i+1, col=1)
    fig.update_xaxes(title_text='Date', row= i+1, col= 1)
    fig.update_traces(line= dict(width=1), row= i+1, col= 1)
    # if i == len(param_list)-1:
    #     fig.update_xaxes(showticklabels=True, title_text='Date', row= i+1, col=1)
        
fig.update_layout(height= 1500, width= 1000, title_text= 'Paramètres météorologiques quotidiens SIM2 (SAFRAN)', title_x= 0.5,
                  hovermode='x unified', hoverlabel= dict(bgcolor='rgba(255,255,255,0.6)'))
# Trace une ligne verticale au travers tous les subplots matérialisant l'abscisse survolée par la souris 
xlast= 'x' + str(len(param_list))
fig.update_traces(xaxis= xlast)
fig.update_xaxes(showticklabels= True, title_text= 'Date', row= len(param_list), col= 1)

# définit le titre des différents subplots
for i, param in enumerate(param_list):
    fig.layout.annotations[i].update(text= dict_units[param][1])

# supprime la légende
fig.update_layout(showlegend=False)
# sauvegarde le graphique dans des fichiers image et html
graph_file= "SIM2_graph"
fig.write_image(os.path.join(folder_out, graph_file + ".png"))
fig.write_html(os.path.join(folder_out, graph_file + ".html"))

print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
fig.show()

#%% 6) Sauvegarde les données et le graphique dans un fichier Excel
"""
# Enregistre le dataframe dans un fichier excel

# ================ Personalisation ====================
# Chemin d'accès aux fichiers de sortie

# Nom du fichier CSV à lire

name_end= os.path.splitext(file_name)[0][-10:]

file_excel= 'QUOT_SIM2' + name_end + '.xlsx'

# ================ Traitement ====================
file_path = os.path.join(folder_out, file_excel)
# Enregistre le dataframe dans un fichier excel
writer = pd.ExcelWriter(file_path, engine='xlsxwriter')
workbook  = writer.book
df_temp.to_excel(writer, sheet_name='data', startrow=3)
worksheet = writer.sheets['data']
worksheet.write('A1', 'Lambert2 =')
worksheet.write('A2', 'Lat. Lon. ')

worksheet.write('B1', df_temp.index.get_level_values(0)[0])
worksheet.write('B2', str(lat) + '_' + str(lon))

# créé un autre sheet avec les graphiques
worksheet = workbook.add_worksheet('graphiques')
if os.path.exists(os.path.join(folder_out, graph_file + '.png')):
    worksheet.insert_image('A1', os.path.join(folder_out, graph_file + '.png'))
if os.path.exists(os.path.join(folder_out, map_file + '.png')):
    worksheet.insert_image('Q1', os.path.join(folder_out, map_file + '.png'))
workbook.close()

if os.path.exists(os.path.join(folder_out, graph_file + '.png')):
    os.remove(os.path.join(folder_out, graph_file + '.png'))
if os.path.exists(os.path.join(folder_out, map_file + '.png')):
    os.remove(os.path.join(folder_out, map_file + '.png'))

print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
print('Enregistrement terminé du fichier excel : ', file_path)
"""
#%% Notes

# x = pd.read_csv('C:/Users/ronan/Downloads/QUOT_SIM2_previous-2020-202312.csv')


