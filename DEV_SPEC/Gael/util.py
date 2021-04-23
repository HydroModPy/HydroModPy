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

def load_model(watershed='name', model_name='modflow_model'):
    import flopy
    return flopy.modflow.Modflow.load('{}.nam'.format(model_name), model_ws=get_base_path(watershed=watershed, model_name=model_name), exe_name=mfnwt_exe, version='mfnwt')

def get_base_path(watershed=None, model_name=None):
    elements = [mfpath]
    if watershed is not None:
        elements.append(watershed)
        if model_name is not None:
            elements.append(model_name)
            elements.append('modraw')
    return os.path.join(*elements)

def modflow_file(watershed='name', model_name='modflow_model', ext='nam'):
    ext = '.' + ext.lstrip('.')
    return os.path.join(mfpath, watershed, model_name, 'modraw', model_name+ext)

def load_data(watershed='name', model_name='modflow_model'):
    return np.load(os.path.join(mfpath, watershed, model_name, 'data.npz'))

def load_meta(watershed='name', model_name='modflow_model'):
    with open(os.path.join(mfpath, watershed, model_name, 'meta.json')) as f:
        return json.load(f)

def exists(watershed='name', model_name='modflow_model'):
    return os.path.isdir(os.path.join(mfpath, watershed, model_name))

def loop_models(watershed='name', model_name_struct='R{:d}'):
    i = 1
    model_name = model_name_struct.format(i)
    while True:
        if exists(watershed=watershed, model_name=model_name):
            yield model_name
            model_name = model_name_struct.format(i)
            i += 1
        else:
            return
