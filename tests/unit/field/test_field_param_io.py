"""A field parameter read from a TOML file and its CSV value table, :mod:`~.field_param_io`."""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigMissingError, ConfigValidationError
from hydromodpy.core.units.physical_bounds import PhysicalBoundsError
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_param_config import resolve_field_param_config_payload
from hydromodpy.spatial.field.field_param_io import field_param_from_toml
from tests._helpers.field_cases import write_text

CSV_FIELD = (
    '[field]\nid = "K"\nkind = "heterogeneous"\nvalues_source = "csv"\nvalues_csv_file = "{csv}"\n'
    'csv_key_column = "zone_key"\ncsv_value_column = "property_value"\nfield_spatial_id = "field_geology"'
)
PROFILE = '\n[field_vertical_profile]\nkind = "exponential"\ncharacteristic_depth = '
ZONES = 'kind = "heterogeneous"\nvalues = { granite = 1e-5, micaschists = 2e-6 }\nfield_spatial_id = "g"\n'
DEPTH = 'kind = "exponential"\ncharacteristic_depth = 30.0\n'


@pytest.mark.parametrize(
    ("text", "expected", "depth_factor"),
    [
        ('id = "K"\nkind = "homogeneous"\nvalue = 12.5', 12.5, 1.0),
        ('id = "Sy"\nkind = "homogeneous"\nvalue = 0.21', 0.21, 1.0),
        ('id = "K"\nkind = "homogeneous"\nvalue = 12.0' + PROFILE + "30.0", 12.0, np.exp(-1.0)),
        ('id = "K"\nkind = "homogeneous"\nvalue = 12.0' + PROFILE + '"30.0 m"', 12.0, np.exp(-1.0)),
    ],
    ids=["k", "sy", "exponential-profile", "profile-depth-with-unit"],
)
def test_a_homogeneous_parameter_reads_its_value_and_profile(
    tmp_path, text, expected, depth_factor
):
    param = field_param_from_toml(write_text(tmp_path / "field.toml", "[field]\n" + text))
    assert param.is_homogeneous
    assert param.has_vertical_variation == (depth_factor != 1.0)
    assert float(param.to_array()) == pytest.approx(expected)
    assert float(param.to_array(depth=30.0)) == pytest.approx(expected * depth_factor)
    np.testing.assert_allclose(param.to_array(shape=(2, 3)), expected)


@pytest.mark.parametrize(
    ("text", "section"),
    [(f'[field]\nid = "K"\n{ZONES}[field_vertical_profile]\n{DEPTH}', "field"),
     (f'[flow]\nparam_list = ["K"]\n[flow.param.K.field]\n{ZONES}[flow.param.K.field_vertical_profile]\n{DEPTH}',
      "flow.param.K.field")],
    ids=["plain", "dotted-takes-its-id-from-the-key"],
)  # fmt: skip
def test_the_named_section_is_read_with_its_profile(tmp_path: Path, text, section):
    param = field_param_from_toml(write_text(tmp_path / "project.toml", text), section=section)
    assert (param.identifier, param.field_spatial_id) == ("K", "g")
    assert param.values_by_key == {"granite": 1e-5, "micaschists": 2e-6}
    assert param.vertical_profile["characteristic_depth"] == 30.0


@pytest.mark.parametrize(
    ("text", "section", "error", "match"),
    [
        ('kind = "homogeneous"\nvalue = 1.0', "field", ConfigMissingError, r"\[field\] of .*field\.toml has no id"),
        ('id = "K"\nkind = "heterogeneous"\nvalues = { granite = 1.0, micaschists = 3.0 }', "field",
         ValueError, "field_spatial_id"),
        ('id = "K"\nkind = "homogeneous"\nvalue = 1.0', "field.id", ConfigValidationError,
         r"Section 'field.id' of .*field\.toml names no \[field\] table"),
        ('id = "K"\nkind = "homogeneous"\nvalue = 1.0', "flow.param.K.field", ConfigMissingError,
         r"field\.toml has no section \[flow.param.K.field\]"),
    ],
    ids=["no-id", "no-support", "a-section-that-is-not-a-field-table", "no-such-section"],
)  # fmt: skip
def test_a_toml_parameter_without_its_keys_is_refused(tmp_path: Path, text, section, error, match):
    path = write_text(tmp_path / "field.toml", "[field]\n" + text)
    with pytest.raises(error, match=match):
        field_param_from_toml(path, section=section)


def _from_toml(folder: Path, csv_name: str) -> FieldParam:
    return field_param_from_toml(write_text(folder / "k.toml", CSV_FIELD.format(csv=csv_name)))


def _from_payload(folder: Path, csv_name: str) -> FieldParam:
    payload = tomllib.loads(CSV_FIELD.format(csv=csv_name))
    return FieldParam.from_dict(resolve_field_param_config_payload(payload, param_id="K", base_dir=folder))  # fmt: skip


@pytest.mark.parametrize("read", [_from_toml, _from_payload], ids=["file", "project"])
@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_a_csv_table_gives_one_value_per_zone_and_skips_blank_keys(tmp_path: Path, read, absolute):
    csv = write_text(tmp_path / "values.csv", "zone_key,property_value\n2141,12.0\n,9\n1501,8.5\nSEA,1.0")  # fmt: skip

    param = read(tmp_path, str(csv) if absolute else csv.name)

    assert param.is_heterogeneous
    assert param.field_spatial_id == "field_geology"
    assert param.values_by_key == {"2141": 12.0, "1501": 8.5, "SEA": 1.0}
    zones = np.array(["1501", "2141", "SEA"], dtype=object)
    np.testing.assert_allclose(param.to_array(zone_ids=zones), [8.5, 12.0, 1.0])


@pytest.mark.parametrize(
    ("csv", "error", "match"),
    [
        (None, FileNotFoundError, "CSV values file not found"),
        ("zone,property_value\na,1", KeyError, "missing key column 'zone_key'"),
        ("zone_key,value\na,1", KeyError, "missing value column 'property_value'"),
        ("zone_key,property_value\n2141,1.0\n2141,2.0", ValueError, "Duplicate key '2141'.*line 3"),
        ("zone_key,property_value\na,high", ValueError, r"line 2: column 'property_value' -> 'high'"),
        ("zone_key,property_value\n,1", ValueError, "does not define any key/value pair"),
        ("zone_key,property_value\na,1e3", PhysicalBoundsError, r"\(id='K'\) in zone 'a' value 1000.0 outside"),
    ],
    ids=["no-file", "no-key-column", "no-value-column", "duplicate-key", "not-a-number", "no-row",
         "out-of-bounds"],
)  # fmt: skip
def test_a_csv_table_it_cannot_read_is_refused(tmp_path: Path, csv, error, match):
    if csv is not None:
        write_text(tmp_path / "values.csv", csv)
    with pytest.raises(error, match=match):
        _from_payload(tmp_path, "values.csv")
