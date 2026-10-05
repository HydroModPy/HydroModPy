"""MODFLOW-NWT builds no channel mask, so a zonal top there is median only."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]
project_root = "{root}"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[{section}.sgrid.top_sampling]
mode = "zonal"
{extra}
"""


def _load(tmp_path: Path, section: str, extra: str = "") -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), section=section, extra=extra),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def test_a_zonal_nwt_top_with_a_channel_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="MODFLOW-NWT does not read the channel tree"):
        _load(tmp_path, "modflownwt")


def test_the_refusal_names_both_ways_out(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, "modflownwt", 'channel_source = "streams_raster"')

    assert "channel_source = 'none'" in str(excinfo.value)
    assert "MODFLOW 6" in str(excinfo.value)


def test_a_zonal_nwt_top_without_channel_source_is_allowed(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "modflownwt", 'channel_source = "none"')

    assert cfg.modflownwt.sgrid.top_sampling.mode == "zonal"


def test_modflow6_keeps_its_channel_source(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "modflow6")

    assert cfg.modflow6.sgrid.top_sampling.channel_source == "streams_raster"
