import numpy as np
import os
import json
import sys

with open(os.path.join(os.path.dirname(__file__), 'conf.json')) as f:
    conf = json.load(f)

mfpath = os.path.expanduser(conf['path']['modflow'])
fspath = os.path.expanduser(conf['path']['fastscape'])
mfnwt_exe = conf['exe']['mfnwt']
mp6_exe = conf['exe']['mp6']

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'CORE_COMM', 'src')))

def get_base_path(watershed=None, modflow_model=None):
    elements = [path]
    if watershed is not None:
        elements.append(watershed)
        if modflow_model is not None:
            element.append(modflow_model)
    return os.path.join(*elements)

def modflow_file(watershed='name', model_name='modflow_model', ext='nam'):
    ext = '.' + ext.lstrip('.')
    return os.path.join(mfpath, watershed, model_name, 'modraw', model_name+ext)

def load_data(watershed='name', model_name='modflow_model'):
    return np.load(os.path.join(mfpath, watershed, modflow_model, 'data.npz'))

def load_meta(watershed='name', model_name='modflow_model'):
    with open(os.path.join(mfpath, watershed, modflow_model, 'meta.json')) as f:
        return json.load(f)
