"""Source settings of the hydrometry variable.

A file source needs the folder that holds the station files. The Hub'Eau
source is the default and reads the mean daily discharge (QmnJ).
"""

import pytest

from hydromodpy.data.variables.hydrometry.config import HydrometrySourceConfig


def test_a_file_source_requires_a_path():
    with pytest.raises(ValueError, match="path"):
        HydrometrySourceConfig(source="file")


@pytest.mark.parametrize(
    ("field", "default"),
    [
        pytest.param("source", "hubeau", id="source"),
        pytest.param("product", "QmnJ", id="product"),
    ],
)
def test_declared_defaults(field, default):
    # The generator writes the declared defaults, so they must form a valid entry.
    assert HydrometrySourceConfig.model_fields[field].default == default
