import math
import numpy as np
from scipy.interpolate import griddata

class Functions:
    def __init__(self, name):
        self.name = name
        
    def getListFromDEL(initbreaker,disLines,celldim):
        if 'CONSTANT' in disLines[initbreaker]:
            constElevation = float(disLines[initbreaker].split()[1])
            anyLines = [constElevation for x in range(celldim)]
        
        elif 'INTERNAL' in disLines[initbreaker]:
            #empty array and number of lines 
            anyLines = []
            #final breaker
            finalbreaker = initbreaker+1+math.ceil(celldim/10)
            #append to list all items
            for linea in range(initbreaker+1,finalbreaker,1):
                listaitem = [float(item) for item in disLines[linea].split()]
                for item in listaitem: anyLines.append(item)
        else:
            anylines = []
        return np.asarray(anyLines)

    def getListFromBreaker(initbreaker,modDis,fileLines):
        #empty array and number of lines
        anyLines = []
        finalbreaker = initbreaker+1+math.ceil(modDis['cellRows'])
        #append to list all items
        for linea in range(initbreaker+1,finalbreaker,1):
            listaitem = [float(item) for item in fileLines[linea].split()]
            for item in listaitem: anyLines.append(item)
        return anyLines

    def getListFromBreaker2(initbreaker,modDis,fileLines):
        #empty array and number of lines 
        anyLines = []
        finalbreaker = initbreaker+1+math.ceil(modDis['cellCols']/10)*modDis['cellRows']
        #append to list all items
        for linea in range(initbreaker+1,finalbreaker,1):
            listaitem = [float(item) for item in fileLines[linea].split()]
            for item in listaitem: anyLines.append(item)
        return anyLines

    #function that return a dictionary of z values on the vertex
    def interpolateCelltoVertex(modDis,item):
        dictZVertex = {}
        for lay in modDis[item].keys():
            values = np.asarray(modDis[item][lay])
            grid_z = griddata(modDis['cellCentroids'], values, 
                          (modDis['vertexXgrid'], modDis['vertexYgrid']), 
                          method='nearest')
            dictZVertex[lay]=grid_z
        return dictZVertex


