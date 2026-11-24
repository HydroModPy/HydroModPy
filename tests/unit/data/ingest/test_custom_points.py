"""Which chronicle a station source reads: a folder picks one or refuses, a named file is read."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.ingest.custom_points import (
    load_file_multiformat,
    load_file_points,
    location_files_beside,
)
from hydromodpy.data.source.file import FileSource
from hydromodpy.data.source.port import FetchRequest

pytestmark = pytest.mark.fast

MONTHLY = "recharge_custom_NANCON_20000101_20021231_M.csv"
DAILY = "recharge_custom_NANCON_20000101_20021231_D.csv"
REA = "recharge_custom_NANCON_REA_19900101_20201231_D.csv"
SIM2 = "recharge_custom_NANCON_SIM2_20000101_20021231_M.csv"


def _folder(tmp_path: Path, stations: tuple[str, ...], files: dict[str, float]) -> Path:
    folder = tmp_path / "recharge"
    folder.mkdir()
    rows = "".join(f"{sid},389285.9,6816518.7,EPSG:2154,mm/day\n" for sid in stations)
    (folder / "recharge_custom_LOC.csv").write_text("id,x,y,crs,unit\n" + rows)
    for name, value in files.items():
        (folder / name).write_text(f"datetime,value\n2000-01-31,{value}\n2000-02-29,{value}\n")
    return folder


def _load(path: Path, station_ids: list[str] | None = None):
    return load_file_points(
        path=path, variable_name="recharge", internal_unit="mm/day", station_ids=station_ids
    )


@pytest.mark.parametrize(
    ("stations", "files", "station", "read"),
    [
        (("NANCON",), {MONTHLY: 1.0, REA: 2.0, SIM2: 3.0}, "NANCON", MONTHLY),
        (("NANCON", "NANCON_REA"), {MONTHLY: 1.0, REA: 2.0}, "NANCON_REA", REA),
        (
            ("NANCON",),
            {"recharge_custom_NANCON_D.csv": 4.0},
            "NANCON",
            "recharge_custom_NANCON_D.csv",
        ),
        (("NANCON",), {"recharge_custom_NANCON.csv": 5.0}, "NANCON", "recharge_custom_NANCON.csv"),
    ],
)
def test_a_folder_reads_the_one_chronicle_of_the_station(
    tmp_path: Path, stations: tuple[str, ...], files: dict[str, float], station: str, read: str
) -> None:
    (record,) = _load(_folder(tmp_path, stations, files), [station])
    assert record.file_path.name == read


def test_a_folder_with_two_chronicles_of_a_station_is_refused(tmp_path: Path) -> None:
    folder = _folder(tmp_path, ("NANCON",), {MONTHLY: 1.0, DAILY: 2.0})
    with pytest.raises(DataSourceError, match=rf"2 chronicles.*{DAILY}, {MONTHLY}"):
        _load(folder, ["NANCON"])


@pytest.mark.parametrize(
    ("stations", "station_ids"), [(("NANCON",), ["NANCON"]), (("NANCON",), None)]
)
def test_a_named_chronicle_is_read_with_the_location_file_of_its_folder(
    tmp_path: Path, stations: tuple[str, ...], station_ids: list[str] | None
) -> None:
    folder = _folder(tmp_path, stations, {MONTHLY: 1.0, DAILY: 2.0})
    (record,) = _load(folder / MONTHLY, station_ids)
    assert record.station_id == "NANCON"
    assert record.data["value"].tolist() == [1.0, 1.0]
    assert record.frequency == "M"
    assert [path.name for path in record.location_files] == ["recharge_custom_LOC.csv"]


def test_the_grid_family_reads_a_named_chronicle(tmp_path: Path) -> None:
    folder = _folder(tmp_path, ("NANCON",), {MONTHLY: 1.0, DAILY: 2.0})
    (record,) = load_file_multiformat(
        folder / DAILY, variable_name="recharge", internal_unit="mm/day", station_ids=["NANCON"]
    )
    assert record.file_path.name == DAILY


@pytest.mark.parametrize(
    ("stations", "named", "station_ids", "refusal"),
    [
        (("NANCON", "KERVIDY"), MONTHLY, None, r"one station, and the source reads 2"),
        (
            ("NANCON", "KERVIDY"),
            MONTHLY,
            ["KERVIDY"],
            r"named for station NANCON.*reads station KERVIDY",
        ),
        (("NANCON",), "recharge.txt", ["NANCON"], r"recharge\.txt is no chronicle"),
    ],
)
def test_a_named_file_that_is_not_the_chronicle_of_the_station_is_refused(
    tmp_path: Path,
    stations: tuple[str, ...],
    named: str,
    station_ids: list[str] | None,
    refusal: str,
) -> None:
    folder = _folder(tmp_path, stations, {MONTHLY: 1.0})
    (folder / "recharge.txt").write_text("datetime,value\n2000-01-31,1.0\n")
    with pytest.raises(DataSourceError, match=refusal):
        _load(folder / named, station_ids)


def test_the_file_source_of_a_named_chronicle_pins_its_location_file(tmp_path: Path) -> None:
    folder = _folder(tmp_path, ("NANCON",), {MONTHLY: 1.0, DAILY: 2.0})
    named = folder / MONTHLY
    source = FileSource(path=named, beside=location_files_beside(named, "recharge"))
    source.section = "recharge"
    files = source.fetch(FetchRequest(out_dir=tmp_path)).files
    assert [Path(record.path).name for record in files] == [MONTHLY, "recharge_custom_LOC.csv"]
