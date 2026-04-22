"""hydromodpy.physics.hydrology.pyhelp

Layout:
- core/: PyHELP scientific model (do not modify lightly)
- preprocessing/: integration layer to generate/stage inputs, run core in-process, and export NetCDF
"""

from .preprocessing.config import PyhelpGridParams, PyhelpPreprocessingConfig
from .preprocessing.pipeline import (
    export_netcdf,
    prepare_inputs,
    preprocess,
    preprocessing_pyhelp,
    preprocessing_pyhelp_netcdf,
    run_help,
)

__all__ = [
    "PyhelpPreprocessingConfig",
    "PyhelpGridParams",
    "preprocessing_pyhelp",
    "preprocessing_pyhelp_netcdf",
    "preprocess",
    "prepare_inputs",
    "run_help",
    "export_netcdf",
]
