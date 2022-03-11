# coding: utf-8

import os, re
import numpy as np
from osgeo import gdal
import flopy
from flopy.export import vtk as fv
#import vtk
from workingFunctions import Functions  # functions from the workingFunctions.py file
import flopy.utils.binaryfile as fpu
from get_geological_structure import get_geological_structure as ggs

def vtk_export_watertable(modelname, modelfolder, coord):
    def GetExtent(gt, geotx, geoty, cols, rows):
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

    mf1 = flopy.modflow.Modflow.load(modelfolder + modelname + '.nam', verbose=False, check=False,
                                     load_only=['upw', 'dis'])
    hk = mf1.upw.hk
    geot_w, geotx_w, geoty_w, demData_w, lay_wt_w, lay_ft_w, lay_kb_w, lay_kf_w, lay_kw_w, sea_earth_w, river_w = ggs(coord)
    cols = demData_w.shape[1]
    rows = demData_w.shape[0]
    ext = GetExtent(geot_w, geotx_w, geoty_w, cols, rows)

    # change directory to the script path
    os.chdir(modelfolder)  # use your own path

    # open the DIS, BAS and FHD and DRN files
    disLines = open(modelfolder+modelname+'.dis').readlines()  # discretization data
    basLines = open(modelfolder+modelname+'.bas').readlines()  # active / inactive data
    hds = fpu.HeadFile(modelfolder+modelname+'.hds')
    times = hds.get_times()
    kstpkper = hds.get_kstpkper()
    tsn = [3652,7305,10957,14610,15340]
    #tsn = [3653,7306,10958,14611,15341]
    # if len(kstpkper) > 1:
    #     tsn = [0, int((len(kstpkper) - 1) / 2), (len(kstpkper) - 1)]
    # else:
    #     tsn = kstpkper

    textoVtk = open(modelfolder+'output_files/VTU_WaterTable.pvd', 'w')
    textoVtk.write('<VTKFile type="Collection" version="0.1">\n')
    textoVtk.write('  <Collection>\n')
    for time_step in tsn:
        #time_step = tsn[time_step_num]
        textoVtk.write('    <DataSet timestep="' + str(time_step) + '" part="0" file="'+modelfolder+'output_files/VTU_WaterTable_' + str(
            time_step) + '.vtu" />\n')
    textoVtk.write('  </Collection>\n')
    textoVtk.write('</VTKFile>\n')
    textoVtk.close()

    for time_step in tsn:
        #time_step = tsn[time_step_num]
        ind = 0
        while (times[ind] != time_step): #+1 if ref
            ind+=1 
        tim = ind
        print(time_step)
        # create a empty dictionay to store the model features
        modDis = {}
        modBas = {}
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
        head = hds.get_data(kstpkper=kstpkper[tim])
        for i in range(0, head.shape[0]):
            modFhd['cellHeadGrid']['lay' + str(lay)] = head[i]
            lay += 1

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
                        if item > -1e+30:
                            headList.append(item)
                    if len(headList) > 0:
                        headMean = sum(headList) / len(headList)
                    else:
                        headMean = -1e+30

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
                        if item > -1e+30:
                            headList.append(item)
                    if len(headList) > 0:
                        headMean = sum(headList) / len(headList)
                    else:
                        headMean = -1e+30

                    matrix[row, col] = headMean

            matrix[-1, :-1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, :]
            matrix[:-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][:, -1]
            matrix[-1, -1] = modFhd['cellHeadGrid']['lay' + str(lay)][-1, -1]

            vertexHKGridCentroid['lay' + str(lay)] = matrix

        # In[15]:

        modFhd['vertexHeadGrid'] = {}
        for lay in range(modDis['vertexLays']):
            anyGrid = vertexHeadGridCentroid
            if lay == modDis['cellLays']:
                modFhd['vertexHeadGrid']['lay' + str(lay)] = anyGrid['lay' + str(lay - 1)]
            elif lay == 0:
                modFhd['vertexHeadGrid']['lay0'] = anyGrid['lay0']
            else:

                value = np.where(anyGrid['lay' + str(lay)] > -1e+30,
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
                if list(a[a > -1e+10]) != []:  # just in case there are some inactive zones
                    waterTableVertexGrid[row, col] = a[a > -1e+10][0]
                else:
                    waterTableVertexGrid[row, col] = -1e+10

        # empty list to store all vertex Water Table XYZ
        vertexWaterTableXYZPoints = []
        # definition of xyz points for all vertex
        for row in range(modDis['vertexRows']):
            for col in range(modDis['vertexCols']):
                if waterTableVertexGrid[row, col] > -1e+10:
                    waterTable = waterTableVertexGrid[row, col]
                else:
                    waterTable = 1000
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
                if list(a[a > -1e+10]) != []:  # just in case there are some inactive zones
                    waterTableCellGrid[row, col] = a[a > -1e+10][0]
                else:
                    waterTableCellGrid[row, col] = -1e+10

        listWaterTableCell = list(waterTableCellGrid.flatten())

        listWaterTableQuadSequenceDef = []
        listWaterTableCellDef = []
        listDrawdownCellDef = []
        for item in range(len(listWaterTableCell)):
            if listWaterTableCell[item] > -1e10:
                listWaterTableQuadSequenceDef.append(listLayerQuadSequence[item])
                listWaterTableCellDef.append(listWaterTableCell[item])
        for item in range(len(listWaterTableCellDef)):
            drawdown = modDis['cellCentroidZList']['lay0'][item] - listWaterTableCellDef[item]
            listDrawdownCellDef.append(drawdown)

        textoVtk = open(modelfolder+'output_files/VTU_WaterTable_' + str(time_step) + '.vtu', 'w')
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
            elif item == len(vertexWaterTableXYZPoints) - 1:
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




