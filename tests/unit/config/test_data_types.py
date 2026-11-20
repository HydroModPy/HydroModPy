"""The types a configuration declares, without the ones it inferred."""

import pytest

from hydromodpy.config.data_types import with_declared_types_only


@pytest.mark.parametrize(
    ("data", "kept"),
    [
        ({"types": ["lake_inflow", "rain"], "rain": {}}, ["rain"]),
        ({"types": ["rain"], "rain": {}}, ["rain"]),
        ({"types": []}, []),
    ],
)
def test_declared_types_only_drops_a_type_with_no_section(data, kept) -> None:
    payload = {"data": data, "other": 1}
    assert with_declared_types_only(payload)["data"]["types"] == kept
    assert payload["data"] is data and with_declared_types_only({"x": 1}) == {"x": 1}
