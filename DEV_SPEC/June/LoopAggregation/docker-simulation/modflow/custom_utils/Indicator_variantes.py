def computeFloodsAndHErrorFromModelnamesByInterpolationWithoutSeaLvl(ref, modelname, site_number,timestep=1):
    
    
    site_name = getSiteNameFromSiteNumber(site_number)
    repoRef = getPathToSimulationDirectoryFromModelname(ref, site_name) 
    repoSimu = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    
    # Get values for topo
    topoRef = getSoilSurfaceValuesForASimulation(repoRef, ref)
    topoSimu = getSoilSurfaceValuesForASimulation(repoSimu, modelname)
    
    # Get heads values for simulation
    simuHds = fpu.HeadFile(repoSimu + '/' + modelname + '.hds')
    simuTimes = simuHds.get_times()
    #simuKstpkper = simuHds.get_kstpkper()
    refHds = fpu.HeadFile(repoRef + '/' + ref + '.hds')
    
    # Comput parameters
    startTime = 0
    endTime = 15340
    dc = 0.3
    alpha = float(1/3)

    #endTime+1 - startTime
    floods = {}
    # hErrorGlobal = 0
    smWs = 0
    sherrorsup = 0
    sea_lvl = getSeaLvl()


    #Pour chaque jour
    for day in range(startTime, endTime+1):
        print(day)
    
        # On récupère la matrice de simulation ref
        refHead = refHds.get_data(kstpkper=(0, day))

        nbPeriod = 0
        while (simuTimes[nbPeriod] < day+1) and (nbPeriod < len(simuTimes)):
            nbPeriod+=1
        print("nbPeriod : " + str(nbPeriod))
        #On récupère la matrice de simulation alt supérieure

        print(simuTimes[nbPeriod], day+1)
        if math.isclose(simuTimes[nbPeriod], day+1, rel_tol=1e-3): #simuTimes[nbPeriod] == day+1
            print("condition ==")
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))       
            altHeadInf = altHeadSup
            duree = int(simuTimes[nbPeriod])
            pas = 0
        else :
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))        
            altHeadInf = simuHds.get_data(kstpkper=(timestep-1, nbPeriod-1))
            duree = int(simuTimes[nbPeriod] - simuTimes[nbPeriod-1])
            pas = day - simuTimes[nbPeriod-1]

        nbrowtot = altHeadInf.shape[1]        
        nbcoltot = altHeadInf.shape[2]

        # onecol = [0]*nbcoltot
        # flood = [onecol]
        # for i in range(1, nbrowtot):  
        #     flood.append(onecol)
        flood = {}
        for nrow in range(nbrowtot):
            flood[nrow] = {}
            for ncol in range(nbcoltot):
                ss = getNonDryCellHdsValue(altHeadInf, nrow, ncol, altHeadInf.shape[0]) # Valeur de head
                se = getNonDryCellHdsValue(altHeadSup, nrow, ncol, altHeadInf.shape[0])
                ajoutSimu = (se - ss) / duree
                #print("ss:", ss)
                s = ss + (ajoutSimu * pas) # valeur head pour le jour considere
                if math.isclose(s, sea_lvl, rel_tol=1e-3):
                    print("Sea zone with watertable level : ", s, "sea_lvl :", sea_lvl)
                    continue

                d = topoSimu[nrow][ncol] - s # profondeur : altitude topo - altitude toit de la nappe
                
                if d <= dc:
                    flood[nrow][ncol] = 1
                    #print("Cas flood = 1", day)
                    print("row : ", nrow, "col: ", ncol)
                    print("topo: ", topoSimu[nrow][ncol], "s: ", s)
                    

                r= getNonDryCellHdsValue(refHead, nrow, ncol,refHead.shape[0]) # valeur de head pour reference
                
                WsRef = getWeightToSurface(topoRef[nrow][ncol], r, dc, alpha)
                WsSimu = getWeightToSurface(topoSimu[nrow][ncol], s, dc, alpha)

                mWs = max(WsRef, WsSimu)
                sherrorsup += (mWs * (r-s)**2)
                smWs += mWs 
        floods[day] = flood
    f = open(repoSimu + "/" + modelname + '_floods_pickle_dict_nosea.txt','wb')
    pickle.dump(floods, f)

    hErrorGlobal = math.sqrt(sherrorsup / smWs)
    
    with open(repoSimu + "/" + modelname + '_Ref_' + ref + '_errorsresult_H_nosea.csv', 'w') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['H Error'])
        writer.writerow([hErrorGlobal])
    print("h error : " + str(hErrorGlobal))
    
    return nbrowtot, nbcoltot

def computeOnlyFloodsFromModelnamesByInterpolation(ref, modelname, site_number,timestep=1):
    
    
    site_name = getSiteNameFromSiteNumber(site_number)
    #repoRef = getPathToSimulationDirectoryFromModelname(ref, site_name) 
    repoSimu = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    
    # Get values for topo
    #topoRef = getSoilSurfaceValuesForASimulation(repoRef, ref)
    topoSimu = getSoilSurfaceValuesForASimulation(repoSimu, modelname)
    
    # Get heads values for simulation
    simuHds = fpu.HeadFile(repoSimu + '/' + modelname + '.hds')
    simuTimes = simuHds.get_times()
    #simuKstpkper = simuHds.get_kstpkper()
    #refHds = fpu.HeadFile(repoRef + '/' + ref + '.hds')
    
    # Comput parameters
    startTime = 0
    endTime = 15340
    dc = 0.3


    #endTime+1 - startTime
    floods = {}
    # hErrorGlobal = 0

    #sea_lvl = getSeaLvl()


    #Pour chaque jour
    for day in range(startTime, endTime+1):
        print(day)
    
        # On récupère la matrice de simulation ref
        #refHead = refHds.get_data(kstpkper=(0, day))

        nbPeriod = 0
        while (simuTimes[nbPeriod] < day+1) and (nbPeriod < len(simuTimes)):
            nbPeriod+=1
        print("nbPeriod : " + str(nbPeriod))
        #On récupère la matrice de simulation alt supérieure
        if math.isclose(simuTimes[nbPeriod], day+1, rel_tol=1e-3): #simuTimes[nbPeriod] == day+1
            print("condition ==")
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))       
            altHeadInf = altHeadSup
            duree = int(simuTimes[nbPeriod])
            pas = 0
        else :
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))        
            altHeadInf = simuHds.get_data(kstpkper=(timestep-1, nbPeriod-1))
            duree = int(simuTimes[nbPeriod] - simuTimes[nbPeriod-1])
            pas = day - simuTimes[nbPeriod-1]

        nbrowtot = altHeadInf.shape[1]        
        nbcoltot = altHeadInf.shape[2]


        flood = {}
        for nrow in range(nbrowtot):
            flood[nrow] = {}
            for ncol in range(nbcoltot):
                ss = getNonDryCellHdsValue(altHeadInf, nrow, ncol, altHeadInf.shape[0]) # Valeur de head
                se = getNonDryCellHdsValue(altHeadSup, nrow, ncol, altHeadInf.shape[0])
                ajoutSimu = (se - ss) / duree
                s = ss + (ajoutSimu * pas) # valeur head pour le jour considere
                # if math.isclose(s, sea_lvl, rel_tol=1e-3):
                #     print("Sea zone with watertable level : ", s, "sea_lvl :", sea_lvl)
                #     continue

                d = topoSimu[nrow][ncol] - s # profondeur : altitude topo - altitude toit de la nappe
                
                if d <= dc:
                    flood[nrow][ncol] = 1
                    print("row : ", nrow, "col: ", ncol)
                    print("topo: ", topoSimu[nrow][ncol], "s: ", s)
                    
        floods[day] = flood
    f = open(repoSimu + "/" + modelname + '_floods_pickle_dict_nosea.txt','wb')
    pickle.dump(floods, f)   

    return nbrowtot, nbcoltot

def getWtAndTsAndTrForASimulationWithoutSeaLvl(modelname, site_number, tsmax, nbrow, nbcol):
    site_name = getSiteNameFromSiteNumber(int(site_number))
    repoSimu = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    file = open(repoSimu + '/' + modelname + "_floods_pickle_dict_nosea.txt", 'rb')
    floods = pickle.load(file)
    file.close()
    weights = {}
    ts = {}
    tr = {}
    for nrow in range(nbrow):
        weights[nrow] = {}
        ts[nrow] = {}
        tr[nrow] = {}
        for ncol in range(nbcol):
            fSimu = False
            sflood = []
            eflood = []
            fduration = 0

            ssaturation = []
            esaturation = []
            sduration = 0

            for day in sorted(floods): # Start at 1 because we did not take the init period into account
                #print(day)
                if (nrow in floods[day]) and (ncol in floods[day][nrow]) and (fSimu is False):
                    # Si on entre dans une periode de saturation 
                    fSimu = True
                    sflood.append(day) # On stocke le jour de debut de la periode de saturation
                    if (len(sflood) != 1):
                        esaturation.append(day)
                elif (nrow not in floods[day] or ncol not in floods[day][nrow]) and (fSimu):
                    # Si on sort de la periode de saturation
                    fSimu = False
                    eflood.append(day) # On stocke le jour de fin de la periode de saturation
                    ssaturation.append(day)
                #elif (floods[day][nrow][ncol]==1) and (fSimu is False):
                    
                elif (day == len(floods)-1) and (fSimu):
                    eflood.append(day)
                    # print("day : ",day,"\n")
                    # print("value of floods : ",floods[day][nrow][ncol])
                    # print("date start flood", len(sflood))
                    # print(sflood[-1])
                    print("nb row : ",nrow, "nb col : ", ncol)
            m = 0
            while m < len(eflood):
                # Pour toutes les periodes de saturation complete (il y a une date de fin)
                # On ajoute la duree de la periode
                fduration += (eflood[m]-sflood[m])
                #print((eflood[m]-sflood[m]))
                m+=1
            # On fait la moyenne des durees
            if len(eflood) == 0:
                fduration = 0
            else: 
                fduration = fduration / len(eflood)
            
            n = 0
            while n < len(esaturation):
                sduration += (esaturation[n] - ssaturation[n])
                n+=1
            if len(esaturation) == 0:
                sduration = 0
            else:
                sduration = sduration / len(esaturation)
            
            # Storing the values for the weights and duration of saturation periods
            wt = getWeightToSaturationDuration(tsmax, fduration)
            weights[nrow][ncol] = wt
            ts[nrow][ncol] = fduration
            tr[nrow][ncol] = sduration
    
    fweights = open(repoSimu + "/" + modelname + '_weights_pickle_nosea.txt','wb')
    pickle.dump(weights, fweights)
    fweights.close()
    fts = open(repoSimu + "/" + modelname + '_ts_pickle_nosea.txt', 'wb')
    pickle.dump(ts, fts)
    fts.close()
    ftr = open(repoSimu + "/" + modelname + '_tr_pickle_nosea.txt', 'wb')
    pickle.dump(tr, ftr)
    fts.close()

    return weights, ts, tr

def computeTsAndTrErrorsForASimulationWithFilesByMedian(ref, modelname, site_number, nbrow, nbcol, tsmax):
    site_name = getSiteNameFromSiteNumber(int(site_number))
    repoRef = getPathToSimulationDirectoryFromModelname(ref, site_name)
    repoSimu = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    # get for reference
    wRef = open(repoRef + '/' + ref + "_weights_pickle.txt", 'rb')
    weightsRef = pickle.load(wRef)
    wRef.close()
    tRef = open(repoRef + '/' + ref + "_ts_pickle.txt", 'rb')
    tsRef = pickle.load(tRef)
    tRef.close()
    ttRef = open(repoRef + '/' + ref + "_tr_pickle.txt", 'rb')
    trRef = pickle.load(ttRef)
    ttRef.close()


    wSimu = open(repoSimu + '/' + modelname + "_weights_pickle.txt", 'rb')
    weightsSimu = pickle.load(wSimu)
    wSimu.close()
    tSimu = open(repoSimu + '/' + modelname + "_ts_pickle.txt", 'rb')
    tsSimu = pickle.load(tSimu)
    tSimu.close()
    ttSimu = open(repoSimu + '/' + modelname + "_tr_pickle.txt", 'rb')
    trSimu = pickle.load(ttSimu)
    ttSimu.close()

    #weightsSimu, tsSimu, trSimu = getWtAndTsAndTrForASimulation(modelname, site_number, tsmax, nbrow, nbcol)

    smWt = 0
    tserrorsup = []
    trerrorsup = []

    for nrow in range(nbrow):
        for ncol in range(nbcol):
            print("nb row : ",nrow, "nb col : ", ncol)
            mWt = max(weightsRef[nrow][ncol], weightsSimu[nrow][ncol])
            print("max poids : ",mWt)
            smWt += mWt
            
            if mWt == 1 and (tsRef[nrow][ncol]- tsSimu[nrow][ncol] != 0):
                tserrorsup.append(abs(tsRef[nrow][ncol]- tsSimu[nrow][ncol]))
                print("tsRef : ", tsRef[nrow][ncol], "tsSimu : ", tsSimu[nrow][ncol], "tsdiff :", (tsRef[nrow][ncol]- tsSimu[nrow][ncol]))
                #print("tserrorsup",tserrorsup)
                trerrorsup.append(abs(trRef[nrow][ncol]- trSimu[nrow][ncol]))

    if smWt == 0:
        tsErrorGlobal = 0
        tsErrorGlobal = 0
    else:
        print("tserrorsup", tserrorsup, "smWt", smWt)
        tsErrorGlobal = statistics.median(tserrorsup)
        trErrorGlobal = statistics.median(trerrorsup)

    with open(repoSimu + "/" + modelname + '_Ref_' + ref + '_errorsresult_TSAndTR_median_abs.csv', 'w') as output:
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['TS Error', 'TR Error'])
        writer.writerow([tsErrorGlobal, trErrorGlobal])
    print("Ts Error value : ", tsErrorGlobal)
    print("Tr Error value : ", trErrorGlobal)



    return tsErrorGlobal,trErrorGlobal

def storeErrorValuesIntoCSVFile(ref, modelname, site_name, periodNumber, simulatedDuration, mea, mre, rmse):
    simuRepo = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    if (periodNumber == 0):
        with open(simuRepo + "/" + modelname + '_Ref_' + ref + '_errorsresult.csv', 'w') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(['Period Number', 'Simulated Time', 'MAE', 'MRE', 'RMSE'])
            writer.writerow([periodNumber, simulatedDuration, mea, mre, rmse])
        print("MEA value : ", mea)
        print("MRE value : ", mre)
        print("RMSE value : ", rmse) 


    else:
        with open(simuRepo + "/" + modelname + '_Ref_' + ref + '_errorsresult.csv', 'a') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow([periodNumber, simulatedDuration, mea, mre, rmse])
        print("-------------------------")
        print("MEA value : ", mea)
        print("MRE value : ", mre)
        print("RMSE value : ", rmse)

def storeErrorValuesIntoCSVFileByInterpolation(ref, modelname, site_name, periodNumber, simulatedDuration, mea, mre, rmse, startTime, endTime):
    simuRepo = getPathToSimulationDirectoryFromModelname(modelname, site_name)
    nbPart = str(startTime) + "_" + str(endTime)
    if (periodNumber == startTime):
        with open(simuRepo + "/" + modelname + '_Ref_' + ref + '_errorsresult_interpolation_' + str(nbPart) + '.csv', 'w') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(['Period Number', 'Simulated Time', 'MAE', 'MRE', 'RMSE'])
            writer.writerow([periodNumber, simulatedDuration, mea, mre, rmse])
        print("MEA value : ", mea)
        print("MRE value : ", mre)
        print("RMSE value : ", rmse) 


    else:
        with open(simuRepo + "/" + modelname + '_Ref_' + ref + '_errorsresult_interpolation_' + str(nbPart) + '.csv', 'a') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow([periodNumber, simulatedDuration, mea, mre, rmse])
        print("-------------------------")
        print("MEA value : ", mea)
        print("MRE value : ", mre)
        print("RMSE value : ", rmse)

def computeErrorRatesFromModelnamesByInterpoliationOptiParalFixedInit(ref, modelname, site_number, startTime, endTime, timestep):
    site_name = getSiteNameFromSiteNumber(site_number)
    repoRef = getPathToSimulationDirectoryFromModelname(ref, site_name) 
    print(repoRef)
    repoSimu = getPathToSimulationDirectoryFromModelname(modelname, site_name)


    refHds = fpu.HeadFile(repoRef + '/' + ref + '.hds')
    refTimes = refHds.get_times()
    refKstpkper = refHds.get_kstpkper()
    simuHds = fpu.HeadFile(repoSimu + '/' + modelname + '.hds')
    simuTimes = simuHds.get_times()
    simuKstpkper = simuHds.get_kstpkper()
    

    #Pour chaque jour
    for day in range(startTime, endTime+1):
        print(day)

        # On récupère la matrice de simulation ref
        refHead = refHds.get_data(kstpkper=(0, day))

        nbPeriod = 0
        while (simuTimes[nbPeriod] < day+1) and (nbPeriod < len(simuTimes)):
            nbPeriod+=1
        print("nbPeriod : " + str(nbPeriod))
        #On récupère la matrice de simulation alt supérieure

        print(simuTimes[nbPeriod], day+1)
        if math.isclose(simuTimes[nbPeriod], day+1, rel_tol=1e-3): #simuTimes[nbPeriod] == day+1
            print("condition ==")
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))       
            altHeadInf = altHeadSup
            duree = int(simuTimes[nbPeriod])
            pas = day
        else :
            altHeadSup = simuHds.get_data(kstpkper=(timestep-1, nbPeriod))        
            altHeadInf = simuHds.get_data(kstpkper=(timestep-1, nbPeriod-1))
            duree = int(simuTimes[nbPeriod] - simuTimes[nbPeriod-1])
            pas = day - simuTimes[nbPeriod-1]
        

        mae = 0
        mre = 0
        rmse = 0

        for nrow in range(refHead.shape[1]):
            for ncol in range(refHead.shape[2]):
                ss = getNonDryCellHdsValue(altHeadInf, nrow, ncol, refHead.shape[0])
                se = getNonDryCellHdsValue(altHeadSup, nrow, ncol, refHead.shape[0])
                ajoutSimu = (se - ss) / duree
                
                r= getNonDryCellHdsValue(refHead, nrow, ncol,refHead.shape[0])

                s = ss + (ajoutSimu * pas)

                mae, mre, rmse = addValueToErrorIndicators(s, r, mae, mre, rmse)
                
        
        sizeHeads = refHead.shape[1] * refHead.shape[2]
        
        mae = mae / (sizeHeads)
        rmse = math.sqrt(rmse / sizeHeads)
        
        storeErrorValuesIntoCSVFileByInterpolation(ref, modelname, site_name, day, refTimes[day], mae, mre, rmse, startTime, endTime)

def addValueToErrorIndicators(s, r, mae, mre, rmse):
    diff = (s - r)
    mae += abs(diff)
    mre += abs(diff / max(1, (s + r)/2))
    rmse += diff**2
    return mae, mre, rmse

# def getSeaLvl():
#     sites = pd.read_csv(mainAppRepo + "data/study_sites.txt", sep='\s+', header=0, index_col=0)
#     port = int(sites._get_values[site_number,5])
#     ram = pd.read_table(mainAppRepo +"data/RAM.csv", delimiter=";", header=0)
#     sea_level = ram.NM_IGN[port-1]
#     return sea_level


if __name__ == '__main__':
    computeErrorRatesFromModelnamesByInterpoliationOptiParalFixedInit(refname, modelname, site_number, startTime, endTime, timestep)