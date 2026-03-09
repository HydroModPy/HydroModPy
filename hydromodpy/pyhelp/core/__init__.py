from hydromodpy.hydrology.pyhelp import core as _core

def __getattr__(name):
    return getattr(_core, name)
