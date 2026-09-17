"""A specific storage of 1e-10 1/m says "no confined storage", and must load.

Every unconfined 1D benchmark in `validation_cases/` writes
``value = "1e-10 m-1"`` and is compared against an analytical solution that
carries no confined storage term at all. The value is a numerical device, not a
measurement: the response belongs to `Sy`.

That declaration stopped loading when `d3b80ad99` taught the schema to split
``"<number> <unit>"`` into a float, because the float then reached the numeric
branch of `FieldParamConfig._enforce_physical_bounds`, which a string had always
bypassed. The floor it met was 1e-9, and 22 validation cases plus 3 e2e tests
died at Pydantic validation, before any solver ran.

The floor is what moved, not the cases. A rigid matrix at the porosity floor of
`PHYSICAL_BOUNDS` itself still stores rho*g*n*beta ~ 4e-9 1/m, so the old bound
refused values that no aquifer can reach either way; what it also refused was the
only way to say that the confined term is switched off.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.spatial.field.core.field_param_config import validate_field_param_toml_data
from hydromodpy.spatial.field.core.physical_bounds import (
    PHYSICAL_BOUNDS,
    PhysicalBoundsError,
    validate_physical_value,
)

NEGLIGIBLE_STORAGE = 1e-10
"""The value every unconfined benchmark writes, and the one that broke."""


def _field_payload(value: object) -> dict[str, object]:
    return {"field": {"id": "Ss", "kind": "homogeneous", "value": value}}


def test_a_benchmark_declares_a_negligible_specific_storage_and_it_loads() -> None:
    """The string spelling, which is what the validation cases actually write."""
    payload = validate_field_param_toml_data(_field_payload("1e-10 m-1"))

    assert payload["field"]["value"] == pytest.approx(NEGLIGIBLE_STORAGE)
    # The schema normalizes to `m-1`; the registry writes the same unit `1/m`,
    # and `_in_canonical_unit` settles the spelling before the range check.
    assert payload["field"]["unit"] == "m-1"


def test_the_two_spellings_of_the_same_statement_agree() -> None:
    """A number with a sibling unit and a number alone reach the same check."""
    assert (
        validate_physical_value(param_id="Ss", value=NEGLIGIBLE_STORAGE, unit="m-1")
        == NEGLIGIBLE_STORAGE
    )
    assert validate_physical_value(param_id="Ss", value=NEGLIGIBLE_STORAGE) == NEGLIGIBLE_STORAGE


def test_the_floor_still_refuses_a_value_no_declaration_explains() -> None:
    """Widened, not removed: two decades below the device is still refused."""
    with pytest.raises(PhysicalBoundsError, match="specific storage"):
        validate_physical_value(param_id="Ss", value=1e-14)

    with pytest.raises(ValueError, match="specific storage"):
        validate_field_param_toml_data(_field_payload(1e-14))


def test_the_ceiling_did_not_move() -> None:
    """Only the floor was wrong. A storage of 1 1/m is still absurd."""
    assert PHYSICAL_BOUNDS["ss"].hi == 1e-3
    with pytest.raises(PhysicalBoundsError, match="specific storage"):
        validate_physical_value(param_id="Ss", value=1.0)


def test_the_floor_stays_a_number_a_log_search_can_walk() -> None:
    """These bounds double as the span of a log-space search.

    `_field_param_sections` declares `transform="log"` on a field value and
    `targets.py` hands the registry range to the search as its physical bounds.
    A floor of zero would say "no confined storage" plainer than 1e-12 does, and
    would put -inf in the sampler.
    """
    for key in ("ss", "specific_storage"):
        bound = PHYSICAL_BOUNDS[key]
        assert bound.lo == 1e-12
        assert bound.lo > 0.0
        assert bound.lo < NEGLIGIBLE_STORAGE
        assert bound.canonical_unit == "1/m"


def test_both_spellings_of_the_identifier_carry_the_same_range() -> None:
    """`Ss` and `specific_storage` are one quantity written twice."""
    assert PHYSICAL_BOUNDS["ss"] == PHYSICAL_BOUNDS["specific_storage"]


def test_the_widened_floor_is_a_ceiling_on_a_declared_bound_and_not_a_span() -> None:
    """The other reader of this range, and the one the repair could have moved.

    `ParameterSpace` faces a declared `[calibration.parameters.Ss] bounds` with
    the registry, so widening the floor widens what a file is allowed to declare.
    It does not widen any search: a field value carries `Calibrable(bounds=None)`
    on purpose, so the span a log-uniform prior walks comes from the file and
    never from this table. A calibration that declares nothing still searches
    nothing.
    """
    space = ParameterSpace.from_toml_mapping(
        {"Ss": {"bounds": [NEGLIGIBLE_STORAGE, 1e-4], "path": "flow.param.Ss.field.value"}}
    )

    assert space["Ss"].lower == pytest.approx(NEGLIGIBLE_STORAGE)

    with pytest.raises(ValueError, match="specific storage"):
        ParameterSpace.from_toml_mapping(
            {"Ss": {"bounds": [1e-14, 1e-4], "path": "flow.param.Ss.field.value"}}
        )
