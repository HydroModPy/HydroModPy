"""A [sites] project without a table reads the site catalog of the workspace."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.config.sites.expansion import expand_plan
from hydromodpy.config.sites.issues import group_issues
from hydromodpy.core.site import SiteRow
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.data.sites.catalog import write_catalog
from tests.unit.config.test_sites_plan import write_sites_project


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
