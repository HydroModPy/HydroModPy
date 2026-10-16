"""Integration tests for the ``hmp`` public surface.

Every read goes through ``import hydromodpy as hmp``. These tests exercise
the journey a downstream user would actually write: runs sealed on disk, the
index built from them, then open the project, find a run, rank by a metric
and read its scores. Any regression in the public API trips this file before
it reaches end users. The runs are sealed the way a finished run seals itself
(``tests/_helpers/sealed_runs.py``); a user never writes a run by hand.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


def _project(tmp_path: Path, scores: dict[str, float] | None = None) -> tuple[Path, dict[str, str]]:
    """Seal one run of project ``demo`` per score, index them; return the root and the ids."""
    root = make_project(tmp_path / "demo")
    sim_ids = {name: seal_run(root, name, nse=nse) for name, nse in (scores or {}).items()}
    rebuild_index(root)
    return root, sim_ids


def test_open_returns_catalog_with_empty_dataframe(tmp_path: Path) -> None:
    """``hmp.open`` on an indexed project without run yields an empty simulations table."""
    root, _ = _project(tmp_path)
    with hmp.open(root) as catalog:
        assert isinstance(catalog, hmp.Catalog)
        df = catalog.simulations
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "sim_id" in df.columns
        assert "project" in df.columns


def test_open_without_an_index_names_the_command_that_builds_it(tmp_path: Path) -> None:
    """A reader never creates an index: the refusal says how to build one."""
    root = make_project(tmp_path / "demo")
    with pytest.raises(FileNotFoundError, match="hmp catalog reindex"):
        hmp.open(root)


def test_catalog_supports_context_manager(tmp_path: Path) -> None:
    """The catalog can be used as a ``with`` block (no leaked DB handle)."""
    root, _ = _project(tmp_path)
    with hmp.open(root) as catalog:
        assert catalog.workspace_path == root.resolve()
    assert catalog.closed


def test_sealed_runs_read_back_through_the_index(tmp_path: Path) -> None:
    """Two sealed runs are listed with their project and their status."""
    root, sim_ids = _project(tmp_path, {"run_a": 0.92, "run_b": 0.45})
    with hmp.open(root) as catalog:
        df = catalog.simulations
        assert {str(x) for x in df["sim_id"]} == set(sim_ids.values())
        assert set(df["project"]) == {"demo"}
        assert set(df["status"]) == {"completed"}


def test_find_returns_simulation_group_filtered_by_metric(tmp_path: Path) -> None:
    """``catalog.find(project=..., nse_gt=...)`` returns a RunSet."""
    root, sim_ids = _project(tmp_path, {"good": 0.92, "bad": 0.45})
    with hmp.open(root) as catalog:
        group = catalog.find(project="demo", nse_gt=0.7)
        assert isinstance(group, hmp.RunSet)
        assert group.sim_ids == [sim_ids["good"]]
        assert len(group) == 1


def test_best_returns_simulation_view_with_public_methods(tmp_path: Path) -> None:
    """``catalog.best`` returns a Run exposing sim_id, project and its sealed scores."""
    root, sim_ids = _project(tmp_path, {"good": 0.92, "bad": 0.45})
    with hmp.open(root) as catalog:
        best = catalog.best("demo", metric="nse")
        assert best.sim_id == sim_ids["good"]
        assert best.project == "demo"
        metrics = best.metrics
        assert isinstance(metrics, pd.DataFrame)
        assert (metrics["metric"] == "nse").any()


def test_doctor_reports_expected_keys() -> None:
    """``hmp.doctor()`` returns a non-empty environment report."""
    report = hmp.doctor()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report
    assert isinstance(report["solvers"], dict)
    assert isinstance(report["optional"], dict)


@pytest.mark.parametrize("legacy_name", ["SimulationCatalog", "SimulationGroup"])
def test_renamed_classes_keep_no_alias(legacy_name: str) -> None:
    """The pre-rename names are gone: ``Catalog``/``RunSet`` are the only spellings."""
    assert legacy_name not in hmp.__all__
    with pytest.raises(AttributeError):
        getattr(hmp, legacy_name)


def test_a_rebuilt_index_reads_the_same_run(tmp_path: Path) -> None:
    """Reopened after a second rebuild, the index still holds the scores and parameters."""
    root = make_project(tmp_path / "lifecycle_demo")
    sim_id = seal_run(
        root,
        "toy_sim",
        project="lifecycle_demo",
        solver="modflow_nwt",
        nse=0.82,
        parameters={"k": 1e-4},
    )
    rebuild_index(root)
    rebuild_index(root)

    with hmp.open(root) as catalog:
        sims = catalog.list_simulations(project="lifecycle_demo")
        assert len(sims) == 1
        assert sims.iloc[0]["solver"] == "modflow_nwt"

        metrics = catalog.connection.execute(
            "SELECT metric_name, value FROM metrics WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(metrics["metric_name"]) == ["nse"]
        assert float(metrics["value"].iloc[0]) == pytest.approx(0.82)

        params = catalog.connection.execute(
            "SELECT param_name, value FROM parameters WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(params["param_name"]) == ["k"]
        assert float(params["value"].iloc[0]) == pytest.approx(1e-4)
