"""The sites table is read and bound to the cases of a sites project."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site import SiteRow
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.data.sites.catalog import write_catalog
from hydromodpy.project.launch.sites.expansion import expand_plan
from hydromodpy.project.launch.sites.issues import group_issues
from hydromodpy.project.launch.sites.tables import is_empty_cell, read_table
from tests.unit.project.launch.test_sites_plan import write_sites_project


def test_the_catalog_columns_reach_the_case_without_bind(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    write_catalog(
        workspace,
        [
            SiteRow(
                site="nancon",
                label="Le Nancon",
                gauge="J0014010",
                x_outlet=389285.91,
                y_outlet=6816518.749,
                crs="EPSG:2154",
            ),
            SiteRow(site="couesnon", x_outlet=377120.0, y_outlet=6831410.0),
        ],
    )
    project = write_sites_project(tmp_path, k_column=False)
    project_toml = project / "project.toml"
    text = project_toml.read_text(encoding="utf-8")
    text = text.replace('data_dir = "data"', f'root = "{workspace.as_posix()}"')
    text = text.replace('table = "sites.csv"\n', "")
    for line in (
        '"site.name" = "site"\n',
        '"site.gauge" = "gauge"\n',
        '"geographic.catchment.x_outlet" = "x_outlet"\n',
        '"geographic.catchment.y_outlet" = "y_outlet"\n',
    ):
        text = text.replace(line, "")
    project_toml.write_text(text, encoding="utf-8")

    draft = expand_plan(project, project_toml)

    assert not draft.errors, group_issues(draft.errors)
    assert [site.name for site in draft.sites] == ["nancon", "couesnon"]
    nancon = next(case for case in draft.cases if case.case_id == "nancon-base")
    assert lookup(nancon.document, "site.label") == "Le Nancon"
    assert lookup(nancon.document, "site.gauge") == "J0014010"
    assert lookup(nancon.document, "geographic.catchment.x_outlet") == 389285.91
    couesnon = next(case for case in draft.cases if case.case_id == "couesnon-k2e_5")
    assert "gauge" not in couesnon.document["site"]


# Site and recipe tables are read as rows, each cell keeping its origin.


def _write_points(path: Path) -> None:
    frame = gpd.GeoDataFrame(
        {"site": ["nancon", "couesnon"], "gauge": ["J0014010", None]},
        geometry=gpd.points_from_xy([389285.91, 377120.0], [6816518.749, 6831410.0]),
        crs="EPSG:2154",
    )
    frame.to_file(path, driver="GPKG")


def test_a_parquet_table_keeps_its_types_and_names_its_rows(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "sites.parquet"
    pq.write_table(pa.table({"site": ["nancon", "couesnon"], "area_km2": [4.5, None]}), path)

    table = read_table(path, label="sites.parquet")

    assert table.columns == ("site", "area_km2")
    assert table.rows[0].cells == {"site": "nancon", "area_km2": 4.5}
    assert is_empty_cell(table.rows[1].cells["area_km2"])
    assert str(table.rows[1].origin(table, "site")) == "sites.parquet row 2 column site"


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("sites.csv", "", "the file is empty"),
        ("sites.csv", "site,site\na,b\n", "column(s) named twice: site"),
        ("sites.csv", "site,\na,b\n", "a column has no name"),
        ("sites.csv", "site,gauge\na\n", "sites.csv:2: 1 cells for 2 columns"),
        ("sites.json", "{}", "a table is one of"),
    ],
)
def test_a_table_that_cannot_be_read_names_its_file(
    tmp_path: Path, name: str, text: str, message: str
) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError) as info:
        read_table(path, label=name)

    assert message in str(info.value)
    assert str(info.value).startswith(name)


def test_a_missing_table_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"^sites\.csv: no such file"):
        read_table(tmp_path / "sites.csv", label="sites.csv")


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
