"""A sidecar and its data file live and die together.

The cache removed a data file and left its ``<file>.json`` sidecar behind. The
orphan was then read as a data file by the next scan.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.provenance.sidecars import (
    Sidecar,
    data_path_for_sidecar,
    sidecar_path_for,
    unlink_with_sidecar,
    write_sidecar,
)
from hydromodpy.data.registry.cache_store import try_unlink
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def _file_with_sidecar(folder: Path, name: str = "geology_brgm_1m_abc.gpkg") -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    write_sidecar(path, Sidecar(source="brgm_1m", sha256="abc"))
    return path


@pytest.mark.parametrize(
    ("name", "data_name"),
    [
        ("foo.gpkg.json", "foo.gpkg"),
        ("foo.TIF.json", "foo.TIF"),
        ("foo.csv.json", "foo.csv"),
        ("foo.nc.json", "foo.nc"),
        ("foo.json.json", "foo.json"),
    ],
)
def test_a_json_named_after_a_data_file_is_its_sidecar(name: str, data_name: str) -> None:
    assert data_path_for_sidecar(Path("/d") / name) == Path("/d") / data_name


@pytest.mark.parametrize("name", ["foo.json", "foo.v1.2.json", "foo.gpkg", "foo.gpkg.bak"])
def test_other_names_are_not_sidecars(name: str) -> None:
    assert data_path_for_sidecar(Path("/d") / name) is None


def test_the_sidecar_rule_does_not_depend_on_the_data_file(tmp_path: Path) -> None:
    orphan = tmp_path / "foo.gpkg.json"
    orphan.write_text("{}", encoding="utf-8")
    assert data_path_for_sidecar(orphan) == tmp_path / "foo.gpkg"


def test_unlink_with_sidecar_removes_both(tmp_path: Path) -> None:
    path = _file_with_sidecar(tmp_path)
    unlink_with_sidecar(path)
    assert not path.exists()
    assert not sidecar_path_for(path).exists()


def test_unlink_with_sidecar_accepts_a_file_without_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "plain.tif"
    path.write_bytes(b"data")
    unlink_with_sidecar(path)
    assert not path.exists()


def test_a_data_file_that_refuses_to_go_never_leaves_an_orphan_sidecar(tmp_path: Path) -> None:
    # A directory standing where the data file is makes its unlink fail. The
    # sidecar is gone first, so the failure leaves data without a sidecar,
    # which the next write describes again, never a sidecar without its data.
    path = tmp_path / "geology_brgm_1m_abc.gpkg"
    path.mkdir()
    sidecar = sidecar_path_for(path)
    sidecar.write_text("{}", encoding="utf-8")

    with pytest.raises(OSError):
        unlink_with_sidecar(path)

    assert not sidecar.exists()
    assert path.exists()


def test_try_unlink_removes_the_sidecar(tmp_path: Path) -> None:
    path = _file_with_sidecar(tmp_path)
    try_unlink(str(path))
    assert not path.exists()
    assert not sidecar_path_for(path).exists()


def test_invalidating_a_cache_entry_removes_its_sidecar(tmp_path: Path) -> None:
    # Outside the workspace, so the catalog stores the absolute path that
    # the delete reads back.
    path = tmp_path / "elsewhere" / "geology_brgm_1m_abc.gpkg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"data")
    catalog = DataCatalogDuckDB(tmp_path / "ws" / "data" / "cache.duckdb")
    try:
        catalog.register(
            variable="geology",
            source="brgm_1m",
            file_path=str(path),
            bbox=(0.0, 0.0, 1.0, 1.0),
            crs="EPSG:2154",
        )
        assert sidecar_path_for(path).is_file()
        catalog.invalidate(variable="geology", source="brgm_1m", delete_files=True)
    finally:
        catalog.close()
    assert not path.exists()
    assert not sidecar_path_for(path).exists()


def test_replacing_an_api_download_removes_the_old_sidecar(tmp_path: Path) -> None:
    old = _file_with_sidecar(tmp_path, "hydrometry_hubeau_X_20200101_20201231_D.csv")
    catalog = SimpleNamespace(find_cached=lambda **_: SimpleNamespace(file_path=old.name))
    manager = SimpleNamespace(
        catalog=catalog,
        VARIABLE_NAME="hydrometry",
        _resolve_catalog_path=lambda fp: tmp_path / fp,
    )
    BaseVariableManager._cleanup_old_api_file(manager, "hubeau", "X")
    assert not old.exists()
    assert not sidecar_path_for(old).exists()
