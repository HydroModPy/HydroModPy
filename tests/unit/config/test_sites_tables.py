"""Site and recipe tables are read as rows, each cell keeping its origin."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from hydromodpy.config.sites.expansion import expand_plan
from hydromodpy.config.sites.issues import group_issues
from hydromodpy.config.sites.tables import is_empty_cell, read_table
from hydromodpy.core.toml_io.paths import lookup
from tests.unit.config.test_sites_plan import write_sites_project


def _write_points(path: Path) -> None:
    frame = gpd.GeoDataFrame(
        {"site": ["nancon", "couesnon"], "gauge": ["J0014010", None]},
        geometry=gpd.points_from_xy([389285.91, 377120.0], [6816518.749, 6831410.0]),
        crs="EPSG:2154",
    )
    frame.to_file(path, driver="GPKG")


def test_a_geopackage_of_points_gains_the_geometry_columns(tmp_path: Path) -> None:
    path = tmp_path / "sites.gpkg"
    _write_points(path)

    table = read_table(path, label="sites.gpkg")

    assert table.columns == ("site", "gauge", "geometry_x", "geometry_y")
    assert [row.cells["site"] for row in table.rows] == ["nancon", "couesnon"]
    assert table.rows[0].cells["geometry_x"] == pytest.approx(389285.91)
    assert table.rows[1].cells["geometry_y"] == pytest.approx(6831410.0)
    assert is_empty_cell(table.rows[1].cells["gauge"])
    # A binary table has no physical line: the origin names the row.
    assert table.rows[1].line is None
    assert str(table.rows[1].origin(table, "gauge")) == "sites.gpkg row 2 column gauge"


def test_a_geopackage_site_table_binds_the_outlet_to_the_geometry(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_column=False)
    _write_points(project / "sites.gpkg")
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8")
        .replace('table = "sites.csv"', 'table = "sites.gpkg"')
        .replace(
            '"geographic.catchment.x_outlet" = "x_outlet"',
            '"geographic.catchment.x_outlet" = "geometry_x"',
        )
        .replace(
            '"geographic.catchment.y_outlet" = "y_outlet"',
            '"geographic.catchment.y_outlet" = "geometry_y"',
        ),
        encoding="utf-8",
    )

    draft = expand_plan(project, project_toml)

    assert not draft.errors, group_issues(draft.errors)
    nancon = next(case for case in draft.cases if case.case_id == "nancon-base")
    assert lookup(nancon.document, "geographic.catchment.x_outlet") == pytest.approx(389285.91)
    assert lookup(nancon.document, "site.gauge") == "J0014010"
    couesnon = next(case for case in draft.cases if case.case_id == "couesnon-base")
    assert "gauge" not in couesnon.document["site"]
    assert "sites.gpkg" in {p.name for p in draft.inputs}
