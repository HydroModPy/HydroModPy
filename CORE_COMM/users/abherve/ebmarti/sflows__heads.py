# -*- coding: utf-8 -*-
"""
Created on Mon May  2 10:40:28 2022

@author: emarti
"""

import os
import numpy as np
import flopy
import flopy.modflow as fpm
import flopy.utils.binaryfile as bf
import flopy.utils.postprocessing as pp
#%%Define model parameters


defKR = np.logspace(-2,2,25)

k= 1e-7 * 86400 # m/s en m/j
#BV.hydrodynamic.update_hyd_cond(k) 
#recharge = 1e-7  #m/j
#BV.forcing.update_recharge(recharge, 'steady')
#defKR = np.logspace(-1,2,4)
#recharge = 1e-4 
thickness = 500
deflaynb = [10]
defbc = [1825]
elapsed = []
box=True
bottom=-1000


#%%Retrive data for surface flows and head (working even with dry first layer for steady state model) and save to txt file

for lay_nb in deflaynb:
    for bc_left in defbc:
        for KR in defKR:   
            KR_name = round(KR,3)
            modeldir = 'D:/emarti/Tarapaca/out/final/Tarapaca/results_simulations/KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb)+ '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom) +'/'

            print('Performing simulation for model : KR = ' +str(KR_name)+' layer_nb='+str(lay_nb)+' bc='+str(bc_left))
            namepath      = 'KR_' + str(KR_name) + '_layers_nb_' + str(lay_nb) + '_bchead_'+str(bc_left)+'m_bottom_' + str(bottom)
            print('________________________')
            print('Retrieving properties   ')
            print('________________________')
            m             = fpm.Modflow()
            mymodel       = m.load(modeldir+namepath+'.nam', version='mf2005', exe_name='mf2005.exe', verbose=False, model_ws=modeldir, load_only=None, forgive=True, check=True)
            mybas         = mymodel.get_package('BAS6')
            mydis         = mymodel.get_package('DIS')

            ncol          = np.unique(mydis.ncol)[0]
            nrow          = np.unique(mydis.nrow)[0]
            nlay          = np.unique(mydis.nlay)[0]
            dcol          = np.unique(mydis.delc)[0]
            drow          = np.unique(mydis.delr)[0]
            hds = bf.HeadFile(modeldir+namepath+ ".hds")
            head = hds.get_data(totim=1.0)
            recharge = round(k / KR_name, 7)
            print('Number of layers:          ', nlay)
            print('Number of rows (North):    ', nrow)
            print('Number of cols (East):     ', ncol)
            print('Mesh size - rows (North):  ', drow)
            print('Mesh size - cols (East):   ', dcol)
            print('')
            print('________________________')
            print('Retrieving surface flows')
            print('________________________')
            period        = 0
            step          = 0
            Qx, Qy, Qz_rech  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, kstpkper=(step, period), totim=None,boundary_ifaces={'RECHARGE': 6}, hdsfile=modeldir+namepath+'.hds', model=mymodel)
            Qx_2, Qy_2, Qz_drain  = pp.get_extended_budget(modeldir+namepath+'.cbc', precision='single', idx=None, kstpkper=(step, period), totim=None,boundary_ifaces={'DRAINS': 6}, hdsfile=modeldir+namepath+'.hds', model=mymodel)
            rech_loop = np.zeros([nrow,ncol])
            for i in range(0,nrow):
                for j in range (0,ncol):
                    if Qz_rech[0,i,j] == 0:
                        rech_loop[i,j] =-recharge*dcol*drow
                    else:
                        rech_loop[i,j] =Qz_rech[0,i,j]
                        
            rech = -rech_loop
            rech[-1,:] = 0
            rech[:,-1] = 0
            rech[:,0] = 0
            drain = Qz_drain[0,:,:]
            sflux = rech - drain
            sflux[sflux > rech] = rech.max()
            sflows = sflux/drow/dcol
            print(sflows)
            
            print('')
            print('________________________')
            print('Retrieving head values')
            print('________________________')
            
            
            head_final = np.zeros([nrow,ncol])
            for i in range(0,nrow):
                for j in range (0,ncol):
                    for l in range(0,nlay): 
                        if head[l,i,j] > 0:
                            head_final[i,j] =head[l,i,j]
                            break     
            
            print(head_final)
            
            print('')
            print('________________________')
            print('Saving surface flows and heads to txt file')
            print('________________________')
            
            if os.path.exists(modeldir+'surface_fluxes.txt'):
                os.remove(modeldir+'surface_fluxes.txt')
            if os.path.exists(modeldir+'surface_flows.txt'):
                os.remove(modeldir+'surface_flows.txt')
            if os.path.exists(modeldir+'heads.txt'):
                os.remove(modeldir+'heads.txt')
            
            f1 = open(modeldir+"surface_fluxes.txt", 'w+')
            f1.writelines("colJ rowI flux\n")
            for i in range(0,nrow):
                for j in range(0,ncol):
                    f1.writelines("%s\t" % int(j))
                    f1.writelines("%s\t" % int(i))
                    f1.writelines("%s\n" % sflux[i,j])
            print('Surface fluxes saved in file', modeldir+"surface_fluxes.txt")
            f1.close()
            
            f2= open(modeldir+"surface_flows.txt", 'w+')
            f2.writelines("colJ rowI flow\n")
            for i in range(0,nrow):
                for j in range(0,ncol):
                    f2.writelines("%s\t" % int(j))
                    f2.writelines("%s\t" % int(i))
                    f2.writelines("%s\n" % sflows[i,j])
            print('Surface flows saved in file', modeldir+"surface_flows.txt")
            f2.close()
            
            f3= open(modeldir+"heads.txt", 'w+')
            f3.writelines("colJ rowI head_height\n")
            for i in range(0,nrow):
                for j in range(0,ncol):
                    f3.writelines("%s\t" % int(j))
                    f3.writelines("%s\t" % int(i))
                    f3.writelines("%s\n" % head_final[i,j])
            print('Heads saved in file', modeldir+"heads.txt")
            f3.close()


