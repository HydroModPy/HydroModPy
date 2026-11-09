"""Schema discovery of the reader, and the data cache of a workspace read by its sidecars."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog, rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.fast


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, str]:
    root = make_project(tmp_path / "naizin")
    sid = seal_run(root, "demo", project="naizin", nse=0.8)
    rebuild_index(root)
    return root, sid


def test_the_reader_answers_with_objects_and_a_frame(project) -> None:
    root, sid = project
    with Catalog(root) as cat:
        group = cat.find(solver="modflow6")
        assert isinstance(group, hmp.RunSet)
        assert group.sim_ids == [sid]
        assert len(cat.frame) == 1
        assert cat[sid].project == "naizin"


def test_find_unknown_filter_lists_valid_keys(project) -> None:
    root, _sid = project
    with Catalog(root) as cat:
        with pytest.raises(ValueError, match="Unknown filter"):
            cat.find(catchment="x")


def test_schema_discovery(project) -> None:
    root, _sid = project
    with Catalog(root) as cat:
        assert "simulations" in cat.tables()
        assert "cases" in cat.tables()
        assert "metrics" in cat.tables()
        assert {"project", "site", "rel_dir", "label"} <= set(cat.columns("simulations"))
        assert "nse" in cat.metrics()
        assert "J0014010" in cat.stations()
        assert cat.variables()


def test_describe_is_human_readable(project) -> None:
    root, _sid = project
    with Catalog(root) as cat:
        text = cat.describe()
        assert "simulations : 1" in text
        assert "naizin" in text
        assert "modflow6" in text
        cat.backend.connection.execute("DROP VIEW timeseries")
        assert "stations    : J0014010" in cat.describe()
        assert cat.variables()


def test_the_data_cache_of_a_workspace_without_data_has_no_rows(tmp_path: Path) -> None:
    from hydromodpy.data.provenance.sidecars import scan

    report = scan(tmp_path / "data")

    assert report.rows == ()
    assert report.data_root == (tmp_path / "data").resolve()
