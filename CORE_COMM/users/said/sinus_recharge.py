# -*- coding: utf-8 -*-
"""
Created on Tue Jun 20 12:48:49 2023

@author: ronan
"""

#%% LIBRAIRIES

import pandas as pd
import numpy as np
import os
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

#%% INITIAL RECHARGE

file = pd.read_csv("C:/Users/ronan/Documents/SIMULATIONS/LASSET/Pyrennees/results_stable/drias/_ALL_D.csv",
                   sep=';', parse_dates=True, index_col=0)
serie = file['REC_ECE-RCA_RCP8.5'] # mm/day

fig, ax = plt.subplots(1,1, figsize=(5,3), dpi=300)
ax.plot(serie, lw=1, c='k')
ax.set_yscale('log')

#%% FUNCTIONS

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

def sinusoid_recharge(serie, period, amplitude, offset, omega, phase):
    """
    SYnthetic Sinusiodal recharge 
    Parameters
    ----------
    serie : panda matrix
        input recharge
    period : string
        D (day) or M (month)
    amplitude : float
        modifies the amplitude (max-min) of the sinusoid
    offset : float
        modifies the mean of the sinusoid
    omega : float
        modifies the sinusoid frequency
    phase : float
        modifies the phase of the sinusoid
    """
    def sinusoid(x, A , offset, omega, phase):
        return A*np.sin(omega*x+phase) + offset
    def get_p0(Y, T):
        A0 = (max(Y[0:T]) - min(Y[0:T]))/2
        offset0 = Y[0]
        phase0 = 0
        omega0 = 2.*np.pi/T
        return [A0, offset0, omega0, phase0]
    if period=='D':
        T=365
    if period=='M':
        T=12
    date = serie.index
    serie = serie.reset_index(drop=True)
    X = serie.index
    Y = serie.values
    param, covariance = curve_fit(sinusoid, X, Y, p0=get_p0(Y, T))
    param[0] = param[0] * amplitude # Amplitude : max
    param[1] = param[1] * offset # Offset : shift v
    param[2] = param[2] * omega # Omega : cycles
    param[3] = param[3] * phase # Phase : shift h
    sinus = sinusoid(X, *param)
    recharge = pd.Series(data = sinus, index=date)
    recharge[recharge < 0] = 0
    return recharge

def synthetic_recharge(rech, shape, years, start_date="2020-08", freq=None, dis='normal'):
    """
    Generate synthetic recharge (inverse Gaussian, normal, uniform)
    Parameters
    ----------
        rech : float
            Mean recharge distribution (or first parameter of the distribution)
        shape: float
            Std of the recharge distribution (or second parameter of the distribution)
        dis: string
            inverse-gaussian 
            normal
            uniform
        start_date: string
            year-month
        years: float
            durateion in years over wich recharge should be generated
        freq: string
            freqency of the rechrage
            D: dayly
            M: monthly
            Y: yearly
    """
    freq = freq
    days = years*365
    date = pd.date_range(start_date, periods=days)
    t = np.linspace(1,365,365)
    time = []
    for y in range(0,years):
        time = np.concatenate((time,t))
    mean = 180
    if dis == 'inverse-gaussian':
        pdf = (((mean*shape)/(2*np.pi*time**3))**0.5*np.exp(-(shape*(time-mean)**2)/(2*mean*time)))*rech
    if dis == 'normal':
        pdf = ((1/(shape*np.sqrt(2*np.pi)))*np.exp(-((time-mean)**2/(2*shape**2))))*rech
    if dis == 'uniform':
        pdf = np.zeros(len(time)) 
        pdf[(time >= (mean-(shape/2))) & (time < ((shape/2)+mean))] = rech/shape
    recharge = pd.Series(data = pdf, index=date)
    if freq != None:
        recharge = recharge.resample(freq).mean()
    return recharge

#%% SINUSOIDAL RECHARGE

serie = select_period(serie, 2050, 2099)

period = 'D'
amplitude = 1
offset = 1
omega = 1
phase = 1
norm = sinusoid_recharge(serie, period, amplitude, offset, omega, phase)
norm = norm.groupby([lambda x: norm.index.month]).mean()
sce_norm = pd.concat([norm, norm, norm, norm, norm, norm, norm, norm, norm, norm], ignore_index=True)

period = 'D'
amplitude = 1
offset = 0.5
omega = 1
phase = 1
dry = sinusoid_recharge(serie, period, amplitude, offset, omega, phase)
dry = dry.groupby([lambda x: dry.index.month]).mean()
sce_dry1 = pd.concat([norm, dry, norm, dry, norm, dry, norm, dry, norm, dry], ignore_index=True)

period = 'D'
amplitude = 1
offset = 0.5
omega = 1
phase = 1
dry = sinusoid_recharge(serie, period, amplitude, offset, omega, phase)
dry = dry.groupby([lambda x: dry.index.month]).mean()
sce_dry2 = pd.concat([norm, dry, dry, norm, dry, dry, norm, dry, dry], ignore_index=True)

fig, ax = plt.subplots(1,1, figsize=(5,3), dpi=300)
ax.plot(sce_norm, lw=1, c='dodgerblue')
ax.plot(sce_dry1, lw=1, c='darkorange')
ax.plot(sce_dry2, lw=1, c='darkred')

#%% SYNTHETIC RECHARGE

serie = select_period(serie, 2050, 2099)
rech = serie.mean() * 365
print(rech)

shape = 24
years = 5
start_date = "2050-01"
freq = 'D' # None
dis = 'normal' # 'inverse-gaussian', 'uniform', 'normal'
dis = 'inverse-gaussian'
dis = 'uniform'
r = synthetic_recharge(rech, shape, years, start_date=start_date, freq=freq, dis=dis)

fig, ax = plt.subplots(1,1, figsize=(5,3), dpi=300)
ax.plot(r, lw=1, c='forestgreen')
print(r.resample('Y').sum())

#%% NOTES

