"""HydroModPy configuration module."""


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

        return HydroModPyConfig
    if name == "AnalysisConfig":
        from hydromodpy.master_config.analysis import AnalysisConfig

        return AnalysisConfig
    if name == "PersistenceConfig":
        from hydromodpy.master_config.persistence import PersistenceConfig

        return PersistenceConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AnalysisConfig", "HydroModPyConfig", "PersistenceConfig"]
