"""The ``state`` field of a DEM source: raw or conditioned, never guessed."""

from __future__ import annotations

from hydromodpy.data.variables.dem.config import DemConfig


def test_from_geotiff_can_declare_a_conditioned_dem() -> None:
    cfg = DemConfig.from_geotiff("dem.tif", state="conditioned")
    assert cfg.sources[0].state == "conditioned"
