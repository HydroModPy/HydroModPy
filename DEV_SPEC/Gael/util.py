import numpy as np
import os
import json
import sys
root = sys.path[0]
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'CORE_COMM', 'src')))
sys.path.append(os.path.join(root, 'HydroModPy', 'CORE_COMM', 'src'))

def get_base_path(watershed=None, modflow_model=None):
    elements = [os.path.dirname(os.getcwd()), 'output']
    if watershed is not None:
        elements.append(watershed)
        if modflow_model is not None:
            element.append(modflow_model)
    return os.path.join(*elements)

def modflow_file(watershed='name', model_name='modflow_model', ext='nam'):
    ext = '.' + ext.lstrip('.')
    return os.path.join(os.path.dirname(os.getcwd()), watershed, model_name, 'modraw', model_name+ext)

def load_data(watershed='name', model_name='modflow_model'):
    return np.load(os.path.join(os.path.dirname(os.getcwd()), 'output', watershed, modflow_model, 'data.npz'))

def load_meta(watershed='name', model_name='modflow_model'):
    with open(os.path.join(os.path.dirname(os.getcwd()), 'output', watershed, modflow_model, 'meta.json')) as f:
        return json.load(f)
