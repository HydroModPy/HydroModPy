"""Domain-specific exception hierarchy for HydroModPy."""


class HydroModPyError(Exception):
    """Base exception for all HydroModPy errors."""


class ConfigError(HydroModPyError):
    """Invalid or inconsistent configuration."""


class SolverError(HydroModPyError):
    """Solver execution or setup failure."""


class DataError(HydroModPyError):
    """Data loading, validation, or registry failure."""


class MeshError(HydroModPyError):
    """Mesh generation or processing failure."""
