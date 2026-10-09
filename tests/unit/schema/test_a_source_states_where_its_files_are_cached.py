"""The cache layout a source states is the one the data managers write.

``schema/sources.py`` tells a reader where a fetch leaves its files. The names
come from functions in ``data``, which ``schema`` may not import, so this test
builds a real name with each function and holds it against the glob the entry
states. A renamed file that leaves the entry behind fails here.
"""

from __future__ import annotations

from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.managers.base_manager_variable import _VAR_FILE_PREFIX
from hydromodpy.data.variables.crossings.manager import cache_file_name as crossings_name
from hydromodpy.data.variables.hydrography.manager import (
    _cache_file_name as hydrography_name,
)
from hydromodpy.data.variables.hydrography.manager import _permanent_copy_path
from hydromodpy.data.variables.oceanic.apis.shom import _cache_file as shom_name
from hydromodpy.schema.sources import CACHE_INDEX, SOURCES, CacheLayout

BBOX = (100000.0, 6800000.0, 110000.0, 6810000.0)
START = datetime(2020, 1, 1)
END = datetime(2020, 12, 31)


def _layouts(slug: str) -> dict[str, CacheLayout]:
    return {layout.folder: layout for layout in SOURCES[slug].cache}


def _matches(slug: str, folder: str, name: str) -> bool:
    return fnmatch(name, _layouts(slug)[folder].pattern)


@pytest.mark.parametrize("slug", ["bdtopage", "euhydro", "osm"])
def test_a_network_answer_is_named_as_the_hydrography_manager_names_it(slug: str) -> None:
    name = hydrography_name(slug, BBOX)
    assert _matches(slug, "data/hydrography", name)
    assert _matches(slug, "data/hydrography", _permanent_copy_path(Path(name)).name)


@pytest.mark.parametrize("slug", ["bdtopo", "roe"])
def test_a_crossing_is_named_as_the_crossings_manager_names_it(slug: str) -> None:
    assert _matches(slug, "data/crossings", crossings_name(slug, BBOX))


@pytest.mark.parametrize(
    ("slug", "variable"),
    [
        ("sim2", "etp"),
        ("sim2", "precipitation_liquid"),
        ("explore2", "precipitation"),
        ("explore2", "etp"),
    ],
)
def test_a_grid_is_named_as_the_field_manager_names_it(slug: str, variable: str) -> None:
    name = BaseFieldManager._nc_filename(variable, slug, BBOX, START, END)
    assert _matches(slug, "data/<variable>", name)


def test_a_gauge_file_is_named_as_the_shom_adapter_names_it() -> None:
    name = shom_name(Path("cache"), "300", START, END).name
    assert _matches("shom", "data/oceanic", name)


def test_a_station_file_is_named_after_its_variable_prefix() -> None:
    folders = {layout.folder: layout for layout in SOURCES["hubeau"].cache}
    assert set(folders) == {
        "data/hydrometry",
        "data/piezometry",
        "data/intermittency",
        "data/water_quality",
    }
    for variable in ("hydrometry", "piezometry", "intermittency", "water_quality"):
        prefix = _VAR_FILE_PREFIX.get(variable, variable)
        name = f"{prefix}_hubeau_ABC_20200101_20201231_D.csv"
        assert fnmatch(name, folders[f"data/{variable}"].pattern)


@pytest.mark.parametrize(
    ("module", "slug", "folder", "literal"),
    [
        (
            "hydromodpy/data/variables/geology/apis/brgm_1m.py",
            "brgm_1m",
            "data/geology",
            "geology_brgm_1m_",
        ),
        (
            "hydromodpy/data/variables/geology/apis/brgm_50k.py",
            "brgm_50k",
            "data/geology",
            "geology_brgm_50k_",
        ),
        (
            "hydromodpy/data/variables/dem/apis/ign_dem_fr.py",
            "ign_geoplateforme_dem",
            "data/dem/processed",
            "dem_ign_geoplateforme_",
        ),
    ],
)
def test_a_name_built_inline_is_still_written_by_its_module(
    module: str, slug: str, folder: str, literal: str
) -> None:
    root = Path(__file__).resolve().parents[3]
    assert literal in (root / module).read_text(encoding="utf-8")
    assert _layouts(slug)[folder].pattern.startswith(literal)


def test_the_index_sits_next_to_the_data_folders() -> None:
    assert CACHE_INDEX == "data/cache.duckdb"
    for entry in SOURCES.values():
        for layout in entry.cache:
            assert layout.folder.startswith("data/")


def test_a_source_that_leaves_no_file_in_a_workspace_states_no_layout() -> None:
    for slug in ("custom", "constant", "synthetic"):
        assert SOURCES[slug].cache == ()
