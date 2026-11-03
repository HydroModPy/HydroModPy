"""``hmp dev rank`` and the calibration criteria read one table of directions.

``hmp dev rank`` used to keep its own list of lower-is-better metrics, and the
calibration criteria their own list of higher-is-better ones. Both now read
``METRIC_SENSE``: the top of ``rmse`` is its lowest value, the top of ``pbias``
the value closest to zero.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.results.catalog.constants import METRIC_SENSE
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.cli_runner import CliRunner
from tests._helpers.metric_rows import headline_row
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import SITE


@pytest.fixture
def workspace(tmp_path):
    """Three completed runs a, b, c of project p, scored on nse, rmse and pbias."""
    scores = {
        "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
        "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
        "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
    }
    root = tmp_path / "p"
    for name, metrics in scores.items():
        store = open_run_store(root, name, create_zarr=False)
        for metric, value in {**metrics, "unknown_score": 1.0}.items():
            store.write_metric(
                store.sim_id, headline_row(metric, value, station=SITE, variable="head")
            )
        seal_completed(store)
    rebuild_index(root)
    return root


def _names(stdout: str) -> list[str]:
    return [line.split()[1] for line in stdout.splitlines() if "#" in line.split()[0]]


@pytest.mark.parametrize(
    ("metric", "best_first", "worst_first"),
    [
        ("nse", ["b", "a", "c"], ["c", "a", "b"]),
        ("rmse", ["b", "a", "c"], ["c", "a", "b"]),
        ("pbias", ["b", "a", "c"], ["c", "a", "b"]),
    ],
)
def test_top_and_bottom_follow_the_metric(workspace, metric, best_first, worst_first) -> None:
    common = ["dev", "rank", "p", "--metric", metric, "--workspace", str(workspace)]

    top = CliRunner().invoke([*common, "--top", "3"])
    bottom = CliRunner().invoke([*common, "--bottom", "3"])

    assert top.exit_code == 0, top.stderr
    assert _names(top.stdout) == best_first
    assert bottom.exit_code == 0, bottom.stderr
    assert _names(bottom.stdout) == worst_first


def test_a_metric_without_direction_is_refused(workspace) -> None:
    result = CliRunner().invoke(
        ["dev", "rank", "p", "--metric", "unknown_score", "--workspace", str(workspace)]
    )

    assert result.exit_code == 10
    assert "no declared direction" in result.stderr


def test_every_calibration_metric_has_a_direction() -> None:
    """A criterion turns a score into a cost: its metric is either max or min."""
    for name in METRICS:
        assert METRIC_SENSE.get(name) in {"max", "min"}, name
    assert {name for name in METRICS if METRIC_SENSE[name] == "max"} == HIGHER_IS_BETTER
