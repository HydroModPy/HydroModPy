# -*- coding: utf-8 -*-
"""
Created on Thu Jul 21 11:04:09 2022

@author: ronan
"""

first_index = 'source la plus en amont de la rivière, point 0'
flat_flux == 'le fichier csv envoyé'

for i in flat_flux.index:
    if i == first_index:
        print(i)
        flat_flux.loc[i,'Csr_riv'] = ( (0.02*flat_flux.loc[i,'Qriv'])+
                                       (1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       flat_flux.loc[i,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
                                       )
    else:
        flat_flux.loc[i,'Csr_riv'] = ( (flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+
                                       (1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       flat_flux.loc[i-1,'Qriv'] + flat_flux.loc[i,'Qdeep'] + flat_flux.loc[i,'Qshal']
                                       )

for i in flat_flux.index:
    if i == first_index:
        print(i)
        flat_flux.loc[i,'Rsr_riv'] = ( (0.7092*flat_flux.loc[i,'Csr_riv']*flat_flux.loc[i,'Qriv'])+
                                       (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.7092*0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       (flat_flux.loc[i,'Qriv']*flat_flux.loc[i,'Csr_riv']) +
                                       (flat_flux.loc[i,'Qdeep']*1.1)+
                                       (flat_flux.loc[i,'Qshal']*0.02)
                                       )
                    
    else:
        flat_flux.loc[i,'Rsr_riv'] = ( (flat_flux.loc[i-1,'Rsr_riv']*flat_flux.loc[i-1,'Csr_riv']*flat_flux.loc[i-1,'Qriv'])+
                                       (0.7041*1.1*flat_flux.loc[i,'Qdeep'])+
                                       (0.7092*0.02*flat_flux.loc[i,'Qshal']) ) / (
                                       (flat_flux.loc[i-1,'Qriv']*flat_flux.loc[i-1,'Csr_riv']) +
                                       (flat_flux.loc[i,'Qdeep']*1.1)+
                                       (flat_flux.loc[i,'Qshal']*0.02)
                                       )                             