"""Sealed runs for the tests of the run API, written the way the pipeline writes them.

A test opens the store of a claimed run, writes through its verbs, then asks
for the catalog: every open store is sealed, the index is rebuilt from the
run directories, and the reader opens it. Nothing here writes the index.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.toml_io.writer import dumps as dump_toml
from hydromodpy.results.annotations import add_tag
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import claim_run, facts_of

PROJECT = "test"
"""Project every run of these tests belongs to, unless a test names another."""

MISSING_SIM_ID = "00000000-0000-4000-8000-000000000000"
"""A well-formed run id that no run of these tests carries."""

GAUGE = "J0014010"
"""Station the scores of :func:`score` are read at, the gauge of the metric rule."""

WINDOW = (date(2020, 1, 1), date(2020, 12, 31))
"""Window of the scores written by :func:`score`."""


class RunBuilder:
    """Open run stores under one project, then seal them and open the catalog."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._pending: list[RunStore] = []
        self._catalog: Catalog | None = None
        self._count = 0

    def open(
        self,
        name: str | None = None,
        *,
        project: str = PROJECT,
        solver: str = "modflow6",
        n_cells: int = 10,
        n_layers: int = 2,
        n_timesteps: int | None = None,
        config: dict[str, Any] | None = None,
        tags: tuple[str, ...] | list[str] = (),
        create_zarr: bool = True,
        **facts: Any,
    ) -> RunStore:
        """Claim ``runs/<name>`` and return its open store.

        ``config`` is frozen as ``config.toml``; ``tags`` are written to the
        annotations of the run. The store is sealed by :meth:`catalog`.
        """
        self._count += 1
        claim = claim_run(self.project_root, name or f"run{self._count:02d}")
        store = RunStore.open(
            claim.run_dir,
            facts=facts_of(
                claim,
                project=project,
                solver=solver,
                n_cells=n_cells,
                n_layers=n_layers,
                n_timesteps=n_timesteps,
                **facts,
            ),
            workspace=self.project_root,
        )
        if create_zarr:
            store.create_zarr(n_cells=n_cells, n_layers=n_layers)
        if config is not None:
            (claim.run_dir / RUN_CONFIG_FILENAME).write_text(dump_toml(config), encoding="utf-8")
        for tag in tags:
            add_tag(claim.run_dir, tag)
        self._pending.append(store)
        return store

    def store(self, sim_id: str) -> RunStore:
        """Return the open store of the run *sim_id*, not sealed yet."""
        for store in self._pending:
            if store.sim_id == sim_id:
                return store
        raise KeyError(f"no open store for the run {sim_id}")

    def reader(self) -> Catalog:
        """Return the reader, sealing and indexing first what is still open."""
        if self._pending or self._catalog is None:
            return self.catalog()
        return self._catalog

    def seal(self, store: RunStore) -> None:
        """Seal *store* now, without indexing it."""
        self._pending.remove(store)
        seal_completed(store)

    def catalog(self) -> Catalog:
        """Seal every open store, rebuild the index and return its reader."""
        for store in self._pending:
            seal_completed(store)
        self._pending.clear()
        self.close_catalog()
        rebuild_index(self.project_root)
        self._catalog = Catalog(self.project_root)
        return self._catalog

    def close_catalog(self) -> None:
        """Close the reader opened last, if any."""
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None

    def close(self) -> None:
        """Close the reader and every store left unsealed."""
        self.close_catalog()
        for store in self._pending:
            store.close()
        self._pending.clear()


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[RunBuilder]:
    """A builder of sealed runs under ``<tmp>/test``."""
    builder = RunBuilder(tmp_path / PROJECT)
    try:
        yield builder
    finally:
        builder.close()


def write_plain_metric(
    store: RunStore, station: str, metric: str, value: float, *, variable: str = "head"
) -> None:
    """Record a metric with no period, as a number of the run outside any scoring rule."""
    store.write_metric(
        store.sim_id, MetricRow(station=station, variable=variable, metric=metric, value=value)
    )


def score(
    store: RunStore,
    value: float,
    *,
    metric: str = "nse",
    station: str = GAUGE,
    variable: str = "discharge",
) -> None:
    """Record a score under the metric rule of the run, as the derive step does.

    An NSE is also the headline score of the run.
    """
    shared = {
        "station": station,
        "variable": variable,
        "window": DateWindow(start=WINDOW[0], end=WINDOW[1]),
        "n_samples": 366,
        "metric_rule_version": "1",
    }
    store.facts.put_metric(headline_row(metric, value, **shared))
    if metric == "nse":
        store.facts.score = headline_score(value, metric=metric, **shared)


def populate(store: RunStore) -> None:
    """Write two parameters, a series, a budget row, a mass balance and two metrics."""
    sid = store.sim_id
    store.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "Sy", "value": 0.05, "unit": "-"},
        ],
    )
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    store.write_timeseries(sid, "P01", "head", pd.Series(np.arange(10.0), index=idx))
    store.write_budget(sid, 0, "z1", "recharge", 100.0, 0.0)
    store.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
    write_plain_metric(store, "P01", "nse", 0.85)
    write_plain_metric(store, "P01", "kge", 0.78)


__all__ = [
    "GAUGE",
    "MISSING_SIM_ID",
    "PROJECT",
    "WINDOW",
    "RunBuilder",
    "populate",
    "runs",
    "score",
    "write_plain_metric",
]
