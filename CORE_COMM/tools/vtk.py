# coding: utf-8

import os
import numpy as np
import math
from scipy.interpolate import griddata
import flopy
import flopy.utils.binaryfile as bf

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

def grid(modelname, modelfolder, save_file, geographic):
    """
    build vtk file of grid model
    Parameters
    ----------
    modelname : str
        name of model.
    modelfolder : str
        folder where the model files are save.
    save_file : str
        folder where the vtk file is save.
    geographic : Python object
        object geographic of watershed class.
    """
    def GetExtent(gt,geotx, geoty, cols, rows):
        ext = []
        xarr = [0, cols]
        yarr = [0, rows]

        for px in xarr:
            for py in yarr:
                x = geotx[0] + (px * gt[1]) + (py * gt[2])
                y = geoty[0] + (px * gt[4]) + (py * gt[5])
                ext.append([x, y])
            yarr.reverse()
        return ext
    
    mf1 = flopy.modflow.Modflow.load(os.path.join(modelfolder,modelname+'.nam'), verbose=False, check=False, load_only=['upw', 'dis'])
    hk = mf1.upw.hk
    ext = GetExtent(geographic.geodata,geographic.x_coord,geographic.y_coord, geographic.x_pixel, geographic.y_pixel)
    
    # change directory to the script path
    os.chdir(modelfolder)  # use your own path

    # open the DIS, BAS files
    disLines = open(os.path.join(modelfolder,modelname+'.dis')).readlines()  # discretization data
    basLines = open(os.path.join(modelfolder,modelname+'.bas')).readlines()  # active / inactive data

    # create a empty dictionay to store the model features
    modDis = {}
    modBas = {}

    # # Working with the DIS (Discretization Data) data

    # ### General model features as modDis dict

    # get the extreme coordinates form the dis header

    modDis["vertexXmin"] = float(ext[0][0])
    modDis["vertexYmin"] = float(ext[2][1])
    modDis["vertexXmax"] = float(ext[2][0])
    modDis["vertexYmax"] = float(ext[0][1])

    # get the number of layers, rows, columns, cell and vertex numbers
    linelaycolrow = disLines[1].split()
    modDis["cellLays"] = int(linelaycolrow[0])
    modDis["cellRows"] = int(linelaycolrow[1])
    modDis["cellCols"] = int(linelaycolrow[2])
    modDis["vertexLays"] = modDis["cellLays"] + 1
    modDis["vertexRows"] = modDis["cellRows"] + 1
    modDis["vertexCols"] = modDis["cellCols"] + 1
    modDis["vertexperlay"] = modDis["vertexRows"] * modDis["vertexCols"]
    modDis["cellsperlay"] = modDis["cellRows"] * modDis["cellCols"]

    # ### Get the DIS Breakers

    # get the grid breakers
    modDis['disBreakers'] = {}
    breakerValues = ["INTERNAL", "CONSTANT"]

    vertexLay = 0
    for item in breakerValues:
        for line in disLines:
            if item in line:
                if 'delr' in line:  # DELR is cell width along rows
                    modDis['disBreakers']['DELR'] = disLines.index(line)
                elif 'delc' in line:  # DELC is cell width along columns
                    modDis['disBreakers']['DELC'] = disLines.index(line)
                else:
                    modDis['disBreakers']['vertexLay' + str(vertexLay)] = disLines.index(line)
                    vertexLay += 1

    # ### Get the DEL Info

    modDis['DELR'] = Functions.getListFromDEL(modDis['disBreakers']['DELR'], disLines, modDis['cellCols'])
    modDis['DELC'] = Functions.getListFromDEL(modDis['disBreakers']['DELC'], disLines, modDis['cellRows'])

    # ### Get the Cell Centroid Z

    modDis['cellCentroidZList'] = {}

    for lay in range(modDis['vertexLays']):

        # add auxiliar variables to identify breakers
        lineaBreaker = modDis['disBreakers']['vertexLay' + str(lay)]
        # two cases in breaker line
        if 'INTERNAL' in disLines[lineaBreaker]:
            lista = Functions.getListFromBreaker(lineaBreaker, modDis, disLines)
            modDis['cellCentroidZList']['lay' + str(lay)] = lista
        elif 'CONSTANT' in disLines[lineaBreaker]:
            constElevation = float(disLines[lineaBreaker].split()[1])
            modDis['cellCentroidZList']['lay' + str(lay)] = [constElevation for x in range(modDis["cellsperlay"])]
        else:
            pass

    # ### List of arrays of cells and vertex coord

    modDis['vertexEasting'] = np.array(
        [modDis['vertexXmin'] + np.sum(modDis['DELR'][:col]) for col in range(modDis['vertexCols'])])
    modDis['vertexNorthing'] = np.array(
        [modDis['vertexYmax'] - np.sum(modDis['DELC'][:row]) for row in range(modDis['vertexRows'])])

    modDis['cellEasting'] = np.array(
        [modDis['vertexXmin'] + np.sum(modDis['DELR'][:col]) + modDis['DELR'][col] / 2 for col in
         range(modDis['cellCols'])])
    modDis['cellNorthing'] = np.array(
        [modDis['vertexYmax'] - np.sum(modDis['DELC'][:row]) - modDis['DELC'][row] / 2 for row in
         range(modDis['cellRows'])])

    # ### Interpolation from Z cell centroid to z vertex

    # # Get the BAS Info

    # ### Get the grid breakers

    # empty dict to store BAS breakers
    modBas['basBreakers'] = {}

    breakerValues = ["INTERNAL", "CONSTANT"]

    # store the breakers in the dict
    lay = 0
    for item in breakerValues:
        for line in basLines:
            if item in line:
                if 'ibound' in line:
                    modBas['basBreakers']['lay' + str(lay)] = basLines.index(line)
                    lay += 1
                else:
                    pass

    # ### Store ibound per lay

    # empty dict to store cell ibound per layer
    modBas['cellIboundList'] = {}

    for lay in range(modDis['cellLays']):

        # add auxiliar variables to identify breakers
        lineaBreaker = modBas['basBreakers']['lay' + str(lay)]

        # two cases in breaker line
        if 'INTERNAL' in basLines[lineaBreaker]:
            lista = Functions.getListFromBreaker(lineaBreaker, modDis, basLines)
            modBas['cellIboundList']['lay' + str(lay)] = lista
        elif 'CONSTANT' in basLines[lineaBreaker]:
            constElevation = float(disLines[lineaBreaker].split()[1])  # todavia no he probado esto
            modBas['cellIboundList']['lay' + str(lay)] = [constElevation for x in range(modDis["cellsperlay"])]
        else:
            pass

    # ### Store Cell Centroids as a Numpy array

    # empty list to store cell centroid
    cellCentroidList = []

    # numpy array of cell centroid
    for row in range(modDis['cellRows']):
        for col in range(modDis['cellCols']):
            cellCentroidList.append([modDis['cellEasting'][col], modDis['cellNorthing'][row]])

    # store cell centroids as numpy array
    modDis['cellCentroids'] = np.asarray(cellCentroidList)
    modDis['vertexXgrid'] = np.repeat(modDis['vertexEasting'].reshape(modDis['vertexCols'], 1), modDis['vertexRows'],
                                      axis=1).T
    modDis['vertexYgrid'] = np.repeat(modDis['vertexNorthing'], modDis['vertexCols']).reshape(modDis['vertexRows'],
                                                                                              modDis['vertexCols'])
    modDis['vertexZGrid'] = Functions.interpolateCelltoVertex(modDis, 'cellCentroidZList')

    # # Lists for the VTK file

    # ### Definition of xyz points for all vertex

    # empty list to store all vertex XYZ
    vertexXYZPoints = []

    # definition of xyz points for all vertex
    for lay in range(modDis['vertexLays']):
        for row in range(modDis['vertexRows']):
            for col in range(modDis['vertexCols']):
                if modDis['vertexZGrid']['lay' + str(lay)][row, col]< -100:
                    a = modDis['vertexZGrid']['lay' + str(lay)]
                    z = np.max(a[np.max([row-1, 0]):np.min([row+1, modDis['vertexRows']-1])+1, np.max([col-1, 0]):np.min([col+1, modDis['vertexCols']-1])+1])
                else :
                    z = modDis['vertexZGrid']['lay' + str(lay)][row, col]
                
                xyz = [
                    modDis['vertexEasting'][col],
                    modDis['vertexNorthing'][row],
                    z
                ]
                
                vertexXYZPoints.append(xyz)

    # empty list to store all ibound
    listIBound = []
    listHk = []
    # definition of IBOUND
    for lay in range(modDis['cellLays']):
        for item in modBas['cellIboundList']['lay' + str(lay)]:
            listIBound.append(item)
        for i in range(hk.shape[1]):
            for j in range(hk.shape[2]):
                listHk.append(hk.array[lay, i, j])
#                listFlow.append(sum_flow[lay, i, j])

    # ### Definition of Cell Ibound List

    # # Hexahedrons and Quads sequences for the VTK File

    # ### List of Layer Quad Sequences (Works only for a single layer)

    # empty list to store cell coordinates
    listLayerQuadSequence = []

    # definition of hexahedrons cell coordinates
    for row in range(modDis['cellRows']):
        for col in range(modDis['cellCols']):
            pt0 = modDis['vertexCols'] * (row + 1) + col
            pt1 = modDis['vertexCols'] * (row + 1) + col + 1
            pt2 = modDis['vertexCols'] * (row) + col + 1
            pt3 = modDis['vertexCols'] * (row) + col
            anyList = [pt0, pt1, pt2, pt3]
            listLayerQuadSequence.append(anyList)

    # ### List of Hexa Sequences

    # empty list to store cell coordinates
    listHexaSequence = []

    # definition of hexahedrons cell coordinates
    for lay in range(modDis['cellLays']):
        for row in range(modDis['cellRows']):
            for col in range(modDis['cellCols']):
                pt0 = modDis['vertexperlay'] * (lay + 1) + modDis['vertexCols'] * (row + 1) + col
                pt1 = modDis['vertexperlay'] * (lay + 1) + modDis['vertexCols'] * (row + 1) + col + 1
                pt2 = modDis['vertexperlay'] * (lay + 1) + modDis['vertexCols'] * (row) + col + 1
                pt3 = modDis['vertexperlay'] * (lay + 1) + modDis['vertexCols'] * (row) + col
                pt4 = modDis['vertexperlay'] * (lay) + modDis['vertexCols'] * (row + 1) + col
                pt5 = modDis['vertexperlay'] * (lay) + modDis['vertexCols'] * (row + 1) + col + 1
                pt6 = modDis['vertexperlay'] * (lay) + modDis['vertexCols'] * (row) + col + 1
                pt7 = modDis['vertexperlay'] * (lay) + modDis['vertexCols'] * (row) + col
                anyList = [pt0, pt1, pt2, pt3, pt4, pt5, pt6, pt7]
                listHexaSequence.append(anyList)

    # ### Active Cells and Hexa Sequences

    listActiveHexaSequenceDef = []
    listIBoundDef = []
    listHkDef = []

    # filter hexahedrons and heads for active cells
    for i in range(len(listIBound)):
        if listIBound[i] == -1:
            listActiveHexaSequenceDef.append(listHexaSequence[i])
            listIBoundDef.append(listIBound[i])
            listHkDef.append(listHk[i])
        if listIBound[i] == 1:
            listActiveHexaSequenceDef.append(listHexaSequence[i])
            listIBoundDef.append(listIBound[i])
            listHkDef.append(listHk[i])

    textoVtk = open(os.path.join(save_file,'VTU_Grid.vtu'), 'w')

    # add header
    textoVtk.write('<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n')
    textoVtk.write('  <UnstructuredGrid>\n')
    textoVtk.write('    <Piece NumberOfPoints="' + str(len(vertexXYZPoints)) + '" NumberOfCells="' + str(
        len(listActiveHexaSequenceDef)) + '">\n')

    # cell data
    textoVtk.write('      <CellData Scalars="Model">\n')
    textoVtk.write('        <DataArray type="Int32" Name="Active" format="ascii">\n')
    for item in range(len(listIBoundDef)):  # cell list
        textvalue = str(int(listIBoundDef[item]))
        if item == 0:
            textoVtk.write('          ' + textvalue + ' ')
        elif item % 20 == 0:
            textoVtk.write(textvalue + '\n          ')
        else:
            textoVtk.write(textvalue + ' ')
    textoVtk.write('\n')
    textoVtk.write('        </DataArray>\n')

    textoVtk.write('        <DataArray type="Float64" Name="HK" format="ascii">\n')
    for item in range(len(listHkDef)):
        textvalue = str(listHkDef[item])
        if item == 0:
            textoVtk.write('          ' + textvalue + ' ')
        elif item % 20 == 0:
            textoVtk.write(textvalue + '\n          ')
        else:
            textoVtk.write(textvalue + ' ')
    textoVtk.write('\n')
    textoVtk.write('        </DataArray>\n')
    """
    textoVtk.write('        <DataArray type="Float64" Name="Flow" format="ascii">\n')
    for item in range(len(listFlowDef)):
        textvalue = str(listFlowDef[item])
        if item == 0:
            textoVtk.write('          ' + textvalue + ' ')
        elif item % 20 == 0:
            textoVtk.write(textvalue + '\n          ')
        else:
            textoVtk.write(textvalue + ' ')
    textoVtk.write('\n')
    textoVtk.write('        </DataArray>\n')
    """
    textoVtk.write('      </CellData>\n')

    # points definition
    textoVtk.write('      <Points>\n')
    textoVtk.write('        <DataArray type="Float64" Name="Points" NumberOfComponents="3" format="ascii">\n')
    for item in range(len(vertexXYZPoints)):
        tuplevalue = tuple(vertexXYZPoints[item])
        if item == 0:
            textoVtk.write("          %.2f %.2f %.2f " % tuplevalue)
        elif item % 4 == 0:
            textoVtk.write('%.2f %.2f %.2f \n          ' % tuplevalue)
        elif item == len(vertexXYZPoints) - 1:
            textoVtk.write("%.2f %.2f %.2f \n" % tuplevalue)
        else:
            textoVtk.write("%.2f %.2f %.2f " % tuplevalue)
    textoVtk.write('        </DataArray>\n')
    textoVtk.write('      </Points>\n')

    # cell connectivity
    textoVtk.write('      <Cells>\n')
    textoVtk.write('        <DataArray type="Int64" Name="connectivity" format="ascii">\n')
    for item in range(len(listActiveHexaSequenceDef)):
        textoVtk.write('          ')
        textoVtk.write('%s %s %s %s %s %s %s %s \n' % tuple(listActiveHexaSequenceDef[item]))
    textoVtk.write('        </DataArray>\n')
    # cell offsets
    textoVtk.write('        <DataArray type="Int64" Name="offsets" format="ascii">\n')
    for item in range(len(listActiveHexaSequenceDef)):
        offset = str((item + 1) * 8)
        if item == 0:
            textoVtk.write('          ' + offset + ' ')
        elif item % 20 == 0:
            textoVtk.write(offset + ' \n          ')
        elif item == len(listActiveHexaSequenceDef) - 1:
            textoVtk.write(offset + ' \n')
        else:
            textoVtk.write(offset + ' ')
    textoVtk.write('        </DataArray>\n')
    # cell types
    textoVtk.write('        <DataArray type="UInt8" Name="types" format="ascii">\n')
    for item in range(len(listActiveHexaSequenceDef)):
        if item == 0:
            textoVtk.write('          ' + '12 ')
        elif item % 20 == 0:
            textoVtk.write('12 \n          ')
        elif item == len(listActiveHexaSequenceDef) - 1:
            textoVtk.write('12 \n')
        else:
            textoVtk.write('12 ')
    textoVtk.write('        </DataArray>\n')
    textoVtk.write('      </Cells>\n')

    # footer
    textoVtk.write('    </Piece>\n')
    textoVtk.write('  </UnstructuredGrid>\n')
    textoVtk.write('</VTKFile>\n')

    textoVtk.close()

def watertable(modelname, modelfolder,save_file, geographic):
    """
    build vtk file of watertable
    
    Parameters
    ----------
    modelname : str
        name of model.
    modelfolder : str
        folder where the model files are save.
    save_file : str
        folder where the vtk file is save.
    geographic : Python object
        object geographic of watershed class.
    """
    def GetExtent(gt,geotx, geoty, cols, rows):
        ext = []
        xarr = [0, cols]
        yarr = [0, rows]

        for px in xarr:
            for py in yarr:
                x = geotx[0] + (px * gt[1]) + (py * gt[2])
                y = geoty[0] + (px * gt[4]) + (py * gt[5])
                ext.append([x, y])
            yarr.reverse()
        return ext
    
    mf1 = flopy.modflow.Modflow.load(os.path.join(modelfolder,modelname+'.nam'), verbose=False, check=False, load_only=['upw', 'dis'])
    hk = mf1.upw.hk
    ext = GetExtent(geographic.geodata,geographic.x_coord,geographic.y_coord, geographic.x_pixel, geographic.y_pixel)

    # change directory to the script path
    os.chdir(modelfolder)  # use your own path

    # open the DIS, BAS and FHD and DRN files
    disLines = open(os.path.join(modelfolder,modelname+'.dis')).readlines()  # discretization data
    #basLines = open(modelfolder+modelname+'.bas').readlines()  # active / inactive data
    hds = bf.HeadFile(os.path.join(modelfolder,modelname+'.hds'))
    kstpkper = hds.get_kstpkper()
    tsn = []
    if len(kstpkper[0]) > 50:
        tsn = [0, int((len(kstpkper) - 1) / 2), (len(kstpkper) - 1)]
    else:
        tsn = np.linspace(0,len(kstpkper)-1,len(kstpkper),dtype=int)

    textoVtk = open(os.path.join(save_file,'VTU_WaterTable.pvd'), 'w')
    textoVtk.write('<VTKFile type="Collection" version="0.1">\n')
    textoVtk.write('  <Collection>\n')
    for time_step_num in range(0, len(tsn)):
        time_step = tsn[time_step_num]
        textoVtk.write('    <DataSet timestep="' + str(time_step) + '" part="0" file="'+os.path.join(save_file,'VTU_WaterTable_' + str(
            time_step) + '.vtu" />\n'))
    textoVtk.write('  </Collection>\n')
    textoVtk.write('</VTKFile>\n')
    textoVtk.close()

    for time_step_num in range(0, len(tsn)):
        time_step = tsn[time_step_num]
        # create a empty dictionay to store the model features
        modDis = {}
        modFhd = {}

        modDis["vertexXmin"] = float(ext[0][0])
        modDis["vertexYmin"] = float(ext[2][1])
        modDis["vertexXmax"] = float(ext[2][0])
        modDis["vertexYmax"] = float(ext[0][1])
        # get the number of layers, rows, columns, cell and vertex numbers
        linelaycolrow = disLines[1].split()
        modDis["cellLays"] = int(linelaycolrow[0])
        modDis["cellRows"] = int(linelaycolrow[1])
        modDis["cellCols"] = int(linelaycolrow[2])
        modDis["vertexLays"] = modDis["cellLays"] + 1
        modDis["vertexRows"] = modDis["cellRows"] + 1
        modDis["vertexCols"] = modDis["cellCols"] + 1
        modDis["vertexperlay"] = modDis["vertexRows"] * modDis["vertexCols"]
        modDis["cellsperlay"] = modDis["cellRows"] * modDis["cellCols"]
        # ### Get the DIS Breakers
        modDis['disBreakers'] = {}
        breakerValues = ["INTERNAL", "CONSTANT"]
        vertexLay = 0
        for item in breakerValues:
            for line in disLines:
                if item in line:
                    if 'delr' in line:  # DELR is cell width along rows
                        modDis['disBreakers']['DELR'] = disLines.index(line)
                    elif 'delc' in line:  # DELC is cell width along columns
                        modDis['disBreakers']['DELC'] = disLines.index(line)
                    else:
                        modDis['disBreakers']['vertexLay' + str(vertexLay)] = disLines.index(line)
                        vertexLay += 1
        modDis['DELR'] = Functions.getListFromDEL(modDis['disBreakers']['DELR'], disLines, modDis['cellCols'])
        modDis['DELC'] = Functions.getListFromDEL(modDis['disBreakers']['DELC'], disLines, modDis['cellRows'])
        modDis['cellCentroidZList'] = {}
        for lay in range(modDis['vertexLays']):
            # add auxiliar variables to identify breakers
            lineaBreaker = modDis['disBreakers']['vertexLay' + str(lay)]
            # two cases in breaker line
            if 'INTERNAL' in disLines[lineaBreaker]:
                lista = Functions.getListFromBreaker(lineaBreaker, modDis, disLines)
                modDis['cellCentroidZList']['lay' + str(lay)] = lista
            elif 'CONSTANT' in disLines[lineaBreaker]:
                constElevation = float(disLines[lineaBreaker].split()[1])
                modDis['cellCentroidZList']['lay' + str(lay)] = [constElevation for x in range(modDis["cellsperlay"])]
            else:
                pass
        modDis['vertexEasting'] = np.array(
            [modDis['vertexXmin'] + np.sum(modDis['DELR'][:col]) for col in range(modDis['vertexCols'])])
        modDis['vertexNorthing'] = np.array(
            [modDis['vertexYmax'] - np.sum(modDis['DELC'][:row]) for row in range(modDis['vertexRows'])])
        modDis['cellEasting'] = np.array(
            [modDis['vertexXmin'] + np.sum(modDis['DELR'][:col]) + modDis['DELR'][col] / 2 for col in
             range(modDis['cellCols'])])
        modDis['cellNorthing'] = np.array(
            [modDis['vertexYmax'] - np.sum(modDis['DELC'][:row]) - modDis['DELC'][row] / 2 for row in
             range(modDis['cellRows'])])

        modFhd['cellHeadGrid'] = {}
        lay = 0
        head = hds.get_data(kstpkper=kstpkper[time_step])
        for i in range(0, head.shape[0]):
            modFhd['cellHeadGrid']['lay' + str(lay)] = head[i]
            lay += 1

        listLayerQuadSequence = []

        # definition of hexahedrons cell coordinates
        for row in range(modDis['cellRows']):
            for col in range(modDis['cellCols']):
                pt0 = modDis['vertexCols'] * (row + 1 ) + col
                pt1 = modDis['vertexCols'] * (row + 1 ) + col + 1
                pt2 = modDis['vertexCols'] * (row ) + col + 1
                pt3 = modDis['vertexCols'] * (row ) + col
                anyList = [pt0, pt1, pt2, pt3]
                listLayerQuadSequence.append(anyList)

        vertexHeadGridCentroid = {}
        # arrange to hace positive heads in all vertex of an active cell
        for lay in range(modDis['cellLays']):
            matrix = np.zeros([modDis['vertexRows'], modDis['vertexCols']])
            for row in range(modDis['cellRows']):
                for col in range(modDis['cellCols']):
                    headLay = modFhd['cellHeadGrid']['lay' + str(lay)]
                    neighcartesianlist = [headLay[row, col], headLay[row, col], headLay[row, col],
                                          headLay[row, col]]
                    headList = []
                    for item in neighcartesianlist:
                        if item > -200:
                            headList.append(item)
                    if len(headList) > 0:
                        headMean = sum(headList) / len(headList)
                    else:
                        headMean = -200

                    matrix[row, col] = headMean

            matrix[-1, :-1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, :]
            matrix[:-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][:, -1]
            matrix[-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, -1]

            vertexHeadGridCentroid['lay' + str(lay)] = matrix

        # empty temporal dictionary to store transformed heads
        vertexHKGridCentroid = {}

        # arrange to hace positive heads in all vertex of an active cell
        for lay in range(modDis['cellLays']):
            matrix = np.zeros([modDis['vertexRows'], modDis['vertexCols']])
            for row in range(modDis['cellRows']):
                for col in range(modDis['cellCols']):
                    headLay = hk.array[lay]
                    neighcartesianlist = [headLay[row, col], headLay[row, col], headLay[row, col],
                                          headLay[row, col]]
                    headList = []
                    for item in neighcartesianlist:
                        if item > -200:
                            headList.append(item)
                    if len(headList) > 0:
                        headMean = sum(headList) / len(headList)
                    else:
                        headMean = -200

                    matrix[row, col] = headMean

            matrix[-1, :-1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, :]
            matrix[:-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][:, -1]
            matrix[-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, -1]

            vertexHKGridCentroid['lay' + str(lay)] = matrix

        modFhd['vertexHeadGrid'] = {}
        for lay in range(modDis['vertexLays']):
            anyGrid = vertexHeadGridCentroid
            if lay == modDis['cellLays']:
                modFhd['vertexHeadGrid']['lay' + str(lay)] = anyGrid['lay' + str(lay - 1)]
            elif lay == 0:
                modFhd['vertexHeadGrid']['lay0'] = anyGrid['lay0']
            else:

                value = np.where(anyGrid['lay' + str(lay)] > -100,
                                 anyGrid['lay' + str(lay)],
                                 (anyGrid['lay' + str(lay - 1)] + anyGrid['lay' + str(lay)]) / 2
                                 )
                modFhd['vertexHeadGrid']['lay' + str(lay)] = value

        # empty numpy array for the water table
        waterTableVertexGrid = np.zeros((modDis['vertexRows'], modDis['vertexCols']))
        # obtain the first positive or real head from the head array
        for row in range(modDis['vertexRows']):
            for col in range(modDis['vertexCols']):
                anyList = []
                for lay in range(modDis['cellLays']):
                    anyList.append(modFhd['vertexHeadGrid']['lay' + str(lay)][row, col])
                a = np.asarray(anyList)
                if list(a[a >-100]) != []:  # just in case there are some inactive zones
                    waterTableVertexGrid[row, col] = a[a > -100][0]
                else:
                    waterTableVertexGrid[row, col] = np.max(modFhd['vertexHeadGrid']['lay' + str(lay)][np.max([row-1, 0]):np.min([row+1, modDis['vertexRows']-1])+1, np.max([col-1, 0]):np.min([col+1, modDis['vertexCols']-1])+1])
                    
        # empty list to store all vertex Water Table XYZ
        vertexWaterTableXYZPoints = []
        # definition of xyz points for all vertex
        for row in range(modDis['vertexRows']):
            for col in range(modDis['vertexCols']):
                if waterTableVertexGrid[row, col] > -100:
                    waterTable = waterTableVertexGrid[row, col]
                else:
                    waterTable = np.max(waterTableVertexGrid[np.max([row-1, 0]):np.min([row+1, modDis['vertexRows']-1])+1, np.max([col-1, 0]):np.min([col+1, modDis['vertexCols']-1])+1])
                xyz = [
                    modDis['vertexEasting'][col],
                    modDis['vertexNorthing'][row],
                    waterTable
                ]
                vertexWaterTableXYZPoints.append(xyz)

        waterTableCellGrid = np.zeros((modDis['cellRows'], modDis['cellCols']))

        # obtain the first positive or real head from the head array
        for row in range(modDis['cellRows']):
            for col in range(modDis['cellCols']):
                anyList = []
                for lay in range(modDis['cellLays']):
                    anyList.append(modFhd['cellHeadGrid']['lay' + str(lay)][row, col])
                a = np.asarray(anyList)
                if list(a[a > -100]) != []:  # just in case there are some inactive zones
                    waterTableCellGrid[row, col] = a[a > -100][0]
                else:
                    waterTableCellGrid[row, col] = -100

        listWaterTableCell = list(waterTableCellGrid.flatten())

        listWaterTableQuadSequenceDef = []
        listWaterTableCellDef = []
        listDrawdownCellDef = []
        for item in range(len(listWaterTableCell)):
            if listWaterTableCell[item] > -100:
                listWaterTableQuadSequenceDef.append(listLayerQuadSequence[item])
                listWaterTableCellDef.append(listWaterTableCell[item])
                drawdown = modDis['cellCentroidZList']['lay0'][item] - listWaterTableCell[item]
                listDrawdownCellDef.append(drawdown)
                
        textoVtk = open(os.path.join(save_file,'VTU_WaterTable_' + str(time_step) + '.vtu'), 'w')
        # add header
        textoVtk.write(
            '<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n')
        textoVtk.write('  <UnstructuredGrid>\n')
        textoVtk.write('    <Piece NumberOfPoints="' + str(len(vertexWaterTableXYZPoints)) + '" NumberOfCells="' +
                       str(len(listWaterTableCellDef)) + '">\n')
        # cell data
        textoVtk.write('      <CellData Scalars="Water Table">\n')
        textoVtk.write('        <DataArray type="Float64" Name="Heads" format="ascii">\n')
        for item in range(len(listWaterTableCellDef)):
            textvalue = str(listWaterTableCellDef[item])
            if item == 0:
                textoVtk.write('          ' + textvalue + ' ')
            elif item % 20 == 0:
                textoVtk.write(textvalue + '\n          ')
            else:
                textoVtk.write(textvalue + ' ')
        textoVtk.write('\n')
        textoVtk.write('        </DataArray>\n')

        textoVtk.write('        <DataArray type="Float64" Name="Drawdown" format="ascii">\n')
        for item in range(len(listDrawdownCellDef)):
            textvalue = str(listDrawdownCellDef[item])
            if item == 0:
                textoVtk.write('          ' + textvalue + ' ')
            elif item % 20 == 0:
                textoVtk.write(textvalue + '\n          ')
            else:
                textoVtk.write(textvalue + ' ')
        textoVtk.write('\n')
        textoVtk.write('        </DataArray>\n')
        textoVtk.write('      </CellData>\n')
        # points definition
        textoVtk.write('      <Points>\n')
        textoVtk.write('        <DataArray type="Float64" Name="Points" NumberOfComponents="3" format="ascii">\n')
        for item in range(len(vertexWaterTableXYZPoints)):
            tuplevalue = tuple(vertexWaterTableXYZPoints[item])
            if item == 0:
                textoVtk.write("          %.2f %.2f %.2f " % tuplevalue)
            elif item % 4 == 0:
                textoVtk.write('%.2f %.2f %.2f \n          ' % tuplevalue)
            elif item == len(vertexWaterTableXYZPoints):
                textoVtk.write("%.2f %.2f %.2f \n" % tuplevalue)
            else:
                textoVtk.write("%.2f %.2f %.2f " % tuplevalue)
        textoVtk.write('        </DataArray>\n')
        textoVtk.write('      </Points>\n')
        # cell connectivity
        textoVtk.write('      <Cells>\n')
        textoVtk.write('        <DataArray type="Int64" Name="connectivity" format="ascii">\n')
        for item in range(len(listWaterTableQuadSequenceDef)):
            textoVtk.write('          ')
            textoVtk.write('%s %s %s %s \n' % tuple(listWaterTableQuadSequenceDef[item]))
        textoVtk.write('        </DataArray>\n')
        # cell offsets
        textoVtk.write('        <DataArray type="Int64" Name="offsets" format="ascii">\n')
        for item in range(len(listWaterTableQuadSequenceDef)):
            offset = str((item + 1) * 4)
            if item == 0:
                textoVtk.write('          ' + offset + ' ')
            elif item % 20 == 0:
                textoVtk.write(offset + ' \n          ')
            elif item == len(listWaterTableQuadSequenceDef) - 1:
                textoVtk.write(offset + ' \n')
            else:
                textoVtk.write(offset + ' ')
        textoVtk.write('        </DataArray>\n')
        # cell types
        textoVtk.write('        <DataArray type="UInt8" Name="types" format="ascii">\n')
        for item in range(len(listWaterTableQuadSequenceDef)):
            if item == 0:
                textoVtk.write('          ' + '9 ')
            elif item % 20 == 0:
                textoVtk.write('9 \n          ')
            elif item == len(listWaterTableQuadSequenceDef) - 1:
                textoVtk.write('9 \n')
            else:
                textoVtk.write('9 ')
        textoVtk.write('        </DataArray>\n')
        textoVtk.write('      </Cells>\n')
        # footer
        textoVtk.write('    </Piece>\n')
        textoVtk.write('  </UnstructuredGrid>\n')
        textoVtk.write('</VTKFile>\n')

        textoVtk.close()

def pathlines(modelname, modelfolder, save_file, geographic):
    """
    build vtk file of pathlines
    
    Parameters
    ----------
    modelname : str
        name of model.
    modelfolder : str
        folder where the model files are save.
    save_file : str
        folder where the vtk file is save.
    geographic : Python object
        object geographic of watershed class.
    """
    geotx_p = geographic.x_coord
    geoty_p = geographic.y_coord
    geot_p = geographic.geodata
    cols = geotx_p.shape[0]
    rows = geoty_p.shape[0]
    ext = []
    xarr = [0, cols]
    yarr = [0, rows]
    for px in xarr:
        for py in yarr:
            x = geotx_p[0] + (px * geot_p[1]) + (py * geot_p[2])
            y = geoty_p[0] + (px * geot_p[4]) + (py * geot_p[5])
            ext.append([x, y])
    pthobj = flopy.utils.PathlineFile(os.path.join(modelfolder,modelname+'.mppth'))
    pth_data = pthobj.get_alldata()
    t_store = []
    x_store = []
    y_store = []
    z_store = []
    l_store = []
    v_store = []
    for i in range(0, len(pth_data)):
        Data = pth_data[i]
        x = [x for (x, y, z, t, l, a) in Data]
        z = [z for (x, y, z, t, l, a) in Data]
        y = [y for (x, y, z, t, l, a) in Data]
        t = [t for (x, y, z, t, l, a) in Data]
        l = [l for (x, y, z, t, l, a) in Data]
        t = np.asarray(t)
        t_store.append(t)
        l_store.append(l)
        y_store.append(y)
        x_store.append(x)
        z_store.append(z)

    nb_points = 0
    for i in range(0, np.alen(x_store)):
        nb_points = nb_points + np.alen(x_store[i])

    for i in range(0, np.alen(x_store)):
        for j in range(0, np.alen(x_store[i])):
            if j == 0:
                v_store.append(0)
            else:
                d = np.sqrt(((x_store[i][j] - x_store[i][j - 1]) ** 2) + ((y_store[i][j] - y_store[i][j - 1]) ** 2) + (
                            (z_store[i][j] - z_store[i][j - 1]) ** 2))
                if (t_store[i][j] - t_store[i][j - 1]) == 0:
                    v_store.append(0)
                else:
                    v = d / (t_store[i][j] - t_store[i][j - 1])
                    v_store.append(v)

    textoVtk = open(os.path.join(save_file,'VTU_Pathlines.vtk'), 'w')
    # add header
    textoVtk.write('# vtk DataFile Version 2.0\n')
    textoVtk.write('Particles Pathlines Modpath\n')
    textoVtk.write('ASCII\n')
    textoVtk.write('DATASET POLYDATA\n')
    textoVtk.write('POINTS ' + str(nb_points) + ' float\n')
    for line in range(0, np.alen(x_store)):
        for particles in range(0, np.alen(x_store[line])):
            textoVtk.write(
                str(x_store[line][particles] + ext[1][0]) + ' ' + str(y_store[line][particles] + ext[1][1]) + ' ' + str(z_store[line][particles]
                    ) + '\n')
    textoVtk.write('\n')
    textoVtk.write('LINES ' + str(np.alen(x_store)) + ' ' + str(nb_points + np.alen(x_store)) + '\n')
    nb = 0
    for i in range(0, np.alen(x_store)):
        textoVtk.write(str(np.alen(x_store[i])) + ' ')
        for j in range(0, np.alen(x_store[i])):
            textoVtk.write(str(nb) + ' ')
            nb = nb + 1
        textoVtk.write('\n')

    textoVtk.write('POINT_DATA ' + str(nb_points) + '\n')
    textoVtk.write('SCALARS Time float\n')
    textoVtk.write('LOOKUP_TABLE default\n')
    for i in range(0, np.alen(x_store)):
        for j in range(0, np.alen(x_store[i])):
            textoVtk.write(str(t_store[i][j]) + '\n')

    #textoVtk.write('SCALARS Velocity float\n')
    #textoVtk.write('LOOKUP_TABLE default\n')
    #for i in range(0, np.alen(v_store)):
    #   textoVtk.write(str(v_store[i]) + '\n')
    textoVtk.close()

def piezometers(save_file,piezometry):
    piezos = piezometry.codes_bss
    textoVtk = open(os.path.join(save_file,'VTU_Piezometers.vtk'), 'w')
    # add header
    textoVtk.write('# vtk DataFile Version 2.0\n')
    textoVtk.write('Particles Pathlines Modpath\n')
    textoVtk.write('ASCII\n')
    textoVtk.write('DATASET POLYDATA\n')
    textoVtk.write('POINTS ' + '18' + ' float\n')
    for i in range(0, np.alen(piezos)):
        x=piezometry.x_coord[i]
        y=piezometry.y_coord[i]
        z=piezometry.elevation_well[i]
        d=piezometry.depth_well[i]
        textoVtk.write(str(x) + ' ' + str(y) + ' ' + str(z) + '\n')
        textoVtk.write(str(x) + ' ' + str(y) + ' ' + str(d) + '\n')
    textoVtk.write('\n')
    textoVtk.write('LINES ' + '9' + ' ' + '27' + '\n')
    nb = 0
    for i in range(0, np.alen(piezos)):
        textoVtk.write('2' + ' ')
        textoVtk.write(str(nb) + ' ')
        nb = nb + 1
        textoVtk.write(str(nb) + ' ')
        nb = nb + 1
        textoVtk.write('\n')
    
    textoVtk.write('POINT_DATA ' + '18' + '\n')
    textoVtk.close()