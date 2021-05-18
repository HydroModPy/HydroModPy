#!/usr/bin/env python3
#import util
import numpy as np

def get_critical_drainage(drainage, is_seepage):
    drnflat = drainage.flatten()
    #seepflat = is_seepage.flatten()
    drnorder = np.argsort(drnflat)
    seeporder = is_seepage.flatten()[drnorder]
    varyline = np.cumsum(seeporder*2-1)

    minorder = varyline.argmin()
    drncritical = drnflat[drnorder[minorder]]
    return drncritical

if __name__ == '__main__':
    import sys
    import util
    from osgeo import gdal
    import os

    drncritical = np.zeros((9, 16))
    for i in range(9):
        terrain = 'U{:d}T'.format(i+1)
        drainage_file = os.path.join(util.fspath, 'topo_uplift', 'U{:d}D.tif'.format(i+1))
        drn = gdal.Open(drainage_file).ReadAsArray()
        j = 0
        for model in util.loop_models(terrain):
            #print(j, model)
            desc = {'watershed': terrain, 'model_name': model}
            data = util.load_data(**desc)
            is_seepage = data['outflow'][0] > 0
            drnc = get_critical_drainage(drn, is_seepage)
            #print(i,j, drnc)
            drncritical[i,j] = drnc
            #print(drnc)
            
            j += 1
        #print(drncritical)
    #print(drncritical)
    np.savetxt('drncritical_U.txt', drncritical)
