from __future__ import annotations

from typing import Any

import geopandas as gpd
import pytest
from pydantic import ValidationError

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.sites import RecipeSpec, SitesConfig, SitesRunConfig
from hydromodpy.core.site.row import SiteRow
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.data.sites.catalog import write_catalog
from hydromodpy.data.sites.single_site import SiteMismatchError, match_site
from hydromodpy.project.launch.plan import expand_plan, group_issues, is_empty_cell, read_table
from tests.unit.project.launch.test_plan import write_sites_project


def _validate(payload: dict[str, Any]) -> HydroModPyConfig:
    """Validate a payload that declares its DEM under ``[[data.dem.sources]]``."""
    return HydroModPyConfig.model_validate(payload, context={"allow_dem_bootstrap": True})


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


def test_an_unknown_name_near_a_declared_site_names_it() -> None:
    match = match_site("romazy", (377100.0, 6831400.0), "EPSG:2154", _ROWS, near_site_m=500.0)
    assert match is not None and match.row.site == "couesnon" and not match.known_name


def test_an_unknown_name_far_from_every_site_is_new() -> None:
    assert match_site("vire", (300000.0, 6900000.0), "EPSG:2154", _ROWS, near_site_m=500.0) is None
    assert match_site("vire", None, None, _ROWS) is None


def _one_site_config(root, name: str, x: float, y: float):
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    (root / "data").mkdir(exist_ok=True)
    (root / "dem.tif").write_bytes(b"never read")
    return HydroModPyConfig.from_dict(
        {
            "workspace": {"data_dir": "data"},
            "site": {"name": name},
            "data": {"dem": {"sources": [{"source": "file", "path": "dem.tif"}]}},
            "geographic": {
                "crs_project": "EPSG:2154",
                "catchment": {
                    "kind": "from_outlet_coord",
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
    from hydromodpy.data.sites.single_site import resolve_single_site

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


REAL: dict[str, Any] = {
    "geographic": {"catchment": {"kind": "dem"}},
    "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
}


def test_a_reversed_metrics_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="before it starts"):
        _validate(
            {**SYNTHETIC, "metrics": {"window": {"start": "2002-01-01", "end": "2001-01-01"}}}
        )
