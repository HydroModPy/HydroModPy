"""``[geographic]``: its source modes, the DEM conditioning, the engine and the retired keys."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.spatial.geographic import GeographicConfig, pipeline
from hydromodpy.spatial.geographic.core import ground_corrections, ground_inputs
from hydromodpy.spatial.terrain import registry

_RETIRED_LAKE_KEYS = (
    "slope",
    "buffer_m",
    "capture_radius_m",
    "capture_max_streams",
    "capture_min_acc_fraction",
)


def _outlet(**overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(x=1.0, y=2.0, dem="dem.tif", **overrides)


def _project_toml(tmp_path, geographic: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        f'[workflow]\nmode = "simulation"\n[workspace]\nroot = "{tmp_path.as_posix()}"\n'
        + geographic,
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def _standard(**overrides: object) -> dict:
    return {"catchment": {"catch_def": "dem", "dem_init_path": __file__}, **overrides}


# --- source modes ---------------------------------------------------------------


def test_a_synthetic_support_needs_no_catchment_even_from_a_project_file(tmp_path) -> None:
    cfg = GeographicConfig.model_validate({"source_mode": "synthetic"})

    assert cfg.uses_synthetic_geographic() is True
    assert cfg.catch_def is None
    assert cfg.synthetic.case_id == "flat20"
    project = _project_toml(tmp_path, '[geographic]\nsource_mode = "synthetic"\n')
    assert project.geographic.uses_synthetic_geographic() is True


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"source_mode": "standard"}, "geographic.catchment.catch_def is required when"),
        (
            {
                "catch_def": "from_outlet_coord",
                "dem_init_path": "dem.tif",
                "x_outlet": 1.0,
                "y_outlet": 2.0,
            },
            "Extra inputs are not permitted",
        ),
        (
            {"catchment": {"catch_def": "txt", "dem_init_path": "dem.xyz", "cell_size": "150.0 m"}},
            "not implemented",
        ),
        (
            {"catchment": {"catch_def": "txt", "dem_init_path": "dem.xyz", "cell_size": "0.15 km"}},
            "not implemented",
        ),
        ({"enforce_streams": {"enabled": True}}, "enforce_streams"),
    ],
    ids=["standard-without-catch-def", "flat-catchment-keys", "txt-in-m", "txt-in-km", "burn"],
)
def test_a_geographic_table_is_refused(payload, match) -> None:
    with pytest.raises(ValidationError, match=match):
        GeographicConfig.model_validate(payload)


# --- the DEM conditioning ---------------------------------------------------------


def test_a_file_that_says_nothing_gets_fill_and_one_that_writes_breach_keeps_it() -> None:
    assert GeographicConfig(source_mode="synthetic").dem_correc_type == "fill"
    breach = GeographicConfig(source_mode="synthetic", dem_correc_type="breach")
    assert breach.dem_correc_type == "breach"
    with pytest.raises(ValidationError):
        GeographicConfig(source_mode="synthetic", dem_correc_type="carve")


def test_the_description_says_what_each_method_does_and_why_fill_leads() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""
    for words in ("'fill' (default)", "spill level", "'breach'", "Lindsay 2016", "FillDepressions"):
        assert words in description
    assert "recommended" not in description


def test_capped_breach_limits_without_the_capped_breach_are_refused() -> None:
    with pytest.raises(ValidationError, match=r"\[geographic.capped_breach\] sets the limits"):
        _outlet(dem_correc_type="fill", capped_breach={"max_depth": 0.8, "max_distance": 100.0})


# --- the terrain engine -----------------------------------------------------------


def test_a_project_names_an_engine_this_installation_serves_or_none() -> None:
    """The default lives in the registry, so the document does not copy it."""
    engine_id = registry.builtin_engine_ids()[0]

    assert GeographicConfig.model_validate(_standard(terrain_engine=engine_id)).terrain_engine == (
        engine_id
    )
    assert GeographicConfig.model_validate(_standard()).terrain_engine is None


def test_a_project_naming_an_engine_nobody_installed_is_refused_while_reading() -> None:
    """Refused at the document, before a DEM is conditioned for nothing."""
    with pytest.raises(ValidationError) as raised:
        GeographicConfig.model_validate(_standard(terrain_engine="no-such-engine"))

    message = str(raised.value)
    assert "geographic.terrain_engine" in message
    assert registry.ENTRY_POINT_GROUP in message
    for engine_id in registry.builtin_engine_ids():
        assert engine_id in message


# --- retired keys -----------------------------------------------------------------


def test_a_toml_declaring_the_stream_burn_is_refused_not_ignored(tmp_path) -> None:
    (tmp_path / "dem.tif").touch()
    burn = (
        '[geographic.catchment]\ncatch_def = "dem"\ndem_init_path = "dem.tif"\n'
        "[geographic.enforce_streams]\nenabled = true\ndepth_m = 10.0\n"
    )

    with pytest.raises(Exception, match="enforce_streams"):
        _project_toml(tmp_path, burn)
    assert "enforce_streams" not in GeographicConfig.model_fields


@pytest.mark.parametrize(
    ("overrides", "match"),
    [({"dam_carve": {"enabled": True, "line_path": "dam.gpkg"}}, "dam_carve")]
    + [
        ({"enforce_lakes": {"enabled": True, "lake_geometry_path": "l.gpkg", key: 1.0}}, key)
        for key in _RETIRED_LAKE_KEYS
    ],
)
def test_the_dam_carve_the_lake_ramp_and_the_capture_are_refused_with_their_reason(
    overrides, match
) -> None:
    """``D`` makes the water cross the lake, so none of them moved a result."""
    with pytest.raises(ValidationError, match=rf"{match}.*not accepted any more"):
        _outlet(**overrides)


def test_the_lake_polygons_stay_a_declared_input_and_no_carve_code_is_left() -> None:
    config = _outlet(enforce_lakes={"enabled": True, "lake_geometry_path": "l.gpkg"})

    assert config.enforce_lakes.enabled is True
    assert not hasattr(config, "dam_carve")
    for module, names in (
        (
            ground_inputs,
            (
                "carve_routing_dem",
                "capture_stream_gaps",
                "capture_from_config",
                "carve_dam_into_top_dem",
                "dam_lines_from_config",
                "routing_dem_from_config",
            ),
        ),
        (ground_corrections, ("GROUND_DAM_FILENAME",)),
        (pipeline, ("capture_from_config", "routing_dem_from_config")),
    ):
        for name in names:
            assert not hasattr(module, name), f"{module.__name__}.{name} is still there"
