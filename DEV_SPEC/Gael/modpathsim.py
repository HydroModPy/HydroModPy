import sys
import os.path as pth
import flopy
import numpy as np
import matplotlib.pyplot as plt
import collections

import util
from modpath import modpath_model as _mp

class PathlineFile(flopy.utils.PathlineFile):
    def get_alldata(self, totim=None, ge=True):
        if totim is not None:
            if ge:
                idx = self._data['time'] >= totim
            else:
                idx = self._data['time'] <= totim
        else:
            idx = slice(None, None, None) # All values
        ta = self._data[idx]
        names = ["x", "y", "z", "time", "k", "particleid"]
        ta2 = np.rec.fromarrays(
            (ta[name] for name in names), dtype=self.outdtype
        )
        index = collections.defaultdict(list)
        i = 0
        for pid in ta['particleid']:
            index[pid].append(i)
            i += 1

        return [
            ta2[index[partid]] for partid in self.nid
        ]

class MpModel(_mp):
    def __init__(self, model_folder=None, exe=None, **kwargs):
        if model_folder is None:
            model_folder = util.mfpath
        if exe is None:
            exe = util.mp6_exe
        _mp.__init__(self, model_folder=model_folder, exe=exe, **kwargs)

    def extract_data(self):
        pathobj = PathlineFile(pth.join(self.full_path, self.model_name+'.mppth'))
        path_data = pathobj.get_alldata()
        npath = len(path_data)
        path_index = np.zeros((npath, 2), dtype=int)

        path_raw = np.concatenate(path_data)
        model_shape = self.mf.dis.top.array.shape
        path_length = np.zeros(model_shape)
        path_time = np.zeros(model_shape)
        path_samples = np.zeros(model_shape, dtype=int)

        n = 0
        i0 = 0
        for line in path_data:
            origin = self.point_data[line['particleid']]
            x, y = origin['i0'], origin['j0']
            path_samples[x,y] += 1
            dist = 0.
            n0 = line[0]
            for n1 in line[1:]:
                dist += ((n0['x']-n1['x'])**2 + (n0['y']-n1['y'])**2)**0.5
                n0 = n1
            path_length[x,y] += dist
            path_time[x,y] += line['time'][-1]

            i1 = i0 + len(line)
            path_index[n] = (i0, i1)
            i0 = i1
            n += 1
        valid = path_samples > 0
        path_length[valid] /= path_samples[valid]
        path_time[valid] /= path_samples[valid]

        data = {
            'path': path_raw,
            'path_index': path_index,
            'path_length': path_length,
            'path_time': path_time,
            'path_samples': path_samples,
            'points': self.point_data,
        }

        return data

    def export_data(self):
        base_path = pth.dirname(self.full_path)
        data_path = pth.join(base_path, 'data.npz')
        data = self.extract_data()
        if pth.isfile(data_path):
            old_data = np.load(data_path)
        else:
            old_data = {}
        np.savez_compressed(data_path, **data, **old_data)
