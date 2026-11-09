"""A sidecar and its data file live and die together.

The cache removed a data file and left its ``<file>.json`` sidecar behind. The
orphan was then read as a data file by the next scan. Now a sidecar goes first,
and a sidecar left without its file is no row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    data_path_for_sidecar,
    scan,
    sidecar_path_for,
    unlink_with_sidecar,
)


def _recorded(data_root: Path, name: str = "geology_brgm_1m_abc.gpkg", **fields: object):
    variable = name.split("_")[0]
    path = data_root / variable / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    index = CacheIndex(data_root)
    fields = {"source": "brgm_1m", **fields}
    return index, index.record(path, variable=variable, **fields)


def _file_with_sidecar(folder: Path, name: str = "geology_brgm_1m_abc.gpkg") -> Path:
    _, row = _recorded(folder, name)
    return row.path


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


def test_forgetting_a_row_with_its_file_removes_both(tmp_path: Path) -> None:
    index, row = _recorded(tmp_path / "data")
    index.forget(row, delete_file=True)
    assert not row.path.exists()
    assert not row.sidecar_path.exists()
    assert index.rows() == []


def test_forgetting_a_row_alone_keeps_its_file(tmp_path: Path) -> None:
    index, row = _recorded(tmp_path / "data")
    index.forget(row)
    assert row.path.exists()
    assert not row.sidecar_path.exists()
    assert scan(tmp_path / "data").rows == ()


def test_replacing_an_api_download_removes_the_old_file_and_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    index, old = _recorded(
        data_root, "hydrometry_hubeau_X_20200101_20201231_D.csv", source="hubeau", station_id="X"
    )
    new = data_root / "hydrometry" / "hydrometry_hubeau_X_20200101_20211231_D.csv"
    new.write_bytes(b"longer data")

    with index.chronicle(new.parent, "hydrometry_hubeau_X"):
        index.record(new, variable="hydrometry", source="hubeau", station_id="X")

    assert not old.path.exists()
    assert not old.sidecar_path.exists()
    assert [row.path for row in scan(data_root).rows] == [new]


def test_a_sidecar_whose_file_is_gone_is_an_orphan_not_a_row(tmp_path: Path) -> None:
    _, row = _recorded(tmp_path / "data")
    row.path.unlink()

    report = scan(tmp_path / "data")

    assert report.rows == ()
    assert report.orphans == (row.sidecar_path,)
