"""The ``state`` field of a DEM source: raw or conditioned, never guessed."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.dem.config import DemConfig, FileDemSource, UrlDemSource


def test_a_file_source_defaults_to_raw() -> None:
    source = FileDemSource(path=Path("dem.tif"))
    assert source.state == "raw"


def test_a_file_source_accepts_a_conditioned_dem() -> None:
    source = FileDemSource(path=Path("dem.tif"), state="conditioned")
    assert source.state == "conditioned"


def test_a_file_source_refuses_an_unknown_state() -> None:
    with pytest.raises(ValidationError):
        FileDemSource(path=Path("dem.tif"), state="flat")


def test_a_url_source_defaults_to_raw() -> None:
    source = UrlDemSource(url="https://example.com/dem.tif")
    assert source.state == "raw"


def test_from_geotiff_can_declare_a_conditioned_dem() -> None:
    cfg = DemConfig.from_geotiff("dem.tif", state="conditioned")
    assert cfg.sources[0].state == "conditioned"
