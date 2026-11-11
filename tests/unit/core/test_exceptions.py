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

from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.core import exceptions as exc_module
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import Category, HydroModPyError
from hydromodpy.core.toml_io.error_locator import json_pointer

EXPORTED = tuple(getattr(exc_module, name) for name in exc_module.__all__ if name != "Category")


def test_every_exported_name_is_a_hydromodpy_error_or_the_category() -> None:
    assert "Category" in exc_module.__all__
    for cls in EXPORTED:
        assert issubclass(cls, HydroModPyError), cls


def test_every_exported_class_declares_its_own_code_or_inherits_one() -> None:
    for cls in EXPORTED:
        assert cls.code.startswith("HMPY.E"), cls


def test_every_exported_class_has_a_title_that_is_not_its_own_name() -> None:
    """The title comes from the first docstring line, so a class that lost its
    docstring degrades to its class name. None of them has."""
    for cls in EXPORTED:
        assert cls.title() and cls.title() != cls.__name__, cls


def test_the_problem_object_is_json_and_carries_the_urn() -> None:
    error = HydroModPyError("something went wrong")
    payload = error.to_dict()
    assert payload == {
        "type": "urn:hmp:error:HMPY.E000",
        "code": "HMPY.E000",
        "title": "Base class for all HydroModPy exceptions.",
        "detail": "something went wrong",
    }
    json.dumps(payload)


def test_the_problem_object_carries_the_run_context_only_when_it_has_one() -> None:
    bare = HydroModPyError("no context").to_dict()
    assert "sim_id" not in bare
    assert "run_id" not in bare

    placed = HydroModPyError("placed", sim_id="s1", run_id="r1").to_dict()
    assert placed["sim_id"] == "s1"
    assert placed["run_id"] == "r1"


def test_every_exported_class_renders_a_problem_object_from_one_argument() -> None:
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


def test_the_exit_code_of_a_class_is_the_one_the_mapper_produces() -> None:
    """The description a capability ships claims an exit code per exception
    class. It may not claim one the mapper does not produce."""
    from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_SOLVER_ERROR, EXIT_VALIDATION

    assert exit_code_for(exc_module.ConfigValidationError("x")) == EXIT_CONFIG
    assert exit_code_for(exc_module.DataError("x")) == EXIT_VALIDATION
    assert exit_code_for(exc_module.SolverError("x")) == EXIT_SOLVER_ERROR


# The category of each class: said once, on the class that owns it.

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
"""The classes of ``core.exceptions`` that say their category; the others inherit it."""


def test_the_categories_are_the_sixteen_of_the_exit_codes() -> None:
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
def test_a_class_says_its_own_category(name: str, category: Category) -> None:
    cls = getattr(exc_module, name)
    assert "category" in vars(cls)
    assert cls.category is category


@pytest.mark.parametrize("cls", EXPORTED, ids=lambda cls: cls.__name__)
def test_every_other_class_inherits_the_category_of_its_first_parent_of_ours(
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
def test_a_class_of_results_carries_the_category_of_its_exit_code(
    path: str, category: Category
) -> None:
    import importlib

    module, _, name = path.rpartition(".")
    assert getattr(importlib.import_module(module), name).category is category


def test_a_class_that_is_also_a_file_not_found_error_is_not_found() -> None:
    """Two parents of different categories: the class says the one of its exit code."""
    assert issubclass(exc_module.JobInputNotFoundError, exc_module.DataError)
    assert exc_module.JobInputNotFoundError.category is Category.NOT_FOUND


@pytest.mark.parametrize(
    ("loc", "pointer"),
    [
        ((), ""),
        (("workspace",), "/workspace"),
        (("flow", "param_list", 0, "kind"), "/flow/param_list/0/kind"),
        (("data", "a/b"), "/data/a~1b"),
        (("data", "a~b"), "/data/a~0b"),
        (("data", "a~/b"), "/data/a~0~1b"),
    ],
)
def test_a_pointer_escapes_what_rfc_6901_requires(loc: tuple, pointer: str) -> None:
    assert json_pointer(loc) == pointer


# ---------------------------------------------------------------------------
# The diagnostics a refusal carries
# ---------------------------------------------------------------------------

LAKE = Diagnostic(
    "",
    "incompatible",
    "error",
    detail="solver.backend = 'modflow_nwt' does not honor flow.sinks_sources.lakes",
)
SITE = Diagnostic("site.name", "to_fill", "error", detail="Field required", error_type="missing")


@pytest.mark.parametrize(
    "cls",
    [
        exc_module.IncompatibleCapabilitiesError,
        exc_module.ConfigValidationError,
        exc_module.ConfigError,
        HydroModPyError,
    ],
)
def test_a_typed_error_carries_its_diagnostics_as_details(cls: type[HydroModPyError]) -> None:
    error = cls("refused", diagnostics=[LAKE, SITE])

    payload = error.to_dict()

    assert error.diagnostics == (LAKE, SITE)
    assert [entry["pointer"] for entry in payload["details"]] == ["", "/site/name"]
    assert [entry["code"] for entry in payload["details"]] == ["incompatible", "to_fill"]
    json.dumps(payload)


@pytest.mark.parametrize(
    "cls",
    [exc_module.IncompatibleCapabilitiesError, exc_module.ConfigValidationError, HydroModPyError],
)
def test_the_details_member_is_absent_when_there_is_nothing_to_point_at(
    cls: type[HydroModPyError],
) -> None:
    error = cls("nothing structured")

    assert error.diagnostics == ()
    assert error.details == ()
    assert "details" not in error.to_dict()


def test_given_details_are_kept_as_written() -> None:
    record = {"pointer": "/geographic", "loc": "geographic", "msg": "m", "type": "value_error"}

    error = exc_module.ConfigValidationError("m", details=[record])

    assert error.details == (record,)
    assert error.to_dict()["details"] == [record]


@pytest.mark.parametrize(
    ("message", "expected"),
    [(None, "first fault"), ("first fault\nsecond fault", "first fault\nsecond fault")],
)
def test_carrying_gives_every_diagnostic_to_the_error_of_the_first(
    message: str | None, expected: str
) -> None:
    error = exc_module.IncompatibleCapabilitiesError("first fault", diagnostics=[LAKE])

    carried = error.carrying([LAKE, SITE], message=message)

    assert carried is error
    assert error.diagnostics == (LAKE, SITE)
    assert [entry["code"] for entry in error.details] == ["incompatible", "to_fill"]
    assert str(error) == expected
    assert error.message == expected
    assert exit_code_for(error) == exit_code_for(exc_module.IncompatibleCapabilitiesError("x"))
