"""``find(<metric>_gt=...)`` refuses a metric name it does not know.

A retired spelling (``log_nse_gt``) or a typo used to join no row and return an
empty ``RunSet``, which reads as "no run is that good". It is now refused with
the known names, the retired spelling with the name to write.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store


@pytest.fixture
def cat(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    for metric, value in {"nse": 0.8, "nse_log": 0.7}.items():
        store.facts.put_metric(headline_row(metric, value))
    store.facts.score = headline_score(0.8)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog


def test_a_known_metric_filters(cat) -> None:
    assert len(cat.find(nse_gt=0.5)) == 1
    assert len(cat.find(nse_log_gte=0.9)) == 0


def test_a_retired_spelling_is_refused_with_the_name_to_write(cat) -> None:
    with pytest.raises(ValueError, match="write 'nse_log'"):
        cat.find(log_nse_gt=0.5)


def test_a_typo_is_refused_with_the_known_names(cat) -> None:
    with pytest.raises(ValueError, match="nse_lgo") as raised:
        cat.find(nse_lgo_gt=0.5)
    assert "kge_alpha" in str(raised.value)
