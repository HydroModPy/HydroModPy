"""Integration tests for the ``hmp`` public surface.

The only import allowed here is ``import hydromodpy as hmp``. These tests
exercise the journey a downstream user would actually write - open a
workspace, register a simulation, attach metrics, query the catalog -
so any regression in the public API trips this file before it reaches
end users. Workflows that need internal machinery belong in
``tests/unit/`` or ``tests/e2e/``.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.core.state.paths import catalog_path_for


def _register_demo_sim(catalog, *, project: str, nse: float, sim_name: str):
    """Register a minimal simulation + one metric via the public surface only."""
    sim_id = str(uuid4())
    catalog.register_simulation(
        sim_id=sim_id,
        project=project,
        solver="boussinesq",
        name=sim_name,
        flow_regime="transient",
    )
    catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=nse)
    catalog.finalize(sim_id, status="completed", duration_s=0.0)
    return sim_id


def test_open_returns_catalog_with_empty_dataframe(tmp_path: Path) -> None:
    """``hmp.open`` on a fresh directory yields an empty simulations table."""
    with hmp.open(tmp_path / "workspace", create=True) as catalog:
        assert isinstance(catalog, hmp.Catalog)
        df = catalog.simulations
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "sim_id" in df.columns
        assert "project" in df.columns


def test_catalog_supports_context_manager(tmp_path: Path) -> None:
    """The catalog can be used as a ``with`` block (no leaked DB handle)."""
    ws = tmp_path / "workspace"
    with hmp.open(ws, create=True) as catalog:
        assert catalog.workspace_path == ws
    assert catalog_path_for(ws).is_file()


def test_register_write_query_roundtrip(tmp_path: Path) -> None:
    """Register two sims, attach metrics, and retrieve them via the public API."""
    with hmp.open(tmp_path / "workspace", create=True) as catalog:
        sid_a = _register_demo_sim(catalog, project="demo", nse=0.92, sim_name="run_a")
        sid_b = _register_demo_sim(catalog, project="demo", nse=0.45, sim_name="run_b")

        df = catalog.simulations
        assert {str(x) for x in df["sim_id"]} == {sid_a, sid_b}
        assert set(df["project"]) == {"demo"}
        assert set(df["status"]) == {"completed"}


def test_find_returns_simulation_group_filtered_by_metric(tmp_path: Path) -> None:
    """``catalog.find(project=..., nse_gt=...)`` returns a RunSet."""
    with hmp.open(tmp_path / "workspace", create=True) as catalog:
        sid_good = _register_demo_sim(catalog, project="demo", nse=0.92, sim_name="good")
        _register_demo_sim(catalog, project="demo", nse=0.45, sim_name="bad")

        group = catalog.find(project="demo", nse_gt=0.7)
        assert isinstance(group, hmp.RunSet)
        assert group.sim_ids == [sid_good]
        assert len(group) == 1


def test_best_returns_simulation_view_with_public_methods(tmp_path: Path) -> None:
    """``catalog.best`` returns a Run exposing sim_id/project/metrics."""
    with hmp.open(tmp_path / "workspace", create=True) as catalog:
        sid_good = _register_demo_sim(catalog, project="demo", nse=0.92, sim_name="good")
        _register_demo_sim(catalog, project="demo", nse=0.45, sim_name="bad")

        best = catalog.best("demo", metric="nse")
        assert best.sim_id == sid_good
        assert best.project == "demo"
        metrics = best.metrics
        assert isinstance(metrics, pd.DataFrame)
        assert (metrics["metric_name"] == "nse").any()


def test_doctor_reports_expected_keys() -> None:
    """``hmp.doctor()`` returns a non-empty environment report."""
    report = hmp.doctor()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report
    assert isinstance(report["solvers"], dict)
    assert isinstance(report["optional"], dict)


def test_catalog_alias_is_not_exposed() -> None:
    with pytest.raises(AttributeError):
        hmp.Catalog  # noqa: B018


def test_open_register_query_roundtrip(tmp_path: Path) -> None:
    """Register a sim with parameters + timeseries, reopen, verify durability."""
    workspace = tmp_path / "workspace"
    with hmp.open(workspace, create=True) as catalog:
        sim_id = str(uuid4())
        catalog.register_simulation(
            sim_id=sim_id,
            project="lifecycle_demo",
            solver="modflow_nwt",
            name="toy_sim",
            flow_regime="steady",
        )
        catalog.write_parameters(
            sim_id,
            [{"param_name": "k", "zone_id": "default", "value": 1e-4, "unit": "m/s"}],
        )
        index = pd.date_range("2024-01-01", periods=5, freq="D")
        series = pd.Series(np.linspace(10.0, 10.2, 5), index=index, name="head")
        catalog.write_timeseries(sim_id, station_id="P01", variable="head", ts=series)
        catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=0.82)
        catalog.finalize(sim_id, status="completed", duration_s=0.1)

    # Re-open the workspace and verify every write is durable.
    with hmp.open(workspace, create=True) as catalog2:
        sims = catalog2.list_simulations(project="lifecycle_demo")
        assert len(sims) == 1
        assert sims.iloc[0]["solver"] == "modflow_nwt"

        metrics = catalog2.connection.execute(
            "SELECT metric_name, value FROM metrics WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(metrics["metric_name"]) == ["nse"]
        assert float(metrics["value"].iloc[0]) == pytest.approx(0.82)

        params = catalog2.connection.execute(
            "SELECT param_name, value FROM parameters WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(params["param_name"]) == ["k"]
        assert float(params["value"].iloc[0]) == pytest.approx(1e-4)
