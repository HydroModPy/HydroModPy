# -*- coding: utf-8 -*-
"""
Created on Mon Nov 25 14:59:59 2024

@author: roquesc
"""


import sys
sys.modules[__name__].__dict__.clear() 

#%%
import pandas as pd
import matplotlib.pyplot as plt
import random 
import numpy as np
from math import sqrt


#%%
plt.close('all')

#%% open weather stattion data
# File path (replace 'weather.txt' with the actual file path)
file_path = 'L:\_poschiavino\_data\_weather_station_KB4\weather.txt'

data = pd.read_csv(file_path, sep=',')

# Convert the 'Date' column to a datetime format
station_data = pd.DataFrame()
station_data['time'] = pd.to_datetime(data['Date'], format='%d-%b-%Y %H:%M:%S')

# Extract the year for grouping
station_data['year'] = station_data['time'].dt.year

# Ensure numeric columns are correctly converted
station_data['CRain'] = pd.to_numeric(data['CRain'], errors='coerce')  # Corrected Precipitation
station_data['T'] = pd.to_numeric(data['T'], errors='coerce')          # Temperature

station_data.set_index('time', inplace=True)

#%%
# Resample every 3-hours 
station_data_3h = station_data.resample('3H').agg({
    'CRain': 'sum',  # Summing precipitation over each 3-hour period
    'T': 'mean'      # Taking the mean temperature over each 3-hour period
})

station_data_day = station_data.resample('D').agg({
    'CRain': 'sum',  # Summing precipitation over each 3-hour period
    'T': 'mean'      # Taking the mean temperature over each 3-hour period
})

# Reset the index to convert the time back to a column
# station_data_3h.reset_index(inplace=True)
# station_data_3h.set_index('time', inplace=True)
# Display the resampled data
# print(station_data_3h)

#%% open cerra data 
variables = ['2m_temperature','total_precipitation']
start = 1984
end = 2022 
grid_id = '_alps'
catchement = 'urse'
cerra_data = pd.DataFrame()
for var in variables: 
    path = f'M:/crash_zone/{var}_{catchement}.csv'
    # Load the data (assuming the file uses ',' as the delimiter)
    var_data = pd.read_csv(path, sep=',')
    cerra_data['time'] = pd.to_datetime(var_data['time'], format='%Y-%m-%d %H:%M:%S')
    # Ensure numeric columns are correctly converted
    cerra_data[var] = pd.to_numeric(var_data[var], errors='coerce')    
    
cerra_data.set_index('time', inplace=True)

cerra_data_day = cerra_data.resample('D').agg({
    'total_precipitation': 'sum',  
    '2m_temperature': 'mean'      
})

#%%
# fig, ax = plt.subplots(2,1)


# cerra_data.plot(ax=ax[0], y ='2m_temperature', marker = '.', ls = '', label = 'cerra')
# station_data_3h.plot(ax=ax[0], y ='T', marker = '.', ls = '', label = 'station')

# cerra_data.plot(ax=ax[1], y ='total_precipitation', marker = '.', ls = '', label = 'cerra')
# station_data_3h.plot(ax=ax[1], y ='CRain', marker = '.', ls = '', label = 'station')

# # ax.set_xlim(['2017-06-01','2017-06-03'])
# ax[0].set_title('CERRA and Urse weather station data')
# ax[0].set_xticks([]) 
# ax[0].set_xlabel('') 
# ax[0].legend('') 
# plt.show()

#%%

# fig, ax = plt.subplots()

# cerra_data.plot(ax=ax, y ='2m_temperature',label = 'cerra')
# station_data.plot(ax=ax, y ='T', label = 'station')

# # ax.set_xlim([list(station_data['time'])[0],list(station_data['time'])[30*18*24]])
# ax.set_title('full time serie')
# plt.show()

#%%
data = station_data_day.merge(cerra_data_day, how = 'left', on = 'time')

data.rename(columns = {'2m_temperature': 't2m_cerra',
                       'T': 't2m_urse',
                       'total_precipitation': 'tp_cerra',
                       'CRain':'tp_urse'}, inplace = True)
# data.plot(ls = '', marker ='+')
# plt.title('Data Urse and CERRA closest pixel')

#%% split debaising dataset and validate data set
data_ = data.dropna()
data_.reset_index(inplace=True)

ratio_val = 0.2
nb_points = data_.shape[0]
size1 = int(nb_points*ratio_val//1)

index = list(data_.index)
random.shuffle(index)
index_val = index[:size1]
index_val.sort()
index_bias = index[size1:]
index_bias.sort()

data_val = data_.iloc[index_val,:]
data_bias = data_.iloc[index_bias,:]
#%%
# data_val.plot(x = 'time',ls='',marker = '.')
# data_bias.plot(x = 'time',ls='',marker = '.')


#%% 
import numpy as np
from scipy.stats import percentileofscore

# Linear scaling x* = a + b.x
def generate_debiaser(data_ref,data_raw,method='LinearScaling'):
    """
        
    method dispo : 'LinearScaling'
    corr = a + b. mes
    a = 1/b.(ref_mean-mes_mean)
    b = ref_std
    
    """

    if method == 'LinearScaling':
        mean_ref = data_ref.mean()
        mean_raw = data_raw.mean()
        std_ref = data_ref.std()
        std_raw = data_raw.std()
        
        b = std_ref/std_raw
        a = 1/b*(mean_ref-mean_raw)
        
        debiaser = (lambda x: a+b*x)
        
    elif method == 'QuantileMappingReplace':
        data_model = data_raw
        debiaser = (lambda x: (np.percentile(data_ref, percentileofscore(data_model, x))) )
    
    elif method == 'QuantileMappingDelta':
        data_model = data_raw
        debiaser = (lambda x, data_sim : (x + np.percentile(data_ref,   percentileofscore(data_sim, x))
                                           - np.percentile(data_model, percentileofscore(data_sim, x))) )             
    else:
        print('> debiaser generator - mathod asked not available')
        debiaser = (lambda x: x)
        
    return debiaser

def statistics(data, cols, stats = dict()):
    
    for var in cols:
        stats[f'{var}_mean'] = data[var].mean()
        stats[f'{var}_std'] = data[var].std()
        
    return stats

def evaluate_debias(data_ref, data_raw, data_corr, method = 'diff'):
    """
    method - diff (difference stepBystep - mean - std)

    """
    rmse = (lambda X,Y: sqrt(np.mean((X-Y)**2)))
    
    diff_raw = data_ref - data_raw
    diff_corr = data_ref - data_corr
    
    diff_raw_abs = abs(diff_raw)
    diff_raw_mean = diff_raw.mean()
    diff_raw_std = diff_raw_abs.std()
    rmse_raw = rmse(data_ref,data_raw)
    
    diff_corr_abs = abs(diff_corr)
    diff_corr_mean = diff_corr.mean()
    diff_corr_std = diff_corr_abs.std()
    rmse_corr = rmse(data_ref,data_corr)
    
    evaluation = {'diff_raw': diff_raw,
                  'diff_raw_abs': diff_raw_abs,
                  'diff_raw_mean': diff_raw_mean,
                  'diff_raw_std': diff_raw_std,
                  'rmse_raw': rmse_raw,
                  
                  'diff_corr': diff_corr,
                  'diff_corr_abs': diff_corr_abs,
                  'diff_corr_mean': diff_corr_mean,
                  'diff_corr_std': diff_corr_std,
                  'rmse_corr': rmse_corr}
    
    return evaluation

def evaluate_debias_(data, cRef, cRaw, cCor, label = 'corr', output = dict(), cTime = 'time'):
    """
    method - diff (difference stepBystep - mean - std)

    """
    # 
    rmse = (lambda X,Y: sqrt(np.mean((X-Y)**2)))
    data_ref  = data.loc[:,cRef]
    data_raw  = data.loc[:,cRaw]
    data_corr = data.loc[:,cCor]
    timeline  = data.loc[:,cTime]

    # compute indicators
    diff_raw = data_ref - data_raw
    diff_corr = data_ref - data_corr
    
    diff_raw_abs = abs(diff_raw)
    diff_raw_mean = diff_raw_abs.mean()
    diff_raw_std = diff_raw_abs.std()
    rmse_raw = rmse(data_ref,data_raw)
    
    diff_corr_abs = abs(diff_corr)
    diff_corr_mean = diff_corr.mean()
    diff_corr_std = diff_corr_abs.std()
    rmse_corr = rmse(data_ref,data_corr)
    
    diffs = pd.DataFrame({  cTime: timeline, 
                           'diff_raw':     diff_raw,
                           'diff_raw_abs': diff_raw_abs,
                          f'diff_{label}':     diff_corr,
                          f'diff_{label}_abs': diff_corr_abs})
    
    indicators = { 'diff_raw_mean': diff_raw_mean,
                   'diff_raw_std':  diff_raw_std,
                   'rmse_raw':      rmse_raw,                
                   f'diff_{label}_mean': diff_corr_mean,
                   f'diff_{label}_std':  diff_corr_std,
                   f'rmse_{label}':      rmse_corr}
    
    for key,val in indicators.items():
        output[key] = val

    return diffs, output
#%% 

debiaser_ls  = generate_debiaser(data_bias['t2m_urse'], data_bias['t2m_cerra'], method = 'LinearScaling')
debiaser_qmR = generate_debiaser(data_bias['t2m_urse'], data_bias['t2m_cerra'], method = 'QuantileMappingReplace')
debiaser_qmD = generate_debiaser(data_bias['t2m_urse'], data_bias['t2m_cerra'], method = 'QuantileMappingDelta')

data_val['t2m_ls'] = data_val['t2m_cerra'].apply(debiaser_ls)
data_val['t2m_qmR'] = data_val['t2m_cerra'].apply(debiaser_qmR)
data_val['t2m_qmD'] = data_val['t2m_cerra'].apply(lambda x: debiaser_qmD(x,data_val['t2m_cerra']))

# cerra_data['t2m_ls'] = cerra_data['2m_temperature'].apply(debiaser_ls)
# cerra_data['t2m_qmR'] = cerra_data['2m_temperature'].apply(debiaser_qmR)
# cerra_data['t2m_qmD'] = cerra_data['2m_temperature'].apply(lambda x: debiaser_qmD(x, cerra_data['2m_temperature']))

#%%
 
debias_indicators = dict()

diffs_ls,  debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_ls',  label = 'ls',  output = debias_indicators)
diffs_qmR, debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_qmR', label = 'qmR', output = debias_indicators)
diffs_qmD, debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_qmD', label = 'qmD', output = debias_indicators)

print(debias_indicators)

#%%
debias_indicators_h = dict()

diffs_ls,  debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_ls',  label = 'ls',  output = debias_indicators)
diffs_qmR, debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_qmR', label = 'qmR', output = debias_indicators)
diffs_qmD, debias_indicators = evaluate_debias_(data_val, 't2m_urse', 't2m_cerra', 't2m_qmD', label = 'qmD', output = debias_indicators)

print(debias_indicators)
#%%

stat_val = statistics(data_val,['t2m_urse','t2m_cerra','t2m_ls','t2m_qmR','t2m_qmD'])

#%% 

print('raw',debias_indicators['rmse_raw'])
print('ls ', debias_indicators['rmse_ls'])
print('qmR',debias_indicators['rmse_qmR'])
print('qmD',debias_indicators['rmse_qmD'])

#%% 

cols   = ['t2m_cerra','t2m_ls','t2m_qmR','t2m_qmD']
colors = ['blue','orange','pink','purple']

fig, ax = plt.subplots(4,1,figsize = [10,15])


for i in range(4):
    data_val.plot(ax=ax[i], x = 'time', y = 't2m_urse', color = 'grey', ls=':')
    data_val.plot(ax=ax[i], x = 'time', y = cols[i], color = colors[i], ls='-')
    ax[i].axhline(y = stat_val['t2m_urse_mean'],   color = 'grey', ls = '--')
    ax[i].axhline(y = stat_val[f'{cols[i]}_mean'], color = colors[i], ls='--')
    ax[i].set_xlim(['2015-07-01','2017-02-01'])
    ax[i].set_ylim([-20,+30])
    ax[i].set_title('')
    ax[i].legend(loc = 'upper right')
    
for i in range(3):    
    ax[i].set_xlabel('')
    ax[i].set_xticklabels('')

plt.show()

#%% 

cols   = ['t2m_cerra','t2m_ls','t2m_qmR','t2m_qmD']
cols_   = ['2m_temperature','t2m_ls','t2m_qmR','t2m_qmD']
colors = ['blue','orange','pink','purple']
bins = list(range(-20,25))

fig, ax = plt.subplots()

for i in range(4):
    ax.hist(data_val['t2m_urse'], bins = bins, color = 'grey', ls=':', density = True, cumulative = True, histtype = 'step')
    ax.hist(data_val[cols[i]], bins = bins, color = colors[i], ls='-', density = True, cumulative = True, histtype = 'step')
    ax.hist(cerra_data[cols_[i]], bins = bins, color = colors[i], ls='--', density = True, cumulative = True, histtype = 'step')

ax.set_title('')
ax.legend(loc = 'upper right')
    
# for i in range(3):    
#     ax[i].set_xlabel('')
#     ax[i].set_xticklabels('')

plt.show()
#%%
cols   = ['t2m_cerra','t2m_ls','t2m_qmR','t2m_qmD']
colors = ['blue','orange','red','purple']


fig, ax = plt.subplots()

diffs_ls.plot(ax=ax,  x = 'time', y = ['diff_raw_abs','diff_ls_abs'], color = ['blue','orange'], ls='-',marker = '.')
diffs_qmR.plot(ax=ax, x = 'time', y = ['diff_qmR_abs'], color = ['red'], ls='-',marker = '.')
diffs_qmD.plot(ax=ax, x = 'time', y = ['diff_qmD_abs'], color = ['purple'], ls='-',marker = '.')

ax.set_xlim(['2015-06-01','2020-01-01'])
ax.set_title('')

plt.show()

# for i in range(4):
#     data_val.plot(ax=ax[i], x = 'time', y = 't2m_urse', color = 'grey', ls=':')
#     data_val.plot(ax=ax[i], x = 'time', y = cols[i], color = colors[i], ls='-')
#     ax[i].axhline(y = stat_val['t2m_urse_mean'],   color = 'grey', ls = '--')
#     ax[i].axhline(y = stat_val[f'{cols[i]}_mean'], color = colors[i], ls='--')
#     ax[i].set_xlim(['2015-07-01','2017-02-01'])
#     ax[i].set_ylim([-20,+30])
#     ax[i].set_title('')
#     ax[i].legend(loc = 'upper right')
    
# for i in range(3):    
#     ax[i].set_xlabel('')
#     ax[i].set_xticklabels('')

plt.show()


#%%

# # fig, ax = plt.subplots()

# # ax.plot(data_val['time'], diffs['diff_raw'], color = 'r', ls='',marker = '.', label = 'diff cerra')
# # ax.axhline(y = diffs['diff_raw_mean'], color = 'r', ls = ':', label = 'mean cerra')


# # ax.plot(data_val['time'], diffs['diff_corr'], color = 'b', ls='',marker = '.', label = 'diff corr')
# # ax.axhline(y = diffs['diff_raw_mean'], color = 'b', ls = ':', label = 'mean corr')

# # # ax.set_xlim([list(station_data['time'])[0],list(station_data['time'])[30*18*24]])
# # # ax.set_title('full time serie')

# # plt.show()

# #%%
# stat_val = statistics(data_val, ['t2m_urse','t2m_cerra', 't2m_corr'])

# # fig, ax = plt.subplots()

# # data_val.plot(ax=ax, x = 'time', y = ['t2m_urse','t2m_cerra','t2m_corr'],color = ['blue','orange','green'], ls='',marker = '+')
# # ax.axhline(y = stat_val['t2m_urse_mean'], color = 'blue', ls = ':', label = 'mean urse')
# # ax.axhline(y = stat_val['t2m_cerra_mean'], color = 'orange', ls = ':', label = 'mean cerra')
# # ax.axhline(y = stat_val['t2m_corr_mean'], color = 'green', ls = ':', label = 'mean corr')

# # ax.set_xlim(['2015-06-01','2020-01-01'])
# # ax.set_title('')

# # plt.show()


# #%% 


# t2m_urse = data_val.loc[:,'t2m_urse']
# t2m_cerra = data_val.loc[:,'t2m_cerra']
# t2m_corr = data_val.loc[:,'t2m_corr']

# # deltaT = 2
# # bins = np.array(list(range(-25,+31,deltaT)))
# # bins_ = bins + 1 

# # normal_urse  = 1/(t2m_urse.std() * np.sqrt(2 * np.pi)) * np.exp( - (bins_ + deltaT/2 - t2m_urse.mean())**2 / (2 * t2m_urse.std()**2))
# # normal_cerra = 1/(t2m_cerra.std() * np.sqrt(2 * np.pi)) * np.exp( - (bins_ + deltaT/2 - t2m_cerra.mean())**2 / (2 * t2m_cerra.std()**2))
# # normal_corr  = 1/(t2m_corr.std() * np.sqrt(2 * np.pi)) * np.exp( - (bins_ + deltaT/2 - t2m_corr.mean())**2 / (2 * t2m_corr.std()**2))

# # plt.hist(t2m_urse, bins=bins, density = True, color = 'b', histtype='step', label = 'station',cumulative = True)  
# # plt.plot(bins_, normal_urse, color='b', ls = ':')

# # plt.hist(t2m_cerra, bins=bins, density = True,color = 'orange', histtype='step', label = 'cerra',cumulative = True)  
# # plt.plot(bins_, normal_cerra, color='orange', ls = ':')

# # plt.hist(t2m_corr, bins=bins, density = True,color = 'green', histtype='step', label = 'corr',cumulative = True)  
# # plt.plot(bins_, normal_corr, color='green', ls = ':')

# # plt.title("Distribution temperature")
# # plt.legend()

# # # plt.yscale('log')

# # plt.show()



# # hist, bin_edges = np.histogram(a, density=True)


# #%%

# import numpy as np
# from scipy.stats import percentileofscore

# def eQM_replace(ref_dataset, model_present, model_future):
#         """
#         For each model_future value, get its percentile on the CDF of model_present,
#         then ust it to get a value from the model_present.
#         returns: downscaled model_present and model_future        
#         """
#         model_present_corrected = np.zeros(model_present.size)  
#         model_future_corrected = np.zeros(model_future.size)

#         for ival, model_value in enumerate(model_present):
#             percentile = percentileofscore(model_present, model_value)
#             model_present_corrected[ival] = np.percentile(ref_dataset, percentile)

#         for ival, model_value in enumerate(model_future):
#             percentile = percentileofscore(model_present, model_value)
#             model_future_corrected[ival] = np.percentile(ref_dataset, percentile)
            
#         return model_present_corrected, model_future_corrected
    
    
# def eQM_delta(ref_dataset, model_present, model_future):
#         """
#         Remove the biases for each quantile value taking the difference between 
#         ref_dataset and model_present at each percentile as a kind of systematic bias (delta)
#         and add them to model_future at the same percentile.

#         returns: downscaled model_present and model_future        
#         """
   
#         model_present_corrected = np.zeros(model_present.size)  
#         model_future_corrected = np.zeros(model_future.size)

#         for ival, model_value in enumerate(model_present):
#             percentile = percentileofscore(model_present, model_value)
#             model_present_corrected[ival] = np.percentile(ref_dataset, percentile)

#         for ival, model_value in enumerate(model_future):
#             percentile = percentileofscore(model_future, model_value)
#             model_future_corrected[ival] = model_value + np.percentile(
#                 ref_dataset, percentile) - np.percentile(model_present, percentile)
        
#         return model_present_corrected, model_future_corrected
    
# #%%
# t2m_urse = data_val.loc[:,'t2m_urse']
# t2m_cerra = data_val.loc[:,'t2m_cerra']
# t2m_corr = data_val.loc[:,'t2m_corr']

# # percentile = percentileofscore(t2m_cerra, t2m_cerra[1])
# # print(percentile)
# # print(t2m_cerra[1],np.percentile(t2m_urse, percentile))


# data_ref = t2m_urse
# data_mes = t2m_cerra
# debiaser = (lambda x: np.percentile(data_ref, percentileofscore(data_mes,x)))

# data_val['t2m_qm'] = data_val['t2m_cerra'].apply(debiaser)

# #%% 
# stat_val = statistics(data_val, ['t2m_urse','t2m_cerra', 't2m_corr','t2m_qm'])

# # fig, ax = plt.subplots()

# # data_val.plot(ax=ax, x = 'time', y = ['t2m_urse','t2m_cerra','t2m_corr','t2m_qm'],color = ['blue','orange','green','purple'], ls='',marker = '+')
# # ax.axhline(y = stat_val['t2m_urse_mean'], color = 'blue', ls = ':', label = 'mean urse')
# # ax.axhline(y = stat_val['t2m_cerra_mean'], color = 'orange', ls = ':', label = 'mean cerra')
# # # ax.axhline(y = stat_val['t2m_corr_mean'], color = 'green', ls = ':', label = 'mean corr')
# # ax.axhline(y = stat_val['t2m_qm_mean'], color = 'purple', ls = ':', label = 'mean qm')

# # ax.set_xlim(['2015-06-01','2020-01-01'])
# # ax.set_title('')

# # plt.show()
# #%% 
# # stat_val = statistics(data_val, ['t2m_urse','t2m_cerra', 't2m_corr','t2m_qm'])

# # fig, ax = plt.subplots()

# # data_val.plot(ax=ax, x = 'time', y = ['t2m_urse','t2m_cerra','t2m_corr','t2m_qm'],color = ['blue','orange','green','purple'], ls='-')
# # ax.axhline(y = stat_val['t2m_urse_mean'], color = 'blue', ls = ':', label = 'mean urse')
# # ax.axhline(y = stat_val['t2m_cerra_mean'], color = 'orange', ls = ':', label = 'mean cerra')
# # # ax.axhline(y = stat_val['t2m_corr_mean'], color = 'green', ls = ':', label = 'mean corr')
# # ax.axhline(y = stat_val['t2m_qm_mean'], color = 'purple', ls = ':', label = 'mean qm')

# # ax.set_xlim(['2015-06-01','2016-01-01'])
# # ax.set_title('')

# # plt.show()

# #%%
# diffs_corr = evaluate_debias(data_val['t2m_urse'], data_val['t2m_cerra'], data_val['t2m_corr'])
# diffs_qm = evaluate_debias(data_val['t2m_urse'], data_val['t2m_cerra'], data_val['t2m_qm'])

# # fig, ax = plt.subplots()

# # ax.plot(data_val['time'], diffs_corr['diff_raw_abs'], color = 'r', ls='',marker = '.', label = 'diff cerra')
# # ax.axhline(y = diffs_corr['diff_raw_mean'], color = 'r', ls = ':', label = 'mean cerra')


# # ax.plot(data_val['time'], diffs_corr['diff_corr_abs'], color = 'b', ls='',marker = '.', label = 'diff corr')
# # ax.axhline(y = diffs_corr['diff_corr_mean'], color = 'b', ls = ':', label = 'mean corr')

# # ax.plot(data_val['time'], diffs_qm['diff_corr_abs'], color = 'g', ls='',marker = '.', label = 'diff qm')
# # ax.axhline(y = diffs_qm['diff_corr_mean'], color = 'g', ls = ':', label = 'mean qm')

# # # ax.set_xlim([list(station_data['time'])[0],list(station_data['time'])[30*18*24]])
# # # ax.set_title('full time serie')

# # plt.show()
# #%%
# print('raw',diffs_corr['rmse_raw'])
# print('ls',diffs_corr['rmse_corr'])
# print('qm',diffs_qm['rmse_corr'])

# # # Compute annual cumulated corrected precipitation
# # annual_cumulated_precip = data.groupby('Year')['CRain'].sum()

# # # Compute interannual mean corrected precipitation
# # interannual_mean_precip = annual_cumulated_precip.mean()

# # # Compute interannual mean air temperature
# # interannual_mean_temp = data.groupby('Year')['T'].mean().mean()

# # # Display results
# # print("Annual Cumulated Corrected Precipitation (mm):")
# # print(annual_cumulated_precip)
# # print("\nInterannual Mean Corrected Precipitation (mm):", interannual_mean_precip)
# # print("\nInterannual Mean Air Temperature (°C):", interannual_mean_temp)

# # # Plot annual corrected precipitation
# # plt.figure(figsize=(8, 6))
# # annual_cumulated_precip.plot(kind='bar', color='blue', alpha=0.8, edgecolor='black', label='Annual Cumulated Corrected Precipitation')
# # plt.axhline(interannual_mean_precip, color='red', linestyle='--', linewidth=2, label='Interannual Mean')
# # plt.title('Annual Cumulated Corrected Precipitation')
# # plt.xlabel('Year')
# # plt.ylabel('Corrected Precipitation (mm)')
# # plt.legend()
# # plt.tight_layout()
# # plt.show()

# # # Plot interannual mean air temperature
# # annual_mean_temp = data.groupby('Year')['T'].mean()
# # plt.figure(figsize=(8, 6))
# # annual_mean_temp.plot(kind='bar', color='orange', alpha=0.8, edgecolor='black', label='Annual Mean Air Temperature')
# # plt.axhline(interannual_mean_temp, color='green', linestyle='--', linewidth=2, label='Interannual Mean Temperature')
# # plt.title('Annual Mean Air Temperature')
# # plt.xlabel('Year')
# # plt.ylabel('Temperature (°C)')
# # plt.legend()
# # plt.tight_layout()
# # plt.show()

# # # Extract the date without time for daily aggregation
# # data['Day'] = data['Date'].dt.date

# # # Compute daily mean temperature and daily cumulated precipitation
# # daily_data = data.groupby('Day').agg({'T': 'mean', 'CRain': 'sum'}).reset_index()

# # # Plot daily mean temperature and daily cumulated precipitation
# # fig, axs = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

# # # Daily mean temperature subplot
# # axs[0].plot(daily_data['Day'], daily_data['T'], color='orange', label='Daily Mean Temperature')
# # axs[0].set_title('Daily Mean Temperature')
# # axs[0].set_ylabel('Temperature (°C)')
# # axs[0].legend()
# # axs[0].grid()

# # # Daily cumulated precipitation subplot
# # axs[1].bar(daily_data['Day'], daily_data['CRain'], color='blue', alpha=0.7, label='Daily Cumulated Precipitation')
# # axs[1].set_title('Daily Cumulated Precipitation')
# # axs[1].set_xlabel('Date')
# # axs[1].set_ylabel('Precipitation (mm)')
# # axs[1].legend()
# # axs[1].grid()

# # # Tight layout for better spacing
# # plt.tight_layout()

# # # Show the plots
# # plt.show()
