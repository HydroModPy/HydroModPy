"""Only the values the schema declares as paths are made absolute in a child config.

The rule used before matched any key containing ``dir``, ``file``, ``root``,
``path``, ``folder`` or ``mask``: ``track_dir = "forward"`` became
``/base/forward`` and ``profile = "x"`` became ``/base/x``.
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
def test_a_text_field_named_as_a_path_becomes_absolute(tmp_path: Path) -> None:
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
def test_a_bare_output_folder_is_resolved_against_its_source(tmp_path: Path) -> None:
    payload = {"display": {"output_dir": "figures"}}

    assert _walk(payload, tmp_path)["display"]["output_dir"] == (tmp_path / "figures").as_posix()


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
