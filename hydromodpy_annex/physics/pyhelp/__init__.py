"""hydromodpy_annex.physics.pyhelp

Layout:
- core/: PyHELP scientific model
- preprocessing/: integration layer to generate/stage inputs, run core in-process, and export NetCDF
"""

from __future__ import annotations

from importlib import import_module

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

_LAZY_IMPORTS = {
    "PyhelpGridParams": "hydromodpy_annex.physics.pyhelp.preprocessing.config:PyhelpGridParams",
    "PyhelpPreprocessingConfig": "hydromodpy_annex.physics.pyhelp.preprocessing.config:PyhelpPreprocessingConfig",
    "export_netcdf": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:export_netcdf",
    "prepare_inputs": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:prepare_inputs",
    "preprocess": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:preprocess",
    "preprocessing_pyhelp": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:preprocessing_pyhelp",
    "preprocessing_pyhelp_netcdf": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:preprocessing_pyhelp_netcdf",
    "run_help": "hydromodpy_annex.physics.pyhelp.preprocessing.pipeline:run_help",
}


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
