# ---- Chargement des flux d'entrée à partir des données mensuelles
logging.info("   . Chargement des flux d'entrée mensuels")

dam_data_path = os.path.join(data_path, "Reservoir", 
                             "Donnees mensuelles base historique",
                             r"dam_cheze_volume_raw_2000-2022.csv")

dam_input_df = pd.read_csv(dam_data_path,
                           sep = ";",
                           header = 0,
                           skiprows = 0,
                           index_col = 'time',
                           parse_dates = True)

#### Gestion de la temporalité des valeurs :
# 1. Conversion des valeurs (sommes mensuelles) en flux journaliers
days_in_month = pd.DataFrame( 
    index = dam_input_df.index,
    data = dam_input_df.index.days_in_month)
days_in_month.rename(columns = {'time':'n_days'}, inplace = True)
# dam_input_df = dam_input_df.divide(days_in_month.n_days, axis="index")
sum_col = dam_input_df.columns != 'cheze'
dam_input_df.loc[:, sum_col] = dam_input_df.loc[:, sum_col].divide(
    days_in_month.n_days, axis="index")

# 2. Sous-échantillonage des données d'entrée en journalier
daily_index = pd.date_range(start = BV.climatic.recharge.index[0], 
                             periods = (BV.climatic.recharge.index[-1] \
                                 - BV.climatic.recharge.index[0]).days + 1,
                                 freq = 'D') 
dam_input_df = dam_input_df.reindex(index = daily_index)
dam_input_df.fillna(method = 'bfill', inplace = True) # backward fill
dam_input_df.fillna(0, inplace = True) # replace remaining NaN with 0
# 3. puis sur-échantillonage selon la temporalité de la recharge
rules = {
    'cheze': 'mean',
    'canut':'mean',
    'meu':'mean',
    'usine':'mean',
    'resti':'mean',
    'stream':'mean',
    'ppt_surf':'mean',
    'ae_oudin':'mean',
    }
dam_input_df = dam_input_df.resample(freq_input).agg(rules)

# Méthode alternative pour 1., 2. et 3. : 
# Sous-échantillonage des données d'entrée selon la temporalité de la recharge, avec interpolation
# =============================================================================
# # interpolation method
# dam_input_df = dam_input_df.shift(periods = -15.21875, freq = 'D') # 15.21875 is half of average number of days per month
# dam_input_df = dam_input_df.resample('D').agg(rules)
# dam_input_df.interpolate(method = "time", limit_direction = 'backward', inplace = True)
# =============================================================================

# ---- Raffinage des débits de la Chèze
# Ce n'est plus utile maintenant que les débits modélisés sont utilisés à la
# place, grace à la section suivante: "ECOULEMENTS DE SURFACE avec SFR2"
# =============================================================================
# logging.info("   . Raffinage des débits de la Chèze à partir de eaufrance.fr")
# 
# code_station = 'J736422001' # La Chèze à Plélan-le-Grand - L'Enlevrier
# # Details sur la station:
# # -----------------------
# url = r"https://hubeau.eaufrance.fr/api/v1/hydrometrie/referentiel/stations"
# params = {
#     # 'code_region': ['44'],
#     # "code_site": "J7364220", 
#     "code_station": code_station,
#     "size": 10000,
#     }
# res = requests.get(url, params)
# # =============================================================================
# # with open(os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits",
# #                        "stations_liste.csv"), "w",
# #           encoding = res.encoding, ) as f:
# #     f.write(res.text)
# # 
# # stations_list = pd.read_csv(
# #     os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits",
# #                  "stations_liste.csv"),
# #     sep = ";",
# #     quotechar = '"',
# #     parse_dates = ['date_ouverture_station', 'date_fermeture_station'],
# #     # date_format = "%d/%m/%Y",
# #     )
# # =============================================================================
# if 'data' in res.json().keys():
#     stations_info = pd.DataFrame.from_dict(res.json()['data'])
# else:
# # elif ('code' in res.json().keys()) or (res.json()['code'] == 'Internal server error'):
#     stations_info = pd.read_csv(os.path.join(data_path, "Debits", "stations_list.csv"),
#         sep = ";",
#         header = 0,
#         index_col = 0)
#     logging.error("        Erreur sur la mise-à-jour des infos des stations de jaugeage")
# # Mise à jour des fichiers
# stations_info.to_csv(os.path.join(data_path, "Debits", "stations_list.csv"), 
#     sep = ";")
# 
# # Valeurs de flux journaliers :
# # -----------------------------
# url = r"https://hubeau.eaufrance.fr/api/v1/hydrometrie/obs_elab"
# # idx = stations_info.index[stations_info['code_station'] == code_station][0]
# # date_ini = stations_info.loc[idx, 'date_ouverture_station']
# date_ini = stations_info.loc[0, 'date_ouverture_station']
# date_today = pd.to_datetime('today').strftime("%Y-%m-%d")
# # As it is possible only to extract 10000 values, only the most recent values
# # will be retrieved
# date_start = max(pd.to_datetime(date_ini).replace(tzinfo = None), 
#                  pd.to_datetime(date_today) - pd.Timedelta(10000, 'D')
#                  ).strftime("%Y-%m-%d")
# 
# quantity = 'QmJ' # [l/s]
# 
# params = {
#     "size": 10000, # max
#     "code_entite": code_station,
#     "date_debut_obs_elab": date_start,
#     "date_fin_obs_elab": date_today, # NB: la dernière semaine est généralement manquante
#     "grandeur_hydro_elab": quantity,
#           }
# res = requests.get(url, 
#                     params = params
#                    )
# if 'data' in res.json().keys():
#     discharge = pd.DataFrame.from_dict(res.json()['data'])
# else:
#     discharge = pd.read_csv(os.path.join(data_path, "Debits",
#         "J736422001_QmnJ(n=1_non-glissant) debit_cheze_plelan-le-grand.csv"),
#         sep = ";",
#         header = 0,
#         index_col = 0)
#     logging.error("        Erreur sur la mise-à-jour du débit")
# # Update file:
# discharge.to_csv(os.path.join(data_path, "Debits",
#     "J736422001_QmnJ(n=1_non-glissant) debit_cheze_plelan-le-grand.csv"),
#     sep = ";")    
# 
# discharge = discharge.loc[:, ['date_obs_elab', 'resultat_obs_elab']]
# discharge.columns = ['time', 'val']
# discharge['val'] = discharge['val']*1e-3*60*60*24 # convertit [l/s] -> [m3/d]
# discharge['time'] = pd.to_datetime(discharge['time'])
# discharge.index = discharge.time
# discharge = discharge.reindex(index = daily_index)
# # discharge.fillna(0, inplace = True) # replace NaN with 0
# discharge = discharge.resample(freq_input).mean()
# 
# # Set the first value (used for steady initialization) as the average value
# discharge.iloc[0] = toolbox.hydrological_mean(discharge, 4)
# 
# dam_input_df['stream'].update(discharge.val)
# =============================================================================


# ---- Raffinage du niveau initial
logging.info("   . Raffinage du niveau initial de la retenue avec l'abaque")

abaque = pd.read_csv(os.path.join(data_path, "Reservoir", "Abaque",
    "abaque_cheze_2020.csv"),
                     sep = "\t",
                     header = 0,
                     names = ['level', 'volume'],
                     )


data_volumes = dam_input_df[['cheze']].copy()

# Données hebdomadaires
# ---------------------
Stock_Cheze_xls_folder = os.path.join(data_path, "Reservoir", 
                                      "Donnees journalieres EBR", "Niveaux")
try:
    Stock_Cheze_xls_path = os.path.join(
        Stock_Cheze_xls_folder,
        f"Villejean_Stock_Cheze_{pd.to_datetime('today').year}_val.xlsx")
    data = pd.read_excel(
        Stock_Cheze_xls_path,
        sheet_name = "Histos",
        header = 3, 
        # index_col = 0,
        # skiprows = 3,
        )
except:
    Stock_Cheze_xls_path = os.path.join(
        Stock_Cheze_xls_folder,
        f"Villejean_Stock_Cheze_{pd.to_datetime('today').year-1}_val.xlsx")
    data = pd.read_excel(
        Stock_Cheze_xls_path,
        sheet_name = "Histos",
        header = 3, 
        # index_col = 0,
        # skiprows = 3,
        )        

data = data.iloc[:, 3:-2]
if data.iloc[:, -1].count() == 0:
    logging.warning(f"        Les dernières valeurs ({data.columns[-1]}) n'ont pas été correctement récupérées.")
    logging.info("        Aller sur la feuille 'Histos', puis effectuer Ctrl+A, Ctrl+C, Maj+F10+V, et enregistrer sous un nouveau fichier <nom>_val.xlsx")

# Pivot from wide-format to long-format
data_volumes = pd.lreshape(data, 
                           groups = {'vol':data.columns},
                           dropna = False)

weekly_index = pd.date_range(start = pd.to_datetime(f'{data.columns[0]}:01_1', format = '%Y:%W_%w'),
                             periods = int(data_volumes.size*1.05), # extended
                             freq = 'W')

data_volumes.set_index(weekly_index[weekly_index.isocalendar().week != 53][0:data_volumes.size], 
                          inplace = True)
data_volumes = data_volumes.reindex(
    weekly_index[weekly_index <= data_volumes[data_volumes.notna().vol].index[-1]])

data_volumes.interpolate(method = 'time', inplace = True)

# Mise à jour des données d'entrées (optionnel)
# ---------------------------------------------
data_volumes = data_volumes.resample(freq_input).mean()
data_volumes.fillna(method = 'bfill', inplace = True) # backward fill
data_volumes.fillna(0, inplace = True) # replace remaining NaN with 0
dam_input_df['cheze'].update(data_volumes.vol)

# Conversion des volumes en stages
# --------------------------------
data_levels = data_volumes.copy()
data_levels.rename(columns = {'vol': 'lvl'}, inplace = True)
for t in data_levels.index:
    if not abaque[abaque.volume <= data_volumes.loc[t].item()].empty:
        data_levels.loc[t] = abaque[abaque.volume <= data_volumes.loc[t].item()].iloc[-1].level
    else:
        if data_volumes.loc[t].item() > abaque.volume.max():
            slope = (abaque.volume.iloc[-1] - abaque.volume.iloc[-2]) / (abaque.level.iloc[-1] - abaque.level.iloc[-2])
            add_level = abaque.level.iloc[-1] + (data_volumes.loc[t].item() - abaque.volume.iloc[-1])/slope
            abaque_interp = abaque.append({'level':add_level, 'volume':data_volumes.loc[t].item()}, 
                                          ignore_index = True)
        elif data_volumes.loc[t].item() < abaque.volume.min():
            slope = (abaque.volume.iloc[1] - abaque.volume.iloc[0]) / (abaque.level.iloc[1] - abaque.level.iloc[0])
            add_level = abaque.level.iloc[0] + (data_volumes.loc[t].item() - abaque.volume.iloc[0])/slope
            abaque_interp = pd.DataFrame(data = {'level':add_level, 'volume':data_volumes.loc[t].item()}, index = [0]).append(abaque, ignore_index = True)
        data_levels.loc[t] = abaque_interp[abaque_interp.volume <= data_volumes.loc[t].item()].iloc[-1].level

if BV.climatic.recharge.index[0] in data_levels.index:
    level_init = data_levels.loc[BV.climatic.recharge.index[0]].item()
else:
    # Method 'nearest'
# =============================================================================
#     level_init = float(data_levels.iloc[
#         data_levels.index.get_indexer([BV.climatic.recharge.index[0]], 'nearest')[0]])
# =============================================================================
    
    # Method 'interpolated'
    idx = data_levels.index.get_indexer([BV.climatic.recharge.index[0]], 'pad').item()
    
    data_levels_interp = data_levels.reindex(index = [data_levels.index[idx],
                                                      BV.climatic.recharge.index[0],
                                                      data_levels.index[idx+1]])
    data_levels_interp.interpolate(method = "time", inplace = True)
    level_init = data_levels_interp.loc[BV.climatic.recharge.index[0]].item()


BV.lakeres.update_stageinit(
    lake_id,
    level_init) # [m]


# ---- Raffinage des flux d'entrée récents à partir des données journalières
logging.info("   . Raffinage des flux d'entrée avec les données journalières :")

Flux_Cheze_xls_folder = os.path.join(data_path, "Reservoir",
                                     "Donnees journalieres EBR", "Flux")

for path, folders, files in os.walk(Flux_Cheze_xls_folder):
    if len(files) > 0:
        logging.info(f"        mise-à-jour {os.path.split(path)[-1]}")
        for f in files:
            if (f[0] != '~') & (f[-8:-5].casefold() != 'old'):
                if f[-11:-5] in ['1_2020', '2_2020', '3_2020',
                                 '4_2020', '5_2020']: # ancien format
                    data = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 7, 9, 11, 13, 14],
                        names = ['time', 'canut', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                    data['radar'] = data['cheze']
                else:
                    data = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 7, 9, 10, 12, 14, 15],
                        names = ['time', 'canut', 'radar', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                data = data[data.index.notna()] # remove the rows with no date
                # data.dropna(axis = 0, how = 'all', inplace = True) # remove the last rows if empty
                data.index = pd.to_datetime(data.index, format = '%d/%m/%Y')
                # Use radar values to fill in missing piezo values:
                data.cheze[data.cheze.isna()] = data.radar[data.cheze.isna()] 
                data = data.loc[:, data.columns != 'radar']
                data.interpolate(method = 'time', inplace = True)
                
                data = data.resample(freq_input).agg({var:rules[var] for var in data.columns})

                # Conversion des niveaux en volumes
                # ---------------------------------
                for t in data.index:
                    if not abaque[abaque.level <= data.cheze.loc[t].item()].empty:
                        data.cheze.loc[t] = abaque[abaque.level <= data.cheze.loc[t].item()].iloc[-1].volume
                    else:
                        if data.cheze.loc[t].item() > abaque.level.max():
                            slope = (abaque.level.iloc[-1] - abaque.level.iloc[-2]) / (abaque.volume.iloc[-1] - abaque.volume.iloc[-2])
                            add_volume = abaque.volume.iloc[-1] + (data.cheze.loc[t].item() - abaque.level.iloc[-1])/slope
                            abaque_interp = abaque.append({'volume':add_volume, 'level':data.cheze.loc[t].item()}, 
                                                          ignore_index = True)
                        elif data.cheze.loc[t].item() < abaque.level.min():
                            slope = (abaque.level.iloc[1] - abaque.level.iloc[0]) / (abaque.volume.iloc[1] - abaque.volume.iloc[0])
                            add_volume = abaque.volume.iloc[0] + (data.cheze.loc[t].item() - abaque.level.iloc[0])/slope
                            abaque_interp = pd.DataFrame(data = {'volume':add_volume, 'level':data.cheze.loc[t].item()}, index = [0]).append(abaque, ignore_index = True)
                        data.cheze.loc[t] = abaque_interp[abaque_interp.level <= data.cheze.loc[t].item()].iloc[-1].volume

                for col in ['cheze', 'resti', 'meu', 'canut', 'usine']:
                    dam_input_df[col].update(data[col])
                # dam_input_df[['cheze', 'resti', 'meu', 'usine']].update(data)