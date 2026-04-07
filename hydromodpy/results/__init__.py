"""Result storage for HydroModPy simulations (DuckDB + Zarr).

Public API
----------
ResultStore : class
    Unified read/write interface for simulation results.
ResultsConfig : class
    Pydantic configuration for ``[simulation.results]``.
"""

from hydromodpy.results.config import ResultsConfig
from hydromodpy.results.store import ResultStore

__all__ = ["ResultStore", "ResultsConfig"]
