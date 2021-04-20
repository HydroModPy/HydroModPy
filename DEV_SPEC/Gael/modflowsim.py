import sys
import os.path as pth
import flopy
import numpy as np
import json
import matplotlib.pyplot as plt

import util
from modflow import modflow_model as _mf

class MfModel(_mf):
    def extract_data(self):
        ztop = self.mf.dis.top.array
        zbot = self.mf.dis.botm.array
        headfile = pth.join(self.full_path, self.model_name+'.hds')
        head = flopy.utils.HeadFile(headfile).get_data()
        data = {
            'ztop': ztop,
            'zbot': zbot,
            'head': head,
        }
        metadata = {
            'dem_path': self.dem_path,
            'watershed': self.watershed,
            'model_name': self.model_name,
            'climatic': self.climatic,
            'thick': self.thick if self.bottom is None else None,
            'bottom': self.bottom,
            'nlay': self.nlay,
            'hyd_cond': self.hyd_cond,
            'porosity': self.porosity,
            'projection': {
                'crs': self.dem.crs,
                'geodata': self.dem.geodata,
                'bbox': [self.dem.xmin, self.dem.ymin, self.dem.xmax, self.dem.ymax],
            }
        }

        return data, metadata

    def export_data(self):
        base_path = pth.dirname(self.full_path)
        data, metadata = self.extract_data()
        np.savez_compressed(pth.join(base_path, 'data.npz'), **data)
        with open(pth.join(base_path, 'meta.json'), 'w') as f:
            json.dump(metadata, f, indent=4)
