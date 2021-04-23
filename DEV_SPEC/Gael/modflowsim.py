import sys
import os.path as pth
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
import json
import matplotlib.pyplot as plt

import util
from modflow import modflow_model as _mf

class MfModel(_mf):
    def __init__(self, dem_path, model_folder=None, exe=None, **kwargs):
        dem_path = pth.join(util.fspath, dem_path)
        if model_folder is None:
            model_folder = util.mfpath
        if exe is None:
            exe = util.mfnwt_exe
        _mf.__init__(self, dem_path, model_folder=model_folder, exe=exe, **kwargs)

    def get_dem_metadata(self):
        md1 = self.dem.dem.GetMetadata()
        md2 = self.dem.dem.GetRasterBand(1).GetMetadata()
        md2.update(md1)
        metadata = {}
        for k, v in md2.items():
            try:
                vn = float(v)
            except ValueError:
                vn = v
            metadata[k] = vn
        return metadata

    def extract_data(self):
        ztop = self.mf.dis.top.array
        zbot = self.mf.dis.botm.array
        headfile = pth.join(self.full_path, self.model_name+'.hds')
        cbcfile = pth.join(self.full_path, self.model_name+'.cbc')
        head = fpu.HeadFile(headfile).get_data()
        drn = fpu.CellBudgetFile(cbcfile).get_data(text='DRAINS', full3D=True)
        outflow = -drn[0].filled(fill_value=0.)
        data = {
            'ztop': ztop,
            'zbot': zbot,
            'head': head,
            'outflow': outflow,
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
            },
            'dem_metadata': self.get_dem_metadata(),
        }

        return data, metadata

    def export_data(self):
        base_path = pth.dirname(self.full_path)
        data, metadata = self.extract_data()
        np.savez_compressed(pth.join(base_path, 'data.npz'), **data)
        with open(pth.join(base_path, 'meta.json'), 'w') as f:
            json.dump(metadata, f, indent=4)
