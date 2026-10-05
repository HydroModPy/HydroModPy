"""The stream burn is gone: a TOML that still declares it is refused, not ignored."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{project}"
project_root = "{project}"

[geographic.catchment]
catch_def = "dem"
dem_init_path = "dem.tif"

[geographic.enforce_streams]
enabled = true
depth_m = 10.0
"""


def test_a_toml_declaring_enforce_streams_is_refused(tmp_path) -> None:
    (tmp_path / "dem.tif").touch()
    cfg_path = tmp_path / "project.toml"
    cfg_path.write_text(_TOML.format(project=tmp_path.as_posix()), encoding="utf-8")

    with pytest.raises(Exception, match="enforce_streams"):
        HydroModPyConfig.from_toml(cfg_path)


def test_the_section_is_not_a_field_of_the_geographic_config() -> None:
    assert "enforce_streams" not in GeographicConfig.model_fields

    with pytest.raises(ValidationError, match="enforce_streams"):
        GeographicConfig.model_validate({"enforce_streams": {"enabled": True}})
