"""The ``[sites]`` section: a campaign over many sites, one recipe per run.

``parallel`` and ``threads_per_case`` are counts, recipe names are file-safe
words, and bind keys and summary columns are dotted paths without an index.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config.sites import RecipeSpec, SitesConfig, SitesRunConfig
from hydromodpy.project.launch.plan import is_empty_cell

REFUSALS = [
    pytest.param(
        SitesConfig, {"recipes": {"k2e-5": "k.toml"}}, "'k2e_5'", id="dash in a recipe name"
    ),
    pytest.param(
        SitesConfig, {"recipes": {"base.v2": "project.toml"}}, r"\.v<N>", id="recipe like a version"
    ),
    pytest.param(SitesConfig, {"recipes": {"a b": "project.toml"}}, "recipe", id="space in a name"),
    pytest.param(SitesConfig, {"recipes": {"é": "project.toml"}}, "recipe", id="accent in a name"),
    pytest.param(SitesConfig, {"recipes": {"a.b": "project.toml"}}, "recipe", id="dot in a name"),
    # TOML reads site.name = "site" as a table site holding a key name.
    pytest.param(
        SitesConfig, {"bind": {"site": {"name": "site"}}}, "without quotes", id="bind not quoted"
    ),
    pytest.param(
        SitesConfig,
        {"bind": {"data.hydrometry.sources[0].path": "path"}},
        "no index",
        id="bind with an index",
    ),
    pytest.param(
        SitesConfig, {"bind": {"site.name": []}}, "name a column", id="bind without a column"
    ),
    pytest.param(
        RecipeSpec,
        {"file": "p.toml", "set": {"flow": {"param": 1}}},
        "without quotes",
        id="inline set not quoted",
    ),
    pytest.param(
        SitesConfig, {"summary": {"columns": ["metrics[0]"]}}, "no index", id="column with index"
    ),
    pytest.param(
        SitesConfig, {"export": [{"format": "csv"}]}, "table or runs", id="export names nothing"
    ),
    pytest.param(
        SitesConfig,
        {"export": [{"table": "by_site", "runs": "best"}]},
        "table or runs",
        id="export names both",
    ),
    pytest.param(
        SitesConfig,
        {"include": ["J0014010"], "exclude": ["J0014010"]},
        "J0014010",
        id="include and exclude overlap",
    ),
    pytest.param(SitesRunConfig, {"parallel": 0}, "parallel", id="zero budget"),
]

VALID = [
    pytest.param({"summary": {"columns": ["checks.budget_pct", "metrics.nse"]}}, id="columns"),
    pytest.param({"export": [{"table": "by_site"}]}, id="export a table"),
    pytest.param(
        {"export": [{"runs": "best", "variables": ["discharge"]}]}, id="export the best runs"
    ),
]


EMPTY_CELLS = [
    pytest.param(None, True, id="none"),
    pytest.param(float("nan"), True, id="nan"),
    pytest.param("  ", True, id="blank text"),
    pytest.param("J0014010", False, id="text"),
    pytest.param(0.0, False, id="zero"),
]


def test_defaults_are_the_measured_budget() -> None:
    run = SitesConfig().run

    assert (run.parallel, run.on_error, run.threads_per_case) == (8, "warn", 1)
    assert (run.keep_attempts, run.prepare_parallel) == (1, 2)
    assert SitesConfig().summary.metrics == ["nse"]


@pytest.mark.parametrize("payload", VALID)
def test_valid_sections_load(payload: dict[str, Any]) -> None:
    SitesConfig.model_validate(payload)


@pytest.mark.parametrize(("model", "payload", "message"), REFUSALS)
def test_refusals(model: type, payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        model.model_validate(payload)


@pytest.mark.parametrize(("value", "empty"), EMPTY_CELLS)
def test_empty_cells(value: object, empty: bool) -> None:
    assert is_empty_cell(value) is empty
