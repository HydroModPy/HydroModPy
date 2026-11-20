"""Source and date settings of the oceanic variable (sea level, m)."""

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig

pytestmark = pytest.mark.fast

REFUSALS = [
    pytest.param(
        {"source": "constant"}, "Constant source requires 'value'", id="constant without value"
    ),
    pytest.param({"source": "file"}, "File source requires 'path'", id="file without path"),
]


@pytest.mark.parametrize(("fields", "match"), REFUSALS)
def test_source_refusals(fields, match):
    with pytest.raises(ValidationError, match=match):
        OceanicSourceConfig(**fields)


def test_invalid_date_format_is_refused():
    with pytest.raises(ValidationError, match="Invalid ISO date"):
        OceanicConfig(sources=[{"source": "constant", "value": 0.0}], date_start="01-01-2003")
