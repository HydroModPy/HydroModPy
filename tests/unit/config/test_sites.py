from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.hydromodpy_config import require_site_for_real_catchment
from hydromodpy.config.sites import RecipeSpec, SitesConfig, SitesRunConfig
from hydromodpy.config.sites.expansion import expand_plan
from hydromodpy.config.sites.issues import group_issues
from hydromodpy.config.sites.single_site import SiteMismatchError, match_site
from hydromodpy.config.sites.tables import is_empty_cell, read_table
from hydromodpy.core.config_kit.introspect import site_scoped_paths
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
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


# Site and recipe tables are read as rows, each cell keeping its origin.


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


def test_the_three_forms_of_a_recipe_are_read() -> None:
    sites = SitesConfig.model_validate(
        {
            "table": "sites.csv",
            "recipes_table": "recipes.csv",
            "recipes": {
                "base": "project.toml",
                "k2e_5": {"file": "project.toml", "set": {"flow.param.K.field.value": 2e-5}},
            },
        }
    )
    assert sites.recipes["base"] == Path("project.toml")
    inline = sites.recipes["k2e_5"]
    assert isinstance(inline, RecipeSpec)
    assert inline.set == {"flow.param.K.field.value": 2e-5}
    assert sites.recipes_table == Path("recipes.csv")


def test_the_defaults_are_the_measured_budget() -> None:
    run = SitesConfig().run
    assert (run.parallel, run.on_error, run.threads_per_case) == (8, "warn", 1)
    assert (run.keep_attempts, run.prepare_parallel) == (1, 2)
    assert SitesConfig().summary.metrics == ["nse"]


def test_a_dash_in_a_recipe_name_is_refused_with_the_name_to_write() -> None:
    with pytest.raises(ValidationError, match="'k2e_5'"):
        SitesConfig.model_validate({"recipes": {"k2e-5": "k.toml"}})


def test_a_recipe_named_like_a_version_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"\.v<N>"):
        SitesConfig.model_validate({"recipes": {"base.v2": "project.toml"}})


@pytest.mark.parametrize("name", ["a b", "é", "a.b"])
def test_a_recipe_name_outside_the_grammar_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match="recipe"):
        SitesConfig.model_validate({"recipes": {name: "project.toml"}})


def test_a_bind_key_written_without_quotes_is_refused() -> None:
    # TOML reads site.name = "site" as a table site holding a key name.
    with pytest.raises(ValidationError, match="without quotes"):
        SitesConfig.model_validate({"bind": {"site": {"name": "site"}}})


def test_a_bind_key_with_an_index_is_refused() -> None:
    with pytest.raises(ValidationError, match="no index"):
        SitesConfig.model_validate({"bind": {"data.hydrometry.sources[0].path": "path"}})


def test_a_bind_maps_a_key_to_a_column_or_a_list_of_columns() -> None:
    sites = SitesConfig.model_validate(
        {
            "bind": {
                "site.name": "site",
                "calibration.parameters.K.bounds": ["k_low", "k_high"],
            }
        }
    )
    assert sites.bind["calibration.parameters.K.bounds"] == ["k_low", "k_high"]


def test_a_bind_without_a_column_is_refused() -> None:
    with pytest.raises(ValidationError, match="name a column"):
        SitesConfig.model_validate({"bind": {"site.name": []}})


def test_an_inline_set_written_without_quotes_is_refused() -> None:
    with pytest.raises(ValidationError, match="without quotes"):
        RecipeSpec.model_validate({"file": "p.toml", "set": {"flow": {"param": 1}}})


def test_a_summary_column_is_a_dotted_path_without_index() -> None:
    SitesConfig.model_validate({"summary": {"columns": ["checks.budget_pct", "metrics.nse"]}})
    with pytest.raises(ValidationError, match="no index"):
        SitesConfig.model_validate({"summary": {"columns": ["metrics[0]"]}})


def test_an_export_names_a_table_or_runs() -> None:
    SitesConfig.model_validate({"export": [{"table": "by_site"}]})
    SitesConfig.model_validate({"export": [{"runs": "best", "variables": ["discharge"]}]})
    with pytest.raises(ValidationError, match="table or runs"):
        SitesConfig.model_validate({"export": [{"format": "csv"}]})
    with pytest.raises(ValidationError, match="table or runs"):
        SitesConfig.model_validate({"export": [{"table": "by_site", "runs": "best"}]})


def test_include_and_exclude_must_not_overlap() -> None:
    with pytest.raises(ValidationError, match="J0014010"):
        SitesConfig.model_validate({"include": ["J0014010"], "exclude": ["J0014010"]})


def test_a_zero_budget_is_refused() -> None:
    with pytest.raises(ValidationError, match="parallel"):
        SitesRunConfig(parallel=0)


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="where"):
        SitesConfig.model_validate({"where": "area > 10"})


_ROWS = [
    SiteRow(
        site="nancon", gauge="J0014010", x_outlet=389285.91, y_outlet=6816518.749, crs="EPSG:2154"
    ),
    SiteRow(site="couesnon", x_outlet=377120.0, y_outlet=6831410.0, crs="EPSG:2154"),
]


def test_a_known_name_at_its_outlet_is_the_row() -> None:
    match = match_site("nancon", (389300.0, 6816500.0), "EPSG:2154", _ROWS, near_site_m=500.0)
    assert match is not None and match.row.site == "nancon" and match.known_name
    assert match.distance_m == pytest.approx(23.5, abs=0.5)


def test_a_known_name_far_from_its_outlet_is_refused() -> None:
    with pytest.raises(SiteMismatchError, match="'nancon'.*m away"):
        match_site("nancon", (377120.0, 6831410.0), "EPSG:2154", _ROWS, near_site_m=500.0)


def test_an_unknown_name_near_a_declared_site_names_it() -> None:
    match = match_site("romazy", (377100.0, 6831400.0), "EPSG:2154", _ROWS, near_site_m=500.0)
    assert match is not None and match.row.site == "couesnon" and not match.known_name


def test_an_unknown_name_far_from_every_site_is_new() -> None:
    assert match_site("vire", (300000.0, 6900000.0), "EPSG:2154", _ROWS, near_site_m=500.0) is None
    assert match_site("vire", None, None, _ROWS) is None


def _one_site_config(root, name: str, x: float, y: float):
    from hydromodpy.config import HydroModPyConfig

    (root / "data").mkdir(exist_ok=True)
    (root / "dem.tif").write_bytes(b"never read")
    return HydroModPyConfig.from_dict(
        {
            "workspace": {"data_dir": "data"},
            "site": {"name": name},
            "geographic": {
                "crs_project": "EPSG:2154",
                "catchment": {
                    "kind": "from_outlet_coord",
                    "dem_init_path": "dem.tif",
                    "x_outlet": x,
                    "y_outlet": y,
                    "snap_dist": "150 m",
                    "buff_area": "10%",
                },
            },
            "simulation": {
                "name": "probe",
                "time": {
                    "start_datetime": "2000-01-01",
                    "end_datetime": "2000-03-31",
                    "step_value": "1 month",
                },
                "process": [{"id": "flow_main", "kind": "flow", "solvers": ["modflow6"]}],
            },
            "flow": {
                "flow_regime": "steady",
                "param_list": ["K"],
                "bc": {"drainage": {}},
                "param": {"K": {"field": {"kind": "homogeneous", "unit": "m/s", "value": 5e-5}}},
            },
        },
        base_dir=root,
    )


def test_resolve_single_site_reads_the_catalog_of_the_workspace(tmp_path) -> None:
    from hydromodpy.config.sites.single_site import resolve_single_site
    from hydromodpy.data.sites.catalog import write_catalog

    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    write_catalog(workspace, _ROWS)
    project = tmp_path / "project"
    project.mkdir()

    match = resolve_single_site(_one_site_config(project, "nancon", 389300.0, 6816500.0), workspace)
    assert match is not None and match.known_name and match.row.gauge == "J0014010"
    assert match.distance_m == pytest.approx(23.5, abs=0.5)

    near = resolve_single_site(_one_site_config(project, "romazy", 377100.0, 6831400.0), workspace)
    assert near is not None and not near.known_name and near.row.site == "couesnon"

    with pytest.raises(SiteMismatchError, match="'nancon'.*m away"):
        resolve_single_site(_one_site_config(project, "nancon", 377120.0, 6831410.0), workspace)

    # No catalog in the workspace: nothing to resolve against.
    bare = tmp_path / "bare"
    bare.mkdir()
    assert (
        resolve_single_site(_one_site_config(project, "nancon", 389300.0, 6816500.0), bare) is None
    )


SYNTHETIC: dict[str, Any] = {"geographic": {"source_mode": "synthetic"}}


REAL: dict[str, Any] = {"geographic": {"catchment": {"kind": "dem", "dem_init_path": "dem.tif"}}}


def test_the_four_sections_are_root_sections() -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            **SYNTHETIC,
            "metrics": {"window": {"start": "2001-01-01", "end": "2002-12-31"}},
            "publication": {"license": "etalab-2.0", "creators": ["A. Author"]},
        }
    )
    assert cfg.metrics is not None and cfg.metrics.window is not None
    assert str(cfg.metrics.window.start) == "2001-01-01"
    assert cfg.publication is not None and cfg.publication.license == "etalab-2.0"
    assert cfg.site is None and cfg.sites is None
    for name in ("site", "sites", "metrics", "publication"):
        assert name in HydroModPyConfig.model_fields


def test_a_reversed_metrics_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="before it starts"):
        HydroModPyConfig.model_validate(
            {**SYNTHETIC, "metrics": {"window": {"start": "2002-01-01", "end": "2001-01-01"}}}
        )


def test_site_and_sites_are_refused_together() -> None:
    with pytest.raises(ValidationError, match=r"\[site\] and \[sites\]"):
        HydroModPyConfig.model_validate(
            {**SYNTHETIC, "site": {"name": "nancon"}, "sites": {"table": "sites.csv"}}
        )


def test_a_real_catchment_without_a_site_is_refused_by_the_rule() -> None:
    cfg = HydroModPyConfig.model_construct(
        site=None,
        sites=None,
        geographic=HydroModPyConfig.model_fields["geographic"].annotation.model_validate(
            REAL["geographic"]
        ),
    )
    with pytest.raises(ConfigError) as caught:
        require_site_for_real_catchment(cfg)
    message = str(caught.value)
    assert "kind = 'dem'" in message
    assert '[site] with name = "<catchment>"' in message


def test_a_synthetic_domain_needs_no_site() -> None:
    cfg = HydroModPyConfig.model_validate(SYNTHETIC)
    require_site_for_real_catchment(cfg)
    assert cfg.site is None


def test_a_named_site_satisfies_the_rule() -> None:
    cfg = HydroModPyConfig.model_validate({**REAL, "site": {"name": "nancon"}})
    require_site_for_real_catchment(cfg)
    assert cfg.site is not None and cfg.site.name == "nancon"


def test_a_sites_project_takes_its_site_from_the_table() -> None:
    cfg = HydroModPyConfig.model_validate({**REAL, "sites": {"table": "sites.csv"}})
    require_site_for_real_catchment(cfg)


def test_a_toml_real_catchment_without_a_site_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[geographic.catchment]\ncatch_def = "dem"\ndem_init_path = "dem.tif"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match=r"no \[site\] names it"):
        HydroModPyConfig.from_toml(path)


def test_the_workflow_section_is_optional() -> None:
    cfg = HydroModPyConfig.model_validate(SYNTHETIC)
    assert cfg.workflow.mode is None


def test_the_site_scoped_fields_are_listed() -> None:
    paths = set(site_scoped_paths(HydroModPyConfig))
    expected = {
        "geographic.catchment.x_outlet",
        "geographic.catchment.y_outlet",
        "geographic.catchment.polyg_shp_path",
        "data.hydrometry.sources[].station_ids",
        "data.hydrometry.sources[].path",
        "data.hydrometry.sources[].mask_path",
        "data.recharge.sources[].path",
        "data.runoff.sources[].station_ids",
        "data.dem.sources[].mask_path",
        "calibration.outputs.*.observes",
        "calibration.outputs.*.map.complete",
    }
    assert expected <= paths
    # A regional input is shared by every site: not site scoped.
    assert "geographic.catchment.dem_init_path" not in paths
    assert "data.dem.sources[].path" not in paths
    assert "data.geology.sources[].path" not in paths
