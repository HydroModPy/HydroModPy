"""``bootstrap_proj`` points PROJ_DATA at a database every PROJ of the environment reads.

pyproj and rasterio wheels each bundle their own PROJ and ``proj.db``. pyproj
reads its own copy first, rasterio reads ``PROJ_DATA`` first. PROJ accepts a
database of its own layout or a newer minor one. On Windows with Python 3.11,
pyproj 3.7.2 ships layout 1.4 and rasterio 1.4.4 layout 1.5: pointing
``PROJ_DATA`` at pyproj's copy broke every ``rasterio`` CRS lookup in the
process and in every child that inherits the variable.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from hydromodpy.core.io import proj_bootstrap


def _proj_db(directory: Path, minor: int) -> Path:
    directory.mkdir(parents=True)
    with sqlite3.connect(str(directory / "proj.db")) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [("DATABASE.LAYOUT.VERSION.MAJOR", "1"), ("DATABASE.LAYOUT.VERSION.MINOR", str(minor))],
        )
    return directory


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An environment whose pyproj and rasterio ship the given database layouts."""
    pyproj_datadir = pytest.importorskip("pyproj.datadir")
    prefix = tmp_path / "env"
    monkeypatch.setattr(sys, "prefix", str(prefix))
    for name in ("PROJ_DATA", "PROJ_LIB"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)

    def build(pyproj_minor: int, rasterio_minor: int) -> tuple[Path, Path]:
        pyproj_dir = _proj_db(prefix / "site-packages" / "pyproj" / "proj_dir", pyproj_minor)
        rasterio_dir = _proj_db(prefix / "site-packages" / "rasterio" / "proj_data", rasterio_minor)
        monkeypatch.setattr(pyproj_datadir, "get_data_dir", lambda: str(pyproj_dir))
        monkeypatch.setattr(proj_bootstrap, "_bundled_proj_data_dirs", lambda: [rasterio_dir])
        return pyproj_dir, rasterio_dir

    return build


def test_an_older_pyproj_database_is_not_imposed_on_rasterio(environment) -> None:
    _, rasterio_dir = environment(pyproj_minor=4, rasterio_minor=5)

    proj_bootstrap.bootstrap_proj()

    assert Path(os.environ["PROJ_DATA"]).resolve() == rasterio_dir.resolve()
    assert Path(os.environ["PROJ_LIB"]).resolve() == rasterio_dir.resolve()


def test_the_newest_database_stays_when_pyproj_ships_it(environment) -> None:
    pyproj_dir, _ = environment(pyproj_minor=6, rasterio_minor=5)

    proj_bootstrap.bootstrap_proj()

    assert Path(os.environ["PROJ_DATA"]).resolve() == pyproj_dir.resolve()
