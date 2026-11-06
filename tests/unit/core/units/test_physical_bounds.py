"""The physical range of a parameter, :mod:`hydromodpy.core.units.physical_bounds`.

Every unconfined 1D benchmark in `validation_cases/` writes ``value = "1e-10 m-1"`` to say
that the confined storage term is switched off. Once `d3b80ad99` split ``"<number> <unit>"``
into a float, that value met the old 1e-9 floor and 22 validation cases died at validation.
The floor moved to 1e-12. It stays above zero because the same range bounds a log-space
calibration search, and the ceiling did not move.
"""

from __future__ import annotations

from contextlib import nullcontext

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.config_kit.field_param.config import validate_field_param_toml_data
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.units.physical_bounds import (
    PHYSICAL_BOUNDS,
    PhysicalBoundsError,
    validate_physical_array,
    validate_physical_value,
)

NEGLIGIBLE_STORAGE = 1e-10  # the value every unconfined benchmark writes, and the one that broke


def _field_payload(value: object) -> dict[str, object]:
    return {"field": {"id": "Ss", "kind": "homogeneous", "value": value}}


def test_a_benchmark_declares_a_negligible_specific_storage_and_it_loads() -> None:
    payload = validate_field_param_toml_data(_field_payload("1e-10 m-1"))
    assert payload["field"]["value"] == pytest.approx(NEGLIGIBLE_STORAGE)
    # The schema writes `m-1`, the registry `1/m`; `_in_canonical_unit` settles the spelling.
    assert payload["field"]["unit"] == "m-1"
    with pytest.raises(ValueError, match="specific storage"):
        validate_field_param_toml_data(_field_payload(1e-14))


@pytest.mark.parametrize(
    ("param_id", "value", "unit", "refused"),
    [("Ss", NEGLIGIBLE_STORAGE, "m-1", False), ("Ss", NEGLIGIBLE_STORAGE, None, False),
     ("Ss", 1e-14, None, True), ("Ss", 1.0, None, True), ("porosity_of_the_moon", -5.0, "m", False)],
    ids=["number-and-unit", "number-alone", "two-decades-below-the-device", "ceiling", "no-range"],
)  # fmt: skip
def test_a_value_is_checked_against_the_range_of_its_parameter(param_id, value, unit, refused):
    if refused:
        with pytest.raises(PhysicalBoundsError, match="specific storage"):
            validate_physical_value(param_id=param_id, value=value, unit=unit)
    else:
        assert validate_physical_value(param_id=param_id, value=value, unit=unit) == value


def test_a_refusal_is_a_config_error_that_names_the_place_the_value_and_its_unit() -> None:
    with pytest.raises(ConfigValidationError, match=(
        r"hydraulic conductivity \(id='K'\) in zone 'a' value 1000000000.0 m/day \(11574.1 m/s\) outside"
    )):  # fmt: skip
        validate_physical_value(param_id="K", value=1e9, unit="m/day", where="zone 'a'")


@pytest.mark.parametrize(
    ("param_id", "values", "unit", "refused"),
    [("K", [1e-5, 2e-5], None, None), ("K", [[1e-5, 1e3], [np.nan, 1e-6]], None,
      r"\(id='K'\) in the override: 2 of 4 value\(s\) outside \[1e-14, 100.0\] m/s, the first at index 1: 1000.0"),
     ("K", [8640.0], "m/day", None), ("K", [1e9], "m/day", r"index 0: 1000000000.0 m/day \(11574.1 m/s\)"),
     ("K", [1e-5], "m-1", "expects 'm/s'"), ("porosity_of_the_moon", [-5.0], "m", None)],
    ids=["inside", "outside-and-not-a-number", "declared-unit", "outside-in-its-unit", "other-quantity",
         "no-range"],
)  # fmt: skip
def test_an_array_is_checked_against_the_range_of_its_parameter(param_id, values, unit, refused):
    with nullcontext() if refused is None else pytest.raises(PhysicalBoundsError, match=refused):
        checked = validate_physical_array(
            param_id=param_id, values=values, unit=unit, where="the override"
        )
        np.testing.assert_array_equal(checked, values)


def test_the_floor_stays_a_number_a_log_search_can_walk() -> None:
    assert "porosity_of_the_moon" not in PHYSICAL_BOUNDS
    assert PHYSICAL_BOUNDS["ss"] == PHYSICAL_BOUNDS["specific_storage"]
    assert PHYSICAL_BOUNDS["ss"].hi == 1e-3
    for key in ("ss", "specific_storage"):
        bound = PHYSICAL_BOUNDS[key]
        assert bound.lo == 1e-12
        assert bound.lo > 0.0
        assert bound.lo < NEGLIGIBLE_STORAGE
        assert bound.canonical_unit == "1/m"


def test_the_widened_floor_is_a_ceiling_on_a_declared_bound_and_not_a_span() -> None:
    """A field value carries `Calibrable(bounds=None)`, so the span searched comes from the file."""
    path = "flow.param.Ss.field.value"
    space = ParameterSpace.from_toml_mapping({"Ss": {"bounds": [NEGLIGIBLE_STORAGE, 1e-4], "path": path}})  # fmt: skip
    assert space["Ss"].lower == pytest.approx(NEGLIGIBLE_STORAGE)
    with pytest.raises(ValueError, match="specific storage"):
        ParameterSpace.from_toml_mapping({"Ss": {"bounds": [1e-14, 1e-4], "path": path}})
