"""The one shape of a finding of a check: its pointer, its record, its line."""

from __future__ import annotations

import json

import pytest

from hydromodpy.core.diagnostic import Diagnostic


@pytest.mark.parametrize(
    ("diagnostic", "parts", "pointer"),
    [
        (Diagnostic("", "to_fill", "to_fill"), (), ""),
        (Diagnostic("geographic", "to_fill", "to_fill"), ("geographic",), "/geographic"),
        (
            Diagnostic("flow.param.K.field", "wrong_type", "error"),
            ("flow", "param", "K", "field"),
            "/flow/param/K/field",
        ),
        (
            Diagnostic("export[0].variables", "unknown_name", "error"),
            ("export", "0", "variables"),
            "/export/0/variables",
        ),
        (
            Diagnostic("flow.param_list[2].kind", "not_a_choice", "error"),
            ("flow", "param_list", "2", "kind"),
            "/flow/param_list/2/kind",
        ),
        (
            Diagnostic(
                "sites.bind.site.name", "unknown_key", "error", keys=("sites", "bind", "site.name")
            ),
            ("sites", "bind", "site.name"),
            "/sites/bind/site.name",
        ),
        (
            Diagnostic("data.a/b", "unknown_key", "error", keys=("data", "a/b")),
            ("data", "a/b"),
            "/data/a~1b",
        ),
    ],
)
def test_the_pointer_follows_the_path_or_its_exact_keys(
    diagnostic: Diagnostic, parts: tuple[str, ...], pointer: str
) -> None:
    assert diagnostic.parts == parts
    assert diagnostic.pointer == pointer


def test_the_record_keeps_the_four_keys_a_refusal_always_carried() -> None:
    record = Diagnostic(
        "flow.flow_regime",
        "not_a_choice",
        "error",
        detail="Input should be 'steady' or 'transient'",
        help="Steady or transient.",
        line_number=7,
        error_type="literal_error",
    ).to_dict()

    assert record == {
        "pointer": "/flow/flow_regime",
        "loc": "flow.flow_regime",
        "msg": "Input should be 'steady' or 'transient'",
        "type": "literal_error",
        "code": "not_a_choice",
        "severity": "error",
        "help": "Steady or transient.",
        "line": 7,
    }
    json.dumps(record)


@pytest.mark.parametrize(
    ("diagnostic", "kind", "loc", "has_line"),
    [
        (Diagnostic("geographic", "to_fill", "to_fill"), "to_fill", "geographic", False),
        (
            Diagnostic("", "cross_rule", "error", error_type="value_error"),
            "value_error",
            "<root>",
            False,
        ),
        (
            Diagnostic("solver.backend", "unknown_name", "error", line_number=3),
            "unknown_name",
            "solver.backend",
            True,
        ),
    ],
)
def test_the_type_is_the_pydantic_one_else_the_code(
    diagnostic: Diagnostic, kind: str, loc: str, has_line: bool
) -> None:
    record = diagnostic.to_dict()

    assert record["type"] == kind
    assert record["loc"] == loc
    assert ("line" in record) is has_line


def test_with_severity_changes_the_severity_and_nothing_else() -> None:
    draft = Diagnostic("site.name", "to_fill", "to_fill", detail="Field required", help="The name.")

    final = draft.with_severity("error")

    assert final.severity == "error"
    assert (final.path, final.code, final.detail, final.help) == (
        draft.path,
        draft.code,
        draft.detail,
        draft.help,
    )
    assert draft.severity == "to_fill"


@pytest.mark.parametrize(
    ("diagnostic", "line"),
    [
        (
            Diagnostic("calibration.parameters.K", "calibration_preflight", "error", "no bounds"),
            "ERROR   calibration.parameters.K: no bounds",
        ),
        (
            Diagnostic("", "cross_warning", "warning", "one layer"),
            "WARNING <document>: one layer",
        ),
        (
            Diagnostic("geographic", "to_fill", "to_fill", "required"),
            "TO_FILL geographic: required",
        ),
    ],
)
def test_a_diagnostic_prints_as_one_line(diagnostic: Diagnostic, line: str) -> None:
    assert diagnostic.line() == line


def test_a_diagnostic_is_frozen() -> None:
    diagnostic = Diagnostic("geographic", "to_fill", "to_fill")
    with pytest.raises(AttributeError):
        diagnostic.code = "unknown_key"  # type: ignore[misc]
