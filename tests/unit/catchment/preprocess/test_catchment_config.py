"""``[geographic.catchment]``: its required keys, its refusals and the forms of the buffer.

The table has no default and no table carries a DEM path: the DEM comes from the
[[data.dem.sources]] entry. A synthetic support still leaves the catchment out.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.catchment.algorithms.river_network_config import river_network_for_the_mesh
from hydromodpy.catchment.preprocess.catchment_config import DemCatchDef
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig

_OUTLET = {
    "kind": "from_outlet_coord",
    "x_outlet": 1.0,
    "y_outlet": 2.0,
    "snap_dist": "50 m",
}


def _outlet(**keys) -> dict:
    return {"catchment": {**_OUTLET, **keys}}


def _buffer_of(value):
    return GeographicConfig.model_validate(_outlet(buff_area=value)).buff_area


@pytest.mark.fast
def test_the_catchment_has_no_default_and_no_table_names_a_dem_path_but_a_source_gives_it():
    assert GeographicConfig.model_fields["catchment"].is_required()
    assert "dem_init_path" not in DemCatchDef.model_fields
    assert GeographicConfig.model_validate({"source_mode": "synthetic"}).catchment is None
    bootstrap = {"allow_dem_bootstrap": True}
    dem_shape = {"catchment": {"kind": "dem"}}
    assert GeographicConfig.model_validate(dem_shape, context=bootstrap).catch_def == "dem"
    with pytest.raises(ValidationError, match="dem_init_path"):
        GeographicConfig.model_validate({"catchment": {**_OUTLET, "dem_init_path": "dem.tif"}})


def test_a_dem_from_a_data_source_survives_the_assignment_of_the_section():
    example = Path(__file__).parents[4] / "examples/projects/12_network_calibration_from_apis"
    cfg = HydroModPyConfig.from_toml(example / "project.toml")
    assert cfg.geographic.catch_def == "from_outlet_coord"
    cfg.geographic = river_network_for_the_mesh(cfg)
    assert cfg.geographic.catch_def == "from_outlet_coord"


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        pytest.param({}, r"Add a \[geographic.catchment\] table", id="no-table"),
        pytest.param(
            {"catchment": {"kind": "dem"}},
            r"requires a \[\[data.dem.sources\]\] entry",
            id="dem-shape-without-its-dem",
        ),
        pytest.param(
            {"catchment": {"kind": "from_outlet_coord"}},
            "from_outlet_coord",
            id="outlet-without-its-coordinates",
        ),
        pytest.param(_outlet(buff_area=""), "buff_area cannot be empty", id="empty-buffer"),
        pytest.param(
            _outlet(buff_area="-5%"), "buff_area percent must be > 0", id="negative-percent"
        ),
        pytest.param(
            _outlet(buff_area="0 m"), "buff_area distance must be > 0", id="zero-distance"
        ),
        pytest.param(
            _outlet(buff_area=-2.0), "buff_area percent must be > 0", id="negative-number"
        ),
        pytest.param(
            _outlet(dem_resolution=0.0), "a cell size is a positive length", id="zero-resolution"
        ),
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
    """A sealed run is read again, so the validator reads its own output ('10 m' once became '10.0')."""
    once = _buffer_of(declared)
    assert once == f"{metres!r} m"
    assert _buffer_of(once) == once


def test_a_buffer_percentage_keeps_its_sign_and_a_bare_number_stays_a_number() -> None:
    """What tells the three rules apart downstream is the form, not the magnitude."""
    assert (_buffer_of("2%"), _buffer_of("2.5%"), _buffer_of(2.0)) == ("2%", "2.5%", 2.0)


def test_a_polygon_catchment_is_built_from_its_shapefile() -> None:
    config = GeographicConfig.from_polygon("catchment.shp", crs_project="EPSG:2154")
    assert config.catch_def == "from_polyg_shp"
    assert str(config.polyg_shp_path) == "catchment.shp"
    assert config.cell_size is None
    assert GeographicConfig.model_validate(config) == config
