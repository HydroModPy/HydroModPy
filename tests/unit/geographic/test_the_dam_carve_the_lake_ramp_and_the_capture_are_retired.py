"""The dam carve, the lake ramp and the stream capture are gone (finding DAM-2, DAM-3).

``D`` makes the water cross the lake, so none of them moves a result. A user
TOML that still names them is refused with the reason; the routing DEM is the
ground itself.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic import pipeline
from hydromodpy.spatial.geographic.core import ground_corrections, lake_enforcement
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

_RETIRED_LAKE_KEYS = (
    "slope",
    "buffer_m",
    "capture_radius_m",
    "capture_max_streams",
    "capture_min_acc_fraction",
)


def _outlet(**overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", **overrides)


def test_a_dam_carve_section_is_refused_with_its_reason() -> None:
    with pytest.raises(ValidationError, match=r"dam_carve.*not accepted any more"):
        _outlet(dam_carve={"enabled": True, "line_path": "dam.gpkg"})


@pytest.mark.parametrize("key", _RETIRED_LAKE_KEYS)
def test_a_ramp_or_capture_key_of_enforce_lakes_is_refused_with_its_reason(key) -> None:
    with pytest.raises(ValidationError, match=rf"{key}.*not accepted any more"):
        _outlet(enforce_lakes={"enabled": True, "lake_geometry_path": "l.gpkg", key: 1.0})


def test_the_lake_polygons_stay_a_declared_input() -> None:
    config = _outlet(enforce_lakes={"enabled": True, "lake_geometry_path": "l.gpkg"})

    assert config.enforce_lakes.enabled is True
    assert not hasattr(config, "dam_carve")


def test_no_carve_or_capture_code_is_left() -> None:
    for module, names in (
        (lake_enforcement, ("carve_routing_dem", "capture_stream_gaps", "capture_from_config")),
        (lake_enforcement, ("carve_dam_into_top_dem", "dam_lines_from_config")),
        (lake_enforcement, ("routing_dem_from_config",)),
        (ground_corrections, ("GROUND_DAM_FILENAME",)),
        (pipeline, ("capture_from_config", "routing_dem_from_config")),
    ):
        for name in names:
            assert not hasattr(module, name), f"{module.__name__}.{name} is still there"
