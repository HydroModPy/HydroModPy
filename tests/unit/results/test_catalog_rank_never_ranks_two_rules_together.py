"""``hmp catalog rank`` refuses scores of two rules, and ranks one station when it names it."""

from __future__ import annotations

import argparse
from datetime import date

import pytest

from hydromodpy.cli._workers.dev import rank_simulations
from hydromodpy.cli.commands.catalog import rank
from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.results.catalog import rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.sealed import MixedWindowsError
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.unit

FIVE_YEARS = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))
NINETY_DAYS = DateWindow(start=date(2020, 10, 1), end=date(2020, 12, 29))


@pytest.fixture
def windows(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    return ids


@pytest.fixture
def stations(tmp_path):
    """Two sites, so two gauges, on the same window."""
    root = make_project(tmp_path / "demo")
    ids = {
        "a1": seal_run(root, "a1", site="J001", nse=0.8, window=FIVE_YEARS),
        "a2": seal_run(root, "a2", site="J001", nse=0.7, window=FIVE_YEARS),
        "b1": seal_run(root, "b1", site="J002", nse=0.9, window=FIVE_YEARS),
    }
    rebuild_index(root)
    return ids


def test_catalog_rank_refuses_two_windows(windows, tmp_path) -> None:
    ids = windows
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        rank_simulations("demo", workspace=root, metric="nse")
    with pytest.raises(MixedWindowsError):
        rank_simulations("demo", workspace=root, metric="nse", station="J0014010")
    frame = rank_simulations("demo", workspace=root, metric="nse", mixed_windows=True)
    assert frame["sim_id"].astype(str).tolist()[0] == ids["short"]


def test_catalog_rank_of_one_station_ranks_it(stations, tmp_path) -> None:
    ids = stations
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="J002"):
        rank_simulations("demo", workspace=root, metric="nse")
    frame = rank_simulations("demo", workspace=root, metric="nse", station="J001")
    assert frame["sim_id"].astype(str).tolist() == [ids["a1"], ids["a2"]]


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hmp catalog")
    sub = parser.add_subparsers(dest="action")
    rank.register(sub)
    return parser.parse_args([rank.NAME, *argv])


def test_the_command_exits_with_the_validation_code_and_forces(windows, tmp_path, capsys) -> None:
    root = str(tmp_path / "demo")
    args = _parse(["--project", "demo", "-w", root, "--top", "3"])
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as stopped:
        args._handler(args)
    assert exit_code_for(stopped.value) == EXIT_VALIDATION

    args = _parse(["--project", "demo", "-w", root, "--top", "3", "--mixed-windows"])
    args._handler(args)
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("TOP#1: short")
    assert "window=2020-10-01..2020-12-29" in out
