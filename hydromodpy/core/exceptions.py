"""Typed exception hierarchy for HydroModPy.

Canonical source for every ``*Error`` raised by the package. All exceptions
inherit from :class:`HydroModPyError`, which carries optional ``sim_id`` and
``run_id`` context plus a ``code`` class attribute used by the CLI to map
failures to exit codes and stable user-facing messages.

See ``architecture_cible/13_coherence_globale.md`` §1.5 for the canonical
code assignments. Codes follow the ``HMPY.Exxx`` convention.
"""

from __future__ import annotations

from typing import Any


class HydroModPyError(Exception):
    """Base class for all HydroModPy exceptions.

    Parameters
    ----------
    message:
        Human-readable error message.
    sim_id, run_id:
        Optional identifiers propagated by the pipeline before reraising.
    **context:
        Arbitrary key/value context kept on the exception for logging.
    """

    code: str = "HMPY.E000"

    def __init__(
        self,
        message: str = "",
        *,
        sim_id: str | None = None,
        run_id: str | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.sim_id = sim_id
        self.run_id = run_id
        self.context = context


# -- Configuration -------------------------------------------------------------


class ConfigError(HydroModPyError):
    """Configuration loading, validation, or resolution failure."""

    code = "HMPY.E100"


class ConfigValidationError(ConfigError):
    """Pydantic validation error surfaced as a typed exception."""

    code = "HMPY.E101"


class ConfigMissingError(ConfigError):
    """A required configuration section or key is missing."""

    code = "HMPY.E102"


class ImplicitInferenceError(ConfigError):
    """Data inference triggered a type not whitelisted in ``strict`` mode."""

    code = "HMPY.E103"


class SchemaVersionTooNewError(ConfigError):
    """TOML schema version is newer than the installed HydroModPy."""

    code = "HMPY.E104"


class UnitAliasConflict(ConfigError):
    """Duplicate / conflicting unit alias registration."""

    code = "HMPY.E105"


# -- Data ----------------------------------------------------------------------


class DataError(HydroModPyError):
    """Input data loading, validation, or provenance failure."""

    code = "HMPY.E200"


class DataContractViolation(DataError):
    """A dataset does not satisfy its declared contract."""

    code = "HMPY.E201"


class ContractViolationError(DataContractViolation):
    """Alias retained for compatibility with spec §1.5 naming."""

    code = "HMPY.E201"


class DataCacheError(DataError):
    """Local cache corruption or inconsistency."""

    code = "HMPY.E202"


class CacheCorruptionError(DataCacheError):
    """Cache hit with an invalid fingerprint or unreadable payload."""

    code = "HMPY.E203"


class DataSourceError(DataError):
    """Remote data source (HTTP/FTP) refused or returned invalid data."""

    code = "HMPY.E204"


class NetworkError(DataSourceError):
    """HTTP 5xx, 429, or timeout while fetching a remote dataset."""

    code = "HMPY.E205"


class MissingForcingError(DataError):
    """Required climatic / hydrometric forcing is absent for the period."""

    code = "HMPY.E206"


# -- Mesh ----------------------------------------------------------------------


class MeshError(HydroModPyError):
    """Mesh generation or consistency failure."""

    code = "HMPY.E300"


class MeshGenerationError(MeshError):
    """Mesh generator (gmsh / FloPy helper) failed to produce a valid mesh."""

    code = "HMPY.E301"


class IncompatibleMeshError(MeshError):
    """Two meshes expected to be congruent are not."""

    code = "HMPY.E302"


# -- Solver --------------------------------------------------------------------


class SolverError(HydroModPyError):
    """Solver execution failure.

    ``sim_id`` and ``run_id`` are canonical attributes exposed on the base
    class so that pipeline code can read ``exc.sim_id`` without downcasting.
    """

    code = "HMPY.E400"


class SolverDivergedError(SolverError):
    """Solver reported non-convergence."""

    code = "HMPY.E401"


class SolverTimeoutError(SolverError):
    """Solver exceeded the configured wall-clock budget."""

    code = "HMPY.E402"


class SolverBinaryError(SolverError):
    """Solver binary missing, unreadable, or crashed before producing output."""

    code = "HMPY.E403"


class SolverMassBalanceError(SolverError):
    """Mass balance residual exceeds the acceptance threshold."""

    code = "HMPY.E404"


class SolverInputError(SolverError):
    """Invalid or inconsistent package data passed to the solver."""

    code = "HMPY.E405"


class SolverEnvironmentError(SolverError):
    """Solver runtime environment (PATH, licences) is misconfigured."""

    code = "HMPY.E406"


class IncompatibleCapabilitiesError(SolverError):
    """Requested capability is not implemented by the selected solver."""

    code = "HMPY.E407"


# -- Pipeline ------------------------------------------------------------------


class PipelineError(HydroModPyError):
    """Pipeline orchestration failure."""

    code = "HMPY.E500"


class StepError(PipelineError):
    """A pipeline step raised an unrecoverable error.

    Always carries the offending ``step_name`` and the original ``cause``
    so callers can introspect the failure without unwrapping the chained
    ``__cause__`` reference.
    """

    code = "HMPY.E501"

    def __init__(
        self,
        step_name: str,
        cause: BaseException,
        *,
        run_id: str | None = None,
        sim_id: str | None = None,
        **context: Any,
    ) -> None:
        message = f"step {step_name!r} failed: {type(cause).__name__}: {cause}"
        super().__init__(message, sim_id=sim_id, run_id=run_id, **context)
        self.step_name = step_name
        self.cause = cause


class CheckpointError(PipelineError):
    """Checkpoint read/write failure."""

    code = "HMPY.E502"


class LedgerError(PipelineError):
    """Pipeline ledger (run history) corruption or write conflict."""

    code = "HMPY.E503"


class ResumeError(PipelineError):
    """Pipeline cannot resume (incompatible checkpoint / config drift)."""

    code = "HMPY.E504"


class ExtractError(PipelineError):
    """Result extraction failed after a successful solver run."""

    code = "HMPY.E505"


class ExportError(PipelineError):
    """Exporter (NetCDF / CSV / VTU / GeoTIFF) failed to serialise results."""

    code = "HMPY.E506"


class WorkspaceLockedError(PipelineError):
    """A concurrent process holds the workspace lock."""

    code = "HMPY.E507"


# -- Calibration ---------------------------------------------------------------


class CalibrationError(HydroModPyError):
    """Calibration loop failure."""

    code = "HMPY.E600"


class ObjectiveError(CalibrationError):
    """Objective function evaluation failure."""

    code = "HMPY.E601"


class OptimizerError(CalibrationError):
    """Optimizer backend (CMA, Optuna, ...) raised an unrecoverable error."""

    code = "HMPY.E602"


# -- Display -------------------------------------------------------------------


class DisplayError(HydroModPyError):
    """Figure rendering failure."""

    code = "HMPY.E700"


class FigureNotFoundError(DisplayError):
    """Requested figure name is not registered."""

    code = "HMPY.E701"


class BackendError(DisplayError):
    """Matplotlib / PyVista backend failure."""

    code = "HMPY.E702"


# -- Storage -------------------------------------------------------------------


class StorageError(HydroModPyError):
    """Catalog or Zarr storage failure."""

    code = "HMPY.E800"


class CatalogError(StorageError):
    """DuckDB catalog failure."""

    code = "HMPY.E801"


class ZarrStoreError(StorageError):
    """Zarr store read/write failure."""

    code = "HMPY.E802"


__all__ = [
    "HydroModPyError",
    # Config
    "ConfigError",
    "ConfigValidationError",
    "ConfigMissingError",
    "ImplicitInferenceError",
    "SchemaVersionTooNewError",
    "UnitAliasConflict",
    # Data
    "DataError",
    "DataContractViolation",
    "ContractViolationError",
    "DataCacheError",
    "CacheCorruptionError",
    "DataSourceError",
    "NetworkError",
    "MissingForcingError",
    # Mesh
    "MeshError",
    "MeshGenerationError",
    "IncompatibleMeshError",
    # Solver
    "SolverError",
    "SolverDivergedError",
    "SolverTimeoutError",
    "SolverBinaryError",
    "SolverMassBalanceError",
    "SolverInputError",
    "SolverEnvironmentError",
    "IncompatibleCapabilitiesError",
    # Pipeline
    "PipelineError",
    "StepError",
    "CheckpointError",
    "LedgerError",
    "ResumeError",
    "ExtractError",
    "ExportError",
    "WorkspaceLockedError",
    # Calibration
    "CalibrationError",
    "ObjectiveError",
    "OptimizerError",
    # Display
    "DisplayError",
    "FigureNotFoundError",
    "BackendError",
    # Storage
    "StorageError",
    "CatalogError",
    "ZarrStoreError",
]
