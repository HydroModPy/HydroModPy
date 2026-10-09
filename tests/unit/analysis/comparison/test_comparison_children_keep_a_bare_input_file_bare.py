"""A comparison child finds a bare DEM name in the data folder of the base workspace.

The comparison used the substring rule the testbed dropped: ``DEM.tif`` under
``dem_init_path`` was written as ``<folder of the base file>/DEM.tif``, where the
file is not, and every child stopped at its first step.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.child_materialization import _simulation_paths_made_absolute


@pytest.mark.fast
def test_a_bare_input_file_absent_from_the_base_folder_stays_bare(tmp_path: Path) -> None:
    payload = {"geographic": {"catchment": {"dem_init_path": "DEM.tif"}}}

    out = _simulation_paths_made_absolute(payload, source_dir=tmp_path)

    assert out["geographic"]["catchment"]["dem_init_path"] == "DEM.tif"


@pytest.mark.fast
def test_a_relative_path_and_a_choice_are_treated_as_in_the_testbed(tmp_path: Path) -> None:
    payload = {
        "geographic": {"catchment": {"dem_init_path": "../data/dem.tif"}},
        "transport": {"modpath": {"parameters": {"track_dir": "forward"}}},
    }

    out = _simulation_paths_made_absolute(payload, source_dir=tmp_path / "project")

    assert out["geographic"]["catchment"]["dem_init_path"] == (tmp_path / "data/dem.tif").as_posix()
    assert out["transport"]["modpath"]["parameters"]["track_dir"] == "forward"


@pytest.mark.fast
def test_a_bare_input_file_found_in_a_data_folder_is_written_as_its_path(tmp_path: Path) -> None:
    data = tmp_path / "workspace" / "data"
    (data / "dem").mkdir(parents=True)
    (data / "dem" / "DEM.tif").write_bytes(b"")
    payload = {"geographic": {"catchment": {"dem_init_path": "DEM.tif"}}}

    out = _simulation_paths_made_absolute(
        payload, source_dir=tmp_path / "project", data_dirs=(data,)
    )

    assert out["geographic"]["catchment"]["dem_init_path"] == (data / "dem" / "DEM.tif").as_posix()


@pytest.mark.fast
def test_a_bare_input_file_found_nowhere_stays_bare(tmp_path: Path) -> None:
    payload = {"geographic": {"catchment": {"dem_init_path": "DEM.tif"}}}

    out = _simulation_paths_made_absolute(
        payload, source_dir=tmp_path / "project", data_dirs=(tmp_path / "data",)
    )

    assert out["geographic"]["catchment"]["dem_init_path"] == "DEM.tif"
