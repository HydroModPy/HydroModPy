# -*- coding: utf-8 -*-
"""
Created on Fri Jul  5 08:54:34 2024

@author: roquesc
"""

import numpy as np

#%% gr4j model

"""
    MODEL PARAMETERS
        X1: Production reservoir capacity [ mm]
        X2 : Underground exchange coefficient
        X3 : Routing reservoirervoir capacity [ mm ] # % X4 : Base flow time [ mm
        X4 : Base time of HU1 unit hydrograph [ day ] # % X5 : Separation temperature [ mm
        X5 : Rain/snow separation temperature
        X6 : Melting temperature
        X7 : Melt factor HBV
        S0: initial filling of the production reservoir
        R0 : Initial filling of the routing reservoir
    
    MODEL INPUT: time series in the form of a dataframe
    input.p : precipitation [ mm.d-1 ]
    input.etp : potential evapotranspiration [ mm.d-1 ]
    input.t : temperature [ °C ] # % input.type : type of soil [ °C 
    input.type : type of output
        'discharge' : discharge
        'storage' : storage
        'dischargestorage' : discharge + storage with input.ratio as ratio
    input.transform : transformation 
        '' : normal
        'sqrt' : squareroot of flow rate
        'log10' : log10 of flow rate
        '1./' : inverse of output
    input.ratio: ratio on storage/discharge for calibration
    
    MODEL OUTPUT PARAMETERS
    output_main : output_main in the form requested in input.transform
    
    output : All model output stored as a dataframe
    output.r : routing storage
    output.s : production storage
    output.Qsim : discharge (untransformed)
    output.gain : Interbasin groundwater flow
    output.etr : actual ET
    output.Ssim : storage (untransformed)
    output.n : snow store
    output.nf : snowmelt
"""

    
    
def gr4j_cal(par, input):
    X1 = par[0]
    X2 = par[1]
    X3 = par[2]
    X4 = par[3]
    X5 = par[4]
    X6 = par[5]
    X7 = par[7]
    s = [par[7]]
    r = [par[8]]
    n = [0]
    
    P = input['p']
    ETP = input['etp']
    T = input['t']
    
    
    if 'indices' not in input:
        input['indices'] = np.arange(len(P))
 
    ntemp = len(ETP)
    output = {
        'Qsim': np.full(ntemp, np.nan),
        'Ssim': np.full(ntemp, np.nan),
        'gain': np.full(ntemp, np.nan),  # Initialize 'gain' regardless of input['type']
        'perc': np.full(ntemp, np.nan),
        'pr': np.full(ntemp, np.nan)
    }
    
    if input['type'] in ['storage', 'dischargestorage']:
        output.update({
            'r': np.full(ntemp, np.nan),
            's': np.full(ntemp, np.nan),
            'etr': np.full(ntemp, np.nan),
            'n': np.full(ntemp, np.nan),
            'nf': np.full(ntemp, np.nan),
        })
    
    jour = np.arange(1, 2 * np.ceil(X4) + 2)
    SS1 = np.ones(int(np.ceil(len(jour) / 2)))
    SS2 = np.ones(len(jour))
    
    for ij in range(len(jour) * 2):
        if jour[ij] < X4:
            SS1[ij] = (jour[ij] / X4) ** 2.5
            SS2[ij] = 0.5 * (jour[ij] / X4) ** 2.5
        elif jour[ij] < 2 * X4:
            SS2[ij] = 1 - 0.5 * (2 - jour[ij] / X4) ** 2.5
        else:
            break
    
    HU1 = np.diff(np.concatenate([[SS1[0]], SS1]))
    HU2 = np.diff(np.concatenate([[SS2[0]], SS2]))
    v = np.zeros((len(HU1), 2))
    w = np.zeros((len(HU2), 2))
    
    for ij in range(ntemp):
        Pn = 0
        if P[ij] >= ETP[ij]:
            Pn = P[ij] - ETP[ij]
            En = 0
        else:
            En = ETP[ij] - P[ij]
        
        Nn = 0
        Fonte = 0
        if T[ij] < X5:
            Nn = Pn
            Pn = 0
        ntemporaire = n[ij] + Nn
        nf = 0
        if T[ij] > X6:
            nf = min(ntemporaire, X7 * (T[ij] - X6))
        n.append(ntemporaire - nf)
        Pn += nf
        
        Ps = 0
        if Pn > 0:
            Ps = X1 * (1 - s[ij] ** 2) * np.tanh(Pn / X1) / (1 + s[ij] * np.tanh(Pn / X1))
        Es = 0
        if En > 0:
            Es = s[ij] * X1 * (2 - s[ij]) * np.tanh(En / X1) / (1 + (1 - s[ij]) * np.tanh(En / X1))
        s.append(s[ij] + (Ps - Es) / X1)
        
        Perc = s[ij] * X1 * (1 - (1 + (4 / 9 * s[ij]) ** 4) ** (-0.25))
        s[-1] -= Perc / X1
        Pr = Perc + (Pn - Ps)
        
        v[:, 1] = v[:, 0]
        for pq in range(len(HU1) - 1):
            v[pq, 0] = v[pq + 1, 1] + Pr * 0.9 * HU1[pq]
        
        w[:, 1] = w[:, 0]
        for pq in range(len(HU2) - 1):
            w[pq, 0] = w[pq + 1, 1] + Pr * 0.1 * HU2[pq]
        
        F = X2 * (r[ij]) ** 3.5
        r[ij] = max(0, r[ij] + (F + v[0, 0]) / X3)
        Qr = r[ij] * X3 * (1 - (1 + (r[ij] ** 4)) ** (-0.25))
        r.append(r[ij] - Qr / X3)
        r[-1] = max(0, r[-1])
        Qd = max(0, w[0, 0] + F)
        
        output['perc'][ij] = Perc
        output['pr'][ij] = Pr
        output['Qsim'][ij] = Qr + Qd
        
        if input['type'] in ['storage', 'dischargestorage']:
            if X2 > 0:
                output['gain'][ij] = 2 * F
            else:
                output['gain'][ij] = -min([abs(F), r[ij] * X3]) - min([abs(F), w[0, 0]])
        
        if ij == 0:
            output['Ssim'][0] = Pn - Es + output['gain'][0] - output['Ssim'][0]
        else:
            output['Ssim'][ij] = output['Ssim'][ij - 1] + Pn - Es + output['gain'][ij] - output['Qsim'][ij]
        
        if input['type'] in ['storage', 'dischargestorage']:
            output['etr'][ij] = max([0, P[ij] - Pn + Es])
            output['qe'][ij] = max(0, w[0, 0])
            output['qe2'][ij] = Pn - Ps
    
    output['Ssim'] -= np.mean(output['Ssim'])
    
    if input['type'] == 'discharge':
        output_main = output['Qsim']
    elif input['type'] == 'storage':
        output_main = output['Ssim']
    elif input['type'] == 'dischargestorage':
        output_main = np.concatenate([output['Qsim'], output['Ssim'] * input['ratio']])
    
    if 'transform' in input and input['transform'] != '':
        if input['transform'] == 'sqrt':
            output_main = np.sqrt(output_main[input['indices']])
        elif input['transform'] == 'log10':
            output_main = np.log10(output_main[input['indices']])
        elif input['transform'] == '1./':
            output_main = 1. / output_main[input['indices']]
        else:
            output_main = output_main[input['indices']]
    else:
        output_main = output_main[input['indices']]
    

    output['s'] = X1 * np.array(s[:-1])
    output['r'] = X3 * np.array(r[:-1])
    output['n'] = np.array(n[:-1])
    
    return output_main, output