"""A variable config reads its own section of a TOML file, one entry per ``[[...sources]]``."""

from pathlib import Path

import pytest

from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.data.variables.piezometry.config import PiezometryConfig
from hydromodpy.data.variables.water_quality.config import WaterQualityConfig

SECTIONS = [
    pytest.param(
        HydrometryConfig,
        '[hydrometry]\n[[hydrometry.sources]]\nsource = "hubeau"\nproduct = "QmnJ"\n',
        {"source": "hubeau", "product": "QmnJ"},
        id="hydrometry",
    ),
    pytest.param(
        PiezometryConfig,
        '[piezometry]\n[[piezometry.sources]]\nsource = "hubeau"\nproduct = "level"\n',
        {"product": "level"},
        id="piezometry",
    ),
    pytest.param(
        WaterQualityConfig,
        '[water_quality]\n[[water_quality.sources]]\nsource = "file"\npath = "/tmp/wq"\n',
        {"source": "file"},
        id="water quality",
    ),
    pytest.param(
        HydrometryConfig,
        '[hydrometry]\n[[hydrometry.sources]]\nsource = "file"\npath = "/tmp/data"\n'
        'mask_path = "/tmp/mask.shp"\n',
        {"mask_path": Path("/tmp/mask.shp")},
        id="file with a mask",
    ),
]


@pytest.mark.parametrize(("config_cls", "text", "expected"), SECTIONS)
def test_from_toml(config_cls, text, expected, tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(text)

    config = config_cls.from_toml(toml_path)

    assert len(config.sources) == 1
    for key, value in expected.items():
        assert getattr(config.sources[0], key) == value
