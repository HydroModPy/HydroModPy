"""hydromodpy.pyhelp

Layout:
- core/: PyHELP scientific model (do not modify lightly)
- preprocessing/: integration layer to generate/stage inputs, run core in-process, and export NetCDF
"""

from .preprocessing.config import PyhelpPreprocessingConfig, PyhelpGridParams
from .preprocessing.pipeline import (
    preprocessing_pyhelp,
    preprocess,
    prepare_inputs,
    run_help,
    export_netcdf,
)

__all__ = [
    "PyhelpPreprocessingConfig",
    "PyhelpGridParams",
    "preprocessing_pyhelp",
    "preprocess",
    "prepare_inputs",
    "run_help",
    "export_netcdf",
]
