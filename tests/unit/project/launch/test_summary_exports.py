"""A ``[[sites.export]]`` the collect cannot write is refused, and the unfit rows are skipped."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.config.sites.models import SitesExportRequest
from hydromodpy.project.launch.summary_exports import check_exports, write_exports
from hydromodpy.project.launch.summary_tables import SummaryError


@pytest.mark.parametrize(
    ("request_data", "match"),
    [
        ({"runs": "best", "format": "parquet", "variables": ["discharge"]}, "not written"),
        ({"runs": "best"}, "name the variables"),
    ],
    ids=["best-runs-in-parquet", "best-runs-without-variables"],
)
def test_a_best_run_export_the_collect_cannot_write_is_refused(request_data, match) -> None:
    with pytest.raises(SummaryError, match=match):
        check_exports([SitesExportRequest.model_validate(request_data)])


def test_a_file_leaving_the_exports_folder_is_refused(tmp_path: Path) -> None:
    request = SitesExportRequest(table="by_site", file="../outside.csv")

    with pytest.raises(SummaryError, match="leaves summary/exports"):
        write_exports(tmp_path, tmp_path, [request], pd.DataFrame(), [], tmp_path / "exports")


def test_the_catalog_table_is_written_from_the_resolved_sites(tmp_path: Path) -> None:
    request = SitesExportRequest(table="catalog")

    write_exports(tmp_path, tmp_path, [request], pd.DataFrame(), [], tmp_path / "exports")

    assert (tmp_path / "exports" / "catalog.csv").is_file()


def test_a_site_without_a_sealed_best_run_writes_no_series(tmp_path: Path) -> None:
    (tmp_path / "runs" / "empty").mkdir(parents=True)
    by_site = pd.DataFrame(
        {"site": ["a", "b"], "rel_dir": [None, "runs/empty"], "best_case": [None, "x"]}
    )
    request = SitesExportRequest(runs="best", variables=["discharge"])

    write_exports(tmp_path, tmp_path, [request], by_site, [], tmp_path / "exports")

    assert not list((tmp_path / "exports").rglob("*.csv"))
