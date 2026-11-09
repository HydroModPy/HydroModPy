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
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.core.toml_io.error_locator import json_pointer

EXPORTED = tuple(getattr(exc_module, name) for name in exc_module.__all__)


def test_every_exported_name_is_a_hydromodpy_error() -> None:
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
