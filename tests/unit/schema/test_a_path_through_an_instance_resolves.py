"""The per-field validator refused the paths a calibration actually writes.

Every path a hydrogeologist declares crosses an instance: ``flow.param.K`` names
one parameter among a mapping of them, ``flow.bc.drainage`` one boundary,
``flow.sinks_sources.lakes.cheze`` one lake. The walk treated each segment as a
field of the model above it, so an instance key read as an unknown field and the
most common paths in the repository came back invalid, with a message naming a
field nobody had written.

The mapping is where an instance lives: the key is a name the user chose, so the
segment after it belongs to the value type and not to the mapping.
"""

from __future__ import annotations

import pytest

from hydromodpy.schema import validate_field


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("flow.param.K.field.value", 1e-5),
        ("flow.param.Sy.field.value", 0.05),
        ("flow.bc.drainage.value", 0.1),
        ("flow.sinks_sources.lakes.cheze.bedleak", 1e-6),
        ("flow.flow_regime", "steady"),
    ],
)
def test_a_path_a_calibration_writes_resolves(path: str, value: object) -> None:
    result = validate_field(path, value)

    assert result.valid, result.error


def test_the_instance_key_is_a_name_the_user_chose() -> None:
    assert validate_field("flow.param.hk_bedrock.field.value", 1e-5).valid
    assert validate_field("flow.bc.whatever_they_called_it.value", 1.0).valid


def test_a_value_of_the_wrong_type_is_still_refused() -> None:
    assert not validate_field("flow.flow_regime", "sideways").valid


def test_a_leaf_no_variant_declares_is_still_refused() -> None:
    result = validate_field("flow.param.K.field.no_such_leaf", 1.0)

    assert not result.valid
    assert "no_such_leaf" in str(result.error)


def test_a_section_that_does_not_exist_is_still_refused() -> None:
    assert not validate_field("nowhere.at.all", 1.0).valid


def test_a_path_stopping_on_the_instance_says_what_is_missing() -> None:
    """``domain.supports.aquifer`` is a whole support, not one of its values."""
    result = validate_field("domain.supports.aquifer", 1.0)

    assert not result.valid
    assert "entry" in str(result.error)
