"""``hmp site import``: three sources, one row shape, one catalog.

A site table, a vector layer of outlets and the Hub'Eau stations of a box all
become ``SiteRow`` rows; ``--tag`` marks them, ``--dry-run``
writes nothing, and the catalog refuses what ``add`` refuses.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.cli.commands import site
from hydromodpy.cli.helpers import fail
from hydromodpy.core.site import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.data.sites.catalog import read_catalog, write_catalog
from hydromodpy.data.sites.importers import (
    rows_from_hubeau,
    rows_from_layer,
    rows_from_table,
    site_name,
)

NANCON_LON, NANCON_LAT = -1.19785, 48.37462


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "projects").mkdir()
    return root


def _hmp_site(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="hmp")
    site.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["site", *argv])
    try:
        args._handler(args)
    except Exception as exc:  # noqa: BLE001 - what the dispatcher of hmp does
        fail(exc)


def _stations() -> list[dict]:
    return [
        {
            "code_station": "J001401001",
            "code_site": "J0014010",
            "libelle_station": "Le Nancon a Lecousse",
            "longitude_station": NANCON_LON,
            "latitude_station": NANCON_LAT,
            "date_ouverture_station": "1970-01-01T00:00:00Z",
            "date_fermeture_station": None,
        },
        {
            "code_station": "J001401002",
            "code_site": "J0014010",
            "libelle_station": "Le Nancon, second sensor",
            "longitude_station": NANCON_LON,
            "latitude_station": NANCON_LAT,
            "date_ouverture_station": "1990-01-01T00:00:00Z",
            "date_fermeture_station": None,
        },
        {
            "code_station": "J002001001",
            "code_site": "J0020010",
            "libelle_station": "A young station",
            "longitude_station": -1.30,
            "latitude_station": 48.30,
            "date_ouverture_station": "2020-01-01T00:00:00Z",
            "date_fermeture_station": None,
        },
    ]


@pytest.mark.fast
def test_a_site_table_is_read_in_site_row_columns(tmp_path):
    table = tmp_path / "stations.csv"
    table.write_text(
        ",".join(SITE_ROW_COLUMNS)
        + "\nnancon,Le Nancon,J001401001,hubeau:J0014010,389285.9,6816518.7,EPSG:2154,a;b\n",
        encoding="utf-8",
    )

    rows = rows_from_table(table).rows

    assert rows == (
        SiteRow(
            site="nancon",
            label="Le Nancon",
            gauge="J001401001",
            uri="hubeau:J0014010",
            x_outlet=389285.9,
            y_outlet=6816518.7,
            crs="EPSG:2154",
            tags=("a", "b"),
        ),
    )


@pytest.mark.fast
def test_a_free_column_in_a_site_table_is_refused_with_its_line(tmp_path):
    table = tmp_path / "stations.csv"
    table.write_text("site,k_table\nnancon,k.csv\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match=r"stations\.csv:2: unknown site table column\(s\): k_table"
    ):
        rows_from_table(table)


def test_a_layer_of_outlet_points_is_read_with_its_crs(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    layer = tmp_path / "exutoires.gpkg"
    gpd.GeoDataFrame(
        {"code": ["nancon", "aber-wrach"], "station": ["J001401001", None]},
        geometry=[Point(389285.9, 6816518.7), Point(150000.0, 6850000.0)],
        crs="EPSG:2154",
    ).to_file(layer, driver="GPKG")

    rows = rows_from_layer(layer, name_field="code", gauge_field="station").rows

    assert [row.site for row in rows] == ["nancon", "aber_wrach"]
    assert rows[0].gauge == "J001401001"
    assert rows[1].gauge is None
    assert rows[0].crs == "EPSG:2154"
    assert rows[0].x_outlet == pytest.approx(389285.9)


def test_a_layer_field_that_does_not_exist_is_named(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    layer = tmp_path / "exutoires.gpkg"
    gpd.GeoDataFrame({"code": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:2154").to_file(
        layer, driver="GPKG"
    )

    with pytest.raises(ValueError, match="no field 'name'; the fields are code"):
        rows_from_layer(layer, name_field="name")


@pytest.mark.fast
def test_hubeau_stations_become_one_site_per_hubeau_site():
    asked: list[tuple] = []

    def discover(bbox):
        asked.append(bbox)
        return _stations()

    imported = rows_from_hubeau(
        (150000, 6700000, 420000, 6900000),
        min_years=10,
        discover=discover,
        today=date(2026, 10, 15),
    )

    xmin, ymin, xmax, ymax = asked[0]
    assert -6.0 < xmin < xmax < 0.0 and 46.0 < ymin < ymax < 50.0
    assert [row.site for row in imported.rows] == ["J0014010"]
    nancon = imported.rows[0]
    assert nancon.gauge == "J001401001"
    assert nancon.uri == "hubeau:J0014010"
    assert nancon.crs == "EPSG:2154"
    assert nancon.x_outlet == pytest.approx(389285.9, abs=5.0)
    assert imported.skipped == ("station J002001001: open 6.8 years, under --min-years 10",)


def test_hubeau_outlets_are_snapped_onto_the_network_or_skipped(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from pyproj import Transformer
    from shapely.geometry import LineString

    x, y = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform(
        NANCON_LON, NANCON_LAT
    )
    network = tmp_path / "rivers.gpkg"
    gpd.GeoDataFrame(
        geometry=[LineString([(x - 500, y + 50), (x + 500, y + 50)])], crs="EPSG:2154"
    ).to_file(network, driver="GPKG")

    imported = rows_from_hubeau(
        (150000, 6700000, 420000, 6900000),
        discover=lambda bbox: _stations(),
        snap_network=network,
        snap_max_m=200.0,
        today=date(2026, 10, 15),
    )

    assert [row.site for row in imported.rows] == ["J0014010"]
    assert imported.rows[0].y_outlet == pytest.approx(y + 50, abs=0.01)
    assert len(imported.skipped) == 1
    assert imported.skipped[0].startswith("site J0020010:")


@pytest.mark.fast
def test_site_name_keeps_only_the_site_name_grammar():
    assert site_name(" aber-wrach 2 ") == "aber_wrach_2"
    with pytest.raises(ValueError):
        site_name("---")


@pytest.mark.fast
def test_hmp_site_import_tags_every_row_and_writes_the_catalog(tmp_path, capsys):
    root = _workspace(tmp_path)
    table = tmp_path / "stations.csv"
    table.write_text(
        "site,x_outlet,y_outlet,crs\nnancon,389285.9,6816518.7,EPSG:2154\n"
        "aber,150000,6850000,EPSG:2154\n",
        encoding="utf-8",
    )

    _hmp_site(["import", str(table), "--tag", "bretagne", "-w", str(root)])

    rows = read_catalog(root)
    assert [row.site for row in rows] == ["nancon", "aber"]
    assert all(row.tags == ("bretagne",) for row in rows)
    assert "[written] 2 site(s)" in capsys.readouterr().out


@pytest.mark.fast
def test_hmp_site_import_dry_run_writes_nothing(tmp_path, capsys):
    root = _workspace(tmp_path)
    table = tmp_path / "stations.csv"
    table.write_text("site\nnancon\n", encoding="utf-8")

    _hmp_site(["import", str(table), "--dry-run", "-w", str(root)])

    assert "nothing written" in capsys.readouterr().out
    assert read_catalog(root) == []


@pytest.mark.fast
def test_hmp_site_import_refuses_a_close_outlet_and_writes_nothing(tmp_path, capsys):
    root = _workspace(tmp_path)
    write_catalog(
        root, [SiteRow(site="nancon", x_outlet=389285.9, y_outlet=6816518.7, crs="EPSG:2154")]
    )
    table = tmp_path / "stations.csv"
    table.write_text(
        "site,x_outlet,y_outlet,crs\nJ0014010,389300,6816520,EPSG:2154\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["import", str(table), "-w", str(root)])

    assert stop.value.code == 12
    assert "site J0014010: outlet 14 m from site nancon" in capsys.readouterr().err
    assert [row.site for row in read_catalog(root)] == ["nancon"]

    _hmp_site(["import", str(table), "--force", "-w", str(root)])
    assert [row.site for row in read_catalog(root)] == ["nancon", "J0014010"]


@pytest.mark.fast
def test_hmp_site_import_reads_exactly_one_source(tmp_path, capsys):
    root = _workspace(tmp_path)
    table = tmp_path / "stations.csv"
    table.write_text("site\nnancon\n", encoding="utf-8")

    with pytest.raises(SystemExit) as stop:
        _hmp_site(["import", str(table), "--hubeau", "-w", str(root)])

    assert stop.value.code == 2
    assert "exactly one source" in capsys.readouterr().err
