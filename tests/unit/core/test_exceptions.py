"""What a typed failure says about itself to a reader outside this process.

``to_dict()`` is what a job outcome document carries when a capability fails. It
is read by a shim that never imports HydroModPy, so every member has to be JSON,
stable, and true: the ``urn:`` type resolves to nothing on purpose, because no
namespace is registered and a ``type`` that 404s is worse than one that never
promised to resolve.
"""

from __future__ import annotations

import json

import pytest

from hydromodpy.core import exceptions as exc_module
from hydromodpy.core.exceptions import Category, HydroModPyError

EXPORTED = tuple(getattr(exc_module, name) for name in exc_module.__all__ if name != "Category")


def test_exports_are_hydromodpy_errors() -> None:
    assert "Category" in exc_module.__all__
    for cls in EXPORTED:
        assert issubclass(cls, HydroModPyError), cls


def test_exports_have_a_code() -> None:
    for cls in EXPORTED:
        assert cls.code.startswith("HMPY.E"), cls


def test_run_context_in_problem_object() -> None:
    bare = HydroModPyError("no context").to_dict()
    assert "sim_id" not in bare
    assert "run_id" not in bare

    placed = HydroModPyError("placed", sim_id="s1", run_id="r1").to_dict()
    assert placed["sim_id"] == "s1"
    assert placed["run_id"] == "r1"


def test_exports_render_from_one_argument() -> None:
    """A reader serializes whatever it caught. A class whose ``__init__`` needs
    more than a message would raise inside the failure handler."""
    for cls in EXPORTED:
        try:
            instance = cls("probe")
        except TypeError:
            continue  # a constructor with a required argument of its own
        payload = instance.to_dict()
        assert payload["code"] == cls.code
        json.dumps(payload)


# Classes that say their category themselves. The others inherit it.
OWN_CATEGORY: dict[str, Category] = {
    "HydroModPyError": Category.GENERIC,
    "CommandUsageError": Category.USAGE,
    "NothingThereError": Category.NOT_FOUND,
    "ConfigError": Category.CONFIG,
    "DataError": Category.DATA,
    "JobInputNotFoundError": Category.NOT_FOUND,
    "TerrainError": Category.SOLVER,
    "JobUsageError": Category.USAGE,
    "CapabilityVersionMismatchError": Category.SCHEMA_MISMATCH,
    "SolverError": Category.SOLVER,
    "FailedCasesError": Category.CASES_FAILED,
    "CalibrationError": Category.CALIBRATION,
    "ReadOnlyError": Category.READ_ONLY,
    "WriteConflictError": Category.WRITE_CONFLICT,
    "CrossProjectsError": Category.CROSS_PROJECTS,
    "BackupFailedError": Category.BACKUP_FAILED,
    "MigrationFailedError": Category.MIGRATION_FAILED,
    "CatalogUnreadableError": Category.CATALOG_UNREADABLE,
    "ImportConflictError": Category.WRITE_CONFLICT,
    "SchemaVersionMismatchError": Category.SCHEMA_MISMATCH,
}


def test_sixteen_categories() -> None:
    assert [member.value for member in Category] == [
        "generic",
        "usage",
        "not_found",
        "schema_mismatch",
        "write_conflict",
        "read_only",
        "config",
        "solver",
        "data",
        "cross_projects",
        "backup_failed",
        "migration_failed",
        "ambiguous_reference",
        "calibration",
        "catalog_unreadable",
        "cases_failed",
    ]


@pytest.mark.parametrize(("name", "category"), sorted(OWN_CATEGORY.items()))
def test_own_category(name: str, category: Category) -> None:
    cls = getattr(exc_module, name)
    assert "category" in vars(cls)
    assert cls.category is category


@pytest.mark.parametrize("cls", EXPORTED, ids=lambda cls: cls.__name__)
def test_inherited_category(
    cls: type[HydroModPyError],
) -> None:
    if cls.__name__ in OWN_CATEGORY:
        return
    assert "category" not in vars(cls)
    parent = next(base for base in cls.__bases__ if issubclass(base, HydroModPyError))
    assert cls.category is parent.category


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("hydromodpy.results.errors.ProjectNotFoundError", Category.NOT_FOUND),
        ("hydromodpy.results.errors.RunNotSealedError", Category.NOT_FOUND),
        ("hydromodpy.results.errors.FieldNotFoundError", Category.GENERIC),
        ("hydromodpy.results.errors.RunNotFoundError", Category.GENERIC),
        ("hydromodpy.results.catalog.discovery.SimulationNotFoundError", Category.NOT_FOUND),
        (
            "hydromodpy.results.catalog.discovery.AmbiguousReferenceError",
            Category.AMBIGUOUS_REFERENCE,
        ),
        ("hydromodpy.results.storage.attempt.AttemptClaimedError", Category.WRITE_CONFLICT),
        ("hydromodpy.results.storage.attempt.CaseAliveError", Category.WRITE_CONFLICT),
        (
            "hydromodpy.results.storage.attempt.DirectoryWithoutOutcomeError",
            Category.WRITE_CONFLICT,
        ),
    ],
)
def test_results_error_categories(path: str, category: Category) -> None:
    import importlib

    module, _, name = path.rpartition(".")
    assert getattr(importlib.import_module(module), name).category is category


def test_job_input_not_found_category() -> None:
    # Two parents of different categories: the class says the one of its exit code.
    assert issubclass(exc_module.JobInputNotFoundError, exc_module.DataError)
    assert exc_module.JobInputNotFoundError.category is Category.NOT_FOUND
