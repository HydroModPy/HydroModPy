"""A station manager warns about a station outside its extent, in the right frame.

``project_extent`` reaches a station manager in WGS84; a station may be
declared in any CRS. The check reprojects the station before comparing, so a
Lambert-93 station inside the basin is not reported, and a request served by
box hands the station manager its box in WGS84. The same holds for a user's
custom station folder whose locations are written in Lambert-93.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data import DataRequest, DataStore, run_request
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

RENNES_WGS84 = (-1.75, 48.05, -1.60, 48.15)
RENNES_L93 = [340000.0, 6780000.0, 360000.0, 6800000.0]
PERIOD = (pd.Timestamp("2020-01-01").to_pydatetime(), pd.Timestamp("2020-01-10").to_pydatetime())
# J0001 lies in Rennes, J9999 in Brest; both are written in Lambert-93.
CUSTOM_STATIONS_L93 = {"J0001": (351500.0, 6789500.0), "J9999": (146636.0, 6836217.0)}


def _station(station_id: str, x: float, y: float, crs: str) -> PointRecord:
    dates = pd.date_range("2020-01-01", periods=10, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.ones(10)}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=x, y=y, crs=crs),
    )


def _outside_warnings(monkeypatch, stations: list[PointRecord]) -> list[str]:
    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", lambda cfg, **kwargs: stations)
    cfg = HydrometryConfig.model_validate({"sources": [{"source": "hubeau"}]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        DataStore().load_variable(
            "hydrometry", cfg, project_extent=RENNES_WGS84, project_period=PERIOD
        )
    return [str(w.message) for w in caught if "outside project_extent" in str(w.message)]


def test_a_lambert93_station_inside_the_basin_is_not_reported(monkeypatch) -> None:
    inside_l93 = _station("J0001", 351500.0, 6789500.0, "EPSG:2154")
    assert _outside_warnings(monkeypatch, [inside_l93]) == []


def test_a_station_outside_the_basin_is_named(monkeypatch) -> None:
    far = _station("J9999", -3.5, 47.0, "EPSG:4326")
    (message,) = _outside_warnings(monkeypatch, [far])
    assert "J9999" in message


def test_a_box_request_hands_the_station_manager_its_box_in_wgs84(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(
        HydrometryManager.SOURCES,
        "hubeau",
        lambda cfg, **kwargs: [_station("J0001", -1.68, 48.11, "EPSG:4326")],
    )
    request = DataRequest.for_variable(
        "hydrometry",
        bbox=[340000.0, 6780000.0, 360000.0, 6800000.0],
        crs="EPSG:2154",
        start="2020-01-01",
        end="2020-01-10",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_request(request, tmp_path / "out")
    assert not [w for w in caught if "outside project_extent" in str(w.message)]


def _custom_folder(tmp_path: Path, fmt: str) -> Path:
    """A user's station folder: a Lambert-93 location file and one chronicle per station."""
    folder = tmp_path / "hydrometry"
    folder.mkdir()
    ids = list(CUSTOM_STATIONS_L93)
    xs = [x for x, _ in CUSTOM_STATIONS_L93.values()]
    ys = [y for _, y in CUSTOM_STATIONS_L93.values()]
    if fmt == "gpkg":
        gpd = pytest.importorskip("geopandas")
        gpd.GeoDataFrame(
            {"id": ids, "unit": "m3/s"},
            geometry=gpd.points_from_xy(xs, ys),
            crs="EPSG:2154",
        ).to_file(folder / "hydrometry_custom_LOC.gpkg")
    else:
        pd.DataFrame({"id": ids, "x": xs, "y": ys, "crs": "EPSG:2154", "unit": "m3/s"}).to_csv(
            folder / "hydrometry_custom_LOC.csv", index=False
        )
    dates = pd.date_range("2020-01-01", periods=10, freq="D")
    for station_id in ids:
        pd.DataFrame({"datetime": dates, "value": np.ones(10)}).to_csv(
            folder / f"hydrometry_custom_{station_id}.csv", index=False
        )
    return folder


def _named_outside(caught: list[warnings.WarningMessage]) -> list[str]:
    return [str(w.message) for w in caught if "outside project_extent" in str(w.message)]


@pytest.mark.parametrize("fmt", ["gpkg", "csv"])
def test_a_custom_lambert93_folder_is_judged_in_wgs84(tmp_path: Path, fmt: str) -> None:
    folder = _custom_folder(tmp_path, fmt)
    cfg = HydrometryConfig.model_validate({"sources": [{"source": "custom", "path": str(folder)}]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = DataStore(data_root=tmp_path / "data").load_variable(
            "hydrometry", cfg, project_extent=RENNES_WGS84, project_period=PERIOD
        )

    assert {p.location.crs for p in result.points} == {"EPSG:2154"}, (
        "anti-vacuity: the stations must come from the file, in Lambert-93"
    )
    (message,) = _named_outside(caught)
    assert "J9999" in message
    assert "J0001" not in message


def test_a_box_request_keeps_the_custom_lambert93_station_inside_its_box(tmp_path: Path) -> None:
    # The box becomes a mask on the custom source: the Brest station is dropped
    # before the warning runs, and the Rennes one survives only if the mask
    # reads its Lambert-93 coordinates in the right frame.
    folder = _custom_folder(tmp_path, "gpkg")
    request = DataRequest.model_validate(
        {
            "data": {"hydrometry": {"sources": [{"source": "custom", "path": str(folder)}]}},
            "extent": {"bbox": RENNES_L93, "crs": "EPSG:2154"},
            "period": {"start": "2020-01-01", "end": "2020-01-10"},
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_request(request, tmp_path / "out", store=DataStore(data_root=tmp_path / "data"))

    report = json.loads((tmp_path / "out" / "request.json").read_text(encoding="utf-8"))
    (served,) = report["files"]
    assert served["stations"] == ["J0001"]
    assert _named_outside(caught) == []
