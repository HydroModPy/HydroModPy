"""``[geographic.catchment]``: its required keys, its refusals and the forms of the buffer.

The table and the DEM of the dem shape have no default, so the reference shows
both as required. A synthetic support still leaves the catchment out, and a
[data.dem] source may still give the DEM.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.catchment_config import DemCatchDef
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _outlet(**keys) -> dict:
    return {
        "catchment": {
            "catch_def": "from_outlet_coord",
            "dem_init_path": "dem.tif",
            "x_outlet": 1.0,
            "y_outlet": 2.0,
            "snap_dist": "50 m",
            **keys,
        }
    }


def _buffer_of(value):
    return GeographicConfig.model_validate(_outlet(buff_area=value)).buff_area


@pytest.mark.fast
def test_the_catchment_and_the_dem_of_the_dem_shape_have_no_default() -> None:
    assert GeographicConfig.model_fields["catchment"].is_required()
    dem = DemCatchDef.model_fields["dem_init_path"]
    assert dem.is_required()
    assert dem.examples == ["dem.tif"]
    assert GeographicConfig.model_validate({"source_mode": "synthetic"}).catchment is None


@pytest.mark.fast
def test_a_dem_source_may_still_give_the_dem() -> None:
    cfg = GeographicConfig.model_validate(
        {"catchment": {"catch_def": "dem"}}, context={"allow_dem_bootstrap": True}
    )

    assert cfg.dem_init_path is None


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({}, r"Add a \[geographic.catchment\] table"),
        ({"catchment": {"catch_def": "dem"}}, "requires 'dem_init_path'"),
        (
            {"catchment": {"catch_def": "from_outlet_coord", "dem_init_path": "d.tif"}},
            "from_outlet_coord",
        ),
        (_outlet(buff_area=""), "buff_area cannot be empty"),
        (_outlet(buff_area="-5%"), "buff_area percent must be > 0"),
        (_outlet(buff_area="0 m"), "buff_area distance must be > 0"),
        (_outlet(buff_area=-2.0), "buff_area percent must be > 0"),
        (_outlet(dem_resolution=0.0), "a cell size is a positive length"),
        (
            {
                "catchment": {
                    "catch_def": "txt",
                    "dem_init_path": "dem.xyz",
                    "cell_size": "25 m",
                    "dem_resolution": 50.0,
                }
            },
            "would say the grid twice",
        ),
    ],
    ids=[
        "no-table",
        "dem-shape-without-its-dem",
        "outlet-without-its-coordinates",
        "empty-buffer",
        "negative-percent",
        "zero-distance",
        "negative-number",
        "zero-dem-resolution",
        "txt-grid-said-twice",
    ],
)
def test_a_catchment_table_is_refused_with_a_message_that_names_the_key(payload, match) -> None:
    with pytest.raises(ValidationError, match=match):
        GeographicConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("declared", "metres"),
    [("10 m", 10.0), ("0.5 km", 500.0), ("200m", 200.0), ("2 m", 2.0), ("5", 5.0)],
)
def test_a_declared_buffer_distance_survives_being_read_twice(declared, metres) -> None:
    """A run is re-read from its sealed configuration, so the validator reads its own output.

    This one once turned '10 m' into '10.0' and then refused '10.0' as
    dimensionless.
    """
    once = _buffer_of(declared)

    assert once == f"{metres!r} m"
    assert _buffer_of(once) == once


def test_a_buffer_percentage_keeps_its_sign_and_a_bare_number_stays_a_number() -> None:
    """What tells the three rules apart downstream is the form, not the magnitude."""
    assert _buffer_of("2%") == "2%"
    assert _buffer_of("2.5%") == "2.5%"
    assert _buffer_of(2.0) == 2.0


def test_a_polygon_catchment_is_built_from_its_shapefile_and_its_dem() -> None:
    config = GeographicConfig.from_polygon("catchment.shp", dem="dem.tif", crs_project="EPSG:2154")

    assert config.catch_def == "from_polyg_shp"
    assert str(config.polyg_shp_path) == "catchment.shp"
    assert config.cell_size is None
    assert GeographicConfig.model_validate(config) == config
