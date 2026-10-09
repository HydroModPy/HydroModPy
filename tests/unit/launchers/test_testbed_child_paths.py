"""Only the values the schema declares as paths are made absolute in a child config.

A rule on key names made ``track_dir = "forward"`` into ``/base/forward``,
``profile = "x"`` into ``/base/x``, and rewrote the dotted key of a calibrated
parameter and the figure folder name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.testbed.child_paths import (
    absolutize_child_paths,
    comparison_model,
    root_simulation_model,
)


def _walk(payload: dict, base: Path) -> dict:
    return absolutize_child_paths(payload, model=root_simulation_model(), source_dir=base)


@pytest.mark.fast
def test_a_choice_whose_key_contains_dir_is_copied(tmp_path: Path) -> None:
    payload = {"transport": {"modpath": {"parameters": {"track_dir": "forward"}}}}

    out = _walk(payload, tmp_path)

    assert out["transport"]["modpath"]["parameters"]["track_dir"] == "forward"


@pytest.mark.fast
def test_a_text_whose_key_contains_file_is_copied(tmp_path: Path) -> None:
    payload = {"workflow": {"profile": "x"}}

    assert _walk(payload, tmp_path)["workflow"]["profile"] == "x"


@pytest.mark.fast
def test_a_relative_path_field_becomes_absolute(tmp_path: Path) -> None:
    payload = {"geographic": {"catchment": {"dem_init_path": "../data/dem.tif"}}}

    out = _walk(payload, tmp_path / "project")

    dem = out["geographic"]["catchment"]["dem_init_path"]
    assert dem == (tmp_path / "data/dem.tif").as_posix()


@pytest.mark.fast
def test_a_bare_file_name_absent_from_the_source_folder_stays_bare(tmp_path: Path) -> None:
    payload = {"geographic": {"catchment": {"dem_init_path": "DEM.tif"}}}

    assert _walk(payload, tmp_path)["geographic"]["catchment"]["dem_init_path"] == "DEM.tif"


@pytest.mark.fast
def test_a_bare_file_name_present_in_the_source_folder_becomes_absolute(tmp_path: Path) -> None:
    (tmp_path / "DEM.tif").write_bytes(b"")
    payload = {"geographic": {"catchment": {"dem_init_path": "DEM.tif"}}}

    out = _walk(payload, tmp_path)

    dem = out["geographic"]["catchment"]["dem_init_path"]
    assert dem == (tmp_path / "DEM.tif").as_posix()


@pytest.mark.fast
def test_a_mesh_domain_file_becomes_absolute(tmp_path: Path) -> None:
    payload = {"mesh_catchment": {"domain": {"path": "masks/domain.gpkg"}}}

    out = _walk(payload, tmp_path)

    assert out["mesh_catchment"]["domain"]["path"] == (tmp_path / "masks/domain.gpkg").as_posix()


@pytest.mark.fast
def test_a_source_list_is_walked_item_by_item(tmp_path: Path) -> None:
    payload = {
        "data": {"recharge": {"sources": [{"source": "custom", "path": "rech/r.nc"}]}},
    }

    out = _walk(payload, tmp_path)

    assert out["data"]["recharge"]["sources"][0]["path"] == (tmp_path / "rech/r.nc").as_posix()
    assert out["data"]["recharge"]["sources"][0]["source"] == "custom"


@pytest.mark.fast
def test_the_figure_folder_name_stays_a_name(tmp_path: Path) -> None:
    """display.output_dir names a folder inside the run, not a path."""
    payload = {"display": {"output_dir": "figures"}}

    assert _walk(payload, tmp_path)["display"]["output_dir"] == "figures"


@pytest.mark.fast
def test_the_dotted_key_of_a_calibrated_parameter_is_copied(tmp_path: Path) -> None:
    payload = {"calibration": {"parameters": {"k": {"path": "flow.param.K.field.value"}}}}

    out = _walk(payload, tmp_path)

    assert out["calibration"]["parameters"]["k"]["path"] == "flow.param.K.field.value"


@pytest.mark.fast
def test_the_paths_typed_as_paths_become_absolute(tmp_path: Path) -> None:
    payload = {
        "flow": {"param": {"K": {"field": {"values_csv_file": "k.csv"}}}},
        "mesh_catchment": {
            "rivers": {"source": "file", "path": "rivers.gpkg"},
            "refinement_zone": [{"path": "zones.gpkg", "cell_size": 50.0}],
        },
        "calibration": {"outputs": {"net": {"stream_geometry_path": "net.gpkg"}}},
    }

    out = _walk(payload, tmp_path)

    assert out["flow"]["param"]["K"]["field"]["values_csv_file"] == (tmp_path / "k.csv").as_posix()
    mesh = out["mesh_catchment"]
    assert mesh["rivers"]["path"] == (tmp_path / "rivers.gpkg").as_posix()
    assert mesh["refinement_zone"][0]["path"] == (tmp_path / "zones.gpkg").as_posix()
    network = out["calibration"]["outputs"]["net"]["stream_geometry_path"]
    assert network == (tmp_path / "net.gpkg").as_posix()


@pytest.mark.fast
def test_a_merge_directive_is_walked_as_its_field(tmp_path: Path) -> None:
    payload = {"mesh_catchment": {"refinement_zone__merge": [{"path": "zones.gpkg"}]}}

    out = _walk(payload, tmp_path)

    assert (
        out["mesh_catchment"]["refinement_zone__merge"][0]["path"]
        == (tmp_path / "zones.gpkg").as_posix()
    )


@pytest.mark.fast
def test_an_unknown_key_is_copied(tmp_path: Path) -> None:
    payload = {"not_a_section": {"some_dir": "relative"}}

    assert _walk(payload, tmp_path) == payload


@pytest.mark.fast
def test_a_comparison_overlay_is_read_as_a_simulation_fragment(tmp_path: Path) -> None:
    payload = {
        "comparison": {
            "base_simulation_config": "flow_base.toml",
            "output_root": "out",
            "base_simulation_overlay": {
                "geographic": {"catchment": {"dem_init_path": "../dem.tif"}},
                "workflow": {"profile": "fast"},
            },
        }
    }
    (tmp_path / "flow_base.toml").write_text("", encoding="utf-8")

    out = absolutize_child_paths(payload, model=comparison_model(), source_dir=tmp_path)

    section = out["comparison"]
    assert section["base_simulation_config"] == (tmp_path / "flow_base.toml").as_posix()
    assert section["output_root"] == (tmp_path / "out").as_posix()
    overlay = section["base_simulation_overlay"]
    dem = overlay["geographic"]["catchment"]["dem_init_path"]
    assert dem == (tmp_path.parent / "dem.tif").as_posix()
    assert overlay["workflow"]["profile"] == "fast"
