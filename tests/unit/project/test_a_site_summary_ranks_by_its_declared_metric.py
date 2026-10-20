"""``[sites.summary] rank_by`` names the metric of the best case; the order of ``metrics`` does not."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.config.sites import SitesConfig
from hydromodpy.project.summary import collect_project
from tests.unit.project.test_project_summary import _plan, _seal

PROJECT_TOML = """\
[sites]
table = "sites.csv"

[sites.summary]
{summary}
best = "any"
"""


def _two_cases(tmp_path: Path, summary: str) -> Path:
    """One site, a case better by nse (``base``) and a case better by kge (``wide``)."""
    root = tmp_path / "bretagne_k"
    root.mkdir()
    (root / "project.toml").write_text(PROJECT_TOML.format(summary=summary), encoding="utf-8")
    _plan(root, ["J0014010-base", "J0014010-wide"])
    _seal(root, "J0014010", "base", nse=0.80, kge=0.50)
    _seal(root, "J0014010", "wide", nse=0.60, kge=0.90)
    return root


def _best_case(root: Path) -> str:
    collect_project(root)
    by_site = pd.read_parquet(root / "summary" / "by_site.parquet").set_index("site")
    return str(by_site.loc["J0014010", "best_case"])


def test_the_default_ranking_metric_is_nse() -> None:
    assert SitesConfig().summary.rank_by == "nse"


def test_a_site_ranks_by_the_metric_it_declares(tmp_path: Path) -> None:
    root = _two_cases(tmp_path, 'metrics = ["nse", "kge"]\nrank_by = "kge"')

    assert _best_case(root) == "J0014010-wide"


def test_the_order_of_metrics_does_not_choose_the_ranking(tmp_path: Path) -> None:
    root = _two_cases(tmp_path, 'metrics = ["kge", "nse"]')

    assert _best_case(root) == "J0014010-base"


def test_rank_by_must_be_a_metric_the_rule_writes() -> None:
    with pytest.raises(ValidationError, match="rank_by"):
        SitesConfig.model_validate({"summary": {"rank_by": "kling"}})


def test_rank_by_must_be_a_column_of_the_summary() -> None:
    with pytest.raises(ValidationError, match="rank_by.*metrics"):
        SitesConfig.model_validate({"summary": {"metrics": ["nse"], "rank_by": "rmse"}})
