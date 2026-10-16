"""The NSE on log discharge has one name, ``nse_log``, in calibration and in the index.

A calibration scores ``nse_log``; the old spelling ``log_nse`` is refused
with the one to write, in the ranking helper and in the ``@best`` selector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog, SimulationNotFoundError, rebuild_index
from hydromodpy.results.catalog.constants import UnrankedMetricError, metric_rank_sql


def test_the_old_name_is_refused_with_the_new_one(tmp_path: Path) -> None:
    from tests._helpers.sealed_runs import make_project, seal_run

    root = make_project(tmp_path / "demo")
    seal_run(root, "only")
    rebuild_index(root)
    with Catalog(root) as catalog:
        with pytest.raises(SimulationNotFoundError, match="was renamed: write 'nse_log'"):
            catalog.resolve("@best:log_nse")
    with pytest.raises(UnrankedMetricError, match="write 'nse_log'"):
        metric_rank_sql("log_nse", best=True)


def test_the_new_name_has_a_direction() -> None:
    assert metric_rank_sql("nse_log", best=True).endswith("DESC")
