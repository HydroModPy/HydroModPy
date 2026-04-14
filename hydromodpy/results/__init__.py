"""Result storage for HydroModPy simulations (DuckDB + Zarr)."""

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.config import ResultsConfig

__all__ = ["SimulationCatalog", "ResultsConfig"]
