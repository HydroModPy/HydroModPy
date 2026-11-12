"""Lazy-import maps for the top-level ``hydromodpy`` package facade.

Kept separate from ``__init__.py`` so the package init stays minimal. Every
value of ``LAZY_IMPORTS`` names ``hydromodpy.project.api``,
``hydromodpy.project.kept_readers`` or ``hydromodpy.core.exceptions``: the root
reads only ``core`` and ``project``.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.core.old_members import OLD_MEMBERS
from hydromodpy.project.old_paths import LEFT_BEFORE_2_0, RETIRED_MODULES


@dataclass(frozen=True, slots=True)
class OldName:
    """A name of ``hydromodpy.__all__`` that moved."""

    new: str
    """What replaces it: a name of ``hydromodpy.__all__``, the path of a refused name, or the
    call that replaces it. The part before ``(`` resolves."""
    since: str
    """The version that moved it. It leaves this table two minor versions later."""
    refused: bool = False
    """It left before the first stable version, so it has no alias: it is refused, with
    ``new`` in the message. An entry that is not refused warns and forwards."""


VERBS: tuple[str, ...] = (
    "open",
    "run",
    "check",
    "calibrate",
    "spinup",
    "replay",
    "stop",
    "status",
    "trash",
    "compare",
    "show",
    "export",
    "publish",
    "example",
    "doctor",
)
"""The fifteen verbs, in the order of ``hydromodpy.project.api.__all__``."""

OBJECTS: tuple[str, ...] = ("Project", "Run", "RunSet", "Session", "HydroModPyConfig")
"""The five objects the verbs take and return. ``hydromodpy.project.api`` imports them."""

# The frozen runs of a pre-release are read through these three names.
KEPT_READERS: tuple[str, ...] = ("read", "index", "Catalog")
"""The readers the top level keeps beside the verbs, from ``hydromodpy.project.kept_readers``."""

KEPT_EXCEPTIONS: tuple[str, ...] = (
    "HydroModPyError",
    # The class each exit code of ``hmp`` is mapped from, by its category.
    "CommandUsageError",
    "NothingThereError",
    "WriteConflictError",
    "ConfigError",
    "ConfigMissingError",
    "DataError",
    "CalibrationError",
    "FailedCasesError",
    "JobUsageError",
    "CapabilityVersionMismatchError",
    "SchemaVersionMismatchError",
    "ImportConflictError",
    "ReadOnlyError",
    "SolverError",
    "TerrainError",
    "CrossProjectsError",
    "BackupFailedError",
    "MigrationFailedError",
    "CatalogUnreadableError",
    "StepError",
    # The other categories of the hierarchy.
    "MeshError",
    "PipelineError",
    "DisplayError",
    "StorageError",
    "ResultsError",
    # What the facade raises for a name that left.
    "OldNameError",
)
"""The exceptions ``hydromodpy.__all__`` holds, all of ``hydromodpy.core.exceptions``.

A leaf stays importable from where it is defined (``hydromodpy.core.exceptions``,
``hydromodpy.results.errors`` or its own module) and is not frozen at the top level.
"""

_LEAF_EXCEPTIONS: dict[str, str] = {
    "BackendError": "hydromodpy.core.exceptions.BackendError",
    "BoundsError": "hydromodpy.core.exceptions.BoundsError",
    "CacheCorruptionError": "hydromodpy.core.exceptions.CacheCorruptionError",
    "CheckpointError": "hydromodpy.core.exceptions.CheckpointError",
    "ConfigValidationError": "hydromodpy.core.exceptions.ConfigValidationError",
    "CredentialsError": "hydromodpy.core.exceptions.CredentialsError",
    "DataCacheError": "hydromodpy.core.exceptions.DataCacheError",
    "DataCapabilityError": "hydromodpy.core.exceptions.DataCapabilityError",
    "DataContractViolation": "hydromodpy.core.exceptions.DataContractViolation",
    "DataProductError": "hydromodpy.core.exceptions.DataProductError",
    "DataRequestError": "hydromodpy.core.exceptions.DataRequestError",
    "DataSourceError": "hydromodpy.core.exceptions.DataSourceError",
    "EmptyCatchmentError": "hydromodpy.core.exceptions.EmptyCatchmentError",
    "ExportError": "hydromodpy.core.exceptions.ExportError",
    "ExtractError": "hydromodpy.core.exceptions.ExtractError",
    "FigureNotFoundError": "hydromodpy.core.exceptions.FigureNotFoundError",
    "FrozenConfigError": "hydromodpy.core.exceptions.FrozenConfigError",
    "FrozenDataError": "hydromodpy.core.exceptions.FrozenDataError",
    "ImplicitInferenceError": "hydromodpy.core.exceptions.ImplicitInferenceError",
    "IncompatibleCapabilitiesError": "hydromodpy.core.exceptions.IncompatibleCapabilitiesError",
    "IncompatibleMeshError": "hydromodpy.core.exceptions.IncompatibleMeshError",
    "JobInputNotFoundError": "hydromodpy.core.exceptions.JobInputNotFoundError",
    "JournalError": "hydromodpy.core.exceptions.JournalError",
    "LedgerError": "hydromodpy.core.exceptions.LedgerError",
    "MeshGenerationError": "hydromodpy.core.exceptions.MeshGenerationError",
    "MeshRequestError": "hydromodpy.core.exceptions.MeshRequestError",
    "MissingForcingError": "hydromodpy.core.exceptions.MissingForcingError",
    "MixedWindowsError": "hydromodpy.results.run.sealed.MixedWindowsError",
    "NetworkError": "hydromodpy.core.exceptions.NetworkError",
    "ObjectiveError": "hydromodpy.core.exceptions.ObjectiveError",
    "ObservableNotAvailableError": "hydromodpy.core.exceptions.ObservableNotAvailableError",
    "OptimizerError": "hydromodpy.core.exceptions.OptimizerError",
    "PointOutsideMeshError": "hydromodpy.results.run.point.PointOutsideMeshError",
    "ProjectNotFoundError": "hydromodpy.results.errors.ProjectNotFoundError",
    "ResumeError": "hydromodpy.core.exceptions.ResumeError",
    "ResumeIntegrityError": "hydromodpy.core.exceptions.ResumeIntegrityError",
    "RunNotFoundError": "hydromodpy.results.errors.RunNotFoundError",
    "SchemaVersionTooNewError": "hydromodpy.core.exceptions.SchemaVersionTooNewError",
    "SeveralCasesError": "hydromodpy.results.errors.SeveralCasesError",
    "SolverBinaryError": "hydromodpy.core.exceptions.SolverBinaryError",
    "SolverDivergedError": "hydromodpy.core.exceptions.SolverDivergedError",
    "SolverEnvironmentError": "hydromodpy.core.exceptions.SolverEnvironmentError",
    "SolverInputError": "hydromodpy.core.exceptions.SolverInputError",
    "SolverMassBalanceError": "hydromodpy.core.exceptions.SolverMassBalanceError",
    "SolverTimeoutError": "hydromodpy.core.exceptions.SolverTimeoutError",
    "TerrainCapabilityError": "hydromodpy.core.exceptions.TerrainCapabilityError",
    "TerrainProductError": "hydromodpy.core.exceptions.TerrainProductError",
    "TerrainRequestError": "hydromodpy.core.exceptions.TerrainRequestError",
    "TimeSelectionError": "hydromodpy.core.time.selection.TimeSelectionError",
    "UncertaintyNotAvailableError": "hydromodpy.core.exceptions.UncertaintyNotAvailableError",
    "UnitAliasConflict": "hydromodpy.core.exceptions.UnitAliasConflict",
    "UnknownFieldError": "hydromodpy.core.exceptions.UnknownFieldError",
    "UnrankedMetricError": "hydromodpy.results.catalog.constants.UnrankedMetricError",
    "WorkflowDAGCycleError": "hydromodpy.core.exceptions.WorkflowDAGCycleError",
    "WorkspaceLockedError": "hydromodpy.core.exceptions.WorkspaceLockedError",
    "ZarrStoreError": "hydromodpy.core.exceptions.ZarrStoreError",
}
"""The leaves of the hierarchy refused at the top level since 2.0.0, with their path.

Written as text and frozen: it only refuses names that left the top level.
"""

_LEFT_LEAVES: dict[str, str] = {
    "AmbiguousReferenceError": "hydromodpy.results.catalog.discovery.AmbiguousReferenceError",
    "CatalogError": "hydromodpy.core.exceptions.CatalogError",
    "ComparisonCaseError": "hydromodpy.project.compare.ComparisonCaseError",
    "ComparisonReferenceError": "hydromodpy.project.compare.ComparisonReferenceError",
    "FieldNotFoundError": "hydromodpy.results.errors.FieldNotFoundError",
    "RunNotSealedError": "hydromodpy.results.errors.RunNotSealedError",
    "SimulationNotFoundError": "hydromodpy.results.catalog.discovery.SimulationNotFoundError",
}
"""The seven exceptions of ``results`` and ``project`` that left the top level in 2.0.0."""

_LEFT_CALLS: dict[str, str] = {
    "figure": "hydromodpy.show(ref, what='figure', name=...)",
    "report": "hydromodpy.show(ref, what='report')",
    "calibration_phases": "hydromodpy.calibrate(source, dry_run=True)",
    "compare_pair": "hydromodpy.compare([a, b]).table",
    "example_list": "hydromodpy.example()",
    "example_show": "hydromodpy.example(name)",
    "example_add": "hydromodpy.example(name, add=True)",
    "Workspace": "hydromodpy.project.accessors.Workspace",
}
"""The verbs and objects that left the top level in 2.0.0, with the call that replaces them."""

OLD_NAMES: dict[str, OldName] = {
    name: OldName(path, "2.0.0", refused=True)
    for name, path in {
        **LEFT_BEFORE_2_0,
        **OLD_MEMBERS,
        **_LEAF_EXCEPTIONS,
        **RETIRED_MODULES,
        **_LEFT_LEAVES,
        **_LEFT_CALLS,
    }.items()
}
"""The old names ``hydromodpy.__getattr__`` answers: it refuses them or forwards them.

A dotted name is a member of a public object, and that object refuses it. The table
holds the names refused because they left before 2.0.0 or in it.
``tools/surface_snapshot.py`` refuses a name that leaves ``__all__`` without an
entry here, and a test fails once an entry outlives its delay. The policy is
``docs/source/about/versions.md``.
"""

LAZY_IMPORTS: dict[str, str] = {
    **{name: f"hydromodpy.project.api:{name}" for name in (*VERBS, *OBJECTS)},
    **{name: f"hydromodpy.project.kept_readers:{name}" for name in KEPT_READERS},
    **{name: f"hydromodpy.core.exceptions:{name}" for name in KEPT_EXCEPTIONS},
}
"""What ``hydromodpy.<name>`` loads on first use: the verbs and the objects through
``hydromodpy.project.api``, the kept readers through ``hydromodpy.project.kept_readers``,
the categories of the hierarchy through ``hydromodpy.core.exceptions``."""
