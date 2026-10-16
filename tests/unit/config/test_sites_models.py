"""The [sites] models are checked when the file is read, without the disk."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.config.sites import RecipeSpec, SitesConfig, SitesRunConfig


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
