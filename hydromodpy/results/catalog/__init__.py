"""Catalog facade for the results layer.

Central registry for finished simulations. Backed by DuckDB for tabular state
and by Zarr / Parquet for field arrays and timeseries written under the
workspace.

Public API
----------
- :class:`SimulationCatalog`: connection-managed entry point. Methods cover
  registration (``register_simulation``), per-simulation writers
  (``write_parameters``, ``write_timeseries``, ``write_budget``,
  ``write_field``, ``write_mesh`` ...), readers / queries (``query_field``,
  ``query_timeseries``, ``list_simulations``, ``sql``), reference resolution
  (``resolve``, ``__getitem__``, ``find``, ``latest``, ``best``), and lifecycle
  helpers (``finalize``, ``cleanup``, ``export_package``, ``import_package``,
  ``delete``).
- :class:`RegistrationResult`: dataclass returned by ``register_simulation``.
- Errors: :class:`SimulationNotFoundError`, :class:`AmbiguousReferenceError`,
  :class:`DuplicateSimulationNameError`.
- :func:`short_id`: Git-style short identifier (first 8 hex chars).
"""

from hydromodpy.results.catalog.discovery import (
    AmbiguousReferenceError,
    SimulationNotFoundError,
    short_id,
)
from hydromodpy.results.catalog.facade import SimulationCatalog
from hydromodpy.results.catalog.registration import (
    DuplicateSimulationNameError,
    RegistrationResult,
)

__all__ = [
    "AmbiguousReferenceError",
    "DuplicateSimulationNameError",
    "RegistrationResult",
    "SimulationCatalog",
    "SimulationNotFoundError",
    "short_id",
]
