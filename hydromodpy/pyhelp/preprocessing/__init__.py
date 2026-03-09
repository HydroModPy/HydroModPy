from hydromodpy.hydrology.pyhelp import preprocessing as _preprocessing

def __getattr__(name):
    return getattr(_preprocessing, name)
