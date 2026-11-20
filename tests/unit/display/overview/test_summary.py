"""Counts and tables of the overview of a site: stations per family, area (km2), date window."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.overview.summary import compute_overview_summary, station_table


def station(family: str, item_id: str, first: str | None, last: str | None, **extra):
    row = {
        "row_kind": "station",
        "family": family,
        "item_id": item_id,
        "x": 1.0,
        "y": 2.0,
        "first": None if first is None else pd.Timestamp(first, tz="UTC"),
        "last": None if last is None else pd.Timestamp(last, tz="UTC"),
    }
    row.update(extra)
    return row


def loaded_points(*station_ids: str) -> SimpleNamespace:
    points = [SimpleNamespace(station_id=station_id) for station_id in station_ids]
    return SimpleNamespace(points=points)


STATION_TABLES = [
    pytest.param(
        [
            {"row_kind": "family", "family": "hydrometry", "item_id": ""},
            station("hydrometry", "H1", "2020-01-02", "2020-01-03"),
            station("water_quality", "WQ1", "2020-01-01", "2020-03-01"),
        ],
        [
            {
                "type": "Hydrometry",
                "id": "H1",
                "x": 1.0,
                "y": 2.0,
                "start": "2020-01-02",
                "end": "2020-01-03",
            },
            {
                "type": "Water quality",
                "id": "WQ1",
                "x": 1.0,
                "y": 2.0,
                "start": "2020-01-01",
                "end": "2020-03-01",
            },
        ],
        id="stations only, dates as days",
    ),
    pytest.param(
        [station("piezometry", "P1", None, None, x=None, y=None)],
        [{"type": "Piezometry", "id": "P1", "x": None, "y": None, "start": "", "end": ""}],
        id="no location, no period",
    ),
    pytest.param([{"row_kind": "well", "family": "pumping", "item_id": "w"}], [], id="no station"),
]


@pytest.mark.parametrize(("rows", "expected"), STATION_TABLES)
def test_station_table(rows, expected) -> None:
    assert station_table(rows) == expected


def test_summary_counts_stations() -> None:
    loaded = SimpleNamespace(
        hydrometry=loaded_points("H1", "H2"),
        piezometry=loaded_points("P1"),
        intermittency=None,
        water_quality=loaded_points("WQ1", "WQ2"),
        hydrography=SimpleNamespace(
            fields=[SimpleNamespace(metadata={"vector_path": "/missing.gpkg"})]
        ),
    )
    inventory = [
        station("hydrometry", "H1", None, None),
        station("hydrometry", "H2", None, None),
        station("piezometry", "P1", None, None),
        station("water_quality", "WQ1", None, None),
        station("water_quality", "WQ2", None, None),
    ]
    state = SimpleNamespace(
        loaded_data=loaded,
        domain_geographic=SimpleNamespace(catchment_area_km2=12.5, x_outlet=1.25, y_outlet=2.5),
        cfg=SimpleNamespace(
            overview=SimpleNamespace(name="Naizin", date_start="2020-01-01", date_end="2020-12-31")
        ),
        workspace=None,
    )

    summary = compute_overview_summary(state, inventory)

    assert summary.watershed_name == "Naizin"
    assert summary.catchment_area_km2 == 12.5
    assert summary.outlet_xy == (1.25, 2.5)
    assert summary.n_hydrometry == 2
    assert summary.n_piezometry == 1
    assert summary.n_water_quality == 2
    assert summary.n_streams == 0
    assert summary.date_start == "2020-01-01"


def stream_state(hydrography) -> SimpleNamespace:
    loaded = SimpleNamespace(
        hydrometry=None,
        piezometry=None,
        intermittency=None,
        water_quality=None,
        hydrography=hydrography,
    )
    return SimpleNamespace(
        loaded_data=loaded,
        domain_geographic=None,
        cfg=SimpleNamespace(overview=None, site=SimpleNamespace(label="Naizin", name="naizin")),
        workspace=None,
    )


def test_streams_are_counted_in_the_vector_file(tmp_path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString

    reaches = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 0)])], crs="EPSG:2154"
    )
    path = tmp_path / "streams.gpkg"
    reaches.to_file(path, driver="GPKG")
    hydrography = SimpleNamespace(fields=[SimpleNamespace(metadata={"vector_path": str(path)})])

    summary = compute_overview_summary(stream_state(hydrography), [])

    assert summary.n_streams == 2
    assert summary.watershed_name == "Naizin"  # from the site, there is no overview


NO_STREAM_FILE = [
    pytest.param(None, id="no hydrography"),
    pytest.param(SimpleNamespace(fields=[]), id="no record"),
    pytest.param(SimpleNamespace(fields=[SimpleNamespace(metadata={})]), id="no vector path"),
    pytest.param(
        SimpleNamespace(fields=[SimpleNamespace(metadata={"vector_path": ""})]), id="empty path"
    ),
]


@pytest.mark.parametrize("hydrography", NO_STREAM_FILE)
def test_no_stream_file_counts_no_stream(hydrography) -> None:
    assert compute_overview_summary(stream_state(hydrography), []).n_streams == 0
