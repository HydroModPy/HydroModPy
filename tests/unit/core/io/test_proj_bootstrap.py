"""PROJ bootstrap: PROJ_DATA ends on a database whose layout every PROJ build of the environment reads.

The databases are tiny sqlite files that carry only the layout version, so no
real PROJ install is needed and the environment variables are restored by
``monkeypatch``.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pyproj
import pytest
from pyproj import datadir

from hydromodpy.core.io import proj_bootstrap as pb


def _proj_dir(root: Path, name: str, minor: int | None, *, key: str = "key") -> Path:
    """A folder with a proj.db that declares layout 1.<minor> (None: no version rows)."""
    folder = root / name
    folder.mkdir(parents=True)
    with sqlite3.connect(folder / "proj.db") as con:
        con.execute(f"create table metadata ({key} text, value text)")
        if minor is not None:
            con.executemany(
                "insert into metadata values (?, ?)",
                [
                    ("DATABASE.LAYOUT.VERSION.MAJOR", "1"),
                    ("DATABASE.LAYOUT.VERSION.MINOR", str(minor)),
                ],
            )
    return folder


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Clean PROJ variables, an empty environment prefix and no bundled wheel database."""
    monkeypatch.delenv("PROJ_DATA", raising=False)
    monkeypatch.delenv("PROJ_LIB", raising=False)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(pb, "_bundled_proj_data_dirs", lambda: [])
    return monkeypatch


def _pyproj_dir_is(monkeypatch, folder: Path | None) -> None:
    monkeypatch.setattr(datadir, "get_data_dir", lambda: str(folder) if folder else "")


@pytest.mark.parametrize(
    "situation", ["no version rows", "no database", "not sqlite", "unknown columns"]
)
def test_a_database_that_does_not_state_its_layout_gives_none(
    tmp_path: Path, situation: str
) -> None:
    if situation == "no version rows":
        db = _proj_dir(tmp_path, "p", None) / "proj.db"
    elif situation == "no database":
        db = tmp_path / "absent" / "proj.db"
    elif situation == "not sqlite":
        db = tmp_path / "proj.db"
        db.write_bytes(b"this is not a database at all, just text")
    else:
        db = tmp_path / "proj.db"
        with sqlite3.connect(db) as con:
            con.execute("create table metadata (a text, b text)")

    assert pb._read_proj_layout_version(db) is None


def test_with_no_database_to_read_any_layout_is_enough(env) -> None:
    assert pb._required_layout_minor(None) == 0


def test_a_proj_data_already_on_the_pyproj_database_is_kept_and_proj_lib_follows(
    env, tmp_path: Path
) -> None:
    folder = _proj_dir(tmp_path, "pyproj", 4)
    _pyproj_dir_is(env, folder)
    env.setenv("PROJ_DATA", str(folder))

    pb._ensure_proj_data_from_env()

    assert pb.os.environ["PROJ_DATA"] == str(folder)
    assert pb.os.environ["PROJ_LIB"] == str(folder)


@pytest.mark.parametrize("where", ["outside", "missing"])
def test_a_proj_data_outside_the_environment_or_gone_is_replaced_with_a_warning(
    env, tmp_path: Path, caplog, where: str
) -> None:
    folder = _proj_dir(tmp_path, "pyproj", 4)
    _pyproj_dir_is(env, folder)
    stale = _proj_dir(tmp_path, "system", 4) if where == "outside" else tmp_path / "gone"
    env.setenv("PROJ_DATA", str(stale))

    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        pb._ensure_proj_data_from_env()

    assert Path(pb.os.environ["PROJ_DATA"]) == folder.resolve()
    assert str(stale) in caplog.text


@pytest.mark.parametrize("pyproj_dir", [None, "no_db"])
def test_without_a_pyproj_database_the_variables_are_left_alone(
    env, tmp_path: Path, pyproj_dir
) -> None:
    folder = None if pyproj_dir is None else tmp_path / "no_db"
    if folder:
        folder.mkdir()
    _pyproj_dir_is(env, folder)

    pb._ensure_proj_data_from_env()

    assert "PROJ_DATA" not in pb.os.environ


def test_when_no_candidate_is_new_enough_a_warning_tells_what_to_update(
    env, tmp_path: Path, caplog
) -> None:
    old = _proj_dir(tmp_path, "old", 2)
    wheel = _proj_dir(tmp_path, "wheel", 6)
    env.setattr(pb, "_bundled_proj_data_dirs", lambda: [wheel])
    # the wheel database is required (minor 6) yet reported unreadable during the search
    calls = {"n": 0}

    def reader(path):
        calls["n"] += 1
        return (1, 2) if "old" in str(path) else (1, 6) if calls["n"] <= 2 else None

    env.setattr(pb, "_read_proj_layout_version", reader)
    _pyproj_dir_is(env, old)
    env.setenv("PROJ_DATA", str(old))

    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        pb._ensure_proj_db_compatibility()

    assert "older than expected (need >= 6)" in caplog.text


def test_a_layout_error_from_proj_names_the_minor_version_to_look_for(env, tmp_path: Path) -> None:
    old = _proj_dir(tmp_path, "old", 2)
    new = _proj_dir(tmp_path, "new", 5)
    env.setattr(pb, "_bundled_proj_data_dirs", lambda: [new])
    _pyproj_dir_is(env, old)
    env.setenv("PROJ_DATA", str(old))
    outcomes = [
        pyproj.exceptions.CRSError(
            "DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 5 is expected"
        ),
        None,
    ]

    def from_epsg(_code):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome

    env.setattr(pyproj.CRS, "from_epsg", staticmethod(from_epsg))
    env.setattr(pb, "_required_layout_minor", lambda _d: 0)

    pb._ensure_proj_db_compatibility()

    assert pb.os.environ["PROJ_DATA"] == str(new)


def test_a_crs_error_unrelated_to_the_layout_is_not_ours_to_fix(env, tmp_path: Path) -> None:
    folder = _proj_dir(tmp_path, "pyproj", 4)
    _pyproj_dir_is(env, folder)

    def broken(_code):
        raise RuntimeError("something else")

    env.setattr(pyproj.CRS, "from_epsg", staticmethod(broken))

    pb._ensure_proj_db_compatibility()

    assert "PROJ_DATA" not in pb.os.environ


def test_a_layout_problem_that_survives_the_switch_is_logged(env, tmp_path: Path, caplog) -> None:
    folder = _proj_dir(tmp_path, "pyproj", 4)
    _pyproj_dir_is(env, folder)

    def always_broken(_code):
        raise pyproj.exceptions.CRSError(
            "DATABASE.LAYOUT.VERSION.MINOR = 1 whereas a number >= 9 is expected"
        )

    env.setattr(pyproj.CRS, "from_epsg", staticmethod(always_broken))

    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        pb._ensure_proj_db_compatibility()

    assert "mismatch persists" in caplog.text


# ``bootstrap_proj`` points PROJ_DATA at a database every PROJ of the environment reads.
#
# pyproj and rasterio wheels each bundle their own PROJ and ``proj.db``. pyproj
# reads its own copy first, rasterio reads ``PROJ_DATA`` first. PROJ accepts a
# database of its own layout or a newer minor one. On Windows with Python 3.11,
# pyproj 3.7.2 ships layout 1.4 and rasterio 1.4.4 layout 1.5: pointing
# ``PROJ_DATA`` at pyproj's copy broke every ``rasterio`` CRS lookup in the
# process and in every child that inherits the variable.


def _two_databases(
    env, tmp_path: Path, pyproj_minor: int, rasterio_minor: int
) -> tuple[Path, Path]:
    """An environment whose pyproj and rasterio ship the given database layouts."""
    site = tmp_path / "venv" / "site-packages"
    pyproj_dir = _proj_dir(site / "pyproj", "proj_dir", pyproj_minor)
    rasterio_dir = _proj_dir(site / "rasterio", "proj_data", rasterio_minor)
    _pyproj_dir_is(env, pyproj_dir)
    env.setattr(pb, "_bundled_proj_data_dirs", lambda: [rasterio_dir])
    return pyproj_dir, rasterio_dir


def test_the_newest_database_stays_when_pyproj_ships_it(env, tmp_path: Path) -> None:
    pyproj_dir, _ = _two_databases(env, tmp_path, pyproj_minor=6, rasterio_minor=5)

    pb.bootstrap_proj()

    assert Path(pb.os.environ["PROJ_DATA"]).resolve() == pyproj_dir.resolve()
