"""Typed exception hierarchy for HydroModPy.

Canonical source for every ``*Error`` raised by the package. All exceptions
inherit from :class:`HydroModPyError`, which carries optional ``sim_id`` and
``run_id`` context plus a ``code`` class attribute used by the CLI to map
failures to exit codes and stable user-facing messages.

See ``architecture_cible/13_coherence_globale.md`` §1.5 for the canonical
code assignments. Codes follow the ``HMPY.Exxx`` convention.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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

    @classmethod
    def title(cls) -> str:
        """Return a one-line human title for this class of failure.

        The first line of the class docstring, which every class in this module
        carries. Under ``python -OO`` docstrings are stripped and the class name
        is returned instead: a degraded title, never a wrong one.
        """
        doc = cls.__doc__
        if not doc:
            return cls.__name__
        return doc.strip().splitlines()[0].strip()

    def to_dict(self) -> dict[str, Any]:
        """Render the failure as a typed problem object.

        The shape a caller outside this process reads: a ``urn:`` type that
        resolves to nothing on purpose (no domain is registered), the stable
        ``HMPY.Exxx`` code, a title from the class and the detail from the
        instance. Subclasses add their own members by overriding and updating.
        """
        payload: dict[str, Any] = {
            "type": f"urn:hmp:error:{self.code}",
            "code": self.code,
            "title": self.title(),
            "detail": self.message or str(self),
        }
        if self.sim_id is not None:
            payload["sim_id"] = self.sim_id
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        return payload


# -- Configuration -------------------------------------------------------------


class ConfigError(HydroModPyError):
    """Configuration loading, validation, or resolution failure."""

    code = "HMPY.E100"


class ConfigValidationError(ConfigError):
    """The configuration document failed validation."""

    code = "HMPY.E101"

    def __init__(
        self,
        message: str = "",
        *,
        details: Iterable[Mapping[str, Any]] = (),
        source: str | None = None,
        sim_id: str | None = None,
        run_id: str | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message, sim_id=sim_id, run_id=run_id, **context)
        self.details: tuple[dict[str, Any], ...] = tuple(dict(entry) for entry in details)
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        """Add the per-field faults, each with its RFC 6901 JSON Pointer.

        A front end highlights the offending widget from ``pointer``; the flat
        ``detail`` string cannot be pointed at anything. When validation
        produced no structured fault — a refusal raised before the model runs —
        ``details`` is absent rather than an empty list pretending to be one.
        """
        payload = super().to_dict()
        if self.source is not None:
            payload["source"] = self.source
        if self.details:
            payload["details"] = [dict(entry) for entry in self.details]
        return payload


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


class DataRequestError(DataError):
    """A fetch request is malformed, before any source is asked to serve it.

    Separate from :class:`DataSourceError`, which means a source was reached
    and refused: the caller fixes this one without the network being up.
    """

    code = "HMPY.E207"


class DataCapabilityError(DataError):
    """The selected data source does not serve the requested option.

    A refusal, never a silent substitution: a caller asking a static reference
    network for a time window, or a bbox source for station identifiers, is
    told so by name rather than handed a result that ignores the argument.
    """

    code = "HMPY.E208"


class DataProductError(DataError):
    """What a source returned does not satisfy what it declared.

    Raised when the payload of a result does not match the kind the result
    carries, or when records claim a variable the source does not serve.
    """

    code = "HMPY.E209"


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


# -- Terrain -------------------------------------------------------------------
# ``cli.helpers.exit_code_for`` maps the family to EXIT_SOLVER_ERROR since the
# terrain-delineate capability made it reachable: the geospatial backend
# failing is what code 15 means at a process boundary. Until then the family
# had no entry, because an exit code nothing reaches is an untested branch.


class TerrainError(HydroModPyError):
    """Terrain engine failure."""

    code = "HMPY.E1000"


class TerrainCapabilityError(TerrainError):
    """The selected terrain engine does not implement the requested option.

    A refusal, never a silent substitution: a caller asking for a conditioning
    method or a pointer convention an engine cannot produce is told so by name.
    """

    code = "HMPY.E1001"


class TerrainProductError(TerrainError):
    """A terrain product does not satisfy what the member it is passed to needs.

    Raised when a flow-accumulation raster is handed to a member that declares
    it needs untransformed cell counts, and when a product comes out empty.
    """

    code = "HMPY.E1002"


class TerrainRequestError(TerrainError):
    """The request itself is malformed, before any engine is asked to serve it."""

    code = "HMPY.E1003"


class EmptyCatchmentError(TerrainProductError):
    """An outlet delineated nothing at all.

    Its own class and not a message, because a caller decides on it: the
    geographic pipeline retries a breached DEM with a fill when a breach carves
    the outlet off its own catchment, and reading that decision out of the text
    of an error message is how the next rewording breaks it silently.
    """

    code = "HMPY.E1004"


# -- Process boundary ----------------------------------------------------------
# Raised when a capability is invoked as an external process, before and around
# whatever the capability itself does. Both carry a code an orchestrator maps
# without reading a message.


class JobUsageError(HydroModPyError):
    """The job directory is not usable as the caller gave it.

    Its own class because it maps to exit 2: the caller got the invocation
    wrong, which is a different fact from the job failing at its work, and a
    shim retries one and not the other.
    """

    code = "HMPY.E1100"


class CapabilityVersionMismatchError(HydroModPyError):
    """The request targets a different major version of the capability."""

    code = "HMPY.E1101"


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


class ObservableNotAvailableError(SolverError):
    """Solver adapter cannot produce the requested observable for this run.

    Distinct from :class:`IncompatibleCapabilitiesError`, which is raised at
    configuration time against a solver's declared capabilities. This one is
    raised during extraction, about one named observable of one run, and it is
    what replaces reading an adapter's signature to guess what it supports.
    """

    code = "HMPY.E408"


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


class JournalError(PipelineError):
    """Workflow journal write/read inconsistency."""

    code = "HMPY.E508"


class ResumeIntegrityError(ResumeError):
    """A completed-step artefact failed integrity verification on resume."""

    code = "HMPY.E509"


class WorkflowDAGCycleError(PipelineError):
    """The workflow DAG declaration contains a dependency cycle."""

    code = "HMPY.E510"


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


class ReadOnlyError(CatalogError):
    """A write was attempted against a read-only catalog."""

    code = "HMPY.E803"


class WriteConflictError(CatalogError):
    """A concurrent writer holds the catalog and a write cannot proceed."""

    code = "HMPY.E804"


class CrossProjectsError(CatalogError):
    """An operation crossed project boundaries that must stay isolated."""

    code = "HMPY.E805"


class BackupFailedError(CatalogError):
    """The pre-migration catalog backup could not be written."""

    code = "HMPY.E806"


class MigrationFailedError(CatalogError):
    """A catalog schema migration failed to apply."""

    code = "HMPY.E807"


class ZarrStoreError(StorageError):
    """Zarr store read/write failure."""

    code = "HMPY.E802"


# -- Results -------------------------------------------------------------------


class ResultsError(HydroModPyError):
    """Results / postprocessing failure."""

    code = "HMPY.E900"


class UnknownFieldError(ResultsError):
    """Requested field name is not registered in the canonical field registry."""

    code = "HMPY.E901"

    def __init__(
        self,
        name: str,
        available: Iterable[str],
        *,
        sim_id: str | None = None,
        run_id: str | None = None,
        **context: Any,
    ) -> None:
        avail = tuple(sorted(available))
        message = (
            f"Field {name!r} is not registered. Available fields: {', '.join(avail)}"
            if avail
            else f"Field {name!r} is not registered."
        )
        super().__init__(message, sim_id=sim_id, run_id=run_id, **context)
        self.name = name
        self.available = avail


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
    "DataCacheError",
    "CacheCorruptionError",
    "DataSourceError",
    "NetworkError",
    "MissingForcingError",
    "DataRequestError",
    "DataCapabilityError",
    "DataProductError",
    # Mesh
    "MeshError",
    "MeshGenerationError",
    "IncompatibleMeshError",
    # Terrain
    "TerrainError",
    "TerrainCapabilityError",
    "TerrainProductError",
    "TerrainRequestError",
    "EmptyCatchmentError",
    # Process boundary
    "JobUsageError",
    "CapabilityVersionMismatchError",
    # Solver
    "SolverError",
    "SolverDivergedError",
    "SolverTimeoutError",
    "SolverBinaryError",
    "SolverMassBalanceError",
    "SolverInputError",
    "SolverEnvironmentError",
    "IncompatibleCapabilitiesError",
    "ObservableNotAvailableError",
    # Pipeline
    "PipelineError",
    "StepError",
    "CheckpointError",
    "LedgerError",
    "ResumeError",
    "ResumeIntegrityError",
    "JournalError",
    "ExtractError",
    "ExportError",
    "WorkspaceLockedError",
    "WorkflowDAGCycleError",
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
    "ReadOnlyError",
    "WriteConflictError",
    "CrossProjectsError",
    "BackupFailedError",
    "MigrationFailedError",
    "ZarrStoreError",
    # Results
    "ResultsError",
    "UnknownFieldError",
]
