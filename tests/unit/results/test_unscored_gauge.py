"""An observed gauge meets the series of its own name and no other.

A run that simulates discharge at the catchment outlet only used to score every
observed gauge against that series, an upstream gauge included. A gauge without a
simulated series of its name is not scored, and the log and the sealed README say so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from hydromodpy.core.site.config import SiteConfig
from hydromodpy.results.metric_rule import MetricsConfig, MetricsWindow
from hydromodpy.results.readme import render_run_readme
from hydromodpy.results.score import UNSCORED_OBSERVATIONS_CHECK, score_run_under_its_rule
from hydromodpy.results.storage.sealing import build_record
from hydromodpy.results.validity_rules import LabelResult
from tests._helpers.run_stores import open_run_store

OUTLET = "J0014010"
UPSTREAM = "J0013010"


def test_readme_names_unscored_gauge(tmp_path) -> None:
    index = pd.date_range("2020-01-02", periods=10, freq="D")
    observed = pd.Series(np.linspace(1.0, 2.0, 10), index=index)  # m3/s
    cfg = SimpleNamespace(
        site=SiteConfig(name="nancon", gauge=OUTLET),
        metrics=MetricsConfig(window=MetricsWindow(start="2020-01-01", end="2020-01-31")),
    )
    with open_run_store(tmp_path / "demo", "upstream", n_cells=4, n_timesteps=10) as store:
        sid = store.sim_id
        store.facts.period_start = pd.Timestamp("2020-01-01", tz="UTC").to_pydatetime()
        store.write_timeseries(sid, OUTLET, "discharge", observed * 1.0)
        store.write_timeseries(sid, OUTLET, "discharge", observed, source="observed")
        store.write_timeseries(sid, UPSTREAM, "discharge", observed * 0.3, source="observed")

        score_run_under_its_rule(cfg, store=store)

        assert {row.station for row in store.facts.metrics} == {OUTLET}
        failed = [v for v in store.facts.validities if not v.passed]
        assert [v.name for v in failed] == [UNSCORED_OBSERVATIONS_CHECK]
        assert not failed[0].fatal
        record = build_record(store, ended_at=datetime.now(UTC))

    label = LabelResult("unchecked", "3", (), ())
    text = render_run_readme(record, None, label, manifest_sha256="0" * 64)
    assert UPSTREAM in text and "not scored" in text
