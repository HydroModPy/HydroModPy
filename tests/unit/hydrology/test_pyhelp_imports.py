import importlib


def test_pyhelp_new_and_legacy_imports_resolve_same_entry_points():
    new_pkg = importlib.import_module("hydromodpy.hydrology.pyhelp")
    legacy_pkg = importlib.import_module("hydromodpy.hydrology.pyhelp")
    new_pipeline = importlib.import_module("hydromodpy.hydrology.pyhelp.pyhelp_netcdf")
    legacy_pipeline = importlib.import_module("hydromodpy.hydrology.pyhelp.pyhelp_netcdf")
    legacy_core_processing = importlib.import_module("hydromodpy.hydrology.pyhelp.core.processing")
    legacy_preprocessing_pipeline = importlib.import_module("hydromodpy.hydrology.pyhelp.preprocessing.pipeline")
    new_core_processing = importlib.import_module("hydromodpy.hydrology.pyhelp.core.processing")
    new_preprocessing_pipeline = importlib.import_module("hydromodpy.hydrology.pyhelp.preprocessing.pipeline")

    assert legacy_pkg.preprocessing_pyhelp is new_pkg.preprocessing_pyhelp
    assert legacy_pkg.preprocessing_pyhelp_netcdf is new_pkg.preprocessing_pyhelp_netcdf
    assert legacy_pipeline.preprocessing_pyhelp_netcdf is new_pipeline.preprocessing_pyhelp_netcdf
    assert legacy_core_processing.read_daily_help_output is new_core_processing.read_daily_help_output
    assert legacy_preprocessing_pipeline.preprocessing_pyhelp is new_preprocessing_pipeline.preprocessing_pyhelp
